"""Torres, asesinatos, rachas y compras a partir de los eventos de GSI (formato real de una partida)."""
from coach.engine.events import EventWatch, building_label
from coach.gsi import GameState


def _st(clock, buildings=None, events=None, team="dire"):
    return GameState(match_id="0", game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", clock=clock, team=team,
                     hero="npc_dota_hero_pudge", buildings=buildings or {}, events=events or [])


def test_building_labels():
    assert building_label("dota_badguys_tower2_mid") == "T2 mid"
    assert building_label("dota_goodguys_melee_rax_bot") == "Cuartel cuerpo a cuerpo bot"
    assert building_label("dota_badguys_fort") == "Ancestro" and building_label("dota_badguys_fillers") is None


def test_tower_damage_and_loss(gd):
    w = EventWatch(gd)
    t = "dota_badguys_tower1_top"
    assert w.update(_st(100, {t: (1800, 1800)}), {}) == []
    n = w.update(_st(106, {t: (1400, 1800)}), {})
    assert n and n[0].kind == "tower" and "T1 top" in n[0].text and "78%" in n[0].text
    assert w.update(_st(110, {t: (1000, 1800)}), {}) == []          # en enfriamiento
    lost = w.update(_st(140, {t: (0, 1800)}), {})
    assert lost[0].level == "danger" and "perdido" in lost[0].text
    assert w.state.towers == [("T1 top", 0.0)]


def test_kills_streaks_and_purchases(gd):
    w = EventWatch(gd)
    heroes = {0: gd.hero("pa"), 5: gd.hero("Juggernaut"), 8: gd.hero("Lion")}
    ev = [{"type": "CHAT_MESSAGE_HERO_KILL", "playerid1": 0, "playerid2": 5, "time": 300.0},
          {"type": "CHAT_MESSAGE_STREAK_KILL", "playerid1": 0, "playerid2": 3, "time": 300.0},
          {"type": "CHAT_MESSAGE_ITEM_PURCHASE", "playerid1": 8, "value": 37, "time": 310.0}]
    notices = w.update(_st(310, events=ev), heroes)          # tú eres Dire: PA (id 0) es enemiga
    assert [n.kind for n in notices] == ["streak"] and "Phantom Assassin" in notices[0].text
    k = w.state.kills[0]
    assert k.killer.loc == "Phantom Assassin" and k.victim.loc == "Juggernaut" and k.killer_enemy
    assert w.state.purchases == [(310, "Lion", "Ghost Scepter")]
    assert w.update(_st(312, events=ev), heroes) == [] and len(w.state.kills) == 1   # sin duplicados


def test_my_kills_come_from_kill_list(gd):
    from coach.engine.events import EventWatch
    from coach.gsi import parse_state
    w = EventWatch(gd)
    me, lion, pa = gd.hero("jugg"), gd.hero("lion"), gd.hero("pa")
    heroes = {0: me, 5: lion, 7: pa}

    def st(clock, kill_list):
        return parse_state({"map": {"clock_time": clock, "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"},
                            "player": {"team_name": "radiant", "team_slot": 0, "kill_list": kill_list}})
    w.update(st(100, {}), heroes)
    w.update(st(200, {"victimid_5": 1}), heroes)
    w.update(st(260, {"victimid_5": 1, "victimid_7": 2}), heroes)    # dos a PA de golpe
    kills = w.state.kills
    assert [(k.clock, k.killer.loc, k.victim.loc, k.killer_enemy) for k in kills] == [
        (200, "Juggernaut", "Lion", False), (260, "Juggernaut", "Phantom Assassin", False),
        (260, "Juggernaut", "Phantom Assassin", False)]
    w.update(st(300, {"victimid_5": 1, "victimid_7": 2}), heroes)    # sin cambios: nada nuevo
    assert len(w.state.kills) == 3
