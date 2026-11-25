"""Registro de la partida, informe al acabar e historial (sin red; COACH_HOME temporal)."""
from coach.engine.matchlog import MatchLog, history, load_reports, save
from coach.gsi import GameState, MapUnit

JUGG, PA, LION = "npc_dota_hero_juggernaut", "npc_dota_hero_phantom_assassin", "npc_dota_hero_lion"


def _st(clock, deaths=0, alive=True, items=(), near=(), lh=0, gpm=300, win=""):
    units = [MapUnit(JUGG, 2, 5000, -5800, False, True)] + [MapUnit(n, 3, 5200, -5700, True) for n in near]
    return GameState(match_id="0", game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", clock=clock, team="radiant",
                     hero=JUGG, hero_id=8, deaths=deaths, alive=alive, items=list(items), units=units,
                     last_hits=lh, gpm=gpm, win_team=win)


def test_match_report(gd):
    log = MatchLog(gd)
    log.update(_st(60))
    log.update(_st(200, items=["item_bfury"]))
    log.update(_st(250, near=[PA]))
    log.update(_st(252, deaths=1, alive=False))                   # muere con PA a la vista
    log.update(_st(400, deaths=1))
    log.update(_st(470, deaths=2, alive=False))                   # muere sin nadie a la vista
    log.update(_st(520, deaths=2))
    log.update(_st(560, deaths=3, alive=False))
    log.update(_st(605, deaths=3, lh=31))
    log.update(_st(1500, deaths=3, lh=120, gpm=520, win="radiant"))
    bench = {"gold_per_min": [(0.1, 300.0), (0.9, 600.0)], "last_hits_per_min": [(0.1, 4.0), (0.9, 9.0)]}
    r = log.finish(bench)
    assert r.result == "win" and r.lh_at_10 == 31 and r.deaths == 3
    assert r.items == [("Battle Fury", 200)]
    assert [d.enemies_near for d in r.death_list] == [["Phantom Assassin"], [], []]
    assert all(d.zone == "bot" for d in r.death_list)
    assert any("niebla" in n for n in r.notes) and any("bot" in n for n in r.notes)
    assert any("minuto 10" in n for n in r.notes)                 # 3.1 golpes/min: percentil bajo
    assert log.finish(bench) is None                              # solo una vez


def test_short_game_no_report(gd):
    log = MatchLog(gd)
    log.update(_st(60))
    assert log.finish() is None


def test_save_and_history(gd):
    log = MatchLog(gd)
    log.update(_st(60))
    log.update(_st(250, deaths=1, alive=False))
    log.update(_st(300, deaths=1))
    log.update(_st(420, deaths=2, alive=False))
    log.update(_st(700, deaths=2, win="dire"))
    r = log.finish()
    save(r)
    r.finished_at += 1
    save(r)
    reports = load_reports()
    assert len(reports) == 2 and reports[0].hero == "Juggernaut" and reports[0].result == "loss"
    h = history(reports)
    assert h.games == 2 and h.losses == 2 and h.avg_deaths == 2
    assert h.top_death_zone == "bot" and h.fog_death_share == 1.0
    assert any("niebla" in x for x in h.recurring)
