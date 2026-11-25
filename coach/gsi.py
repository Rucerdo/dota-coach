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
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

TEAM_IDS = {"radiant": 2, "dire": 3}
HERO_ICONS = {"minimap_herocircle", "minimap_herocircle_self", "minimap_enemyicon"}
IN_GAME_STATES = {"DOTA_GAMERULES_STATE_PRE_GAME", "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"}


@dataclass
class MapUnit:
    """Un héroe en el minimapa (coordenadas del mundo: aprox. -8300..8300; Radiant abajo a la izquierda)."""
    name: str          # npc_dota_hero_*
    team: int          # 2 Radiant, 3 Dire
    x: int
    y: int
    enemy: bool
    me: bool = False


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
    in_transit: list[str] = field(default_factory=list)  # en el courier (lo rellena engine/courier.py)
    visible_enemies: set[str] = field(default_factory=set)  # npc_dota_hero_* vistos en el minimapa
    visible_allies: set[str] = field(default_factory=set)
    x: int | None = None          # tu posición
    y: int | None = None
    units: list[MapUnit] = field(default_factory=list)  # héroes en el minimapa (enemigos solo si se ven)
    slots: dict[str, str] = field(default_factory=dict)  # slot0..8, stash0..5, neutral0, teleport0 → item_*
    abilities: list[dict] = field(default_factory=list)  # [{name, level, ultimate}] en orden
    attributes_level: int = 0
    talents: int = 0              # talentos elegidos
    talent_flags: list[bool] = field(default_factory=list)  # talent_1..8 de GSI (por parejas: 10, 15, 20, 25)
    win_team: str = ""            # radiant | dire cuando acaba la partida
    draft: dict = field(default_factory=dict)  # {"radiant": [hero_id...], "dire": [...], "pick": bool, ...}
    xpm: int = 0
    net_worth: int = 0
    player_id: int | None = None  # 0-4 Radiant, 5-9 Dire (mismo orden que la barra superior)
    radiant_score: int = 0
    dire_score: int = 0
    buildings: dict[str, tuple[int, int]] = field(default_factory=dict)  # TU bando: nombre → (vida, máxima)
    events: list[dict] = field(default_factory=list)  # eventos con 'type' (CHAT_MESSAGE_*) y sus playerid/valores
    received: float = 0.0

    @property
    def in_game(self) -> bool:
        return self.game_state in IN_GAME_STATES and bool(self.hero)

    @property
    def all_items(self) -> list[str]:
        return self.items + self.stash + self.in_transit

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


def parse_draft(draft) -> dict:
    """Sección 'draft' de GSI (selección de héroes). Formato según Dota2GSI: teamN con pickK_id / pickK_class y
    banK_id / banK_class. Se lee de forma tolerante porque a un jugador puede no llegar (solo espectador)."""
    import re
    if not isinstance(draft, dict) or not draft:
        return {}
    out = {"radiant": [], "dire": [], "radiant_bans": [], "dire_bans": [],
           "active": {2: "radiant", 3: "dire"}.get(_int(draft.get("activeteam"), 0), ""),
           "pick": bool(draft.get("pick", True)), "time_left": _int(draft.get("activeteam_time_remaining"))}
    for team_key, side in (("team2", "radiant"), ("team3", "dire")):
        block = draft.get(team_key) or {}
        for key, value in block.items():
            m = re.fullmatch(r"(pick|ban)(\d+)_(id|class)", key)
            if not m or not value:
                continue
            target = out[side] if m.group(1) == "pick" else out[f"{side}_bans"]
            ref = _int(value) if m.group(3) == "id" else f"npc_dota_hero_{value}"
            if ref and ref not in target:
                target.append(ref)
    return out


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
    st.xpm = _int(p.get("xpm"))
    st.radiant_score, st.dire_score = _int(m.get("radiant_score")), _int(m.get("dire_score"))
    if "team_slot" in p and st.team in TEAM_IDS:
        st.player_id = _int(p.get("team_slot")) + (5 if st.team == "dire" else 0)
    for side in (payload.get("buildings") or {}).values():
        for bname, b in (side or {}).items():
            if isinstance(b, dict) and "health" in b:
                st.buildings[bname] = (_int(b.get("health")), _int(b.get("max_health")))
    for e in payload.get("events") or []:
        if not isinstance(e, dict):
            continue
        data = {}
        if e.get("data"):
            try:
                data = json.loads(e["data"])
            except (TypeError, ValueError):
                data = {}
        data.setdefault("type", e.get("event_type", ""))
        data.setdefault("time", e.get("game_time"))
        st.events.append(data)
    st.win_team = str(m.get("win_team") or "").lower().replace("none", "")
    st.attributes_level = _int(h.get("attributes_level"))
    st.talent_flags = [h.get(f"talent_{i}") is True for i in range(1, 9)]
    st.talents = sum(st.talent_flags)
    for key in sorted((payload.get("abilities") or {}), key=lambda k: _int(k.removeprefix("ability"))):
        a = payload["abilities"][key] or {}
        if a.get("name"):
            st.abilities.append({"name": a["name"], "level": _int(a.get("level")), "ultimate": bool(a.get("ultimate"))})
    st.draft = parse_draft(payload.get("draft"))
    if "xpos" in h and "ypos" in h:
        st.x, st.y = _int(h.get("xpos")), _int(h.get("ypos"))
    for slot, it in items.items():
        name = (it or {}).get("name", "")
        if not name or name == "empty" or slot.startswith("preserved"):
            continue
        st.slots[slot] = name
        if slot.startswith("teleport"):
            continue  # el TP no cuenta como objeto de la build
        (st.stash if slot.startswith("stash") else st.items).append(name)
    my_team = TEAM_IDS.get(st.team)
    for obj in (payload.get("minimap") or {}).values():
        if not isinstance(obj, dict):
            continue
        unit = str(obj.get("unitname") or "")
        if not unit.startswith("npc_dota_hero_"):
            continue
        team = _int(obj.get("team"), -1)
        if team not in (2, 3):
            continue
        image = str(obj.get("image") or "")
        if image and image not in HERO_ICONS:
            # p. ej. minimap_plaincircle: en la fase de estrategia/previa Dota pone marcadores provisionales de TODOS
            # los héroes con team=2 (comprobado en una sala personalizada): no dicen nada del bando
            continue
        me = unit == st.hero or image == "minimap_herocircle_self"
        # el icono manda: enemyicon = enemigo, herocircle = aliado (más fiable que 'team')
        enemy = image == "minimap_enemyicon" if image else (bool(my_team) and team != my_team)
        if "xpos" in obj and "ypos" in obj:
            st.units.append(MapUnit(unit, team, _int(obj.get("xpos")), _int(obj.get("ypos")), enemy=enemy, me=me))
        if not me and (my_team or image):
            (st.visible_enemies if enemy else st.visible_allies).add(unit)
    return st


