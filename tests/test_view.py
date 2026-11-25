"""Datos del panel de partida (sin Tk ni red)."""
import json

from coach.config import DEFAULTS
from coach.engine.advisor import Advisor
from coach.gsi import GameState
from coach.ui.view import build_view


def _state(**kw):
    base = dict(match_id="1", game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", clock=600, team="radiant",
                hero="npc_dota_hero_juggernaut", hero_id=8, level=9, gold=2000, kills=3, deaths=1, assists=4)
    base.update(kw)
    return GameState(**base)


def test_view_has_next_item_build_and_enemies(gd):
    adv = Advisor(gd, None, json.loads(json.dumps(DEFAULTS)), None, sync=True)
    adv.set_enemies([gd.hero("pa"), gd.hero("Riki")])
    adv.set_allies([gd.hero("cm"), gd.hero("Juggernaut")])
    v = build_view(adv, None, _state())
    assert v.hero.loc == "Juggernaut" and v.role == "carry" and v.in_game
    assert v.next_item is not None and v.next_item.name == "item_dust"  # Riki invisible: lo primero
    assert v.next_item not in v.build and v.build
    assert v.phase == "early" and set(v.phase_builds) == {"start", "early", "mid", "late"}
    assert {e.hero.loc for e in v.enemies} == {"Phantom Assassin", "Riki"}
    pa = next(e for e in v.enemies if e.hero.loc == "Phantom Assassin")
    assert "evasión" in pa.traits
    assert pa.counters and pa.counters[0].name == "item_monkey_king_bar"
    assert [h.loc for h in v.allies] == ["Crystal Maiden"]  # tú no sales entre los aliados


def test_view_before_picking_hero(gd):
    adv = Advisor(gd, None, json.loads(json.dumps(DEFAULTS)), None, sync=True)
    v = build_view(adv, None, _state(hero="", hero_id=0, game_state="DOTA_GAMERULES_STATE_HERO_SELECTION"))
    assert v.hero is None and v.next_item is None and v.build == [] and not v.in_game
