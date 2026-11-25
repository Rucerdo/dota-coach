import json

from coach.ai.base import LLMError, Provider
from coach.config import DEFAULTS
from coach.engine.advisor import Advisor
from coach.engine.counters import item_role, player_role, suggest_items
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


def test_item_role(gd):
    assert item_role(gd.hero("Juggernaut")) == "carry"
    assert item_role(gd.hero("cm")) == "support"
    assert item_role(gd.hero("Juggernaut"), "core") == "core"
    assert player_role(gd.hero("Juggernaut"), "carry") == "core"


def test_carry_skips_team_items(gd):
    enemies = [gd.hero("Lion"), gd.hero("cm"), gd.hero("pa")]
    carry = [s.item for s in suggest_items(gd, gd.hero("Juggernaut"), enemies)]
    assert "item_pipe" not in carry and "item_monkey_king_bar" in carry
    offlane = [s.item for s in suggest_items(gd, gd.hero("Juggernaut"), enemies, role="core")]
    assert "item_pipe" in offlane


def test_must_have_counter_beats_common_trait(gd):
    # Dust contra un solo invisible va por delante de un counter genérico contra varios
    sugg = suggest_items(gd, gd.hero("Juggernaut"), [gd.hero("Riki"), gd.hero("Lion"), gd.hero("cm")])
    names = [s.item for s in sugg]
    assert names.index("item_dust") < names.index("item_black_king_bar")


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


def test_alternatives_only_best(gd):
    """Dust y Gem resuelven lo mismo (detección): solo se sugiere uno."""
    names = [s.item for s in suggest_items(gd, gd.hero("Juggernaut"), [gd.hero("Riki")])]
    assert "item_dust" in names and "item_gem" not in names


def test_periodic_zero_means_never(gd):
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg["advisor"]["periodic_minutes"] = 0
    adv = Advisor(gd, None, cfg, None, sync=True)
    adv.triggers(_state(clock=60))
    assert "periodic" not in adv.triggers(_state(clock=3000))
    cfg["advisor"]["periodic_minutes"] = 8
    adv = Advisor(gd, None, cfg, None, sync=True)
    adv.triggers(_state(clock=60))
    assert "periodic" in adv.triggers(_state(clock=60 + 8 * 60))


def test_counter_tip_uses_a_real_counter_of_the_trait(gd):
    """El rasgo más repetido (daño físico) no tiene counter entre las sugerencias: no se debe decir
    'contra daño físico: Dust' solo porque Dust menciona a Riki; se pasa al siguiente rasgo."""
    adv, out = _advisor(gd)
    adv.set_enemies([gd.hero("pa"), gd.hero("Riki")])
    adv.update(_state())
    counter = [t.text for t in out if t.kind == "counter"]
    assert counter and not counter[0].startswith("Contra daño físico")
    assert "Dust of Appearance" in counter[0] or "Monkey King Bar" in counter[0]


def test_hero_never_on_both_sides(gd):
    adv, _ = _advisor(gd)
    adv.set_enemies([gd.hero("pa"), gd.hero("cm"), gd.hero("Juggernaut")])
    adv.set_allies([gd.hero("cm")])                 # CM era aliada: se quita de enemigos
    adv.update(_state())                            # tú (Juggernaut) tampoco eres enemigo
    assert set(adv.enemies) == {gd.hero("pa").id}
    adv.set_enemies([gd.hero("cm")])                # y no vuelve a colarse
    assert gd.hero("cm").id not in adv.enemies


def test_phases_start_cheap_late_big(gd):
    """Al empezar no se sugiere un objeto grande; en late sí."""
    from coach.engine.counters import phase_for
    assert [phase_for(s) for s in (-60, 5 * 60, 18 * 60, 40 * 60)] == ["start", "early", "mid", "late"]
    pop = {"start_game_items": {"36": 50}, "early_game_items": {"50": 40}, "late_game_items": {"135": 30}}
    enemies = [gd.hero("pa"), gd.hero("Lion")]
    start = suggest_items(gd, gd.hero("Juggernaut"), enemies, popularity=pop, phase="start")
    assert start[0].cost <= 600
    assert all(s.to_pay <= 1000 for s in start)  # al salir, nada caro
    late = suggest_items(gd, gd.hero("Juggernaut"), enemies, popularity=pop, phase="late")
    assert late[0].item in ("item_monkey_king_bar", "item_black_king_bar")


