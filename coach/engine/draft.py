"""Asistente de draft: qué héroe elegir con tus aliados y contra los enemigos ya elegidos.

Puntuación de cada candidato =
    Σ ventaja contra cada enemigo visto (matchups de OpenDota, suavizados hacia el 50%)
  + Σ sinergia con cada aliado ya elegido (winrate jugando juntos, OpenDota explorer, suavizado igual)
  + peso del meta actual (winrate en tu rango, tendencia reciente, buffs/nerfs del parche)
Con pick a ciegas (turbo, enemigos ocultos) cuentan solo los aliados y el meta.
Solo se piden los datos de los héroes ya elegidos (≤9 peticiones), no los de los ~127 candidatos.
"""
from dataclasses import dataclass, field
from typing import Callable

from ..data.gamedata import GameData, Hero
from .counters import HARD_CARRIES, player_role

PRIOR_GAMES = 50          # suavizado: la muestra es de partidas pro (pequeña); con pocas, la ventaja tiende a 0
META_WEIGHT = 0.6         # 1 punto de meta_score (≈1 pt de winrate) vale 0.6 pts de ventaja de matchup
SYNERGY_WEIGHT = 0.8      # la sinergia con un aliado pesa algo menos que la ventaja contra un enemigo


@dataclass
class PickSuggestion:
    hero: Hero
    score: float
    vs: dict[str, float] = field(default_factory=dict)   # enemigo → ventaja en puntos de winrate
    with_: dict[str, float] = field(default_factory=dict)  # aliado → sinergia en puntos de winrate
    meta_line: str = ""

    def line(self) -> str:
        parts = [f"{self.hero.loc} ({self.score:+.1f})"]
        good = [f"{k} {v:+.1f}" for k, v in sorted(self.vs.items(), key=lambda kv: -kv[1]) if abs(v) >= 0.5]
        if good:
            parts.append("vs " + ", ".join(good))
        mates = [f"{k} {v:+.1f}" for k, v in sorted(self.with_.items(), key=lambda kv: -kv[1]) if abs(v) >= 0.5]
        if mates:
            parts.append("con " + ", ".join(mates))
        if self.meta_line:
            parts.append(self.meta_line)
        return " · ".join(parts)


def advantage(wins_of_enemy: int, games: int) -> float:
    """Ventaja del candidato en puntos de winrate, a partir del resultado del enemigo contra él."""
    enemy_wr = (wins_of_enemy + PRIOR_GAMES * 0.5) / (games + PRIOR_GAMES)
    return round((0.5 - enemy_wr) * 100, 2)


def synergy_advantage(wins: int, games: int) -> float:
    """Sinergia en puntos de winrate de la pareja (suavizada hacia el 50% con pocas partidas)."""
    wr = (wins + PRIOR_GAMES * 0.5) / (games + PRIOR_GAMES)
    return round((wr - 0.5) * 100, 2)


def suggest_picks(gd: GameData, enemies: list[Hero], allies: list[Hero] = (), role: str = "auto",
                  meta=None, matchups: Callable[[int], list[dict]] | None = None, limit: int = 8,
                  banned: list[Hero] = (), synergy: Callable[[int], list[dict]] | None = None
                  ) -> list[PickSuggestion]:
    taken = {h.id for h in [*enemies, *allies, *banned]}
    mates: dict[int, dict[int, tuple[int, int]]] = {}
    for a in allies:
        try:
            rows = synergy(a.id) if synergy else []
        except Exception:
            rows = []
        mates[a.id] = {int(r["hero_id"]): (int(r.get("wins", 0)), int(r.get("games", 0))) for r in rows}
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
        if role == "carry" and h.loc not in HARD_CARRIES:
            continue
        if role in ("core", "support") and player_role(h) != role:
            continue
        s = PickSuggestion(h, 0.0)
        for e in enemies:
            wins, games = tables[e.id].get(h.id, (0, 0))
            adv = advantage(wins, games)
            s.vs[e.loc] = adv
            s.score += adv
        for a in allies:
            wins, games = mates[a.id].get(h.id, (0, 0))
            syn = synergy_advantage(wins, games)
            if games:
                s.with_[a.loc] = syn
            s.score += SYNERGY_WEIGHT * syn
        if meta is not None:
            hm = meta.hero(h)
            if hm:
                s.score += META_WEIGHT * hm.meta_score
                s.meta_line = hm.one_line().split(": ", 1)[-1]
        s.score = round(s.score, 2)
        out.append(s)
    return sorted(out, key=lambda s: s.score, reverse=True)[:limit]
