import json
import urllib.request

from coach import dota
from coach.gsi import GSIServer, parse_state

PAYLOAD = {
    "map": {"matchid": "123", "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", "clock_time": 754,
            "daytime": False, "paused": False},
    "player": {"team_name": "radiant", "gold": 2300, "gpm": 450, "kills": 3, "deaths": 2, "assists": 5,
               "last_hits": 80},
    "hero": {"id": 8, "name": "npc_dota_hero_juggernaut", "level": 11, "alive": False, "respawn_seconds": 25,
             "buyback_cost": 900},
    "items": {"slot0": {"name": "item_phase_boots"}, "slot1": {"name": "empty"}, "stash0": {"name": "item_magic_wand"}},
    "minimap": {
        "o0": {"unitname": "npc_dota_hero_phantom_assassin", "team": 3},
        "o1": {"unitname": "npc_dota_hero_crystal_maiden", "team": 2},
        "o2": {"unitname": "npc_dota_hero_juggernaut", "team": 2},
        "o3": {"unitname": "npc_dota_creep_badguys_melee", "team": 3},
    },
}


def test_parse_state():
    st = parse_state(PAYLOAD)
    assert st.in_game and st.clock_text == "12:34" and not st.daytime
    assert st.hero == "npc_dota_hero_juggernaut" and st.level == 11 and not st.alive
    assert st.items == ["item_phase_boots"] and st.stash == ["item_magic_wand"]
    assert st.visible_enemies == {"npc_dota_hero_phantom_assassin"}
    assert st.visible_allies == {"npc_dota_hero_crystal_maiden"}


def test_server_roundtrip():
    got = []
    srv = GSIServer(0, got.append)  # puerto 0: el sistema elige uno libre
    srv.start()
    try:
        port = srv._srv.server_address[1]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=json.dumps(PAYLOAD).encode(), method="POST")
        urllib.request.urlopen(req, timeout=5).read()
        assert got and got[0].gold == 2300 and srv.connected
    finally:
        srv.stop()


def test_install_in_fake_dota_dir(tmp_path):
    game = tmp_path / "dota 2 beta" / "game" / "dota"
    (game / "cfg").mkdir(parents=True)
    d = dota.normalize(tmp_path / "dota 2 beta")
    assert d == game
    path = dota.install(d, 53124)
    assert path.parent.name == "gamestate_integration" and '"minimap"' in path.read_text(encoding="utf-8")
    assert dota.is_installed(d, 53124) and not dota.is_installed(d, 1)
    assert dota.uninstall(d) and not path.exists()
