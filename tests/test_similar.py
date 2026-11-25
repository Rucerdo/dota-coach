"""Partidas parecidas: búsqueda que se relaja y resumen de lo que compraron los ganadores (sin red)."""
from coach.engine.similar import find_similar


def test_relaxes_query_and_summarizes_winning_builds(gd):
    calls = []

    def find(team_a, team_b):
        calls.append(len(team_b))
        if len(team_b) > 1:
            return []  # contra los dos a la vez no hay partidas
        return [{"match_id": i, "start_time": i} for i in range(1, 7)]

    def details(mid):
        win = mid % 2 == 0
        items = {"item_0": 145, "item_1": 135 if win else 116, "item_2": 36}  # wand (450) no cuenta
        return {"duration": 300 if mid == 6 else 2400,
                "players": [{"hero_id": 8, "win": int(win), **items}, {"hero_id": 44, "win": int(not win)}]}

    r = find_similar(gd, gd.hero("Juggernaut"), [gd.hero("pa"), gd.hero("Riki")], find, details)
    assert calls == [2, 1] and [h.loc for h in r.vs] == ["Phantom Assassin"]
    assert len(r.matches) == 5 and r.wins == 2          # la partida 6 (5 min) se descarta
    assert dict(r.top_items) == {"item_bfury": 2, "item_monkey_king_bar": 2}


def test_no_enemies_or_no_matches(gd):
    assert find_similar(gd, gd.hero("Juggernaut"), []) is None
    assert find_similar(gd, gd.hero("Juggernaut"), [gd.hero("pa")], lambda a, b: [], lambda m: {}) is None
