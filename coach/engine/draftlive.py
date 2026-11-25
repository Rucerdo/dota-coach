"""Ayuda en la selección de héroes en directo: qué héroes elegir contra lo que ya han cogido los rivales.

Los héroes elegidos salen de la sección 'draft' de GSI si Dota la manda al jugador, o, si no, de los que la
visión haya reconocido en la barra superior. Las sugerencias usan el motor de draft (matchups de OpenDota
suavizados + meta del parche), excluyendo los baneados.
"""
from dataclasses import dataclass, field

from ..data.gamedata import GameData, Hero
from ..gsi import GameState
from .draft import PickSuggestion

DRAFT_STATES = {"DOTA_GAMERULES_STATE_HERO_SELECTION", "DOTA_GAMERULES_STATE_STRATEGY_TIME"}


def is_drafting(st: GameState) -> bool:
    return st.game_state in DRAFT_STATES


@dataclass
class DraftView:
    allies: list[Hero] = field(default_factory=list)
    enemies: list[Hero] = field(default_factory=list)
    bans: list[Hero] = field(default_factory=list)
    picks: list[PickSuggestion] = field(default_factory=list)
    source: str = ""             # gsi | visión
    my_turn: bool = False

    @property
    def key(self) -> tuple:
        return tuple(sorted(h.id for h in self.allies)), tuple(sorted(h.id for h in self.enemies)), \
            tuple(sorted(h.id for h in self.bans))


def _heroes(gd: GameData, refs) -> list[Hero]:
    out = []
    for ref in refs or []:
        h = gd.hero(ref) if isinstance(ref, str) else gd.heroes.get(int(ref))
        if h and h not in out:
            out.append(h)
    return out


def draft_state(gd: GameData, st: GameState, seen_allies: list[Hero] = (), seen_enemies: list[Hero] = ()
                ) -> DraftView:
    """Aliados, enemigos y baneos ahora mismo (GSI si lo trae; si no, lo que haya visto la visión)."""
    team = st.team if st.team in ("radiant", "dire") else ""
    other = {"radiant": "dire", "dire": "radiant"}.get(team, "")
    d = st.draft or {}
    if team and (d.get(team) or d.get(other)):
        view = DraftView(_heroes(gd, d.get(team)), _heroes(gd, d.get(other)),
                         _heroes(gd, (d.get("radiant_bans") or []) + (d.get("dire_bans") or [])), source="gsi",
                         my_turn=d.get("active") == team and bool(d.get("pick", True)))
    else:
        view = DraftView(list(seen_allies), list(seen_enemies), source="visión")
    me = gd.hero(st.hero) if st.hero else None
    if me and me not in view.allies:
        view.allies.insert(0, me)
    return view
