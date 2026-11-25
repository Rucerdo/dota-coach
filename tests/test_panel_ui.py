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
