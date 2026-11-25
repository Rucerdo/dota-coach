"""Servidor local de Game State Integration: convierte cada envío de Dota en un GameState.

En modo jugador, Dota solo envía TUS datos (héroe, oro, objetos, habilidades) más el mapa y el reloj.
Los héroes enemigos se obtienen del minimapa (si Dota lo incluye) y de la barra superior (coach/vision).
"""
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

log = logging.getLogger(__name__)

TEAM_IDS = {"radiant": 2, "dire": 3}
IN_GAME_STATES = {"DOTA_GAMERULES_STATE_PRE_GAME", "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"}


@dataclass
class GameState:
    match_id: str = ""
    game_state: str = ""          # DOTA_GAMERULES_STATE_*
    clock: int = 0                # segundos de partida (negativo antes del minuto 0)
    daytime: bool = True
    paused: bool = False
    team: str = ""                # radiant | dire
    hero: str = ""                # npc_dota_hero_*
    hero_id: int = 0
    level: int = 0
    alive: bool = True
    respawn_seconds: int = 0
    buyback_cost: int = 0
    gold: int = 0
    gpm: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    last_hits: int = 0
    items: list[str] = field(default_factory=list)     # inventario + mochila + neutral (item_*)
    stash: list[str] = field(default_factory=list)
    visible_enemies: set[str] = field(default_factory=set)  # npc_dota_hero_* vistos en el minimapa
    visible_allies: set[str] = field(default_factory=set)
    received: float = 0.0

    @property
    def in_game(self) -> bool:
        return self.game_state in IN_GAME_STATES and bool(self.hero)

    @property
    def all_items(self) -> list[str]:
        return self.items + self.stash

    @property
    def clock_text(self) -> str:
        sign = "-" if self.clock < 0 else ""
        m, s = divmod(abs(self.clock), 60)
        return f"{sign}{m}:{s:02d}"


def _int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def parse_state(payload: dict) -> GameState:
    m = payload.get("map") or {}
    p = payload.get("player") or {}
    h = payload.get("hero") or {}
    items = payload.get("items") or {}
    st = GameState(received=time.time())
    st.match_id = str(m.get("matchid") or "")
    st.game_state = str(m.get("game_state") or "")
    st.clock = _int(m.get("clock_time"))
    st.daytime = bool(m.get("daytime", True))
    st.paused = bool(m.get("paused", False))
    st.team = str(p.get("team_name") or "").lower()
    st.gold, st.gpm = _int(p.get("gold")), _int(p.get("gpm"))
    st.kills, st.deaths, st.assists = _int(p.get("kills")), _int(p.get("deaths")), _int(p.get("assists"))
    st.last_hits = _int(p.get("last_hits"))
    st.hero, st.hero_id = str(h.get("name") or ""), _int(h.get("id"))
    st.level = _int(h.get("level"))
    st.alive = bool(h.get("alive", True))
    st.respawn_seconds = _int(h.get("respawn_seconds"))
    st.buyback_cost = _int(h.get("buyback_cost"))
    for slot, it in items.items():
        name = (it or {}).get("name", "")
        if not name or name == "empty":
            continue
        (st.stash if slot.startswith("stash") else st.items).append(name)
    my_team = TEAM_IDS.get(st.team)
    for obj in (payload.get("minimap") or {}).values():
        if not isinstance(obj, dict):
            continue
        unit = str(obj.get("unitname") or "")
        if not unit.startswith("npc_dota_hero_") or unit == st.hero:
            continue
        team = _int(obj.get("team"), -1)
        if my_team and team in (2, 3):
            (st.visible_allies if team == my_team else st.visible_enemies).add(unit)
    return st


class GSIServer:
    def __init__(self, port: int, on_state: Callable[[GameState], None]):
        self.port, self.on_state = port, on_state
        self.last_state: GameState | None = None
        self.last_payload_time = 0.0
        self._srv: ThreadingHTTPServer | None = None

    @property
    def connected(self) -> bool:
        return time.time() - self.last_payload_time < 40  # heartbeat de Dota = 30 s

    def handle(self, payload: dict):
        self.last_payload_time = time.time()
        state = parse_state(payload)
        self.last_state = state
        self.on_state(state)

    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(200)
                self.end_headers()
                try:
                    outer.handle(json.loads(body.decode("utf-8", errors="replace")))
                except Exception:
                    log.exception("error procesando payload GSI")

            def log_message(self, *a):
                pass

        self._srv = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        log.info("GSI escuchando en 127.0.0.1:%s", self.port)

    def stop(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None
