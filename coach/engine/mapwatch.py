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
MIA_SECONDS = 30
MIA_UNTIL = 14 * 60           # después de la fase de líneas un enemigo "desaparecido" no significa nada
NEAR_DISTANCE = 2200
TP_DISTANCE = 4500
TP_WINDOW = 6                 # segundos entre la última vez que se vio y la nueva aparición
COOLDOWN = 30
QUIET_START = 60              # el primer minuto (y mientras estés en tu base) no hay avisos de enemigos cerca


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
        self.dead: dict[str, int] = {}      # enemigos muertos (hasta que se les vuelve a ver)
        self.multi: set[str] = set()        # héroes con clon/ilusiones (su posición no sirve para TPs)
        self.tp_pending: dict[str, tuple[int, int, int]] = {}   # salto visto una vez: se confirma en la siguiente
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

    def mark_dead(self, unit: str, clock: int):
        """Un enemigo ha muerto (aviso de muerte de GSI): mientras no reaparezca no está "desaparecido"."""
        self.dead[unit] = clock

    def update(self, st: GameState) -> list[Alert]:
        if not st.in_game or not st.units:
            return []
        clock, alerts = st.clock, []
        self.me = st.hero
        # en turbo las líneas se rompen antes: reparto hasta el minuto 6 y "desaparecidos" hasta el 8
        laning_end, mia_until = (6 * 60, 8 * 60) if st.turbo else (LANING[1], MIA_UNTIL)
        me = next((u for u in st.units if u.me), None)
        # un nombre puede salir varias veces (clon de Arc Warden, ilusiones): cuenta como UN héroe, y un nombre
        # repetido no sirve para detectar TPs (el clon y el original están en sitios distintos)
        by_name: dict[str, list] = {}
        for u in st.units:
            by_name.setdefault(u.name, []).append(u)
        seen_now = set()
        for name, units in by_name.items():
            u = units[0]
            self.team[name] = u.enemy
            if LANING[0] <= clock <= laning_end and len(units) == 1:
                self.samples[name][zone(u.x, u.y)] += 1
            if not u.enemy:
                continue
            seen_now.add(name)
            self.dead.pop(name, None)  # se le ve: ya ha reaparecido
            prev = self.last_seen.get(name)
            if prev and len(units) > 1:
                u = min(units, key=lambda x: math.hypot(x.x - prev[1], x.y - prev[2]))
            elif prev and len(units) == 1 and name not in self.multi:
                pend = self.tp_pending.pop(name, None)
                if pend and clock - pend[0] <= 4 and math.hypot(u.x - pend[1], u.y - pend[2]) < 1500:
                    # sigue allí: era un TP de verdad (un dato suelto de GSI vuelve a su sitio al momento)
                    z = zone(u.x, u.y)
                    if z != "base" and self._ready((name, "tp"), clock):
                        alerts.append(Alert("tp", f"{self._name(name)} ha aparecido en {ZONE_LABELS[z]} (TP)", clock))
                elif 0 < clock - prev[0] <= TP_WINDOW and math.hypot(u.x - prev[1], u.y - prev[2]) > TP_DISTANCE:
                    self.tp_pending[name] = (clock, u.x, u.y)
                    continue  # hasta confirmarlo se queda donde estaba (si era un dato suelto, nada cambia)
            if len(units) > 1:
                self.multi.add(name)  # tiene clon/ilusiones: su posición salta y no indica un TP
            self.last_seen[name] = (clock, u.x, u.y)
            self.mia_warned.discard(name)

        if me is None or not st.alive or clock < QUIET_START or zone(me.x, me.y) == "base":
            return alerts  # al salir de la fuente todos están juntos: no es un gank
        my_lane = self.my_lane()
        in_my_lane = bool(my_lane) and zone(me.x, me.y) == my_lane
        # gank: más enemigos (héroes distintos) cerca de ti que aliados contigo
        near_foes = {n for n, units in by_name.items() if units[0].enemy
                     and any(math.hypot(x.x - me.x, x.y - me.y) < NEAR_DISTANCE for x in units)}
        near_mates = {n for n, units in by_name.items() if not units[0].enemy
                      and any(math.hypot(x.x - me.x, x.y - me.y) < NEAR_DISTANCE for x in units)}
        outnumbered = len(near_foes) >= 2 and len(near_foes) > len(near_mates)
        if clock <= mia_until:
            # fase de líneas: solo en TU línea y si llega alguien de fuera (si gankeas tú en otra línea, no)
            strangers = {n for n in near_foes if self.lane_of(n) not in (None, my_lane)}
            danger = in_my_lane and bool(strangers) and outnumbered
        else:
            danger = outnumbered
        if danger and self._ready(("near", "group"), clock, 25):
            names = ", ".join(self._name(n) for n in sorted(near_foes))
            alerts.append(Alert("near", f"Cuidado: {names} vienen a por ti", clock))
        # enemigos de tu línea que han desaparecido (y no están muertos)
        if in_my_lane and clock <= mia_until:
            for name, enemy in self.team.items():
                if (not enemy or name in seen_now or name in self.mia_warned or name in self.dead
                        or self.lane_of(name) != my_lane):
                    continue
                last = self.last_seen.get(name)
                if last and clock - last[0] >= MIA_SECONDS and zone(last[1], last[2]) == my_lane:
                    self.mia_warned.add(name)
                    alerts.append(Alert("mia", f"{self._name(name)} ha desaparecido de tu línea "
                                               f"(hace {clock - last[0]} s): cuidado con un gank", clock))
        return alerts
