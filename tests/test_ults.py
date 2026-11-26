"""Definitivas enemigas marcadas a mano (Ctrl+F1…F5): enfriamiento estimado y orden de los huecos."""
from coach.engine.ults import Ult, UltTracker, cooldown_range, enemy_order, ult_from_herodata, ult_level

BLACK_HOLE = Ult("enigma_black_hole", "Black Hole", [180, 170, 160])


def test_ult_from_valve_herodata_skips_scepter_and_shard():
    hero = {"abilities": [
        {"name": "enigma_malefice", "type": 0, "cooldowns": [14]},
        {"name": "enigma_shard_thing", "type": 1, "ability_is_granted_by_shard": True, "cooldowns": [5]},
        {"name": "enigma_black_hole", "name_loc": "Black Hole", "type": 1, "cooldowns": [180, 170, 160]}]}
    ult = ult_from_herodata(hero)
    assert ult.name == "enigma_black_hole" and ult.cooldowns == [180, 170, 160]


def test_cooldown_range_by_estimated_level():
    assert ult_level(5) == 1 and ult_level(12) == 2 and ult_level(25) == 3
    assert cooldown_range(BLACK_HOLE, 7) == (180, 180)       # 5-9: solo nivel 1
    assert cooldown_range(BLACK_HOLE, 11) == (170, 180)      # 9-13: nivel 1 o 2
    assert cooldown_range(BLACK_HOLE, 25) == (160, 160)
    assert cooldown_range(Ult("juggernaut_omni_slash", "Omnislash", [120]), 18) == (120, 120)


def test_cast_countdown_and_single_warning(gd):
    enigma = gd.hero("pa")  # cualquier héroe del fixture
    tracker = UltTracker(lambda h: BLACK_HOLE)
    t = tracker.cast(enigma, clock=600, my_level=11)
    assert (t.ready_min, t.ready_max) == (770, 780)
    assert t.remaining(700) == (70, 80)
    assert not tracker.update(769)
    assert tracker.update(770) == [t] and not tracker.update(771)   # se avisa una vez
    assert tracker.get(enigma, 790) is t
    assert tracker.get(enigma, 841) is None                          # lista hace rato: se deja de mostrar
    tracker.cast(enigma, 900, 11)
    assert tracker.clear(enigma) and tracker.get(enigma, 901) is None


def test_enemy_order_follows_topbar_slots(gd):
    pa, lion, cm = gd.hero("pa"), gd.hero("lion"), gd.hero("cm")
    # Radiant: los enemigos son los player_id 5-9; el hueco 2 (pid 6) no se ha reconocido
    slots = enemy_order({5: lion, 7: pa, 0: cm}, "radiant", [pa, lion, cm])
    assert slots[0] is lion and slots[2] is pa and slots[1] is cm and slots[3] is None
    slots = enemy_order({0: lion}, "dire", [lion])
    assert slots[0] is lion
