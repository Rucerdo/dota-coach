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
    # Lion (de top) llega a tu lado junto a PA: 2 contra 1, gank; el salto de Lion se confirma como TP al seguir allí
    gank = [(JUGG, False, BOT_LANE), (LION, True, (5300, -5600)), (PA, True, (5200, -5700)), (RIKI, True, MID)]
    near = mw.update(_st(152, gank))
    assert [a.kind for a in near] == ["near"] and "Lion" in near[0].text and "Phantom Assassin" in near[0].text
    assert [a.kind for a in mw.update(_st(154, gank))] == ["tp"]
    quiet = MapWatch(gd)
    _laning(quiet)
    assert not quiet.update(_st(122, [(JUGG, False, BOT_LANE), (PA, True, (5200, -5700))]))
    # Riki salta de mid a top en 2 s: TP
    assert not mw.update(_st(156, [(JUGG, False, BOT_LANE), (RIKI, True, (-6200, 2000))]))
    tp = mw.update(_st(158, [(JUGG, False, BOT_LANE), (RIKI, True, (-6150, 2050))]))
    assert any(a.kind == "tp" and "Riki" in a.text and "top" in a.text for a in tp)


def test_no_near_alert_at_game_start_or_in_base(gd):
    mw = MapWatch(gd)
    fountain = (-6900, -6400)
    assert not mw.update(_st(-60, [(JUGG, False, fountain), (PA, True, (-6600, -6100)), (LION, True, (-6700, -6300))]))
    assert not mw.update(_st(20, [(JUGG, False, MID), (PA, True, (100, 100)), (LION, True, (-100, 50)),
                                  (RIKI, True, (50, -50))]))


def test_clones_count_once_and_do_not_fake_tps(gd):
    """El clon de Arc Warden (mismo nombre) no cuenta como otro héroe ni parece un TP."""
    arc = "npc_dota_hero_arc_warden"
    gd.heroes[113] = type(gd.hero("pa"))(113, arc, "Arc Warden", ["Carry"], "Ranged")
    gd._hero_index["arcwarden"] = gd.heroes[113]
    mw = MapWatch(gd)
    for t in range(30, 120, 2):
        mw.update(_st(t, [(JUGG, False, BOT_LANE), (arc, True, (5100, -5700)), (PA, True, (5200, -5600))]))
    clones = [(JUGG, False, BOT_LANE), (arc, True, (5100, -5700)), (arc, True, (5150, -5650)),
              (PA, True, (5200, -5600))]
    assert not mw.update(_st(122, clones))                       # 2 héroes de tu línea, no 3: nada
    far = [(JUGG, False, BOT_LANE), (arc, True, (5100, -5700)), (arc, True, (-6000, 3000)), (PA, True, (5200, -5600))]
    assert not [a for a in mw.update(_st(124, far)) if a.kind == "tp"]


def test_ganking_another_lane_is_not_a_gank_on_you(gd):
    mw = MapWatch(gd)
    _laning(mw)
    # tú (bot) vas a top con CM a por Lion: no es que te ganken a ti
    top = (-6000, 3000)
    assert not mw.update(_st(130, [(JUGG, False, top), (CM, False, top), (LION, True, (-6100, 3100))]))


def test_dead_enemy_is_not_missing(gd):
    mw = MapWatch(gd)
    _laning(mw)
    mw.mark_dead(PA, 120)
    alerts = []
    for t in range(120, 170, 2):
        alerts += mw.update(_st(t, [(JUGG, False, BOT_LANE), (CM, False, BOT_LANE), (LION, True, TOP_LANE)]))
    assert not [a for a in alerts if a.kind == "mia"]


def test_a_single_position_glitch_is_not_a_tp(gd):
    """Grabación real: la Maiden 'salta' un instante a otro sitio y vuelve. No es un TP."""
    mw = MapWatch(gd)
    _laning(mw)
    alerts = mw.update(_st(120, [(JUGG, False, BOT_LANE), (PA, True, (200, 300))]))
    alerts += mw.update(_st(122, [(JUGG, False, BOT_LANE), (PA, True, (5200, -5600))]))
    alerts += mw.update(_st(124, [(JUGG, False, BOT_LANE), (PA, True, (5250, -5600))]))
    assert not [a for a in alerts if a.kind == "tp"]
