"""Guías elegidas: siguiente compra, desvío con propuesta adaptada, aceptar/rechazar y guardado."""
from coach.engine.buildpaths import BuildPaths
from coach.engine.guides import Guide, GuideFollower, guides_from_rows, rank
from test_buildpaths import _gd, _row


def test_guides_from_real_builds_and_ranking(gd):
    gd = _gd(gd)
    rows = [_row(1, ["phase", "bf", "bkb"]), _row(2, ["phase", "mjol", "blink"], enemies=[44, 26]),
            _row(3, ["phase", "bf"]), _row(4, ["phase", "bf", "mkb"], win=False)]
    guides = guides_from_rows(gd, 8, rows)
    assert [g.id for g in guides] == ["1", "2"]          # cortas (<3 objetos) y perdidas fuera
    assert rank(guides, {44}, set())[0].id == "2"         # la que jugó contra PA, primero
    g = Guide.from_dict(guides[0].to_dict())
    assert g.items == ["item_phase_boots", "item_bfury", "item_black_king_bar"]


def test_follow_guide_and_adapt_when_you_deviate(gd):
    gd = _gd(gd)
    paths = BuildPaths(gd)
    paths.add([_row(10, ["phase", "mjol", "blink"]), _row(11, ["phase", "mjol", "blink", "bkb"]),
               _row(12, ["phase", "bf", "bkb"])])
    f = GuideFollower(gd)
    f.choose(guides_from_rows(gd, 8, [_row(1, ["phase", "bf", "bkb", "mkb"])])[0])
    assert f.next_items({"item_phase_boots"}) == ["item_bfury", "item_black_king_bar"]
    assert f.deviation(["item_phase_boots"], ["item_phase_boots"], paths, set(), set()) is None  # vas bien
    # compras Mjollnir en vez de Battle Fury: los que hicieron eso siguieron con Blink
    bought = ["item_phase_boots", "item_mjollnir"]
    dev = f.deviation(bought, bought, paths, set(), set())
    assert dev.item == "item_mjollnir" and dev.suggestion == "item_blink" and dev.guide_next == "item_bfury"
    f.dismiss(dev)                                                       # "seguir con mi guía"
    assert f.deviation(bought, bought, paths, set(), set()) is None
    f.dismissed.clear()
    f.accept(f.deviation(bought, bought, paths, set(), set()))          # "aceptar y adaptar"
    assert f.guide.source == "adaptada" and f.guide.items[:3] == ["item_phase_boots", "item_mjollnir", "item_blink"]
    assert f.next_items(set(bought)) == ["item_blink"]


def test_view_uses_guide_for_next_purchase(gd):
    import json
    from coach.config import DEFAULTS
    from coach.engine.advisor import Advisor
    from coach.gsi import GameState
    from coach.ui.view import build_view
    gd = _gd(gd)
    adv = Advisor(gd, None, json.loads(json.dumps(DEFAULTS)), None, sync=True)
    adv.follower.choose(guides_from_rows(gd, 8, [_row(1, ["phase", "bf", "bkb"])])[0])
    st = GameState(match_id="1", game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", clock=400, team="radiant",
                   hero="npc_dota_hero_juggernaut", hero_id=8, gold=900, items=["item_phase_boots"])
    adv.update(st)
    v = build_view(adv, None, st)
    assert v.guide and (v.guide.done, v.guide.total) == (1, 3)
    assert v.next_item.name == "item_bfury" and "tu guía" in v.next_item.reasons[0]
    assert v.deviation is None