def test_bare_components_skipped_mid_late(gd):
    from coach.data.gamedata import Item
    broad = Item(999, "item_broadsword", "Broadsword", 1000)
    gd.items[999] = broad
    gd._items_by_name["item_broadsword"] = broad
    gd.component_names = {"item_broadsword"}
    pop = {"early_game_items": {"999": 50}, "mid_game_items": {"999": 50}}
    early = [s.item for s in suggest_items(gd, gd.hero("Juggernaut"), [], popularity=pop, phase="early")]
    mid = [s.item for s in suggest_items(gd, gd.hero("Juggernaut"), [], popularity=pop, phase="mid")]
    assert "item_broadsword" in early and "item_broadsword" not in mid


def test_counters_for_each_enemy(gd):
    from coach.engine.counters import counters_for
    pa = [n for n, _ in counters_for(gd, gd.hero("pa"), gd.hero("Juggernaut"))]
    assert pa[0] == "item_monkey_king_bar"          # evasión pesa más
    riki = [n for n, _ in counters_for(gd, gd.hero("Riki"), gd.hero("Juggernaut"))]
    assert riki[0] == "item_dust" and "item_gem" not in riki
    owned = [n for n, _ in counters_for(gd, gd.hero("pa"), gd.hero("Juggernaut"), owned=["item_monkey_king_bar"])]
    assert "item_monkey_king_bar" not in owned
    cm_support = [n for n, _ in counters_for(gd, gd.hero("pa"), gd.hero("cm"))]
    assert "item_monkey_king_bar" not in cm_support and "item_ghost" in cm_support


def _add_items(gd, *items):
    for it in items:
        gd.items[it.id] = it
        gd._items_by_name[it.name] = it
    gd.component_names = {c for i in gd.items.values() for c in i.components}


def _boots_and_routes(gd):
    from coach.data.gamedata import Item
    _add_items(gd,
               Item(29, "item_boots", "Boots of Speed", 500),
               Item(214, "item_tranquil_boots", "Tranquil Boots", 900, components=["item_boots"]),
               Item(180, "item_arcane_boots", "Arcane Boots", 1400, components=["item_boots"]),
               Item(231, "item_guardian_greaves", "Guardian Greaves", 4350, components=["item_arcane_boots"]),
               Item(48, "item_travel_boots", "Boots of Travel", 2500, components=["item_boots"]),
               Item(166, "item_maelstrom", "Maelstrom", 2950),
               Item(158, "item_mjollnir", "Mjollnir", 5500, components=["item_maelstrom"]))
    return {"early_game_items": {"29": 50, "214": 40, "180": 30}, "mid_game_items": {"48": 20}}


def test_built_items_hide_their_components_and_other_boots(gd):
    pop = _boots_and_routes(gd)
    cm = gd.hero("cm")
    fresh = [s.item for s in suggest_items(gd, cm, [], [], popularity=pop, phase="early", limit=10)]
    assert "item_boots" in fresh and "item_tranquil_boots" in fresh
    tranquil = [s.item for s in suggest_items(gd, cm, [], ["item_tranquil_boots"], popularity=pop, phase="early",
                                              limit=10)]
    assert not {"item_boots", "item_tranquil_boots", "item_arcane_boots"} & set(tranquil)
    arcane = {s.item: s for s in suggest_items(gd, cm, [], ["item_arcane_boots"], popularity=pop, phase="mid",
                                               limit=10)}
    assert "item_guardian_greaves" in arcane and "item_travel_boots" not in arcane
    assert arcane["item_guardian_greaves"].to_pay == 4350 - 1400


def test_owned_route_is_followed(gd):
    _boots_and_routes(gd)
    sugg = suggest_items(gd, gd.hero("Juggernaut"), [gd.hero("pa")], ["item_maelstrom"], phase="mid", limit=10)
    mjol = next(s for s in sugg if s.item == "item_mjollnir")
    assert sugg[0].item == "item_mjollnir" and mjol.to_pay == 5500 - 2950
    assert any("Maelstrom" in r for r in mjol.reasons)


