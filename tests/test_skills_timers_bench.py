"""Habilidades sin gastar, temporizadores y percentiles (sin red)."""
from coach.engine.benchmarks import live_percentiles, percentile
from coach.engine.skills import SkillWatch, unspent_points
from coach.engine.timers import TimerWatch, next_in, upcoming
from coach.gsi import GameState


def _st(clock, level, levels, ult_level=0, talents=0, alive=True):
    abilities = [{"name": f"a{i}", "level": lv, "ultimate": False} for i, lv in enumerate(levels)]
    abilities.append({"name": "ult", "level": ult_level, "ultimate": True})
    return GameState(game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", hero="npc_dota_hero_pudge", clock=clock, level=level,
                     abilities=abilities, talents=talents, alive=alive)


def test_unspent_points_and_alerts():
    assert unspent_points(_st(100, 5, [2, 3, 0])) == 0
    assert unspent_points(_st(100, 6, [2, 3, 0])) == 1
    w = SkillWatch()
    assert w.update(_st(100, 6, [2, 3, 0])) == []                      # acaba de subir: margen
    alert = w.update(_st(110, 6, [2, 3, 0]))
    assert alert and "definitiva" in alert[0].text
    assert w.update(_st(120, 6, [2, 3, 0])) == []                      # una vez por nivel
    w2 = SkillWatch()
    w2.update(_st(500, 10, [4, 3, 1], ult_level=1))
    assert "talento" in w2.update(_st(510, 10, [4, 3, 1], ult_level=1))[0].text
    w3 = SkillWatch()
    w3.update(_st(200, 4, [1, 1, 0]))
    assert "sin gastar" in w3.update(_st(210, 4, [1, 1, 0]))[0].text


def test_timers():
    assert next_in(170, 0, 180) == 10 and next_in(180, 0, 180) == 0 and next_in(100, 360, 120) == 260
    keys = {t.key: t.seconds_left for t in upcoming(350)}
    assert keys["power"] == 10 and keys["bounty"] == 10
    core = TimerWatch("core")
    texts = [a.text for a in core.update(350, True)]
    assert any("poder" in t for t in texts) and any("recompensa" in t for t in texts)
    assert core.update(352, True) == []                                # no se repite
    support = TimerWatch("support")
    assert not any("poder" in a.text for a in support.update(350, True))
    assert TimerWatch("core", enabled=False).update(350, True) == []


def test_percentiles():
    pts = [(0.1, 256), (0.5, 363), (0.9, 522)]
    assert percentile(363, pts) == 0.5
    assert 0.1 < percentile(300, pts) < 0.5
    assert percentile(1000, pts) == 0.9 and percentile(0, pts) == 0.0
    bench = {"gold_per_min": pts, "last_hits_per_min": [(0.1, 2.0), (0.9, 8.0)]}
    assert live_percentiles(bench, 400, 0, 50, 4 * 60) == {}            # antes del minuto 5 no se dice nada
    live = live_percentiles(bench, 363, 0, 50, 10 * 60)
    assert live["gold_per_min"] == 0.5 and 0.1 < live["last_hits_per_min"] < 0.9
