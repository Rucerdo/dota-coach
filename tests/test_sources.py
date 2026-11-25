"""STRATZ primero y OpenDota de respaldo (sin red: todo simulado)."""
from coach.data import opendota, sources, stratz


def test_stratz_first_then_opendota(monkeypatch):
    monkeypatch.setattr(stratz, "token", lambda cfg=None: "clave")
    big = [{"hero_id": i, "games": 1000, "wins": 520} for i in range(1, 40)]
    monkeypatch.setattr(stratz, "matchup", lambda hid, bracket=0: {"vs": big, "with": big})
    monkeypatch.setattr(opendota, "matchups", lambda hid: [{"hero_id": 1, "games_played": 5, "wins": 2}])
    monkeypatch.setattr(opendota, "synergy", lambda hid: [{"hero_id": 1, "games": 5, "wins": 2}])
    s = sources.Sources(bracket=5)
    assert s.matchups(8)[0] == {"hero_id": 1, "games_played": 1000, "wins": 520}
    assert s.synergy(8)[0]["games"] == 1000 and s.last_source == {"matchups": "STRATZ", "synergy": "STRATZ"}

    def broken(hid, bracket=0):
        raise stratz.StratzError("STRATZ: límite de peticiones alcanzado")
    monkeypatch.setattr(stratz, "matchup", broken)
    assert s.matchups(8) == [{"hero_id": 1, "games_played": 5, "wins": 2}]
    assert s.last_source["matchups"] == "OpenDota"


def test_without_key_uses_opendota(monkeypatch):
    monkeypatch.setattr(stratz, "token", lambda cfg=None: "")
    monkeypatch.setattr(opendota, "synergy", lambda hid: [{"hero_id": 2, "games": 3, "wins": 1}])
    s = sources.Sources()
    assert not s.use_stratz and s.synergy(8) == [{"hero_id": 2, "games": 3, "wins": 1}]


def test_stratz_requires_key(monkeypatch):
    import pytest
    monkeypatch.setattr(stratz, "token", lambda cfg=None: "")
    with pytest.raises(stratz.StratzError, match="sin clave"):
        stratz.query("{ x }")


def test_stratz_item_popularity_phases_and_details(monkeypatch):
    data = {"heroStats": {
        "itemFullPurchase": [
            {"itemId": 145, "instance": 0, "time": 14, "matchCount": 700, "winCount": 350},
            {"itemId": 145, "instance": 0, "time": 16, "matchCount": 300, "winCount": 160},
            {"itemId": 145, "instance": 1, "time": 40, "matchCount": 50, "winCount": 40},   # segunda compra: fuera
            {"itemId": 135, "instance": 0, "time": 34, "matchCount": 250, "winCount": 130}],
        "itemStartingPurchase": [{"itemId": 44, "instance": 0, "matchCount": 1200, "winCount": 600},
                                 {"itemId": 44, "instance": 0, "matchCount": 800, "winCount": 400},  # otro tramo
                                 {"itemId": 44, "instance": 1, "matchCount": 1500, "winCount": 750}]}}
    monkeypatch.setattr(stratz, "cached_query", lambda *a, **k: data)
    pop = stratz.item_popularity(8, bracket=5)
    assert pop["_total"] == 2000 and pop["_scope"] == "Legend-Ancient"
    assert pop["start_game_items"] == {"44": 2000}
    assert pop["mid_game_items"] == {"145": 1000} and pop["late_game_items"] == {"135": 250}
    share, minute, wr = pop["_details"]["145"]
    assert share == 0.5 and minute == 14.6 and wr == 0.51
