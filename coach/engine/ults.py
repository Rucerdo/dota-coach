"""Definitivas de los enemigos: cuánto les queda (estimado) desde que TÚ marcas que la han usado.

GSI no dice nada de las habilidades de los demás, así que el momento lo marca el jugador con un atajo
(Ctrl+F1…F5 = huecos 1-5 del bando enemigo en la barra superior, de izquierda a derecha; Ctrl+Shift+F1…F5 = está
lista otra vez / me equivoqué). Es lo mismo que hacer la cuenta de cabeza al verla: solo se automatiza la cuenta.

- Enfriamiento por nivel: datos oficiales de Valve (herodata, `cooldowns`).
- Nivel de la definitiva: no se sabe el nivel del enemigo; se toma el tuyo ±2 (la partida va al mismo ritmo para
  todos, también en turbo) y se da un margen: "lista en 40-70 s".
- No se cuentan Octarine Core, talentos de enfriamiento ni Refresher (no vemos sus objetos): si la vuelve a usar
  antes de tiempo, se marca otra vez.
"""
from dataclasses import dataclass

from ..data.gamedata import Hero

ULT_LEVELS = (6, 12, 18)     # niveles del héroe en que se sube la definitiva
LEVEL_SPREAD = 2             # el enemigo puede ir hasta 2 niveles por delante o por detrás de ti
KEYS = 5


@dataclass
class Ult:
    name: str                 # p. ej. enigma_black_hole (también el nombre del icono de Valve)
    loc: str                  # Black Hole
    cooldowns: list[float]    # por nivel de la definitiva


@dataclass
class UltTimer:
    hero: Hero
    ult: Ult
    cast_at: int              # reloj de la partida al marcarla
    ready_min: int            # reloj en que puede estar lista (nivel más alto posible)
    ready_max: int            # reloj en que seguro que lo está (nivel más bajo posible)
    warned: bool = False

    def remaining(self, clock: int) -> tuple[int, int]:
        return max(0, self.ready_min - clock), max(0, self.ready_max - clock)


def ult_from_herodata(hero: dict) -> Ult | None:
    """La definitiva propia del héroe (no las que dan el Aghanim o el Shard)."""
    for a in hero.get("abilities") or []:
        if a.get("type") == 1 and not a.get("ability_is_granted_by_shard") \
                and not a.get("ability_is_granted_by_scepter"):
            cds = [float(c) for c in a.get("cooldowns") or [] if c is not None]
            return Ult(a["name"], a.get("name_loc") or a["name"], cds)
    return None


def ult_level(hero_level: int) -> int:
    return max(1, sum(1 for lv in ULT_LEVELS if hero_level >= lv))


def cooldown_range(ult: Ult, my_level: int) -> tuple[float, float]:
    """(mínimo, máximo) del enfriamiento según el nivel que pueda llevar el enemigo."""
    if not ult.cooldowns:
        return 0.0, 0.0

    def cd(level: int) -> float:
        return ult.cooldowns[min(level, len(ult.cooldowns)) - 1]
    low, high = ult_level(my_level - LEVEL_SPREAD), ult_level(my_level + LEVEL_SPREAD)
    values = [cd(lv) for lv in range(low, high + 1)]
    return min(values), max(values)


def fmt_seconds(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}" if s >= 60 else f"{s} s"


class UltTracker:
    def __init__(self, ult_of):
        """ult_of(hero) → Ult | None (de los datos de Valve, en caché)."""
        self.ult_of = ult_of
        self.reset()

    def reset(self):
        self.timers: dict[int, UltTimer] = {}   # id del héroe → temporizador

    def cast(self, hero: Hero, clock: int, my_level: int) -> UltTimer | None:
        """El jugador marca que lo ha visto usar la definitiva (si ya estaba marcada, se reinicia: Refresher)."""
        ult = self.ult_of(hero)
        if ult is None:
            return None
        low, high = cooldown_range(ult, my_level)
        timer = UltTimer(hero, ult, clock, clock + int(low), clock + int(high))
        self.timers[hero.id] = timer
        return timer

    def ult_info_cached(self, hero: Hero) -> Ult | None:
        """Sin pedir nada a la red: solo si ya se descargó (para pintar el icono antes de marcarla)."""
        cache = getattr(self.ult_of, "cache", None)
        return cache.get(hero.id) if cache is not None else None

    def clear(self, hero: Hero) -> bool:
        return self.timers.pop(hero.id, None) is not None

    def get(self, hero: Hero, clock: int) -> UltTimer | None:
        t = self.timers.get(hero.id)
        if t and clock >= t.ready_max + 60:
            del self.timers[hero.id]   # lista hace rato: deja de mostrarse
            return None
        if t and clock < t.cast_at - 5:
            del self.timers[hero.id]   # el reloj ha ido hacia atrás (otra partida)
            return None
        return t

    def update(self, clock: int) -> list[UltTimer]:
        """Las que acaban de poder estar listas (para avisar una sola vez)."""
        out = []
        for t in list(self.timers.values()):
            if not t.warned and clock >= t.ready_min:
                t.warned = True
                out.append(t)
        return out

    def context(self, clock: int) -> str:
        """Para la IA."""
        parts = []
        for t in list(self.timers.values()):
            lo, hi = t.remaining(clock)
            state = "may be ready now" if lo == 0 else f"on cooldown, ready in ~{lo}-{hi}s"
            parts.append(f"{t.hero.loc}'s {t.ult.loc}: {state}")
        return ("Enemy ultimates (estimated from when the player saw them used): " + "; ".join(parts)) if parts else ""


def enemy_order(by_player: dict[int, Hero], my_team: str, enemies: list[Hero]) -> list[Hero | None]:
    """Los 5 huecos enemigos de la barra superior, de izquierda a derecha (Ctrl+F1…F5). Los que la visión no ha
    reconocido se rellenan con el resto de enemigos conocidos, en el orden en que se detectaron."""
    first = 5 if my_team == "radiant" else 0
    slots: list[Hero | None] = [by_player.get(first + i) for i in range(KEYS)]
    placed = {h.id for h in slots if h}
    rest = [h for h in enemies if h.id not in placed]
    for i in range(KEYS):
        if slots[i] is None and rest:
            slots[i] = rest.pop(0)
    return slots


__all__ = ["KEYS", "Ult", "UltTimer", "UltTracker", "cooldown_range", "enemy_order", "fmt_seconds",
           "ult_from_herodata", "ult_level"]
