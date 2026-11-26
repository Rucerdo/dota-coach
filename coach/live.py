"""Modo en directo: GSI + visión de la barra superior + asesor + panel de partida (y voz opcional).

Cada estado de GSI pasa por: asesor (consejos de compra/counters), vigilancia del mapa (líneas, ganks, TPs),
habilidades sin gastar, temporizadores, rendimiento frente a tu héroe, registro de la partida (informe al acabar)
y, en la selección de héroes, el draft. El panel pinta el resultado.
"""
import json
import logging
import os
import threading
import time
import tkinter as tk
from typing import Callable

from . import config, dota
from .ai import make_provider
from .ai.prompts import REVIEW_SCHEMA, review_prompt
from .data import opendota
from .data.sources import Sources
from .data.gamedata import GameData, Hero
from .engine import benchmarks
from .engine.advisor import Advisor, Tip
from .engine.counters import item_role
from .engine.draft import suggest_picks
from .engine.draftlive import draft_state, is_drafting
from .engine.courier import CourierTracker
from .engine.events import EventWatch
from .engine.mapwatch import MapWatch
from .engine.matchlog import MatchLog, MatchReport, history, load_reports, save
from .engine.similar import find_similar
from .engine.ults import KEYS as ULT_KEYS, UltTracker, enemy_order, fmt_seconds, ult_from_herodata
from .engine.skills import SkillWatch
from .engine.timers import TimerWatch, upcoming
from .gsi import GameState, GSIRecorder, GSIServer
from .ui.overlay import Overlay
from .ui.view import build_view

log = logging.getLogger(__name__)

POST_GAME = "DOTA_GAMERULES_STATE_POST_GAME"


