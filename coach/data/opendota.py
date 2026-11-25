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
