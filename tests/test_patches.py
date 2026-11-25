import json
from pathlib import Path

import pytest

from coach.data.meta import Meta, _trend
from coach.data.patches import base_version, classify, current_cycle, parse_patch, score

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("text,expected", [
    ("Cooldown decreased from 20 to 16", 1),
    ("Mana Cost rescaled from 100/110/120/130 to 90/105/120/135", 1),
    ("Damage increased from 100 to 120", 1),
    ("Evasion decreased from 25/35/45/55% to 20/30/40/50%", -1),
    ("Base Armor decreased by 1", -1),
    ("Sling Grenade Health Cost increased from 75 to 100", -1),
    ("Level 10 Talent Stifling Dagger Cooldown Reduction increased from 2s to 2.5s", 1),
    ("Tier 1 tower last hit gold decreased from 110-130 to 100", -1),
    ("Base Attack Time improved from 1.7 to 1.6", 0),  # verbo no reconocido sin from..to estándar → neutro
    ("Duration rescaled from 5/6/7/8s to 7s", 1),
    ("Removed Swiftslash ability", -0.5),
])
def test_classify(text, expected):
    assert classify(text)[0] == expected


def test_rework_flag():
    assert classify("Level 10 Talent +3 Health Regeneration replaced with +25% Counterspell")[1] is True


def test_parse_patch(gd):
    raw = json.loads((FIX / "patch_sample.json").read_text(encoding="utf-8"))
    changes = parse_patch(raw, gd)
    hero = [c for c in changes if c.kind == "hero" and c.target == "Phantom Assassin"]
    assert {c.detail for c in hero} == {"Blur", "Immaterial", "Talents"}
    assert score(hero) == 1  # +1 maná, -1 evasión, +1 talento
    am = [c for c in changes if c.target == "Anti-Mage"]
    assert any("(per hit)" in c.text for c in am)
    items = {c.target: c for c in changes if c.kind == "item"}
    assert items["Black King Bar"].direction == 1 and items["Monkey King Bar"].direction == -1
    general = [c for c in changes if c.kind == "general"]
    assert len(general) == 1 and "Subtitle" not in general[0].text  # sin títulos HTML ni líneas ocultas


def test_cycle():
    patches = [{"patch_number": v} for v in ("7.41f", "7.42", "7.42a")]
    assert current_cycle(patches) == ["7.42", "7.42a"]
    assert base_version("7.42a") == "7.42"


def test_trend():
    assert _trend([1000] * 6, [500, 500, 500, 550, 550, 550]) == 5.0
    assert _trend([10] * 6, [5] * 6) == 0.0  # muestra demasiado pequeña


def test_meta_combines_stats_and_patch(gd):
    raw = json.loads((FIX / "patch_sample.json").read_text(encoding="utf-8"))
    changes = parse_patch(raw, gd)
    stats = [{"id": 44, "pub_pick": 1000, "pub_win": 560, "pub_pick_trend": [500] * 4, "pub_win_trend": [250, 250, 280, 280]},
             {"id": 1, "pub_pick": 1000, "pub_win": 450, "3_pick": 100, "3_win": 40}]
    meta = Meta(gd, ["7.99a"], changes, stats, bracket=3)
    pa, am = meta.hero(44), meta.hero(1)
    assert pa.winrate == 0.56 and pa.trend == 6.0 and pa.patch_score == 1
    assert am.winrate == 0.40  # usa el rango 3 cuando hay datos
    assert meta.ranked(min_pick_rate=0)[0].hero.loc == "Phantom Assassin"
    assert "Black King Bar" in meta.context_for([], ["Black King Bar"])
    assert "Phantom Assassin" in meta.brief()
