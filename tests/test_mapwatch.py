"""Vigilancia del mapa con posiciones sintéticas (mismas coordenadas que manda GSI)."""
from coach.engine.mapwatch import MapWatch, zone
from coach.gsi import GameState, MapUnit

JUGG, PA, RIKI, LION, CM = (f"npc_dota_hero_{n}" for n in
                            ("juggernaut", "phantom_assassin", "riki", "lion", "crystal_maiden"))
BOT_LANE = (5000, -5800)
TOP_LANE = (-6000, 3000)
MID = (0, 0)


def _st(clock, units, alive=True):
    return GameState(match_id="0", game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", clock=clock, team="radiant",
                     hero=JUGG, hero_id=8, alive=alive,
                     units=[MapUnit(n, 3 if enemy else 2, x, y, enemy, n == JUGG) for n, enemy, (x, y) in units])


def test_zones_match_real_map():
    assert zone(-5808, 5064) == "top" and zone(-685, -604) == "mid" and zone(6351, -5143) == "bot"
    assert zone(-5920, -5352) == "base" and zone(5528, 5000) == "base" and zone(-2500, 2000) == "jungle"


def _laning(mw, until=120):
    for t in range(30, until, 2):
        mw.update(_st(t, [(JUGG, False, BOT_LANE), (CM, False, BOT_LANE), (PA, True, BOT_LANE),
                          (LION, True, TOP_LANE), (RIKI, True, MID)]))


def test_lanes_assignment(gd):
    mw = MapWatch(gd)
    _laning(mw)
    lanes = mw.lanes()
    assert mw.my_lane() == "bot"
    assert {h.loc for h in lanes["bot"].allies} == {"Juggernaut", "Crystal Maiden"}
    assert [h.loc for h in lanes["bot"].enemies] == ["Phantom Assassin"]
    assert [h.loc for h in lanes["top"].enemies] == ["Lion"] and [h.loc for h in lanes["mid"].enemies] == ["Riki"]


def test_mia_and_stranger_near_and_tp(gd):
    mw = MapWatch(gd)
    _laning(mw)
    # PA deja de verse en tu línea
    alerts = []
    for t in range(120, 150, 2):
        alerts += mw.update(_st(t, [(JUGG, False, BOT_LANE), (LION, True, TOP_LANE), (RIKI, True, MID)]))
    assert [a.kind for a in alerts] == ["mia"] and "Phantom Assassin" in alerts[0].text
    # Lion (de top) aparece junto a ti: gank; tu rival de línea solo no avisa
    near = mw.update(_st(152, [(JUGG, False, BOT_LANE), (LION, True, (5300, -5600)), (RIKI, True, MID)]))
    assert {a.kind for a in near} == {"tp", "near"}  # salta de top a tu lado: TP y peligro a la vez
    assert all("Lion" in a.text for a in near)
    quiet = MapWatch(gd)
    _laning(quiet)
    assert not quiet.update(_st(122, [(JUGG, False, BOT_LANE), (PA, True, (5200, -5700))]))
    # Riki salta de mid a top en 2 s: TP
    tp = mw.update(_st(154, [(JUGG, False, BOT_LANE), (RIKI, True, (-6200, 2000))]))
    assert any(a.kind == "tp" and "Riki" in a.text and "top" in a.text for a in tp)
