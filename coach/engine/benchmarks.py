"""Tu rendimiento comparado con el de tu héroe (OpenDota /benchmarks): en qué percentil estás.

OpenDota da, por héroe, el valor de cada percentil (10, 20 ... 99) de oro/min, XP/min, últimos golpes/min,
daño a héroes/min, etc. en partidas públicas recientes. El percentil se interpola entre esos puntos.
"""
from ..data.cache import cached_json
from ..data.gamedata import OPENDOTA

METRICS = {"gold_per_min": "oro/min", "xp_per_min": "XP/min", "last_hits_per_min": "últimos golpes/min",
           "kills_per_min": "asesinatos/min", "hero_damage_per_min": "daño a héroes/min"}


def fetch(hero_id: int) -> dict:
    """{métrica: [(percentil, valor), ...]} ordenado por percentil."""
    data = cached_json(f"od_bench_{hero_id}", f"{OPENDOTA}/benchmarks", 24 * 3600, params={"hero_id": hero_id})
    out = {}
    for metric, rows in ((data or {}).get("result") or {}).items():
        pts = sorted((float(r["percentile"]), float(r["value"])) for r in rows or [] if "value" in r)
        if pts:
            out[metric] = pts
    return out


def percentile(value: float, points: list[tuple[float, float]]) -> float | None:
    """Percentil (0-1) de 'value' según los puntos (percentil, valor) de OpenDota."""
    if not points:
        return None
    if value <= points[0][1]:
        return points[0][0] * (value / points[0][1]) if points[0][1] > 0 else 0.0
    for (p0, v0), (p1, v1) in zip(points, points[1:]):
        if v0 <= value <= v1:
            return p0 if v1 == v0 else p0 + (p1 - p0) * (value - v0) / (v1 - v0)
    return points[-1][0]


def live_percentiles(bench: dict, gpm: int, xpm: int, last_hits: int, clock: int) -> dict[str, float]:
    """Percentiles en directo de oro/min, XP/min y últimos golpes/min (a partir del minuto 5, antes no dicen nada)."""
    if not bench or clock < 5 * 60:
        return {}
    minutes = clock / 60
    out = {}
    for metric, value in (("gold_per_min", gpm), ("xp_per_min", xpm), ("last_hits_per_min", last_hits / minutes)):
        p = percentile(value, bench.get(metric, []))
        if p is not None:
            out[metric] = p
    return out


def describe(p: float) -> str:
    return f"p{round(p * 100)}"
