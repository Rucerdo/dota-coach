"""Guía en la tienda de Dota: copia de todas las originales, escribir, saber si es nuestra y restaurar.
Todo en una carpeta de Dota FALSA (nunca la de verdad)."""
from coach import itembuilds
from coach.engine.guides import Guide

VALVE = '"itembuilds"\n{\n\t"author"\t\t"Valve"\n\t"hero"\t\t\t"npc_dota_hero_X"\n}\n'


def _fake_dota(tmp_path):
    d = tmp_path / "game" / "dota"
    (d / "itembuilds").mkdir(parents=True)
    for h in ("sniper", "lina", "zuus"):
        (d / "itembuilds" / f"default_{h}.txt").write_text(VALVE.replace("X", h), encoding="utf-8")
    return d


def test_backup_all_then_export_and_restore(tmp_path):
    d = _fake_dota(tmp_path)
    # resto de la primera prueba: sniper ya cambiado y su original suelto al lado
    (d / "itembuilds" / "default_sniper.txt.coach_backup").write_text(VALVE.replace("X", "sniper"), encoding="utf-8")
    (d / "itembuilds" / "default_sniper.txt").write_text('"itembuilds"\n{\n\t"author"\t\t"Dota Coach"\n}\n',
                                                          encoding="utf-8")
    g = Guide("123", 35, [("item_power_treads", 7.0), ("item_maelstrom", 14.0), ("item_satanic", 30.0)])
    path = itembuilds.export(d, "npc_dota_hero_lina", "Dota Coach | Lina [guía 123]",
                             itembuilds.groups_for_guide(g, ["item_tango"]), ["Niveles 1-6: Q W E Q Q R"],
                             ["lina_dragon_slave"])
    backup = d / itembuilds.BACKUP_DIR
    assert sorted(f.name for f in backup.glob("default_*.txt")) == ["default_lina.txt", "default_sniper.txt",
                                                                     "default_zuus.txt"]
    assert '"Valve"' in (backup / "default_sniper.txt").read_text(encoding="utf-8")  # el original, no el del coach
    assert not (d / "itembuilds" / "default_sniper.txt.coach_backup").exists()
    text = path.read_text(encoding="utf-8")
    assert '"Niveles 1-6: Q W E Q Q R"' in text and '"item"\t\t"item_maelstrom"' in text and "AbilityBuild" in text
    assert itembuilds.exported_guide(d, "npc_dota_hero_lina") == "123"
    assert itembuilds.exported_guide(d, "npc_dota_hero_zuus") is None             # la de Valve
    # la copia se hace una sola vez: escribir otra no pisa los originales
    itembuilds.export(d, "npc_dota_hero_zuus", "Dota Coach | Zeus [guía 9]", {"early": ["item_boots"]})
    assert '"Valve"' in (backup / "default_zuus.txt").read_text(encoding="utf-8")
    assert itembuilds.restore(d, "npc_dota_hero_lina")
    assert itembuilds.exported_guide(d, "npc_dota_hero_lina") is None
    assert itembuilds.restore(d, "npc_dota_hero_sniper")
    assert '"Valve"' in (d / "itembuilds" / "default_sniper.txt").read_text(encoding="utf-8")


def test_groups_by_minute():
    g = Guide("1", 1, [("item_a", 5.0), ("item_b", 20.0), ("item_c", 35.0)])
    groups = itembuilds.groups_for_guide(g, ["item_tango"], ["item_b", "item_bkb"])
    assert groups == {"start": ["item_tango"], "early": ["item_a"], "mid": ["item_b"], "late": ["item_c"],
                      "other": ["item_bkb"]}