def run_live(cfg: dict, gd: GameData, meta, manual_enemies: list[Hero] = (),
             should_stop: Callable[[], bool] | None = None, update=None):
    """should_stop: si devuelve True, el coach se cierra solo (lo usa el arranque automático al cerrar Dota)."""
    d = dota.normalize(cfg.get("dota_dir")) or dota.find_dota_dir()
    if d and not dota.is_installed(d, cfg["gsi_port"]):
        print(f"Instalando la integración GSI en {d} (reinicia Dota 2 una vez).")
        dota.install(d, cfg["gsi_port"])
    elif not d:
        print("⚠ No encuentro Dota 2: usa 'coach install --dota-dir ...'")

    provider = make_provider(cfg)
    ai_label = f"IA: {provider.label}" if provider else "sin IA (reglas)"
    panel = None
    if cfg.get("panel", {}).get("enabled", True):
        from .ui.panel import Panel
        root = panel = Panel(cfg, meta.patch, ai_label)  # ventana principal: cerrarla detiene el coach
        panel.item_names = {i.name: i.loc for i in gd.items.values()}
    else:
        root = tk.Tk()
        root.withdraw()
    overlay = Overlay(root, cfg["overlay"]) if cfg["overlay"].get("enabled", False) else None
    speaker = None
    if cfg.get("tts"):
        from .ui.tts import Speaker
        speaker = Speaker()

    def on_tips(tips: list[Tip]):
        if panel:
            panel.post("tips", tips)
        for t in tips:
            if overlay:
                overlay.push(t.kind, t.text)
            print(f"[{t.kind}/{t.source}] {t.text}")
            if speaker:
                speaker.say(t.text)

    mapwatch = MapWatch(gd) if cfg.get("map_alerts", True) else None
    skills = SkillWatch()
    timers = TimerWatch(enabled=cfg.get("timer_alerts", True))
    matchlog = MatchLog(gd)
    events = EventWatch(gd)
    courier = CourierTracker(gd)
    bench: dict[int, dict] = {}
    hero_info: dict[int, tuple] = {}  # héroe → (SkillPlan, detalles de STRATZ); se piden una vez en segundo plano
    hero_synergy: dict[int, list] = {}  # héroe → con quién gana más (para tu compañero de línea)
    lane_ai: dict[tuple, list[str]] = {}  # combinación de la línea → consejos de la IA (una vez por combinación)       # héroe → referencias de OpenDota (se piden una vez, en segundo plano)

    def extra_context(st: GameState) -> list[str]:
        """Lo que la IA no sabría solo con el estado del héroe: mapa, líneas, plan de compra, percentiles."""
        lines = []
        if mapwatch:
            lanes = mapwatch.lanes()
            if any(i.allies or i.enemies for i in lanes.values()):
                lines.append("Lanes: " + "; ".join(
                    f"{lane}: {', '.join(h.loc for h in i.allies) or '-'} vs {', '.join(h.loc for h in i.enemies) or '-'}"
                    for lane, i in lanes.items()) + f" (my lane: {mapwatch.my_lane() or '?'})")
            missing = [mapwatch._name(n) for n, (t, _, _) in mapwatch.last_seen.items() if st.clock - t > 20]
            if missing:
                lines.append("Enemies not seen on the minimap for 20+ s: " + ", ".join(missing))
        sugg = advisor.suggestions(st)
        if sugg:
            from .engine.counters import build_plan, next_purchase
            plan = build_plan(gd, sugg[0].item, st.all_items)
            if plan:
                lines.append(f"Plan for {sugg[0].loc}: " + ", ".join(
                    ("owned " if s.owned else "") + f"{s.loc} ({s.to_pay})" for s in plan))
                nxt = next_purchase(plan, st.gold)
                if nxt:
                    lines.append(f"Affordable now: {nxt.loc} ({nxt.to_pay})")
        hero = advisor.my_hero(st)
        pct = {} if st.turbo else benchmarks.live_percentiles(bench.get(hero.id, {}) if hero else {}, st.gpm,
                                                              st.xpm, st.last_hits, st.clock)
        if pct:
            lines.append("Percentiles vs other players of this hero: " +
                         ", ".join(f"{k} {benchmarks.describe(v)}" for k, v in pct.items()))
        ult_line = ults.context(st.clock)
        if ult_line:
            lines.append(ult_line)
        soon = [t for t in upcoming(st.clock) if t.seconds_left <= 60 and t.key in ("bounty", "power", "wisdom")]
        if soon:
            lines.append("Upcoming: " + ", ".join(f"{t.label} in {t.seconds_left}s" for t in soon))
        return lines

    stats_src = Sources(cfg.get("rank_bracket", 0))  # STRATZ (tu rango) o, de respaldo, OpenDota
    advisor = Advisor(gd, meta, cfg, provider, on_tips, popularity=stats_src.popularity,
                      extra_context=extra_context)
    advisor.set_enemies(list(manual_enemies))
    current = {"team": "", "hero": None, "game": 0, "st": None}

    # ---------- definitivas enemigas (las marcas tú con Ctrl+F1…F5) ----------
    ult_info: dict[int, object] = {}   # id del héroe → Ult | None (datos de Valve, se piden una vez)

    def ult_of(hero: Hero):
        if hero.id not in ult_info:
            from .engine.skillbuild import valve_hero
            try:
                ult_info[hero.id] = ult_from_herodata(valve_hero(hero.id))
            except Exception:
                log.exception("no se pudo leer la definitiva de %s", hero.loc)
                return None  # se reintenta la próxima vez
        return ult_info[hero.id]

    ult_of.cache = ult_info
    ults = UltTracker(ult_of)

    def prefetch_ults():
        missing = [h for h in advisor.enemies.values() if h.id not in ult_info]
        if missing:
            threading.Thread(target=lambda: [ult_of(h) for h in missing], daemon=True).start()

    def confirmed_slots(st: GameState) -> dict[int, int]:
        """héroe → hueco 0-4 de su bando, solo los que la visión ha reconocido (para el rótulo bajo su retrato)."""
        first = 5 if st.team == "radiant" else 0
        return {h.id: pid - first for pid, h in heroes_by_player(st).items() if first <= pid < first + 5}

    def enemy_slots(st: GameState) -> list:
        return enemy_order(heroes_by_player(st), st.team, list(advisor.enemies.values()))

    def ult_hotkey(slot: int, clear: bool):
        st = current["st"]
        if st is None or not st.in_game:
            return
        hero = enemy_slots(st)[slot]
        if hero is None:
            if panel:
                panel.post("toast", {"title": "Definitivas", "level": "warn", "icon": "ult",
                                     "text": f"Todavía no sé qué enemigo hay en el hueco {slot + 1}."})
            return
        if clear:
            if ults.clear(hero) and panel:
                panel.post("toast", {"title": hero.loc, "text": "Definitiva lista otra vez (quitada la cuenta).",
                                     "level": "info", "icon": "ult"})
        else:
            t = ults.cast(hero, st.clock, st.level)
            if panel:
                if t is None:
                    text = "No tengo los datos de su definitiva (¿sin red?)."
                elif t.ready_max <= t.cast_at:
                    text = f"{t.ult.loc} no tiene enfriamiento."
                else:
                    lo, hi = t.remaining(st.clock)
                    when = fmt_seconds(lo) if lo == hi else f"{fmt_seconds(lo)}-{fmt_seconds(hi)}"
                    text = f"{t.ult.loc} usada: lista en {when} (estimado)"
                panel.post("toast", {"title": hero.loc, "text": text, "level": "info", "icon": "ult"})
        push_view(st, force=True)
    view_lock = threading.Lock()
    last_view = {"t": 0.0, "key": None}
    similar_key = {"k": None}
    draft_key = {"k": None}

    # ---------- tareas en segundo plano ----------
    def ensure_bench(hero: Hero | None):
        if hero is None or hero.id in bench:
            return
        bench[hero.id] = {}

        def job():
            try:
                bench[hero.id] = benchmarks.fetch(hero.id)
            except Exception as e:
                log.warning("sin referencias de OpenDota para %s: %s", hero.loc, e)
        threading.Thread(target=job, daemon=True).start()

    def ensure_hero_info(hero: Hero | None):
        if hero is None or hero.id in hero_info:
            return
        hero_info[hero.id] = (None, None)

        def job():
            from .engine.skillbuild import build_plan, valve_hero
            try:
                hero_synergy[hero.id] = stats_src.synergy(hero.id)
            except Exception:
                hero_synergy[hero.id] = []
            details = stats_src.hero_details(hero.id)
            if not details:
                return
            try:
                hero_info[hero.id] = (build_plan(valve_hero(hero.id), details), details)
            except Exception:
                log.exception("no se pudo preparar el orden de habilidades de %s", hero.loc)
        threading.Thread(target=job, daemon=True).start()

    def lane_tips_with_ai(rep):
        """Consejos de la IA para tu línea, una vez por combinación de héroes (en segundo plano)."""
        if provider is None or rep.key in lane_ai or not rep.opponents:
            return
        lane_ai[rep.key] = []

        def job():
            from .ai.prompts import REVIEW_SCHEMA, lane_prompt
            from .engine.laning import lane_context
            system, user = lane_prompt(lane_context(rep, gd), cfg.get("lang", "es"))
            try:
                data = json.loads(provider.complete(system, user, schema=REVIEW_SCHEMA, effort="low",
                                                    max_tokens=2000, timeout=40))
                lane_ai[rep.key] = [str(n).strip() for n in data.get("notes", []) if str(n).strip()][:3]
            except Exception as e:
                log.warning("la IA no pudo dar consejos de línea: %s", e)
        threading.Thread(target=job, daemon=True).start()

    def search_similar(st: GameState):
        """Partidas parecidas (OpenDota) cuando cambian tu héroe o los primeros enemigos."""
        hero, enemies = advisor.my_hero(st), list(advisor.enemies.values())[:3]
        if not panel or not hero or not enemies or not st.in_game:
            return
        key = (hero.id, tuple(h.id for h in enemies))
        if key == similar_key["k"]:
            return
        similar_key["k"] = key
        panel.post("similar_searching")

        def job():
            try:
                result = find_similar(gd, hero, enemies)
            except Exception:
                log.exception("no se pudieron buscar partidas parecidas")
                result = None
            if similar_key["k"] == key:
                advisor.standard = result.standard() if result else {}
                panel.post("similar", result)
        threading.Thread(target=job, daemon=True).start()

    def update_draft(st: GameState):
        if not panel or not is_drafting(st):
            return
        view = draft_state(gd, st, list(advisor.allies.values()), list(advisor.enemies.values()))
        if view.key == draft_key["k"]:
            return
        draft_key["k"] = view.key

        def job():
            try:
                src = Sources(cfg.get("rank_bracket", 0))
                view.picks = suggest_picks(gd, view.enemies, view.allies, cfg.get("role", "auto"), meta,
                                           src.matchups, limit=8, banned=view.bans, synergy=src.synergy)
                view.stats_source = " + ".join(sorted(set(src.last_source.values()))) or "meta"
            except Exception:
                log.exception("no se pudieron calcular los picks")
            if draft_key["k"] == view.key:
                panel.post("draft", view)
        threading.Thread(target=job, daemon=True).start()

    def finish_match():
        """Informe al acabar la partida (o al empezar otra si la anterior se abandonó)."""
        if not matchlog.worth_reporting:
            return
        hero = gd.hero(matchlog.st.hero) if matchlog.st else None
        report = matchlog.finish(bench.get(hero.id) if hero else None)
        if not report:
            return
        try:
            path = save(report)
            log.info("informe de la partida: %s", path)
        except OSError:
            log.exception("no se pudo guardar el informe")
        print("Fin de la partida: " + report.summary())
        for n in report.notes:
            print(" · " + n)
        if panel:
            panel.post("report", report)
            panel.post("history", history(load_reports(30)))
        if provider is not None:
            threading.Thread(target=review_with_ai, args=(report,), daemon=True).start()

    def review_with_ai(report: MatchReport):
        system, user = review_prompt(json.dumps(report.to_json(), ensure_ascii=False), cfg.get("lang", "es"))
        try:
            data = json.loads(provider.complete(system, user, schema=REVIEW_SCHEMA, effort="medium",
                                                max_tokens=4000, timeout=90))
            report.ai_notes = [str(n).strip() for n in data.get("notes", []) if str(n).strip()][:3]
        except Exception as e:
            log.warning("la IA no pudo analizar la partida: %s", e)
            return
        try:
            save(report)
        except OSError:
            pass
        if panel:
            panel.post("report", report)

    def push_view(st: GameState, force: bool = False):
        """Manda al panel lo que hay que pintar: como mucho una vez por segundo, salvo cambios importantes."""
        if not panel:
            return
        key = (st.hero, st.gold // 50, tuple(st.all_items), len(advisor.enemies), len(advisor.allies), st.alive,
               st.in_game, st.clock // 5)
        now = time.time()
        with view_lock:
            if not force and key == last_view["key"] and now - last_view["t"] < 1.0:
                return
            last_view.update(t=now, key=key)
        try:
            v = build_view(advisor, meta, st, mapwatch=mapwatch, ults=ults, enemy_slots=enemy_slots(st),
                           ult_keys=bool(hotkeys), confirmed_slots=confirmed_slots(st))
            hero = advisor.my_hero(st)
            # en turbo el oro y la experiencia no se comparan con partidas normales
            v.percentiles = {} if st.turbo else benchmarks.live_percentiles(
                bench.get(hero.id, {}) if hero else {}, st.gpm, st.xpm, st.last_hits, st.clock)
            v.drafting = is_drafting(st)
            plan, details = hero_info.get(hero.id, (None, None)) if hero else (None, None)
            if hero and mapwatch and st.in_game and st.clock < (8 if st.turbo else 15) * 60:  # fase de líneas
                from .engine.laning import build_report
                rep = build_report(gd, mapwatch, hero, st.clock, details, hero_synergy.get(hero.id))
                if rep:
                    lane_tips_with_ai(rep)
                    rep.ai_tips = lane_ai.get(rep.key, [])
                    v.lane_report = rep
            if plan:
                from .engine.skillbuild import lane_outlook, next_skill
                from .engine.skills import unspent_points
                v.skill_plan = plan
                v.skill_now = next_skill(plan, st) if unspent_points(st) else None
                if mapwatch and details and mapwatch.my_lane():
                    rivals = [h.id for h in mapwatch.lanes()[mapwatch.my_lane()].enemies]
                    v.lane_outlook = lane_outlook(details, rivals)
            v.events = events.state
            panel.post("view", v)
        except Exception:
            log.exception("no se pudo preparar el panel")

    # ---------- visión ----------
    scanner = None
    if cfg.get("vision", True):
        from .vision.topbar import SIDES, HeroMatcher, TopbarScanner

        def known_heroes(side: str) -> list[Hero]:
            if not current["team"]:
                return []
            if side == current["team"]:
                return [h for h in [current["hero"], *advisor.allies.values()] if h]
            return list(advisor.enemies.values())

        def on_heroes(confirmed: dict[int, Hero]):
            if not current["team"]:
                return
            mine = SIDES[current["team"]]
            advisor.set_allies([h for pid, h in confirmed.items() if pid in mine])
            advisor.set_enemies([h for pid, h in confirmed.items() if pid not in mine])

        scanner = TopbarScanner(HeroMatcher(gd), on_heroes, cfg.get("topbar"), known_heroes=known_heroes)
        scanner.start()

    def heroes_by_player(st: GameState) -> dict[int, Hero]:
        """player_id → héroe: los huecos de la barra superior siguen el orden de los player_id (0-4 Radiant,
        5-9 Dire); tú, por GSI."""
        out = dict(scanner.confirmed) if scanner and scanner.mode == "game" else {}
        me = advisor.my_hero(st)
        if me and st.player_id is not None:
            out[st.player_id] = me
        return out

    # ---------- cada envío de Dota ----------
    def on_state(st: GameState):
        st.in_transit = courier.update(st)  # lo que lleva el courier cuenta como tuyo para la build
        current["st"] = st
        current["team"] = st.team if st.team in ("radiant", "dire") else ""
        current["hero"] = gd.hero(st.hero) if st.hero else None
        advisor.update(st)  # detecta también la partida nueva (contra bots el match_id es siempre "0")
        if advisor.games.serial != current["game"]:
            current["game"] = advisor.games.serial
            finish_match()  # la anterior se dejó a medias: informe de lo que hubo
            for part in (scanner, mapwatch, skills, timers, matchlog, events, courier, ults):
                if part:
                    part.reset()
            similar_key["k"] = draft_key["k"] = None
            if panel:
                panel.post("reset")
        active = st.in_game or is_drafting(st)
        if scanner:
            scanner.set_mode("draft" if is_drafting(st) else "game")
            (scanner.active.set if active else scanner.active.clear)()
        if feed:
            (feed.active.set if st.in_game else feed.active.clear)()
        hero = advisor.my_hero(st)
        ensure_bench(hero)
        ensure_hero_info(hero)
        plan = hero_info.get(hero.id, (None, None))[0] if hero else None
        timers.role = item_role(hero, cfg.get("role", "auto"))
        map_alerts = mapwatch.update(st) if mapwatch else []
        alerts = [Tip("map", a.text, "map", a.clock) for a in map_alerts]
        notices = events.update(st, heroes_by_player(st))
        if mapwatch:
            for k in events.state.kills:
                if k.victim and k.killer_enemy is False and st.clock - k.clock <= 5:
                    mapwatch.mark_dead(k.victim.name, k.clock)   # muerto: no está "desaparecido"
        alerts += [Tip("warning", n.text, "rules", n.clock) for n in notices]
        if panel and cfg.get("toasts", True):
            titles = {"mia": ("Enemigo desaparecido", "warn"), "near": ("¡Gank!", "danger"), "tp": ("TP enemigo", "warn")}
            for a in map_alerts:
                title, level = titles.get(a.kind, ("Mapa", "info"))
                panel.post("toast", {"title": title, "text": a.text, "level": level, "icon": a.kind})
            for n in notices:
                if n.toast:
                    panel.post("toast", {"title": n.title, "text": n.text, "level": n.level, "icon": n.kind})
        prefetch_ults()
        for t in ults.update(st.clock):
            text = f"{t.ult.loc} de {t.hero.loc} puede estar lista ya (estimado)"
            alerts.append(Tip("warning", text, "rules", st.clock))
            if panel and cfg.get("toasts", True):
                panel.post("toast", {"title": "Definitiva enemiga", "text": text, "level": "warn", "icon": "ult"})
        alerts += [Tip("play", a.text, "rules", a.clock) for a in skills.update(st, plan)]
        alerts += [Tip("timer", a.text, "rules", a.clock) for a in timers.update(st.clock, st.in_game)]
        if alerts:
            on_tips(alerts)
        matchlog.update(st)
        if st.game_state == POST_GAME:
            finish_match()
        update_draft(st)
        push_view(st)
        search_similar(st)

    hotkeys = None
    if panel and cfg.get("ult_hotkeys", True):
        from .winkeys import GlobalHotkeys
        hotkeys = GlobalHotkeys()
        hotkeys.set({**{f"ult{i + 1}": (f"ctrl+f{i + 1}", lambda i=i: ult_hotkey(i, False)) for i in range(ULT_KEYS)},
                     **{f"ult{i + 1}_lista": (f"ctrl+shift+f{i + 1}", lambda i=i: ult_hotkey(i, True))
                        for i in range(ULT_KEYS)}})
        if hotkeys.failed:
            panel.post("toast", {"title": "Atajos de definitivas", "level": "warn", "icon": "ult",
                                 "text": "Windows no dejó registrar: " + ", ".join(hotkeys.failed)})

    recorder = GSIRecorder(config.APP_DIR / "gsi_record.jsonl") if cfg.get("record_gsi", True) else None
    gsi = GSIServer(cfg["gsi_port"], on_state, recorder)
    feed = None
    if panel and cfg.get("minimap_feed", True):
        from .vision.minimap import MinimapFeed
        feed = MinimapFeed(lambda frame: panel.post("minimap", frame), cfg.get("minimap"))
        feed.start()
    gsi.start()
    if panel:
        panel.post("history", history(load_reports(30)))
        if cfg.get("check_updates", True) and not os.environ.get("COACH_OFFLINE"):
            def check_app_update():
                from . import selfupdate
                try:
                    info = selfupdate.check_latest()
                except Exception:
                    return
                if info:
                    panel.post("toast", {"title": f"Dota Coach {info.version}",
                                         "text": "Hay una versión nueva: actualiza desde los ajustes.",
                                         "level": "info", "icon": "patch"})
            threading.Thread(target=check_app_update, daemon=True).start()
        if update is not None:
            from .data.updater import heroes_without_traits
            update.missing_traits = heroes_without_traits(gd)
            if update.new_patch or update.missing_traits:
                panel.post("toast", {"title": "Parche " + (update.latest or ""), "text": update.message(),
                                     "level": "info", "icon": "patch"})
    if overlay:
        overlay.push("status", f"Dota Coach listo · parche {meta.patch} · {ai_label}")
    print(f"Dota Coach en marcha (parche {meta.patch}, {ai_label}). Ctrl+C para salir.")

    def poll():  # deja que Ctrl+C llegue al intérprete; y se cierra solo si should_stop lo pide
        if should_stop and should_stop():
            log.info("Dota se ha cerrado: cierro el coach")
            finish_match()
            root.destroy()
            return
        root.after(1000, poll)

    poll()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            finish_match()  # cerrar el panel a mitad de partida también deja informe
        except Exception:
            log.exception("no se pudo cerrar el informe de la partida")
        gsi.stop()
        if hotkeys:
            hotkeys.stop()
        if feed:
            feed.stop()
        if scanner:
            scanner.stop()
