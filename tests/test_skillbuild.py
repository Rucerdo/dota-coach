"""Orden de habilidades, talentos y fase de líneas a partir de datos con el formato de Valve y STRATZ."""
from coach.engine.skillbuild import (build_plan, clean_talent, lane_outlook, next_skill, suggested_sequence,
                                      talent_for)
from coach.gsi import GameState

HERO = {"abilities": [{"id": 1, "name": "j_fury", "name_loc": "Blade Fury", "type": 0, "max_level": 4},
                      {"id": 2, "name": "j_ward", "name_loc": "Healing Ward", "type": 0, "max_level": 4},
                      {"id": 3, "name": "j_dance", "name_loc": "Blade Dance", "type": 0, "max_level": 4},
                      {"id": 4, "name": "j_form", "name_loc": "Bladeform", "type": 0, "max_level": 1},
                      {"id": 5, "name": "j_omni", "name_loc": "Omnislash", "type": 1, "max_level": 3}],
        "talents": [{"id": 10, "name_loc": "-{s:x}s Ward Cooldown"}, {"id": 11, "name_loc": "+{s:y} Stack"},
                    {"id": 12, "name_loc": "A"}, {"id": 13, "name_loc": "B"}]}
DETAILS = {"max_level": {1: {7: 900, 9: 100}, 3: {10: 800}, 2: {15: 700}},
           "talents": {10: (100, 50), 11: (700, 380), 12: (300, 150), 13: (100, 40)},
           "lanes": {14: (1000, 400, 300, 300), 31: (500, 150, 150, 200)}}


def _st(level, levels):
    return GameState(level=level, abilities=[{"name": n, "level": v, "ultimate": n == "j_omni"}
                                             for n, v in levels.items()])


def test_plan_order_and_talents():
    plan = build_plan(HERO, DETAILS)
    assert [a.loc for a in plan.order] == ["Blade Fury", "Blade Dance", "Healing Ward"]   # Bladeform (innata) fuera
    assert plan.ultimate.loc == "Omnislash" and "Omnislash en 6/12/18" in plan.summary()
    t10 = talent_for(plan, 10)
    assert t10.pick == "+X Stack" and t10.share == 0.875 and t10.other == "-Xs Ward Cooldown"
    assert clean_talent("-{s:bonus}s Cooldown") == "-Xs Cooldown"


def test_next_skill():
    plan = build_plan(HERO, DETAILS)
    assert next_skill(plan, _st(1, {})) == "Blade Fury"
    assert next_skill(plan, _st(2, {"j_fury": 1})) == "Blade Dance"           # un punto en cada una al principio
    assert next_skill(plan, _st(4, {"j_fury": 2, "j_dance": 1})) == "Blade Dance"  # Fury ya está al tope del nivel
    assert next_skill(plan, _st(6, {"j_fury": 3, "j_dance": 1, "j_ward": 1})) == "Omnislash"


def test_lane_outlook():
    win, draw, loss, games = lane_outlook(DETAILS, [14, 31])
    assert games == 1500 and round(win, 3) == round(550 / 1500, 3)
    assert lane_outlook(DETAILS, [99]) is None


def test_suggested_sequence_and_talent_options():
    plan = build_plan(HERO, DETAILS)
    seq = dict(suggested_sequence(plan))
    assert seq[1] == "j_fury" and seq[2] == "j_dance" and seq[6] == "j_omni" and seq[10] == "talent"
    assert seq[12] == "j_omni" and seq[18] == "j_omni"
    takes = [name for _, name in suggested_sequence(plan)]
    assert takes.count("j_fury") == 4 and takes.count("j_omni") == 3
    t10 = talent_for(plan, 10)
    assert t10.options == [("-Xs Ward Cooldown", 0.125), ("+X Stack", 0.875)] and t10.best == 1


def test_gsi_talent_flags():
    from coach.gsi import parse_state
    st = parse_state({"hero": {"name": "npc_dota_hero_juggernaut", "talent_2": True, "talent_3": False}})
    assert st.talent_flags[:3] == [False, True, False] and st.talents == 1
