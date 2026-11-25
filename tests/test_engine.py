import json

from coach.ai.base import LLMError, Provider
from coach.config import DEFAULTS
from coach.engine.advisor import Advisor
from coach.engine.counters import player_role, suggest_items
from coach.engine.draft import advantage, suggest_picks
from coach.gsi import GameState


def _state(**kw):
    base = dict(match_id="1", game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", clock=300,
                team="radiant", hero="npc_dota_hero_juggernaut", hero_id=8, gold=100)
    base.update(kw)
    return GameState(**base)


def test_role(gd):
    assert player_role(gd.hero("cm")) == "support"
    assert player_role(gd.hero("Juggernaut")) == "core"
    assert player_role(gd.hero("cm"), "core") == "core"


def test_counters_core(gd):
    sugg = suggest_items(gd, gd.hero("Juggernaut"), [gd.hero("pa"), gd.hero("Naga Siren"), gd.hero("Riki")])
    names = [s.item for s in sugg]
    assert "item_monkey_king_bar" in names and "item_mjollnir" in names and "item_dust" in names
    assert "item_glimmer_cape" not in names  # objeto de support


def test_counters_skip_owned_and_support(gd):
    sugg = suggest_items(gd, gd.hero("cm"), [gd.hero("pa"), gd.hero("Lion")], owned=["item_glimmer_cape"])
    names = [s.item for s in sugg]
    assert "item_glimmer_cape" not in names
    assert "item_ghost" in names and "item_monkey_king_bar" not in names


def test_advantage_shrinks_small_samples():
    assert advantage(0, 0) == 0
    assert 0 < advantage(2, 10) < advantage(20, 100)


def test_draft(gd):
    table = {44: [{"hero_id": 26, "games_played": 200, "wins": 60},     # PA pierde mucho contra Lion
                  {"hero_id": 8, "games_played": 200, "wins": 140}]}   # y gana a Juggernaut
    picks = suggest_picks(gd, [gd.hero("pa")], matchups=lambda hid: table.get(hid, []))
    assert picks[0].hero.loc == "Lion" and picks[-1].hero.loc == "Juggernaut"
    assert all(p.hero.loc != "Phantom Assassin" for p in picks)


class FakeAI(Provider):
    id, label = "fake", "Fake"
    needs_key = False

    def __init__(self, reply=None, fail=False):
        super().__init__()
        self.reply, self.fail, self.calls = reply, fail, []

    def complete(self, system, user, schema=None, effort="low", max_tokens=4000, timeout=60.0):
        self.calls.append(user)
        if self.fail:
            raise LLMError("caído")
        return json.dumps(self.reply)


def _advisor(gd, provider=None):
    out = []
    adv = Advisor(gd, None, dict(DEFAULTS), provider, on_tips=out.extend, sync=True)
    return adv, out


def test_advisor_rules_start_death_gold(gd):
    adv, out = _advisor(gd)
    adv.set_enemies([gd.hero("pa")])
    adv.update(_state())
    assert any("Phantom Assassin" in t.text for t in out)  # plan contra los rasgos enemigos al empezar
    out.clear()
    adv.update(_state(clock=320))
    assert out == []  # sin eventos nuevos, silencio
    adv.update(_state(clock=340, deaths=1, respawn_seconds=20, alive=False))
    assert any(t.text.startswith("Muerto") for t in out)
    out.clear()
    adv.update(_state(clock=360, deaths=1, gold=6000))
    assert any(t.text.startswith("Ya puedes comprar") for t in out)
    out.clear()
    adv.update(_state(clock=362, deaths=1, gold=6000))
    assert out == []  # el aviso de oro del mismo objeto no se repite


def test_advisor_minimap_enemy_triggers(gd):
    adv, out = _advisor(gd)
    adv.update(_state())
    out.clear()
    adv.update(_state(clock=310, visible_enemies={"npc_dota_hero_riki"}))
    assert gd.hero("Riki").id in adv.enemies
    assert any("Riki" in t.text for t in out)


def test_advisor_ai_and_fallback(gd):
    ai = FakeAI({"tips": [{"kind": "item", "text": "Compra MKB ya"}]})
    adv, out = _advisor(gd, ai)
    adv.set_enemies([gd.hero("pa")])
    adv.update(_state())
    assert out[0].source == "ai" and out[0].text == "Compra MKB ya"
    assert "Phantom Assassin" in ai.calls[0] and "Monkey King Bar" in ai.calls[0]

    broken = FakeAI(fail=True)
    adv2, out2 = _advisor(gd, broken)
    adv2.set_enemies([gd.hero("pa")])
    adv2.update(_state())
    assert out2 and all(t.source == "rules" for t in out2)


def test_advisor_new_match_resets(gd):
    adv, _ = _advisor(gd)
    adv.set_enemies([gd.hero("pa")])
    adv.update(_state())
    adv.update(_state(match_id="2"))
    assert adv.match_id == "2" and not adv.enemies
