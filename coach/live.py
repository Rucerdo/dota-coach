"""Modo en directo: GSI + visión de la barra superior + asesor + overlay (y voz opcional)."""
import logging
import tkinter as tk

from . import dota
from .ai import make_provider
from .data import opendota
from .data.gamedata import GameData, Hero
from .engine.advisor import Advisor, Tip
from .gsi import GameState, GSIServer
from .ui.overlay import Overlay

log = logging.getLogger(__name__)


def run_live(cfg: dict, gd: GameData, meta, manual_enemies: list[Hero] = ()):
    d = dota.normalize(cfg.get("dota_dir")) or dota.find_dota_dir()
    if d and not dota.is_installed(d, cfg["gsi_port"]):
        print(f"Instalando la integración GSI en {d} (reinicia Dota 2 una vez).")
        dota.install(d, cfg["gsi_port"])
    elif not d:
        print("⚠ No encuentro Dota 2: usa 'coach install --dota-dir ...'")

    root = tk.Tk()
    root.withdraw()
    overlay = Overlay(root, cfg["overlay"])
    speaker = None
    if cfg.get("tts"):
        from .ui.tts import Speaker
        speaker = Speaker()

    def on_tips(tips: list[Tip]):
        for t in tips:
            overlay.push(t.kind, t.text)
            print(f"[{t.kind}/{t.source}] {t.text}")
            if speaker:
                speaker.say(t.text)

    provider = make_provider(cfg)
    advisor = Advisor(gd, meta, cfg, provider, on_tips, popularity=opendota.item_popularity)
    advisor.set_enemies(list(manual_enemies))
    current = {"team": "", "hero": None, "match": ""}

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

    def on_state(st: GameState):
        current["team"] = st.team if st.team in ("radiant", "dire") else ""
        current["hero"] = gd.hero(st.hero) if st.hero else None
        if st.match_id != current["match"]:
            current["match"] = st.match_id
            if scanner:
                scanner.reset()
        if scanner:
            (scanner.active.set if st.in_game else scanner.active.clear)()
        advisor.update(st)

    gsi = GSIServer(cfg["gsi_port"], on_state)
    gsi.start()
    ai_label = f"IA: {provider.label}" if provider else "sin IA (reglas)"
    overlay.push("status", f"Dota Coach listo · parche {meta.patch} · {ai_label}")
    print(f"Dota Coach en marcha (parche {meta.patch}, {ai_label}). Ctrl+C para salir.")

    def poll():  # deja que Ctrl+C llegue al intérprete
        root.after(300, poll)

    poll()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        gsi.stop()
        if scanner:
            scanner.stop()