class GameTracker:
    """Detecta cuándo empieza OTRA partida. No basta con el match_id: contra bots y en lobbies locales Dota
    manda siempre "0". También cuenta como partida nueva cambiar de héroe o que el reloj vuelva muy atrás."""

    def __init__(self):
        self.key: tuple | None = None
        self.last_clock: int | None = None
        self.serial = 0  # sube con cada partida nueva

    def update(self, st: "GameState") -> bool:
        """True si 'st' es de una partida distinta a la anterior (la primera no cuenta como cambio)."""
        key = (st.match_id, st.hero)
        new = False
        if self.key is None:
            self.key = key
        elif st.match_id and st.match_id != self.key[0]:
            new = True
        elif st.hero and self.key[1] and st.hero != self.key[1]:
            new = True
        elif st.in_game and self.last_clock is not None and st.clock + 120 < self.last_clock:
            new = True
        if new:
            self.serial += 1
            self.key = key
            self.last_clock = None
        if st.hero and not self.key[1]:
            self.key = (self.key[0], st.hero)
        if st.in_game:
            self.last_clock = st.clock
        return new


class GSIRecorder:
    """Guarda envíos de Dota en un .jsonl (uno cada 'every' segundos) para estudiar qué datos llegan de verdad
    (p. ej. el minimapa). Se rota al pasar de 'max_mb' para no llenar el disco."""

    def __init__(self, path: Path, every: float = 2.0, max_mb: float = 50.0):
        self.path, self.every, self.max_bytes = path, every, int(max_mb * 1024 * 1024)
        self._last = 0.0
        self._lock = threading.Lock()

    def write(self, payload: dict):
        now = time.time()
        with self._lock:
            if now - self._last < self.every:
                return
            self._last = now
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                    self.path.replace(self.path.with_suffix(".old.jsonl"))
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"t": round(now, 2), "payload": payload}, ensure_ascii=False) + "\n")
            except OSError:
                log.exception("no se pudo grabar el envío de GSI")


class GSIServer:
    def __init__(self, port: int, on_state: Callable[[GameState], None], recorder: GSIRecorder | None = None):
        self.port, self.on_state, self.recorder = port, on_state, recorder
        self.last_state: GameState | None = None
        self.last_payload_time = 0.0
        self._srv: ThreadingHTTPServer | None = None

    @property
    def connected(self) -> bool:
        return time.time() - self.last_payload_time < 40  # heartbeat de Dota = 30 s

    def handle(self, payload: dict):
        self.last_payload_time = time.time()
        if self.recorder:
            self.recorder.write(payload)
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
