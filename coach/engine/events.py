"""Eventos de la partida que llegan por GSI: torres de tu bando, asesinatos, rachas y compras de aliados.

- buildings: vida de las torres/cuarteles/ancestro de TU bando → aviso al recibir daño serio o al perderlas.
- CHAT_MESSAGE_HERO_KILL: playerid1 = quien mata, playerid2 = quien muere (comprobado con una partida real).
- CHAT_MESSAGE_STREAK_KILL: playerid1 = quien lleva la racha, playerid2 = cuántas lleva.
- CHAT_MESSAGE_ITEM_PURCHASE: aviso de chat "X ha comprado…" (solo algunos objetos); playerid1 = comprador.
Los player_id (0-4 Radiant, 5-9 Dire) siguen el orden de la barra superior: el héroe sale de la visión.
"""
import re
from dataclasses import dataclass, field

from ..data.gamedata import GameData, Hero
from ..gsi import GameState

LANE_NAMES = {"top": "top", "mid": "mid", "bot": "bot"}
DAMAGE_DROP = 0.15         # caída de vida (fracción de la máxima) que merece aviso
DAMAGE_WINDOW = 12         # en cuántos segundos
TOWER_COOLDOWN = 40
STREAK_ALERT = 3           # racha enemiga desde la que se avisa


@dataclass
class Notice:
    kind: str              # tower | streak | kill | purchase
    title: str
    text: str
    clock: int
    level: str = "info"    # info | warn | danger (para el color de la notificación)
    toast: bool = True     # merece notificación flotante


MAX_KILLS = 300   # todas las de la partida


@dataclass
class Kill:
    clock: int
    killer: Hero | None
    victim: Hero | None
    killer_enemy: bool | None   # None si no se sabe de qué bando es


@dataclass
class EventsState:
    towers: list[tuple[str, float]] = field(default_factory=list)   # (etiqueta, vida 0-1) de tu bando
    kills: list[Kill] = field(default_factory=list)
    purchases: list[tuple[int, str, str]] = field(default_factory=list)  # (reloj, héroe, objeto)
    streaks: dict[str, int] = field(default_factory=dict)            # héroe → racha actual


def building_label(name: str) -> str | None:
    """dota_badguys_tower2_mid → 'T2 mid'; *_melee_rax_bot → 'Cuartel cuerpo a cuerpo bot'; fort → 'Ancestro'."""
    m = re.search(r"tower(\d)_(top|mid|bot)", name)
    if m:
        return f"T{m.group(1)} {LANE_NAMES[m.group(2)]}"
    if re.search(r"tower4", name):
        return "T4"
    m = re.search(r"(melee|range)_rax_(top|mid|bot)", name)
    if m:
        return f"Cuartel {'cuerpo a cuerpo' if m.group(1) == 'melee' else 'a distancia'} {m.group(2)}"
    if name.endswith("_fort"):
        return "Ancestro"
    return None


