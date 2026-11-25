"""Estadísticas públicas de OpenDota (sin clave; límite gratuito ~60 peticiones/min).

- heroStats: partidas y victorias por héroe, en total y por rango (1 Herald ... 8 Immortal), con tendencia
  reciente (pub_pick_trend / pub_win_trend: tramos consecutivos, el último es el más reciente).
- heroes/{id}/matchups: resultados de ese héroe contra cada rival (muestra de partidas profesionales:
  pequeña, por eso se suaviza con un prior en engine/draft.py).
- heroes/{id}/itemPopularity: objetos más comprados por fase de la partida.
"""
from .cache import cached_json
from .gamedata import OPENDOTA

HOUR = 3600


def hero_stats() -> list[dict]:
    return cached_json("od_herostats", f"{OPENDOTA}/heroStats", 6 * HOUR)


def matchups(hero_id: int) -> list[dict]:
    return cached_json(f"od_matchups_{hero_id}", f"{OPENDOTA}/heroes/{hero_id}/matchups", 24 * HOUR)


def item_popularity(hero_id: int) -> dict:
    return cached_json(f"od_itempop_{hero_id}", f"{OPENDOTA}/heroes/{hero_id}/itemPopularity", 24 * HOUR)


def find_matches(team_a: list[int], team_b: list[int]) -> list[dict]:
    """Partidas públicas recientes con los héroes de team_a en un bando y los de team_b en el otro.
    Cada una: match_id, teama (el bando de team_a), teamb, teamawin, start_time."""
    a, b = sorted(team_a), sorted(team_b)
    params = [("teamA", h) for h in a] + [("teamB", h) for h in b]
    name = "od_find_" + "-".join(map(str, a)) + "_vs_" + "-".join(map(str, b))
    return cached_json(name, f"{OPENDOTA}/findMatches", 12 * HOUR, params=params)


def match_details(match_id: int) -> dict:
    """Detalle de una partida (no cambia nunca: caché de un año)."""
    return cached_json(f"od_match_{match_id}", f"{OPENDOTA}/matches/{match_id}", 365 * 24 * HOUR)
