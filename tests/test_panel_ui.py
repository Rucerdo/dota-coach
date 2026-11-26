"""Panel de partida: actualizar con los mismos datos no recrea widgets (no parpadea). Usa COACH_HOME temporal."""
import json

import pytest

from coach.config import DEFAULTS
from coach.engine.advisor import Advisor, Tip
from coach.gsi import GameState
from coach.ui.view import build_view

pytest.importorskip("customtkinter")


@pytest.fixture
def panel():
    from coach.ui.panel import Panel
    try:
        p = Panel(json.loads(json.dumps(DEFAULTS)), "7.42a", "sin IA")
    except Exception as ex:
        pytest.skip(f"sin Tk: {ex}")
    p.withdraw()
    p.images._get = lambda *a, **k: None  # sin red ni disco: sin iconos
    yield p
    p.destroy()


def _widgets(w) -> set[int]:
    out = {id(w)}
    for c in w.winfo_children():
        out |= _widgets(c)
    return out


def test_same_data_does_not_recreate_widgets(gd, panel):
    adv = Advisor(gd, None, json.loads(json.dumps(DEFAULTS)), None, sync=True)
    adv.set_enemies([gd.hero("pa"), gd.hero("Riki")])
    st = GameState(match_id="1", game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", clock=600, team="radiant",
                   hero="npc_dota_hero_juggernaut", hero_id=8, gold=1000)
    panel.post("view", build_view(adv, None, st))
    panel.post("tips", [Tip("item", "compra algo", "rules", 600)])
    panel._poll()
    before = _widgets(panel)
    for _ in range(3):
        panel.post("view", build_view(adv, None, st))
        panel._poll()
    assert _widgets(panel) == before
    assert panel.enemy_pool.rows[0]["name"].cget("text") in ("Phantom Assassin", "Riki")

    adv.set_enemies([gd.hero("Lion")])                # un enemigo más: solo se añade su fila
    panel.post("view", build_view(adv, None, st))
    panel._poll()
    after = _widgets(panel)
    assert before < after and len(panel.enemy_pool.rows) == 3


def test_panel_geometry_keeps_position_of_old_narrow_panel():
    from coach.ui.panel import panel_geometry
    assert panel_geometry("552x972+1935+14") == "1400x880+1935+14"
    assert panel_geometry("1500x900+10+10") == "1500x900+10+10"
    assert panel_geometry("") == "1400x880"
    assert panel_geometry("basura") == "1400x880"


def test_repaint_does_not_regrid_unmapped_widgets(gd, panel, monkeypatch):
    """La ventana está oculta (todo desmapeado, como lo que queda fuera de la vista): repintar con los mismos
    datos no debe volver a colocar nada. Antes la build por fases se recolocaba cada 300 ms y parpadeaba."""
    adv = Advisor(gd, None, json.loads(json.dumps(DEFAULTS)), None, sync=True)
    adv.set_enemies([gd.hero("pa"), gd.hero("Riki")])
    st = GameState(match_id="1", game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", clock=600, team="radiant",
                   hero="npc_dota_hero_juggernaut", hero_id=8, gold=1000)
    panel.post("view", build_view(adv, None, st))
    panel._poll()
    calls = []
    import tkinter
    for cls, method in ((tkinter.Grid, "grid"), (tkinter.Grid, "grid_configure"),
                        (tkinter.Pack, "pack"), (tkinter.Pack, "pack_configure")):
        orig = getattr(cls, method)
        monkeypatch.setattr(cls, method,
                            lambda self, *a, _o=orig, _m=method, **k: (calls.append((_m, str(self))), _o(self, *a, **k))[1])
    for _ in range(3):
        panel.post("view", build_view(adv, None, st))
        panel._poll()
    assert calls == []


def test_preferred_monitor_is_the_secondary():
    from coach.ui.monitors import Monitor, preferred_monitor
    main = Monitor(0, 0, 1920, 1050, True)
    second = Monitor(1920, 0, 1920, 1050, False)
    small = Monitor(-1280, 0, 1280, 984, False)
    assert preferred_monitor([main, second, small]) == second
    assert preferred_monitor([main]) == main and preferred_monitor([]) is None
    assert second.geometry == "1920x1050+1920+0"


def test_enemy_ult_countdown_in_panel(gd, panel):
    from coach.engine.ults import Ult, UltTracker, enemy_order
    adv = Advisor(gd, None, json.loads(json.dumps(DEFAULTS)), None, sync=True)
    pa, lion = gd.hero("pa"), gd.hero("Lion")
    adv.set_enemies([pa, lion])
    st = GameState(match_id="1", game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", clock=600, team="radiant",
                   hero="npc_dota_hero_juggernaut", hero_id=8, gold=1000, level=11)
    ults = UltTracker(lambda h: Ult("lion_finger_of_death", "Finger of Death", [100, 80, 60]))
    slots = enemy_order({5: lion, 6: pa}, "radiant", [pa, lion])
    ults.cast(lion, 600, 11)
    v = build_view(adv, None, st, ults=ults, enemy_slots=slots, ult_keys=True)
    assert [e.hero.loc for e in v.enemies] == ["Lion", "Phantom Assassin"]   # orden de la barra = de los atajos
    assert v.enemies[0].hotkey == "Ctrl+F1" and v.enemies[0].ult_left == (80, 100)
    assert v.enemies[1].hotkey == "Ctrl+F2" and v.enemies[1].ult_left is None
    panel.post("view", v)
    panel._poll()
    row = panel.enemy_pool.rows[0]
    assert row["ult_text"].cget("text") == "80-100" and row["ult_box"].winfo_manager()


def test_ult_badges_under_enemy_portraits(gd, panel):
    from coach.ui.ultbadges import UltBadges, badge_text
    from coach.ui.view import HeroCard, MatchView
    assert badge_text(80, 100) == ("1:20-1:40", "cd") and badge_text(0, 8) == ("≤8", "maybe")
    assert badge_text(0, 0) == ("LISTA", "ready") and badge_text(30, 30) == ("30", "cd")
    front = {"v": True}
    badges = UltBadges(panel, client_rect=lambda: (0, 0, 1920, 1080), in_front=lambda: front["v"])
    lion, pa = gd.hero("Lion"), gd.hero("pa")
    v = MatchView(in_game=True, team="radiant", enemies=[
        HeroCard(lion, slot=0, ult_left=(80, 100)),
        HeroCard(pa, slot=None, ult_left=(10, 10)),        # hueco sin reconocer: no se pinta en el juego
        HeroCard(gd.hero("riki"), slot=2)])                 # sin marcar: nada
    badges.update(v)
    assert list(badges.badges) == [5] and badges.badges[5].shown
    x, y, w, h = badges.box(5, (0, 0, 1920, 1080))
    assert 960 + 135 - 33 <= x < 960 + 135 and y >= 39                 # bajo el primer retrato de Dire
    front["v"] = False                                                  # alt+tab: se esconden
    badges.update(v)
    assert not badges.badges[5].shown
    badges.destroy()


def test_stale_toasts_are_dropped(panel):
    import time
    from coach.ui.toast import MAX_AGE, ToastManager
    m = ToastManager(panel, "panel")
    m.show("Viejo", "de hace rato", created=time.time() - MAX_AGE - 1)
    assert not m.toasts                                          # caducado: no se enseña
    m.show("Nuevo", "ahora")
    assert len(m.toasts) == 1
    for t in m.toasts:
        t.win.destroy()