class EventWatch:
    def __init__(self, gd: GameData):
        self.gd = gd
        self.reset()

    def reset(self):
        self.seen: set[tuple] = set()
        self.history: dict[str, list[tuple[int, int]]] = {}   # edificio → [(reloj, vida)]
        self.lost: set[str] = set()
        self.cooldown: dict[str, int] = {}
        self.state = EventsState()
        self.my_kills: dict[int, int] | None = None   # último kill_list visto (None = aún ninguno)

    def _hero(self, pid, heroes: dict[int, Hero]) -> Hero | None:
        try:
            return heroes.get(int(pid))
        except (TypeError, ValueError):
            return None

    def update(self, st: GameState, heroes_by_pid: dict[int, Hero]) -> list[Notice]:
        out: list[Notice] = []
        out += self._buildings(st)
        out += self._events(st, heroes_by_pid)
        self._my_kills(st, heroes_by_pid)
        return out

    def _my_kills(self, st: GameState, heroes: dict[int, Hero]):
        """Tus asesinatos (de kill_list: Dota no manda el aviso de chat cuando matas tú)."""
        prev = self.my_kills or {}
        me = heroes.get(st.player_id) if st.player_id is not None else None
        new = []
        for pid, n in st.kill_list.items():
            for _ in range(max(0, n - prev.get(pid, 0))):
                victim = heroes.get(pid)
                new.append(Kill(st.clock, me, victim, False))
                if victim:
                    self.state.streaks.pop(victim.loc, None)
        self.my_kills = dict(st.kill_list)
        if new:
            self.state.kills = (self.state.kills + new)[-MAX_KILLS:]

    # ---------- torres ----------
    def _buildings(self, st: GameState) -> list[Notice]:
        out, towers = [], []
        for name, (hp, max_hp) in st.buildings.items():
            label = building_label(name)
            if not label or max_hp <= 0:
                continue
            frac = hp / max_hp
            if "tower" in name:
                towers.append((label, frac))
            hist = [h for h in self.history.get(name, []) if st.clock - h[0] <= DAMAGE_WINDOW]
            hist.append((st.clock, hp))
            self.history[name] = hist
            if hp <= 0 and name not in self.lost:
                self.lost.add(name)
                out.append(Notice("tower", "Estructura perdida", f"Habéis perdido: {label}", st.clock, "danger"))
                continue
            drop = (max(h for _, h in hist) - hp) / max_hp
            last = self.cooldown.get(name)
            if drop >= DAMAGE_DROP and frac < 0.9 and (last is None or st.clock - last >= TOWER_COOLDOWN):
                self.cooldown[name] = st.clock
                out.append(Notice("tower", f"{label} bajo ataque",
                                  f"{label} está recibiendo daño: le queda un {frac:.0%}", st.clock, "warn"))
        order = {"top": 0, "mid": 1, "bot": 2}
        self.state.towers = sorted(towers, key=lambda t: (order.get(t[0].split(" ")[-1], 3), t[0]))
        return out

    # ---------- asesinatos, rachas, compras ----------
    def _events(self, st: GameState, heroes: dict[int, Hero]) -> list[Notice]:
        out = []
        mine = range(0, 5) if st.team == "radiant" else range(5, 10) if st.team == "dire" else None
        for e in st.events:
            key = (e.get("type"), round(float(e.get("time") or 0), 1), e.get("playerid1"), e.get("playerid2"))
            if key in self.seen:
                continue
            self.seen.add(key)
            etype = str(e.get("type") or "")
            p1, p2 = e.get("playerid1"), e.get("playerid2")
            clock = st.clock
            if etype == "CHAT_MESSAGE_HERO_KILL":
                killer, victim = self._hero(p1, heroes), self._hero(p2, heroes)
                enemy = None if mine is None or p1 is None or int(p1) < 0 else int(p1) not in mine
                if p1 is not None and st.player_id is not None and int(p1) == st.player_id:
                    continue  # tus asesinatos ya salen de kill_list (por si Dota también los avisa)
                self.state.kills = (self.state.kills + [Kill(clock, killer, victim, enemy)])[-MAX_KILLS:]
                if victim:
                    self.state.streaks.pop(victim.loc, None)
            elif etype == "CHAT_MESSAGE_STREAK_KILL":
                killer = self._hero(p1, heroes)
                count = int(p2) if isinstance(p2, int) and p2 > 0 else 0
                enemy = mine is not None and p1 is not None and int(p1) >= 0 and int(p1) not in mine
                if killer and count:
                    self.state.streaks[killer.loc] = count
                    if enemy and count >= STREAK_ALERT:
                        out.append(Notice("streak", f"{killer.loc} va lanzado",
                                          f"{killer.loc} lleva {count} asesinatos seguidos: no le des otro",
                                          clock, "danger"))
            elif etype == "CHAT_MESSAGE_ITEM_PURCHASE":
                buyer = self._hero(p1, heroes)
                item = self.gd.items.get(int(e.get("value") or 0))
                if buyer and item:
                    self.state.purchases = (self.state.purchases + [(clock, buyer.loc, item.loc)])[-6:]
        return out
