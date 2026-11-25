"""Habilidades: avisa de puntos sin gastar, de la definitiva en 6/12/18 y de los talentos en 10/15/20/25.

Puntos gastados = niveles de las habilidades + talentos elegidos + nivel de atributos. GSI no dice cuántos
puntos quedan, pero cada nivel del héroe da uno (salvo algunos niveles altos en los que no hay nada que subir).
"""
from dataclasses import dataclass

from ..gsi import GameState

ULT_LEVELS = (6, 12, 18)
TALENT_LEVELS = (10, 15, 20, 25)
GRACE_SECONDS = 8   # se deja un momento para subirla antes de avisar


@dataclass
class SkillAlert:
    text: str
    clock: int


def unspent_points(st: GameState) -> int:
    if not st.abilities or not st.level:
        return 0
    spent = sum(a["level"] for a in st.abilities) + st.talents + st.attributes_level
    return max(0, st.level - spent)


class SkillWatch:
    def __init__(self):
        self.reset()

    def reset(self):
        self.pending_since: int | None = None
        self.warned_level = 0

    def update(self, st: GameState) -> list[SkillAlert]:
        if not st.in_game or not st.alive:
            return []
        points = unspent_points(st)
        if points <= 0:
            self.pending_since = None
            return []
        if self.pending_since is None:
            self.pending_since = st.clock
            return []
        if st.clock - self.pending_since < GRACE_SECONDS or self.warned_level >= st.level:
            return []
        self.warned_level = st.level
        ult = next((a for a in st.abilities if a["ultimate"]), None)
        if st.level in ULT_LEVELS and ult and ult["level"] < ULT_LEVELS.index(st.level) + 1:
            return [SkillAlert(f"Nivel {st.level}: sube la definitiva", st.clock)]
        if st.level in TALENT_LEVELS:
            return [SkillAlert(f"Nivel {st.level}: elige talento", st.clock)]
        extra = f" ({points} puntos)" if points > 1 else ""
        return [SkillAlert(f"Tienes un punto de habilidad sin gastar{extra}", st.clock)]
