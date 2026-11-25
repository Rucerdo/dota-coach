"""Vigilancia del mapa con las posiciones que manda GSI (los enemigos solo cuando tu minimapa los muestra, es
decir, lo mismo que ves tú): reparto de líneas y avisos de peligro.

Coordenadas del mundo: de -8300 a 8300 aprox.; base Radiant abajo a la izquierda, Dire arriba a la derecha.
Top = borde izquierdo y de arriba, bot = borde de abajo y derecho, mid = la diagonal.

Avisos (como mucho uno por héroe y motivo cada cierto tiempo):
  - mia     un enemigo de tu línea lleva un rato sin verse (posible gank)
  - near    enemigos cerca de ti: dos o más, o uno que no es de tu línea
  - tp      un enemigo aparece muy lejos de donde se le vio hace un momento (TP o similar)
"""
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..data.gamedata import GameData, Hero
from ..gsi import GameState

LANES = ["top", "mid", "bot"]
ZONE_LABELS = {"top": "top", "mid": "mid", "bot": "bot", "jungle": "la jungla", "base": "su base"}
FORTS = {2: (-5920, -5352), 3: (5528, 5000)}

LANING = (30, 10 * 60)        # cuándo se mira quién va a cada línea (segundos de partida)
MIA_SECONDS = 25
MIA_UNTIL = 14 * 60           # después de la fase de líneas un enemigo "desaparecido" no significa nada
NEAR_DISTANCE = 2200
TP_DISTANCE = 4500
TP_WINDOW = 6                 # segundos entre la última vez que se vio y la nueva aparición
COOLDOWN = 30


def zone(x: int, y: int) -> str:
    for fx, fy in FORTS.values():
        if math.hypot(x - fx, y - fy) < 2600:
            return "base"
    if abs(x - y) < 2200 and -5000 < x < 5000:
        return "mid"
    if x < -4200 or y > 4800:
        return "top"
    if x > 4200 or y < -4800:
        return "bot"
    return "jungle"


@dataclass
class Alert:
    kind: str     # mia | near | tp
    text: str
    clock: int


@dataclass
class LaneInfo:
    allies: list[Hero] = field(default_factory=list)
    enemies: list[Hero] = field(default_factory=list)


class MapWatch:
    def __init__(self, gd: GameData):
        self.gd = gd
        self.reset()

    def reset(self):
        self.samples: dict[str, Counter] = defaultdict(Counter)   # héroe → zonas durante la fase de líneas
        self.team: dict[str, bool] = {}                           # héroe → es enemigo
        self.last_seen: dict[str, tuple[int, int, int]] = {}      # enemigo → (reloj, x, y)
        self.cooldown: dict[tuple[str, str], int] = {}
        self.mia_warned: set[str] = set()
        self.me = ""

    # ---------- reparto de líneas ----------
    def lane_of(self, name: str) -> str | None:
        counts = self.samples.get(name)
        if not counts:
            return None
        lanes = {z: n for z, n in counts.items() if z in LANES}
        if not lanes:
            return None
        lane, n = max(lanes.items(), key=lambda kv: kv[1])
        return lane if n >= 0.3 * sum(counts.values()) and n >= 5 else None

    def lanes(self) -> dict[str, LaneInfo]:
        out = {lane: LaneInfo() for lane in LANES}
        for name, enemy in self.team.items():
            lane, hero = self.lane_of(name), self.gd.hero(name)
            if lane and hero:
                (out[lane].enemies if enemy else out[lane].allies).append(hero)
        return out

    def my_lane(self) -> str | None:
        return self.lane_of(self.me) if self.me else None

    # ---------- avisos ----------
    def _name(self, unit: str) -> str:
        h = self.gd.hero(unit)
        return h.loc if h else unit.removeprefix("npc_dota_hero_")

    def _ready(self, key: tuple[str, str], clock: int, every: int = COOLDOWN) -> bool:
        last = self.cooldown.get(key)
        if last is not None and clock - last < every:
            return False
        self.cooldown[key] = clock
        return True

    def update(self, st: GameState) -> list[Alert]:
        if not st.in_game or not st.units:
            return []
        clock, alerts = st.clock, []
        self.me = st.hero
        me = next((u for u in st.units if u.me), None)
        seen_now = set()
        for u in st.units:
            self.team[u.name] = u.enemy
            if LANING[0] <= clock <= LANING[1]:
                self.samples[u.name][zone(u.x, u.y)] += 1
            if not u.enemy:
                continue
            seen_now.add(u.name)
            prev = self.last_seen.get(u.name)
            if prev and 0 < clock - prev[0] <= TP_WINDOW and math.hypot(u.x - prev[1], u.y - prev[2]) > TP_DISTANCE:
                z = zone(u.x, u.y)
                if z != "base" and self._ready((u.name, "tp"), clock):
                    alerts.append(Alert("tp", f"{self._name(u.name)} ha aparecido en {ZONE_LABELS[z]} (TP)", clock))
            self.last_seen[u.name] = (clock, u.x, u.y)
            self.mia_warned.discard(u.name)

        if me is None or not st.alive:
            return alerts
        my_lane = self.my_lane()
        # enemigos cerca de ti
        near = [u for u in st.units if u.enemy and math.hypot(u.x - me.x, u.y - me.y) < NEAR_DISTANCE]
        strangers = [u for u in near if my_lane and self.lane_of(u.name) not in (None, my_lane)]
        # en la fase de líneas tus rivales de línea siempre están cerca: solo avisa si llega alguien de fuera
        danger = (strangers or len(near) >= 3) if clock <= MIA_UNTIL else len(near) >= 2
        if danger and self._ready(("near", "group"), clock, 20):
            names = ", ".join(self._name(u.name) for u in near)
            alerts.append(Alert("near", f"Cuidado: {names} cerca de ti", clock))
        # enemigos de tu línea que han desaparecido
        if my_lane and clock <= MIA_UNTIL and zone(me.x, me.y) == my_lane:
            for name, enemy in self.team.items():
                if not enemy or name in seen_now or name in self.mia_warned or self.lane_of(name) != my_lane:
                    continue
                last = self.last_seen.get(name)
                if last and clock - last[0] >= MIA_SECONDS:
                    self.mia_warned.add(name)
                    alerts.append(Alert("mia", f"{self._name(name)} ha desaparecido de tu línea "
                                               f"(hace {clock - last[0]} s): cuidado con un gank", clock))
        return alerts
