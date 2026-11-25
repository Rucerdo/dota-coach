"""Actualización con cada parche: se borra solo lo que depende del parche (sin red: el parche se simula)."""
import json

from coach import config
from coach.data import updater


def _touch(name):
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (config.CACHE_DIR / f"{name}.json").write_text(json.dumps({"fetched": 0, "data": {}}), encoding="utf-8")


def test_new_patch_clears_only_patch_dependent_cache(monkeypatch):
    monkeypatch.delenv("COACH_OFFLINE", raising=False)
    for f in config.CACHE_DIR.glob("*.json") if config.CACHE_DIR.exists() else []:
        f.unlink()
    first = updater.check(fetch=lambda: "7.42a")
    assert not first.new_patch and first.latest == "7.42a"          # la primera vez solo se apunta
    for name in ("valve_itemlist", "od_itempop_8", "stratz_hero_8", "od_match_123", "valve_patch_7.41"):
        _touch(name)
    same = updater.check(fetch=lambda: "7.42a")
    assert not same.new_patch and same.cleared == 0
    new = updater.check(fetch=lambda: "7.43")
    assert new.new_patch and new.previous == "7.42a" and new.cleared == 3
    left = {f.stem for f in config.CACHE_DIR.glob("*.json")}
    assert {"od_match_123", "valve_patch_7.41"} <= left and "stratz_hero_8" not in left
    assert "Nuevo parche 7.43" in new.message()


def test_without_network_keeps_cache(monkeypatch):
    monkeypatch.delenv("COACH_OFFLINE", raising=False)

    def boom():
        raise OSError("sin red")
    res = updater.check(fetch=boom)
    assert res.error and "uso los datos guardados" in res.message()
