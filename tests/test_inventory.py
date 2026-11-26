"""Objetos de un enemigo seleccionado: lector del HUD (con un HUD sintético) y counters por lo que lleva."""
import numpy as np
from PIL import Image

from coach.vision.inventory import ABILITY, BAR_BOX, HUD_BOX, SLOT, InventoryReader, hud_from_image


def _icon(seed: int, size=(88, 64)) -> Image.Image:
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 255, (4, 4, 3), dtype=np.uint8)   # manchas grandes: se parecen a un icono
    return Image.fromarray(small).resize(size, Image.BILINEAR)


def test_reads_enemy_items_and_hero(tmp_path):
    items, abil = tmp_path / "items", tmp_path / "abil"
    items.mkdir(), abil.mkdir()
    for i, n in enumerate(("tango", "bottle", "blink", "black_king_bar")):
        _icon(i).save(items / f"{n}.png")
    for h, names in ((1, ("a1", "a2", "a3", "a4")), (2, ("b1", "b2", "b3", "b4"))):
        for j, n in enumerate(names):
            _icon(100 + 10 * h + j, (128, 128)).save(abil / f"{n}.png")
    r = InventoryReader(items, abil, ocr=None)
    r.load_items(["item_tango", "item_bottle", "item_blink", "item_black_king_bar"])
    r.load_hero(1, ["a1", "a2", "a3", "a4"])
    r.load_hero(2, ["b1", "b2", "b3", "b4"])
    screen = Image.new("RGB", (1920, 1080), (30, 30, 30))
    screen.paste((150, 60, 50), BAR_BOX)                                     # barra roja: enemigo
    for i, n in enumerate(("b1", "b2", "b3", "b4")):                         # habilidades del héroe 2, en gris
        ic = Image.open(abil / f"{n}.png").convert("L").convert("RGB").resize((ABILITY["size"],) * 2)
        screen.paste(ic, (int(ABILITY["x"] + i * ABILITY["dx"]), ABILITY["y"]))
    for k, n in ((0, "blink"), (4, "black_king_bar")):                      # casillas 1 y 5
        ic = Image.open(items / f"{n}.png").resize((SLOT["w"], SLOT["h"]))
        r_, c_ = divmod(k, 3)
        screen.paste(ic, (SLOT["x"] + c_ * SLOT["dx"], SLOT["y"] + r_ * SLOT["dy"]))
    from coach.data.gamedata import Hero
    h1, h2 = Hero(1, "npc_dota_hero_a", "Alpha", [], "Melee"), Hero(2, "npc_dota_hero_b", "Beta", [], "Melee")
    sel = r.read(hud_from_image(screen), [h1, h2])
    assert sel.side == "enemy" and sel.hero_id == 2 and not sel.by_name   # sin OCR: por las habilidades
    assert sel.items[0] == "item_blink" and sel.items[4] == "item_black_king_bar"
    assert [i for i in sel.items if i] == ["item_blink", "item_black_king_bar"]
    screen.paste((80, 145, 48), BAR_BOX)                                     # verde: aliado o tú → nada
    assert r.read(hud_from_image(screen), [h1, h2]).side == "ally"
    # a otra resolución (2560x1440) se escala igual
    big = r.read(hud_from_image(screen.resize((2560, 1440))), [h1, h2])
    assert big.side == "ally"
    # con OCR manda el nombre (aunque las habilidades no cuadren: HUD de otro largo)
    screen.paste((150, 60, 50), BAR_BOX)
    r.ocr = lambda img: ["ALPHA"]
    sel = r.read(hud_from_image(screen), [h1, h2])
    assert sel.hero_id == 1 and sel.by_name and "item_blink" in sel.items
    # un enemigo que aún no se conocía (nombre de varias palabras, con algún error de lectura)
    cm = Hero(5, "npc_dota_hero_crystal_maiden", "Crystal Maiden", [], "Ranged")
    r.ocr = lambda img: ["CRYSTAL", "MA1DEN"]
    assert r.read(hud_from_image(screen), [h1, h2], [h1, h2, cm]).hero_id == 5


def test_match_hero_names():
    from coach.data.gamedata import Hero
    from coach.vision.ocr import match_hero
    cm = Hero(5, "npc_dota_hero_crystal_maiden", "Crystal Maiden", [], "Ranged")
    lina = Hero(25, "npc_dota_hero_lina", "Lina", [], "Ranged")
    am = Hero(1, "npc_dota_hero_antimage", "Anti-Mage", [], "Melee")
    assert match_hero(["LINA"], [cm, lina, am])[0] is lina
    assert match_hero(["CRYSTAL", "MAIDEN"], [cm, lina, am]) == (cm, 1.0)
    assert match_hero(["ANTI-MAGE"], [cm, lina, am])[0] is am
    assert match_hero([], [lina]) == (None, 0.0)


def test_enemy_items_add_counters(gd):
    from coach.engine.counters import counters_for, enemy_traits
    pa = gd.hero("pa")
    assert "buffs" not in enemy_traits([pa])
    assert enemy_traits([pa], {pa.id: ["item_ghost"]})["buffs"] == ["Phantom Assassin"]
    plain = [n for n, _ in counters_for(gd, pa, items=[])]
    with_ghost = [n for n, _ in counters_for(gd, pa, items=["item_ghost"], limit=6)]
    assert "item_nullifier" not in plain or len(with_ghost) >= len(plain)
