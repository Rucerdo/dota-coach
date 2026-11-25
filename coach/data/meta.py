"""El meta actual: cambios del parche + rendimiento real en partidas públicas.

Para cada héroe se combinan:
  - patch_score: saldo de buffs/nerfs del ciclo de parches actual (7.42 + 7.42a...)
  - winrate: en tu rango si lo configuras (rank_bracket), si no en total
  - trend: cuánto ha subido/bajado su winrate en los tramos más recientes (detecta lo que el parche
    ha cambiado de verdad, no solo lo que dicen las notas)
Con IA (opcional) se relee cada bloque de notas y se resume en una frase, y se escribe un resumen del meta.
"""
import json
import logging
import time
from dataclasses import dataclass, field

from .cache import read_cached, write_cached
from .gamedata import GameData, Hero
from .patches import Change, load_cycle, score
from . import opendota

log = logging.getLogger(__name__)

BRACKETS = {1: "Herald", 2: "Guardian", 3: "Crusader", 4: "Archon", 5: "Legend", 6: "Ancient", 7: "Divine",
            8: "Immortal"}


@dataclass
class HeroMeta:
    hero: Hero
    picks: int = 0
    wins: int = 0
    pick_rate: float = 0.0      # fracción de partidas en las que aparece
    trend: float = 0.0          # puntos de winrate (recientes - antiguos)
    patch_score: float = 0.0
    changes: list[Change] = field(default_factory=list)
    ai_verdict: str = ""        # buff | nerf | mixed | rework | neutral (si se analizó con IA)
    ai_summary: str = ""

    @property
    def winrate(self) -> float:
        return self.wins / self.picks if self.picks else 0.5

    @property
    def meta_score(self) -> float:
        """Positivo = fuerte ahora mismo. Mezcla winrate, tendencia y cambios del parche."""
        return (self.winrate - 0.5) * 100 + 0.5 * self.trend + 0.4 * self.patch_score

    def one_line(self) -> str:
        parts = [f"{self.hero.loc}: {self.winrate:.1%} WR"]
        if self.trend:
            parts.append(f"tendencia {self.trend:+.1f} pts")
        if self.changes:
            verdict = self.ai_verdict or ("buff" if self.patch_score > 0.5 else "nerf" if self.patch_score < -0.5 else "mixto")
            parts.append(f"parche: {verdict} ({len(self.changes)} cambios)")
        if self.ai_summary:
            parts.append(self.ai_summary)
        return " · ".join(parts)


def _trend(picks: list, wins: list) -> float:
    if not picks or len(picks) != len(wins) or len(picks) < 4:
        return 0.0
    half = len(picks) // 2
    old_p, old_w = sum(picks[:half]), sum(wins[:half])
    new_p, new_w = sum(picks[half:]), sum(wins[half:])
    if old_p < 200 or new_p < 200:
        return 0.0
    return round((new_w / new_p - old_w / old_p) * 100, 2)


