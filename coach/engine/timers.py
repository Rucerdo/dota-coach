"""Temporizadores de la partida (runas, stackeo, día/noche) con aviso unos segundos antes.

Los tiempos son los de los últimos parches; REVISARLOS con cada parche grande (constante TIMERS). Solo usan el
reloj de la partida, nada que el jugador no vea.
"""
from dataclasses import dataclass

# nombre → (primera vez en segundos, cada cuántos segundos, roles que reciben aviso: None = todos, () = ninguno)
TIMERS = {
    "bounty": ("Runas de recompensa", 0, 180, None),
    "power": ("Runa de poder", 6 * 60, 120, ("core", "carry")),
    "wisdom": ("Runas de sabiduría", 7 * 60, 7 * 60, ("support",)),
    "lotus": ("Loto", 3 * 60, 180, ("support",)),
    "stack": ("Stackear (x:53)", 53, 60, ()),     # se ve en el panel; avisar cada minuto sería demasiado
    "daynight": ("Cambio día/noche", 5 * 60, 5 * 60, ()),
}
WARN_SECONDS = 15


@dataclass
class TimerState:
    key: str
    label: str
    seconds_left: int


@dataclass
class TimerAlert:
    text: str
    clock: int


def next_in(clock: int, first: int, every: int) -> int:
    """Segundos hasta la próxima aparición (0 si es justo ahora)."""
    if clock < first:
        return first - clock
    return (every - (clock - first) % every) % every


def upcoming(clock: int) -> list[TimerState]:
    out = []
    for key, (label, first, every, _) in TIMERS.items():
        out.append(TimerState(key, label, next_in(clock, first, every)))
    return out


class TimerWatch:
    def __init__(self, role: str = "core", enabled: bool = True):
        self.role, self.enabled = role, enabled
        self.warned: set[tuple[str, int]] = set()

    def reset(self):
        self.warned.clear()

    def update(self, clock: int, in_game: bool) -> list[TimerAlert]:
        if not self.enabled or not in_game or clock < 0:
            return []
        alerts = []
        for key, (label, first, every, roles) in TIMERS.items():
            if roles is not None and self.role not in roles:
                continue
            left = next_in(clock, first, every)
            if 0 < left <= WARN_SECONDS:
                when = clock + left
                if (key, when) not in self.warned:
                    self.warned.add((key, when))
                    alerts.append(TimerAlert(f"{label} en {left} s", clock))
        return alerts
