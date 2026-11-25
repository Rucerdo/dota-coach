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
    m = HeroMatcher(gd, aspect=256 / 144)
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