class Meta:
    def __init__(self, gd: GameData, versions: list[str], changes: list[Change], stats: list[dict],
                 bracket: int = 0):
        self.gd, self.versions, self.changes, self.bracket = gd, versions, changes, bracket
        self.heroes: dict[int, HeroMeta] = {hid: HeroMeta(h) for hid, h in gd.heroes.items()}
        self.items: dict[str, list[Change]] = {}
        self.general = [c for c in changes if c.kind in ("general", "creep")]
        self.item_reviews: dict[str, dict] = {}
        for c in changes:
            if c.kind == "hero" and c.target_id in self.heroes:
                self.heroes[c.target_id].changes.append(c)
            elif c.kind in ("item", "neutral_item"):
                self.items.setdefault(c.target, []).append(c)
        for hm in self.heroes.values():
            hm.patch_score = score(hm.changes)
        total_picks = 0
        for s in stats or []:
            hm = self.heroes.get(s.get("id"))
            if not hm:
                continue
            if bracket and s.get(f"{bracket}_pick"):
                hm.picks, hm.wins = int(s[f"{bracket}_pick"]), int(s.get(f"{bracket}_win") or 0)
            else:
                hm.picks, hm.wins = int(s.get("pub_pick") or 0), int(s.get("pub_win") or 0)
            hm.trend = _trend(s.get("pub_pick_trend") or [], s.get("pub_win_trend") or [])
            total_picks += hm.picks
        matches = total_picks / 10 if total_picks else 0
        for hm in self.heroes.values():
            hm.pick_rate = hm.picks / matches if matches else 0.0

    @property
    def patch(self) -> str:
        return self.versions[-1] if self.versions else "?"

    @classmethod
    def build(cls, gd: GameData, bracket: int = 0) -> "Meta":
        versions, changes = load_cycle(gd)
        try:
            stats = opendota.hero_stats()
        except Exception:
            log.exception("sin estadísticas de OpenDota: el meta solo usará las notas de parche")
            stats = []
        meta = cls(gd, versions, changes, stats, bracket)
        meta.load_ai_review()  # si ya se analizó este parche con IA, se reutiliza
        return meta

    # ---------- consultas ----------
    def hero(self, h: Hero | int | None) -> HeroMeta | None:
        if h is None:
            return None
        return self.heroes.get(h if isinstance(h, int) else h.id)

    def item_changes(self, name: str) -> list[Change]:
        return self.items.get(name, [])

    def ranked(self, min_pick_rate: float = 0.02) -> list[HeroMeta]:
        pool = [h for h in self.heroes.values() if h.picks and h.pick_rate >= min_pick_rate]
        return sorted(pool, key=lambda h: h.meta_score, reverse=True)

    def most_changed(self, n: int = 10) -> tuple[list[HeroMeta], list[HeroMeta]]:
        changed = [h for h in self.heroes.values() if h.changes]
        buffed = sorted((h for h in changed if h.patch_score > 0), key=lambda h: h.patch_score, reverse=True)
        nerfed = sorted((h for h in changed if h.patch_score < 0), key=lambda h: h.patch_score)
        return buffed[:n], nerfed[:n]

    def items_summary(self) -> list[tuple[str, float, int]]:
        return sorted(((name, score(cs), len(cs)) for name, cs in self.items.items()),
                      key=lambda t: t[1], reverse=True)

    def brief(self, n: int = 8) -> str:
        """Resumen del meta sin IA."""
        where = BRACKETS.get(self.bracket, "todos los rangos")
        lines = [f"Parche {' + '.join(self.versions) or '?'} · winrates de {where} (OpenDota)", ""]
        ranked = self.ranked()
        lines.append("En alza (winrate + tendencia + parche):")
        lines += [f"  ▲ {h.one_line()}" for h in ranked[:n]]
        lines.append("")
        lines.append("A la baja:")
        lines += [f"  ▼ {h.one_line()}" for h in ranked[-n:][::-1]]
        buffed, nerfed = self.most_changed(n)
        lines.append("")
        lines.append("Más buffeados en las notas: " + ", ".join(f"{h.hero.loc} ({h.patch_score:+.1f})" for h in buffed))
        lines.append("Más nerfeados en las notas: " + ", ".join(f"{h.hero.loc} ({h.patch_score:+.1f})" for h in nerfed))
        items = self.items_summary()
        if items:
            lines.append("")
            lines.append("Objetos mejorados: " + ", ".join(f"{n} ({s:+.1f})" for n, s, _ in items[:n] if s > 0))
            lines.append("Objetos empeorados: " + ", ".join(f"{n} ({s:+.1f})" for n, s, _ in items[::-1][:n] if s < 0))
        return "\n".join(lines)

    def context_for(self, heroes: list[Hero], items: list[str] = ()) -> str:
        """Lo relevante del parche para estos héroes y objetos, para dárselo a la IA (compacto)."""
        out = []
        for h in heroes:
            hm = self.hero(h)
            if not hm:
                continue
            out.append(hm.one_line())
            for c in hm.changes[:6]:
                out.append(f"   [{c.version} {c.tag}] {c.detail}: {c.text}")
        for name in items:
            for c in self.item_changes(name)[:3]:
                out.append(f"[{c.version} {c.tag}] {name}: {c.text}")
        return "\n".join(out)

    # ---------- IA ----------
    def _review_key(self) -> str:
        return "ai_patch_review_" + "_".join(self.versions)

    def load_ai_review(self) -> bool:
        hit = read_cached(self._review_key())
        if not hit:
            return False
        self._apply_review(hit[1])
        return True

    def _apply_review(self, entries: list[dict]):
        by_name = {e.get("target", "").lower(): e for e in entries or []}
        for hm in self.heroes.values():
            e = by_name.get(hm.hero.loc.lower())
            if e:
                hm.ai_verdict, hm.ai_summary = e.get("verdict", ""), e.get("summary", "")
        self.item_reviews = {k: v for k, v in by_name.items()}

    def ai_review(self, provider, lang: str = "es", batch: int = 20, progress=None) -> int:
        """Relee las notas de cada héroe/objeto con IA y guarda un veredicto + resumen de una frase.
        Se hace una vez por parche y se guarda en caché. Devuelve cuántos elementos se analizaron."""
        from ..ai.prompts import PATCH_REVIEW_SCHEMA, patch_review_prompt
        groups: dict[tuple[str, str], list[Change]] = {}
        for c in self.changes:
            if c.kind in ("hero", "item"):
                groups.setdefault((c.kind, c.target), []).append(c)
        keys = sorted(groups)
        entries: list[dict] = []
        for start in range(0, len(keys), batch):
            chunk = keys[start:start + batch]
            blocks = []
            for kind, target in chunk:
                notes = "\n".join(f"- [{c.version}] {c.detail}: {c.text}" for c in groups[(kind, target)])
                blocks.append(f"## {target} ({kind})\n{notes}")
            system, user = patch_review_prompt(self.patch, "\n\n".join(blocks), lang)
            raw = provider.complete(system, user, schema=PATCH_REVIEW_SCHEMA, effort="medium", max_tokens=16000)
            try:
                entries += json.loads(raw).get("entries", [])
            except ValueError:
                log.warning("respuesta de IA no válida en el lote %d", start // batch)
            if progress:
                progress(min(start + batch, len(keys)), len(keys))
        write_cached(self._review_key(), entries)
        self._apply_review(entries)
        return len(entries)

    def ai_brief(self, provider, lang: str = "es") -> str:
        """Resumen del meta escrito por la IA (se guarda en caché un día por parche)."""
        from ..ai.prompts import meta_brief_prompt
        key = f"ai_meta_brief_{'_'.join(self.versions)}_{self.bracket}_{time.strftime('%Y%m%d')}_{lang}"
        hit = read_cached(key)
        if hit:
            return hit[1]
        system, user = meta_brief_prompt(self.brief(12), self.general[:40], lang)
        text = provider.complete(system, user, effort="medium", max_tokens=8000).strip()
        write_cached(key, text)
        return text
