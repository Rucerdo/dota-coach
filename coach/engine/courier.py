"""Objetos en camino en el courier.

GSI no manda el contenido del courier a un jugador (la sección 'couriers' llega vacía), pero sí el alijo. Cuando un
objeto sale del alijo y no aparece en tu inventario, lo lleva el courier: se cuenta como tuyo ("en camino") para
que la build y el siguiente objeto no lo vuelvan a sugerir. Deja de estar en camino cuando aparece en el inventario
(o un objeto que lo usa como componente: se combinan al llegar) o, por si acaso, a los TRANSIT_MAX segundos.
"""
from collections import Counter
from dataclasses import dataclass

from ..data.gamedata import GameData
from ..gsi import GameState

TRANSIT_MAX = 180


@dataclass
class InTransit:
    name: str
    since: int     # reloj de la partida


class CourierTracker:
    def __init__(self, gd: GameData):
        self.gd = gd
        self.reset()

    def reset(self):
        self.prev_stash: Counter | None = None
        self.prev_inv: Counter = Counter()
        self.transit: list[InTransit] = []

    def _components(self, name: str) -> set[str]:
        out, todo = set(), [name]
        while todo:
            item = self.gd.item(todo.pop())
            for c in (item.components if item else []):
                if c not in out:
                    out.add(c)
                    todo.append(c)
        return out

    def update(self, st: GameState) -> list[str]:
        """Actualiza y devuelve los objetos en camino (item_*)."""
        stash, inv = Counter(st.stash), Counter(st.items)
        if not st.in_game:
            self.prev_stash, self.prev_inv = stash, inv
            return []
        if self.prev_stash is not None:
            arrived = inv - self.prev_inv
            left = self.prev_stash - stash
            for name, n in (left - arrived).items():
                self.transit += [InTransit(name, st.clock) for _ in range(n)]
            # lo que llega (tal cual o combinado en un objeto mayor) deja de estar en camino
            for name, n in arrived.items():
                parts = self._components(name)
                for _ in range(n):
                    match = next((t for t in self.transit if t.name == name), None)
                    if match:
                        self.transit.remove(match)
                self.transit = [t for t in self.transit if t.name not in parts]
        self.transit = [t for t in self.transit if st.clock - t.since <= TRANSIT_MAX]
        self.prev_stash, self.prev_inv = stash, inv
        return [t.name for t in self.transit]
