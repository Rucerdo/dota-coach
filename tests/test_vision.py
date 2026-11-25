"""Reconocimiento de retratos con imágenes sintéticas (sin pantalla ni red), incluido el caso de arcanas."""
import numpy as np
import pytest
from PIL import Image

from coach.vision import topbar
from coach.vision.topbar import HeroMatcher, TopbarScanner


def _img(seed: int, size=(256, 144)) -> Image.Image:
    rng = np.random.default_rng(seed)
    small = rng.integers(30, 255, (9, 16, 3), dtype=np.uint8)  # bloques de color: retrato "único"
    return Image.fromarray(small).resize(size, Image.NEAREST)


@pytest.fixture
def matcher(gd):
    for h in gd.heroes.values():
        p = topbar.official_dir() / f"{h.short}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        _img(h.id).save(p)
    m = HeroMatcher(gd)
    m.load(download=False)
    return m


def test_match_official(gd, matcher):
    hero, score, margin = matcher.match(_img(44, (56, 32)))
    assert hero.loc == "Phantom Assassin" and score > 0.9 and margin > 0.1


def test_arcana_unknown_then_learned_by_elimination(gd, matcher):
    arcana = _img(999, (56, 32))  # retrato distinto al oficial (arcana)
    assert matcher.match(arcana)[0] is None  # ante la duda, desconocido

    enemies = [gd.hero(n) for n in ("pa", "Lion", "Riki", "Naga Siren", "am")]
    tiles = {5 + i: _img(h.id, (56, 32)) for i, h in enumerate(enemies)}
    tiles[5] = arcana  # PA lleva arcana
    scanner = TopbarScanner(matcher, lambda c: None,
                            known_heroes=lambda side: enemies if side == "dire" else [])
    scanner.process(tiles)
    new = scanner.process(tiles)  # 2ª lectura: confirma los 4 reconocidos y deduce el 5º
    assert new[5].loc == "Phantom Assassin"
    assert list((topbar.learned_dir() / "phantom_assassin").glob("*.png"))
    assert matcher.match(arcana)[0].loc == "Phantom Assassin"  # la próxima vez se reconoce sola


def test_unknown_tiles_saved_and_labeled(gd, matcher):
    scanner = TopbarScanner(matcher, lambda c: None)
    scanner.process({7: _img(12345, (56, 32))})
    saved = list(topbar.unknown_dir().glob("*_slot7.png"))
    assert saved
    dest = topbar.label_tile(saved[0], gd.hero("Lion"))
    assert dest.exists() and not saved[0].exists()


def test_diagnose_saved_screenshot(gd, matcher):
    """Una captura completa guardada: recorta los 10 huecos y compara con lo esperado."""
    shot = Image.new("RGB", (1920, 1080), "black")
    client = (0, 0, 1920, 1080)
    lineup = [gd.hero(n) for n in ("am", "cm", "Juggernaut", "Lion", "Riki")] + [None] * 4 + [gd.hero("pa")]
    for pid, h in enumerate(lineup):
        if h:
            box = topbar.tile_box(pid, client, topbar.DEFAULT_TOPBAR)
            shot.paste(_img(h.id, (box[2] - box[0], box[3] - box[1])), box[:2])
    expect = list(lineup)
    expect[1] = gd.hero("Naga Siren")  # error a propósito
    rows = topbar.diagnose(matcher, shot, None, expect)
    assert [r["ok"] for r in rows] == [True, False, True, True, True, None, None, None, None, True]
    assert not rows[6]["valid"]
    assert rows[1]["hero"].loc == "Crystal Maiden"


def test_dead_hero_gray_portrait(gd, matcher):
    """El HUD pinta en gris a los muertos: se compara en escala de grises."""
    gray = _img(44, (66, 35)).convert("L").convert("RGB")
    assert topbar.is_gray(gray) and not topbar.is_gray(_img(44, (66, 35)))
    assert matcher.match(gray)[0].loc == "Phantom Assassin"


def test_gray_template_only_for_gray(gd, matcher):
    """Una plantilla aprendida de un muerto (gris) no debe reconocer retratos en color."""
    dead = _img(777, (66, 35)).convert("L").convert("RGB")
    matcher.learn(gd.hero("Lion"), dead)
    assert matcher.match(dead)[0].loc == "Lion"
    assert matcher.match(_img(777, (66, 35)))[0] is None