def test_bot_games_with_match_id_zero_reset(gd):
    """Contra bots el match_id es siempre "0": otra partida se detecta por el héroe o por el reloj."""
    adv, _ = _advisor(gd)
    adv.update(_state(match_id="0", clock=300))
    adv.set_enemies([gd.hero("pa")])
    adv.update(_state(match_id="0", clock=320))
    assert adv.enemies                                   # misma partida: se conservan
    adv.update(_state(match_id="0", clock=10, hero="npc_dota_hero_lion", hero_id=26))
    assert not adv.enemies and adv.games.serial == 1     # otro héroe: partida nueva
    adv.set_enemies([gd.hero("pa")])
    adv.update(_state(match_id="0", clock=900, hero="npc_dota_hero_lion", hero_id=26))
    adv.update(_state(match_id="0", clock=-60, hero="npc_dota_hero_lion", hero_id=26))
    assert not adv.enemies and adv.games.serial == 2     # el reloj vuelve atrás: partida nueva


def test_build_plan_marks_owned_and_orders_the_rest(gd):
    from coach.data.gamedata import Item
    from coach.engine.counters import build_plan, next_purchase
    _add_items(gd,
               Item(11, "item_quelling_blade", "Quelling Blade", 100),
               Item(3, "item_broadsword", "Broadsword", 1000),
               Item(56, "item_ring_of_health", "Ring of Health", 700),
               Item(57, "item_void_stone", "Void Stone", 700),
               Item(69, "item_pers", "Perseverance", 1400, components=["item_ring_of_health", "item_void_stone"]),
               Item(145, "item_bfury", "Battle Fury", 3900,
                    components=["item_pers", "item_broadsword", "item_broadsword", "item_quelling_blade"]))
    plan = build_plan(gd, "item_bfury", ["item_quelling_blade", "item_broadsword", "item_ring_of_health"])
    assert [(s.name, s.owned) for s in plan] == [
        ("item_broadsword", True), ("item_quelling_blade", True),          # lo que ya llevas
        ("item_pers", False), ("item_broadsword", False), ("recipe", False)]  # lo que falta, receta al final
    assert plan[2].to_pay == 700 and plan[-1].to_pay == 3900 - 1400 - 2000 - 100
    assert next_purchase(plan, 800).name == "item_pers"
    assert next_purchase(plan, 500) is None
    # con 600 no se propone la receta (400) mientras falten componentes
    assert next_purchase(build_plan(gd, "item_bfury", ["item_pers", "item_broadsword", "item_quelling_blade"]),
                         600) is None
    done = build_plan(gd, "item_bfury", ["item_pers", "item_broadsword", "item_broadsword", "item_quelling_blade"])
    assert next_purchase(done, 600).name == "recipe"


def test_draft_state_from_gsi_and_vision(gd):
    from coach.engine.draftlive import draft_state, is_drafting
    st = _state(game_state="DOTA_GAMERULES_STATE_HERO_SELECTION", hero="", hero_id=0,
                draft={"radiant": [8, "npc_dota_hero_juggernaut"], "dire": ["npc_dota_hero_lion"], "radiant_bans": [44],
                       "dire_bans": [], "active": "radiant", "pick": True})
    v = draft_state(gd, st)
    assert is_drafting(st) and v.source == "gsi" and v.my_turn
    assert [h.loc for h in v.allies] == ["Juggernaut"] and [h.loc for h in v.enemies] == ["Lion"]
    assert [h.loc for h in v.bans] == ["Phantom Assassin"]
    vis = draft_state(gd, _state(game_state="DOTA_GAMERULES_STATE_HERO_SELECTION", hero="", hero_id=0),
                      [gd.hero("cm")], [gd.hero("Riki")])
    assert vis.source == "visión" and [h.loc for h in vis.enemies] == ["Riki"]
    picks = suggest_picks(gd, v.enemies, v.allies, banned=v.bans, matchups=lambda hid: [])
    assert all(p.hero.loc not in ("Phantom Assassin", "Juggernaut", "Lion") for p in picks)
