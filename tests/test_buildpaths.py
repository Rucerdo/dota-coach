"""Build adaptativa: builds reales (STRATZ) que siguen tu mismo camino votan tu siguiente objeto."""
from coach.engine.buildpaths import BuildPaths, core_sequence


def _gd(gd):
    for name in ("item_phase_boots", "item_black_king_bar", "item_monkey_king_bar", "item_bfury", "item_mjollnir",
                 "item_pipe", "item_force_staff"):
        gd.item(name).components = ["item_magic_wand"]   # "fabricados" (los básicos sueltos no cuentan)
    return gd


def _row(match, items, enemies=(), win=True):
    ids = {"phase": 50, "bkb": 116, "mkb": 135, "bf": 145, "mjol": 158, "pipe": 127, "blink": 1, "wand": 36}
    return {"match": match, "win": win, "enemies": list(enemies), "allies": [],
            "purchases": [[ids[n], 5 + 5 * i] for i, n in enumerate(items)]}


def test_core_sequence_keeps_only_big_items_in_order(gd):
    gd = _gd(gd)
    core = core_sequence(gd, [[36, 3], [50, 6], [36, 8], [145, 14], [1, 16]])
    assert [n for n, _ in core] == ["item_phase_boots", "item_bfury", "item_blink"]


def test_next_item_follows_builds_like_yours(gd):
    gd = _gd(gd)
    paths = BuildPaths(gd)
    paths.add([_row(1, ["phase", "bf", "bkb"]), _row(2, ["phase", "bf", "bkb", "mkb"]),
               _row(3, ["phase", "mjol", "blink"]), _row(4, ["phase", "bf", "mkb"], enemies=[44]),
               _row(5, ["phase", "bf", "bkb"], win=False)])          # las perdidas no cuentan
    assert len(paths) == 4
    # llevas Phase y Battle Fury: las builds que hicieron lo mismo van a BKB (2) o MKB (1, contra PA)
    sugg = paths.suggest(["item_phase_boots", "item_bfury"], ["item_phase_boots", "item_bfury"], set(), set())
    assert max(sugg, key=lambda k: sugg[k][0]) == "item_black_king_bar"
    assert "item_mjollnir" not in sugg or sugg["item_mjollnir"][0] < sugg["item_black_king_bar"][0]
    # contra PA pesa la build que jugó contra PA
    vs_pa = paths.suggest(["item_phase_boots", "item_bfury"], ["item_phase_boots", "item_bfury"], {44}, set(),
                          {44: "Phantom Assassin"})
    assert "Phantom Assassin" in vs_pa["item_monkey_king_bar"][1]
    # si en vez de eso fuiste a Mjollnir, manda la build de Mjollnir
    other = paths.suggest(["item_phase_boots", "item_mjollnir"], ["item_phase_boots", "item_mjollnir"], set(), set())
    assert max(other, key=lambda k: other[k][0]) == "item_blink"


def test_bought_items_stay_ticked_in_their_phase(gd):
    import json
    from coach.config import DEFAULTS
    from coach.engine.advisor import Advisor
    from coach.gsi import GameState
    adv = Advisor(gd, None, json.loads(json.dumps(DEFAULTS)), None, sync=True)
    st = GameState(match_id="1", game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", clock=300, team="radiant",
                   hero="npc_dota_hero_juggernaut", hero_id=8, items=["item_phase_boots"])
    adv.phase_seen["early"] = ["item_magic_wand", "item_phase_boots"]
    adv.track_purchases(st)
    assert adv.done_in_phase("early", []) == ["item_phase_boots"]
    st.items = []                                      # vendido o usado: sigue marcado como comprado
    adv.track_purchases(st)
    assert adv.done_in_phase("early", []) == ["item_phase_boots"]
    st.clock, st.items = 1000, ["item_black_king_bar"]  # comprado por tu cuenta en mid
    adv.track_purchases(st)
    assert adv.done_in_phase("mid", []) == ["item_black_king_bar"]
