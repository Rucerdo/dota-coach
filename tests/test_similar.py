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


def test_standard_items_drive_suggestions(gd):
    from coach.engine.counters import suggest_items
    from coach.engine.similar import SimilarBuilds, SimilarMatch
    r = SimilarBuilds(gd.hero("Juggernaut"), [gd.hero("pa")], [
        SimilarMatch(1, True, 2400, ["item_bfury", "item_black_king_bar"]),
        SimilarMatch(2, True, 2400, ["item_bfury", "item_black_king_bar"]),
        SimilarMatch(3, True, 2400, ["item_bfury"]),
        SimilarMatch(4, False, 2400, ["item_mjollnir"])])
    std = r.standard()
    assert std["item_bfury"][0] == 1.0 and "3 de 3 ganadores" in std["item_bfury"][1]
    assert "item_mjollnir" not in std                       # solo lo llevó el que perdió
    names = [s.item for s in suggest_items(gd, gd.hero("Juggernaut"), [gd.hero("pa")], standard=std, phase="mid")]
    assert names.index("item_bfury") < names.index("item_monkey_king_bar")
