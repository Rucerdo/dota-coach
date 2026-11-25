"""Los tests no tocan la red, ni %APPDATA%, ni el cfg real de Dota: COACH_HOME apunta a una carpeta temporal
y las instalaciones de GSI usan una carpeta de Dota falsa."""
import os
import tempfile

os.environ["COACH_HOME"] = tempfile.mkdtemp(prefix="coach_test_")

import pytest  # noqa: E402

from coach.data.gamedata import GameData, Hero, Item  # noqa: E402


@pytest.fixture
def gd() -> GameData:
    heroes = [
        Hero(1, "npc_dota_hero_antimage", "Anti-Mage", ["Carry", "Escape"], "Melee", ["am"]),
        Hero(5, "npc_dota_hero_crystal_maiden", "Crystal Maiden", ["Support", "Disabler"], "Ranged", ["cm"]),
        Hero(8, "npc_dota_hero_juggernaut", "Juggernaut", ["Carry", "Pusher"], "Melee"),
        Hero(26, "npc_dota_hero_lion", "Lion", ["Support", "Disabler"], "Ranged"),
        Hero(32, "npc_dota_hero_riki", "Riki", ["Carry", "Escape"], "Melee"),
        Hero(44, "npc_dota_hero_phantom_assassin", "Phantom Assassin", ["Carry", "Escape"], "Melee", ["pa"]),
        Hero(89, "npc_dota_hero_naga_siren", "Naga Siren", ["Carry", "Pusher"], "Melee"),
    ]
    items = [
        Item(1, "item_blink", "Blink Dagger", 2250),
        Item(36, "item_magic_wand", "Magic Wand", 450),
        Item(40, "item_dust", "Dust of Appearance", 80),
        Item(43, "item_ward_sentry", "Sentry Ward", 50),
        Item(50, "item_phase_boots", "Phase Boots", 1500),
        Item(116, "item_black_king_bar", "Black King Bar", 4050),
        Item(135, "item_monkey_king_bar", "Monkey King Bar", 5000),
        Item(145, "item_bfury", "Battle Fury", 3900),
        Item(158, "item_mjollnir", "Mjollnir", 5500),
        Item(254, "item_glimmer_cape", "Glimmer Cape", 2150),
        Item(37, "item_ghost", "Ghost Scepter", 1500),
        Item(102, "item_force_staff", "Force Staff", 2200),
    ]
    abilities = {5004: "Mana Break", 5191: "Blur", 5192: "Immaterial"}
    return GameData(heroes, items, abilities)
