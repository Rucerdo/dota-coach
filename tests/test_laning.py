"""Tu línea: rivales, cómo suele salir contra ti, si se ven y consejo por perfil."""
from coach.engine.laning import build_report, lane_context, lane_tip
from coach.engine.mapwatch import MapWatch
from tests.test_mapwatch import BOT_LANE, CM, JUGG, PA, _laning, _st


def test_lane_report(gd):
    mw = MapWatch(gd)
    _laning(mw)
    mw.update(_st(130, [(JUGG, False, BOT_LANE), (CM, False, BOT_LANE)]))   # PA deja de verse
    details = {"lanes": {gd.hero("pa").id: (1000, 300, 200, 500)}}
    syn = [{"hero_id": gd.hero("cm").id, "games": 200, "wins": 120}]
    rep = build_report(gd, mw, gd.hero("Juggernaut"), 140, details, syn)
    assert rep.lane == "bot" and [h.loc for h in rep.partners] == ["Crystal Maiden"]
    pa = rep.opponents[0]
    assert pa.hero.loc == "Phantom Assassin" and pa.outcome[2] == 0.5 and pa.seen_ago == 22 and not pa.visible
    assert pa.tip and rep.partner_wr["Crystal Maiden"] == (0.6, 200)
    ctx = lane_context(rep, gd)
    assert "Phantom Assassin" in ctx and "lose 50%" in ctx and "Crystal Maiden" in ctx


def test_lane_tip_by_traits(gd):
    assert "Dust" in lane_tip(gd.hero("Riki"))
    assert "definitiva" in lane_tip(gd.hero("Lion"))


def test_no_report_without_lane(gd):
    assert build_report(gd, MapWatch(gd), gd.hero("Juggernaut"), 10) is None
