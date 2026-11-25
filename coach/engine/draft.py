"""Asistente de draft: qué héroe elegir contra los enemigos ya elegidos.

Puntuación de cada candidato =
    Σ ventaja contra cada enemigo (matchups de OpenDota, suavizados hacia el 50%)
  + peso del meta actual (winrate en tu rango, tendencia reciente, buffs/nerfs del parche)
Solo se piden los matchups de los enemigos (≤5 peticiones), no los de los ~127 candidatos.
"""
from dataclasses import dataclass, field
from typing import Callable

from ..data.gamedata import GameData, Hero
from .counters import player_role

PRIOR_GAMES = 50          # suavizado: la muestra es de partidas pro (pequeña); con pocas, la ventaja tiende a 0
META_WEIGHT = 0.6         # 1 punto de meta_score (≈1 pt de winrate) vale 0.6 pts de ventaja de matchup


@dataclass
class PickSuggestion:
    hero: Hero
    score: float
    vs: dict[str, float] = field(default_factory=dict)   # enemigo → ventaja en puntos de winrate
    meta_line: str = ""

    def line(self) -> str:
        parts = [f"{self.hero.loc} ({self.score:+.1f})"]
        good = [f"{k} {v:+.1f}" for k, v in sorted(self.vs.items(), key=lambda kv: -kv[1]) if abs(v) >= 0.5]
        if good:
            parts.append("vs " + ", ".join(good))
        if self.meta_line:
            parts.append(self.meta_line)
        return " · ".join(parts)


def advantage(wins_of_enemy: int, games: int) -> float:
    """Ventaja del candidato en puntos de winrate, a partir del resultado del enemigo contra él."""
    enemy_wr = (wins_of_enemy + PRIOR_GAMES * 0.5) / (games + PRIOR_GAMES)
    return round((0.5 - enemy_wr) * 100, 2)


def suggest_picks(gd: GameData, enemies: list[Hero], allies: list[Hero] = (), role: str = "auto",
                  meta=None, matchups: Callable[[int], list[dict]] | None = None, limit: int = 8
                  ) -> list[PickSuggestion]:
    taken = {h.id for h in [*enemies, *allies]}
    tables: dict[int, dict[int, tuple[int, int]]] = {}
    for e in enemies:
        try:
            rows = matchups(e.id) if matchups else []
        except Exception:
            rows = []
        tables[e.id] = {r["hero_id"]: (int(r.get("wins", 0)), int(r.get("games_played", 0))) for r in rows}

    out = []
    for h in gd.heroes.values():
        if h.id in taken:
            continue
        if role in ("core", "support") and player_role(h) != role:
            continue
        s = PickSuggestion(h, 0.0)
        for e in enemies:
            wins, games = tables[e.id].get(h.id, (0, 0))
            adv = advantage(wins, games)
            s.vs[e.loc] = adv
            s.score += adv
        if meta is not None:
            hm = meta.hero(h)
            if hm:
                s.score += META_WEIGHT * hm.meta_score
                s.meta_line = hm.one_line().split(": ", 1)[-1]
        s.score = round(s.score, 2)
        out.append(s)
    return sorted(out, key=lambda s: s.score, reverse=True)[:limit]
