"""Objetos en camino en el courier (alijo → courier → inventario)."""
from coach.data.gamedata import Item
from coach.engine.courier import CourierTracker
from coach.gsi import GameState


def _st(clock, items=(), stash=()):
    return GameState(match_id="0", game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", hero="npc_dota_hero_juggernaut",
                     clock=clock, items=list(items), stash=list(stash))


def test_item_in_transit_until_it_arrives(gd):
    t = CourierTracker(gd)
    t.update(_st(100, items=["item_phase_boots"], stash=["item_blink"]))
    assert t.update(_st(110, items=["item_phase_boots"])) == ["item_blink"]     # salió del alijo: en camino
    assert t.update(_st(130, items=["item_phase_boots"])) == ["item_blink"]
    assert t.update(_st(140, items=["item_phase_boots", "item_blink"])) == []    # llegó


def test_components_combine_on_arrival_and_expire(gd):
    for it in (Item(3, "item_broadsword", "Broadsword", 1000),
               Item(145, "item_bfury", "Battle Fury", 3900, components=["item_broadsword", "item_quelling_blade"])):
        gd.items[it.id] = it
        gd._items_by_name[it.name] = it
    t = CourierTracker(gd)
    t.update(_st(100, items=["item_quelling_blade"], stash=["item_broadsword"]))
    assert t.update(_st(105, items=["item_quelling_blade"])) == ["item_broadsword"]
    assert t.update(_st(120, items=["item_bfury"])) == []                       # se combinó al llegar
    t.update(_st(200, stash=["item_magic_wand"]))
    assert t.update(_st(205)) == ["item_magic_wand"]
    assert t.update(_st(500)) == []                                             # caduca si nunca llega


def test_owned_counts_items_in_transit(gd):
    st = _st(100, items=["item_phase_boots"])
    st.in_transit = ["item_blink"]
    assert "item_blink" in st.all_items
