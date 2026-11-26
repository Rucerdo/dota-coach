"""Asesor en partida: decide CUÁNDO dar un consejo y QUÉ decir.

Cuándo (eventos, no cada segundo):
  start    al empezar la partida (plan inicial)
  enemy    se identifica un héroe enemigo nuevo
  death    acabas de morir (momento ideal para comprar/replantear)
  gold     ya tienes oro para el siguiente objeto sugerido
  periodic cada N minutos de partida
Qué: reglas (counters + popularidad + parche) siempre; con IA, la IA reescribe y prioriza usando esas
reglas como candidatos, el estado de la partida y los cambios del parche que afectan a los héroes en juego.
Si la IA falla o tarda, se usan las reglas.
"""
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..ai.base import LLMError, Provider
from ..ai.prompts import TIPS_SCHEMA, tips_prompt
from ..data.gamedata import GameData, Hero
from ..gsi import GameState, GameTracker
from .counters import (COUNTER_ITEMS, PHASES, TRAIT_LABELS, ItemSuggestion, enemy_traits, item_role, phase_for,
                       suggest_items)

log = logging.getLogger(__name__)


@dataclass
class Tip:
    kind: str        # item | counter | play | warning
    text: str
    source: str      # ai | rules
    clock: int = 0


class Advisor:
    def __init__(self, gd: GameData, meta, cfg: dict, provider: Provider | None = None,
                 on_tips: Callable[[list[Tip]], None] = lambda tips: None,
                 popularity: Callable[[int], dict] | None = None, sync: bool = False,
                 extra_context: Callable[[GameState], list[str]] | None = None):
        self.gd, self.meta, self.cfg, self.provider = gd, meta, cfg, provider
        self.extra_context = extra_context
        self.standard: dict[str, tuple[float, str]] = {}  # de partidas parecidas (lo pone el modo en directo)  # líneas extra para la IA: mapa, líneas, plan de compra, percentiles
        self.on_tips, self.popularity, self.sync = on_tips, popularity, sync
        adv = cfg.get("advisor", {})
        self.min_ai_gap = float(adv.get("min_seconds_between_ai", 45))
        self.periodic = int(adv.get("periodic_minutes", 8)) * 60
        self.max_tips = int(adv.get("max_tips", 2))
        self.lang = cfg.get("lang", "es")
        self._lock = threading.Lock()
        self._busy = False
        self._pop_cache: dict[int, dict] = {}
        self.games = GameTracker()
        self.reset("")

    # ---------- estado ----------
    def reset(self, match_id: str):
        self.match_id = match_id
        self.enemies: dict[int, Hero] = {}
        self.allies: dict[int, Hero] = {}
        self.my_hero_id = 0
        self.started = False
        self.deaths = 0
        self.last_periodic = 0
        self.announced_items: set[str] = set()
        self.recent: list[str] = []
        self.last_ai_call = 0.0
        self._known_enemy_count = 0
        self.standard = {}

    def set_enemies(self, heroes: list[Hero]):
        """Enemigos indicados a mano o detectados en la barra superior."""
        with self._lock:
            for h in heroes:
                if h.id not in self.allies and h.id != self.my_hero_id:
                    self.enemies[h.id] = h

    def set_allies(self, heroes: list[Hero]):
        """Un aliado confirmado nunca puede ser enemigo (si se coló como tal, se corrige)."""
        with self._lock:
            for h in heroes:
                self.allies[h.id] = h
                self.enemies.pop(h.id, None)
            self._known_enemy_count = min(self._known_enemy_count, len(self.enemies))

    # ---------- entrada desde GSI ----------
    def update(self, st: GameState):
        if self.games.update(st):
            self.reset(st.match_id)  # partida nueva: olvidar la anterior
        elif st.match_id and not self.match_id:
            self.match_id = st.match_id  # primera partida: conservar los enemigos indicados antes
        me = self.my_hero(st)
        if me:
            self.my_hero_id = me.id
            self.enemies.pop(me.id, None)
        if not st.in_game:
            return
        self.set_allies([h for h in map(self.gd.hero, st.visible_allies) if h])
        self.set_enemies([h for h in map(self.gd.hero, st.visible_enemies) if h])
        triggers = self.triggers(st)
        if triggers:
            self.advise(st, triggers)

    def triggers(self, st: GameState) -> list[str]:
        out = []
        if not self.started:
            self.started = True
            self.deaths = st.deaths
            self.last_periodic = st.clock
            out.append("start")
        if len(self.enemies) > self._known_enemy_count:
            self._known_enemy_count = len(self.enemies)
            if "start" not in out:
                out.append("enemy")
        if st.deaths > self.deaths:
            self.deaths = st.deaths
            out.append("death")
        if self.periodic and st.clock - self.last_periodic >= self.periodic:  # 0 = nunca
            self.last_periodic = st.clock
            out.append("periodic")
        nxt = self.next_item(st)
        if nxt and st.gold >= nxt.to_pay and nxt.item not in self.announced_items:
            out.append("gold")
        return out

    # ---------- reglas ----------
    def my_hero(self, st: GameState) -> Hero | None:
        return self.gd.hero(st.hero) or self.gd.hero(st.hero_id or None)

    def _popularity(self, hero: Hero | None) -> dict | None:
        if not hero or not self.popularity:
            return None
        if hero.id not in self._pop_cache:
            try:
                self._pop_cache[hero.id] = self.popularity(hero.id)
            except Exception:
                self._pop_cache[hero.id] = {}
        return self._pop_cache[hero.id]

    def suggestions(self, st: GameState, phase: str | None = "auto", limit: int = 6) -> list[ItemSuggestion]:
        """Objetos de la fase actual (o la indicada), cada uno en su fase. Con "auto", si ya tienes todo lo de tu
        fase, se pasa a la siguiente."""
        hero = self.my_hero(st)
        pop = self._popularity(hero)

        def run(ph):
            return suggest_items(self.gd, hero, list(self.enemies.values()), st.all_items,
                                 self.cfg.get("role", "auto"), self.meta, pop, limit=limit, phase=ph,
                                 standard=self.standard or None, strict=ph is not None, turbo=st.turbo)
        if phase != "auto":
            return run(phase)
        # tu fase primero (de ahí sale la siguiente compra) y después la siguiente: los objetivos a medio plazo
        # (p. ej. la MKB contra PA en early) siguen a la vista para los consejos de counter y para la IA
        out: list[ItemSuggestion] = []
        upcoming = 0
        for ph in PHASES[PHASES.index(phase_for(st.clock, st.turbo)):]:
            fresh = [s for s in run(ph) if s.item not in {o.item for o in out}]
            if out:  # ya hay objetos de tu fase: de las siguientes, solo los 3 primeros
                fresh = fresh[:3 - upcoming]
                upcoming += len(fresh)
            out += fresh
            if upcoming >= 3:
                break
        return out

    def next_item(self, st: GameState) -> ItemSuggestion | None:
        sugg = self.suggestions(st)
        return sugg[0] if sugg else None

    def rule_tips(self, st: GameState, triggers: list[str]) -> list[Tip]:
        sugg = self.suggestions(st)
        tips: list[Tip] = []
        if "gold" in triggers and sugg and st.gold >= sugg[0].to_pay:
            s = sugg[0]
            tips.append(Tip("item", f"Ya puedes comprar {s.loc}: {s.reasons[0]}", "rules", st.clock))
        if "death" in triggers:
            if sugg:
                s = sugg[0]
                falta = max(0, s.to_pay - st.gold)
                tips.append(Tip("item", f"Muerto {st.respawn_seconds}s. Siguiente: {s.loc}"
                                         + (f" (te faltan {falta})" if falta else " (ya te llega)"), "rules", st.clock))
            if st.clock > 30 * 60 and st.gold < st.buyback_cost + 500:
                tips.append(Tip("warning", "Guarda oro para el buyback a partir de ahora", "rules", st.clock))
        if "start" in triggers or "enemy" in triggers or "periodic" in triggers:
            traits = enemy_traits(list(self.enemies.values()))
            if traits:
                # el rasgo más repetido que tenga un counter de verdad entre las sugerencias (no basta con que
                # el objeto mencione a esos héroes por otro motivo: BKB no es un counter de la curación)
                for trait, heroes in sorted(traits.items(), key=lambda kv: len(kv[1]), reverse=True):
                    counters = {name for name, _, _ in COUNTER_ITEMS.get(trait, [])}
                    counter = next((s for s in sugg if s.item in counters), None)
                    if counter:
                        tips.append(Tip("counter", f"Contra {TRAIT_LABELS.get(trait, trait)} ({', '.join(heroes)}): "
                                                   f"{counter.loc}", "rules", st.clock))
                        break
            elif "start" in triggers and sugg:
                tips.append(Tip("item", "Plan: " + ", ".join(s.loc for s in sugg[:3]), "rules", st.clock))
        hero = self.my_hero(st)
        if "start" in triggers and hero and self.meta is not None:
            hm = self.meta.hero(hero)
            if hm and hm.changes:
                tips.append(Tip("play", f"Parche {self.meta.patch}: {hm.ai_summary or hm.changes[0].text}",
                                "rules", st.clock))
        return [t for t in tips if t.text not in self.recent][: self.max_tips]

    # ---------- IA ----------
    def context(self, st: GameState, triggers: list[str], sugg: list[ItemSuggestion]) -> str:
        hero = self.my_hero(st)
        role = item_role(hero, self.cfg.get("role", "auto"))
        enemies = list(self.enemies.values())
        lines = [
            f"Trigger: {', '.join(triggers)}",
            f"Game time: {st.clock_text} ({'day' if st.daytime else 'night'})"
            + (" · TURBO game (double gold, everything happens about twice as fast)" if st.turbo else ""),
            f"My hero: {hero.loc if hero else st.hero} · level {st.level} · role {role} · "
            f"K/D/A {st.kills}/{st.deaths}/{st.assists} · last hits {st.last_hits}",
            f"Gold: {st.gold} · GPM {st.gpm} · buyback cost {st.buyback_cost}" + ("" if st.alive else
                                                                                f" · DEAD, respawn in {st.respawn_seconds}s"),
            "My items: " + (", ".join(self._item_loc(i) for i in st.all_items) or "none"),
        ]
        if enemies:
            traits = {h.loc: [TRAIT_LABELS.get(t, t) for t in enemy_traits([h]).keys()] for h in enemies}
            lines.append("Enemy heroes: " + "; ".join(f"{k} ({', '.join(v) or '?'})" for k, v in traits.items()))
        else:
            lines.append("Enemy heroes: unknown")
        if self.allies:
            lines.append("Allied heroes: " + ", ".join(h.loc for h in self.allies.values()))
        lines.append("Candidate items (from counter rules, hero popularity and patch):")
        lines += [f"- {s.line()}" for s in sugg]
        if self.meta is not None:
            ctx = self.meta.context_for([h for h in [hero, *enemies] if h], [s.loc for s in sugg[:4]])
            if ctx:
                lines.append(f"Current patch {self.meta.patch} — relevant changes and meta:")
                lines.append(ctx)
        if self.extra_context:
            try:
                lines += self.extra_context(st)
            except Exception:
                log.exception("no se pudo añadir el contexto extra")
        if self.recent:
            lines.append("Recent tips (do not repeat): " + " | ".join(self.recent[-4:]))
        return "\n".join(lines)

    def _item_loc(self, name: str) -> str:
        it = self.gd.item(name)
        return it.loc if it else name

    def ai_tips(self, st: GameState, triggers: list[str]) -> list[Tip]:
        sugg = self.suggestions(st)
        system, user = tips_prompt(self.context(st, triggers, sugg), self.lang, self.max_tips)
        raw = self.provider.complete(system, user, schema=TIPS_SCHEMA, effort="low", max_tokens=3000, timeout=25)
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise LLMError("respuesta de la IA no es JSON") from e
        return [Tip(t.get("kind", "play"), str(t.get("text", "")).strip(), "ai", st.clock)
                for t in data.get("tips", []) if str(t.get("text", "")).strip()][: self.max_tips]

    # ---------- emitir ----------
    def advise(self, st: GameState, triggers: list[str]):
        use_ai = (self.provider is not None and self.provider.available
                  and time.time() - self.last_ai_call >= self.min_ai_gap)
        if not use_ai:
            self._emit(st, self.rule_tips(st, triggers))
            return
        with self._lock:
            if self._busy:
                return  # ya hay una consulta en curso; el siguiente evento la recogerá
            self._busy = True
            self.last_ai_call = time.time()

        def job():
            try:
                tips = self.ai_tips(st, triggers)
            except Exception as e:
                log.warning("IA no disponible (%s): uso reglas", e)
                tips = self.rule_tips(st, triggers)
            finally:
                with self._lock:
                    self._busy = False
            self._emit(st, tips)

        if self.sync:
            job()
        else:
            threading.Thread(target=job, daemon=True).start()

    def _emit(self, st: GameState, tips: list[Tip]):
        nxt = self.next_item(st)
        if nxt and st.gold >= nxt.to_pay:
            self.announced_items.add(nxt.item)  # no repetir el aviso de oro del mismo objeto
        if not tips:
            return
        self.recent = (self.recent + [t.text for t in tips])[-12:]
        self.on_tips(tips)
