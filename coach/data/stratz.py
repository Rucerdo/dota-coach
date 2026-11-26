"""STRATZ (api.stratz.com/graphql): estadísticas de partidas PÚBLICAS por rango. Fuente principal para
enfrentamientos y sinergias; si no hay clave o algo falla, se usa OpenDota (ver data/sources.py).

- Necesita una clave gratuita (stratz.com/api, iniciando sesión con Steam): cabecera "Authorization: Bearer <clave>"
  y "User-Agent: STRATZ_API". Sin clave responde 403 ("A bearer token is required") — comprobado el 2026-11-25.
- Los nombres de campos de las consultas vienen de la documentación conocida de STRATZ; `introspect()` pide el
  esquema real a la API para comprobarlos cuando haya clave (`coach stratz check`).
"""
import logging
import os

import requests

from .. import config
from .cache import read_cached, write_cached

log = logging.getLogger(__name__)

URL = "https://api.stratz.com/graphql"
KEY_PAGE = "https://stratz.com/api"
HOUR = 3600

# Rango de los ajustes (0 todos, 1 Herald ... 8 Immortal) → tramos de STRATZ
BRACKETS = {1: "HERALD_GUARDIAN", 2: "HERALD_GUARDIAN", 3: "CRUSADER_ARCHON", 4: "CRUSADER_ARCHON",
            5: "LEGEND_ANCIENT", 6: "LEGEND_ANCIENT", 7: "DIVINE_IMMORTAL", 8: "DIVINE_IMMORTAL"}


class StratzError(Exception):
    pass


def token(cfg: dict | None = None) -> str:
    """Clave guardada (cifrada) en la configuración o en la variable de entorno STRATZ_TOKEN."""
    from ..ai.secrets import decrypt_key
    cfg = cfg if cfg is not None else config.load()
    return decrypt_key(cfg.get("stratz_key_enc", "")) or os.environ.get("STRATZ_TOKEN", "")


def query(gql: str, variables: dict | None = None, key: str = "", timeout: float = 25.0) -> dict:
    key = key or token()
    if not key:
        raise StratzError("sin clave de STRATZ")
    try:
        r = requests.post(URL, json={"query": gql, "variables": variables or {}}, timeout=timeout,
                          headers={"Authorization": f"Bearer {key}", "User-Agent": "STRATZ_API",
                                   "Content-Type": "application/json"})
    except requests.RequestException as e:
        raise StratzError(f"sin conexión con STRATZ ({e})") from e
    if r.status_code in (401, 403):
        raise StratzError("clave de STRATZ no válida")
    if r.status_code == 429:
        raise StratzError("STRATZ: límite de peticiones alcanzado")
    if r.status_code >= 400:
        raise StratzError(f"STRATZ respondió {r.status_code}: {r.text[:200]}")
    data = r.json()
    if data.get("errors"):
        raise StratzError("STRATZ: " + "; ".join(str(e.get("message")) for e in data["errors"])[:300])
    return data.get("data") or {}


def cached_query(name: str, gql: str, variables: dict, ttl: float) -> dict:
    hit = read_cached(name)
    import time
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        data = query(gql, variables)
    except StratzError:
        if hit:
            return hit[1]
        raise
    write_cached(name, data)
    return data


MATCHUP_GQL = """
query Matchup($heroId: Short!, $brackets: [RankBracketBasicEnum]) {
  heroStats {
    matchUp(heroId: $heroId, bracketBasicIds: $brackets, take: 200) {
      vs { heroId2 matchCount winCount }
      with { heroId2 matchCount winCount }
    }
  }
}"""


def matchup(hero_id: int, bracket: int = 0) -> dict[str, list[dict]]:
    """{'vs': [{hero_id, games, wins}], 'with': [...]}: 'wins' son las victorias de hero_id (contra o junto a)."""
    brackets = [BRACKETS[bracket]] if bracket in BRACKETS else None
    data = cached_query(f"stratz_matchup_{hero_id}_{bracket}", MATCHUP_GQL,
                        {"heroId": int(hero_id), "brackets": brackets}, 24 * HOUR)
    rows = ((data.get("heroStats") or {}).get("matchUp") or [{}])
    block = rows[0] if isinstance(rows, list) and rows else rows or {}
    out = {}
    for kind in ("vs", "with"):
        out[kind] = [{"hero_id": int(r["heroId2"]), "games": int(r.get("matchCount") or 0),
                      "wins": int(r.get("winCount") or 0)} for r in block.get(kind) or [] if r.get("heroId2")]
    return out


ITEMS_GQL = """
query Items($heroId: Short!, $brackets: [RankBracketBasicEnum]) {
  heroStats {
    itemFullPurchase(heroId: $heroId, bracketBasicIds: $brackets) { itemId instance time matchCount winCount }
    itemStartingPurchase(heroId: $heroId, bracketBasicIds: $brackets) { itemId instance matchCount winCount }
    itemBootPurchase(heroId: $heroId, bracketBasicIds: $brackets) { itemId matchCount winCount timeAverage }
  }
}"""

HERO_GQL = """
query Hero($heroId: Short!, $brackets: [RankBracketBasicEnum]) {
  heroStats {
    abilityMaxLevel(heroId: $heroId, bracketBasicIds: $brackets) { abilityId level matchCount }
    abilityMinLevel(heroId: $heroId, bracketBasicIds: $brackets) { abilityId level matchCount }
    talent(heroId: $heroId, bracketBasicIds: $brackets) { abilityId matchCount winCount timeAverage }
    laneOutcome(heroId: $heroId, isWith: false, bracketBasicIds: $brackets) {
      heroId2 matchCount winCount drawCount lossCount
    }
  }
}"""


def hero_details(hero_id: int, bracket: int = 0) -> dict:
    """Orden de habilidades, talentos y fase de líneas del héroe en tu rango (verificado el 2026-11-25):
    {'max_level': {abilityId: {nivel del héroe: partidas}}, 'min_level': {...}, 'talents': {abilityId: (partidas,
    victorias)}, 'lanes': {heroId2: (partidas, ganadas, empatadas, perdidas)}} — con varios tramos, sumado."""
    brackets = [BRACKETS[bracket]] if bracket in BRACKETS else None
    data = cached_query(f"stratz_hero_{hero_id}_{bracket}", HERO_GQL, {"heroId": int(hero_id), "brackets": brackets},
                        24 * HOUR)
    hs = data.get("heroStats") or {}
    out = {"max_level": {}, "min_level": {}, "talents": {}, "lanes": {}}
    for key, field in (("max_level", "abilityMaxLevel"), ("min_level", "abilityMinLevel")):
        for r in hs.get(field) or []:
            levels = out[key].setdefault(int(r["abilityId"]), {})
            levels[int(r["level"])] = levels.get(int(r["level"]), 0) + int(r.get("matchCount") or 0)
    for r in hs.get("talent") or []:
        m, w = out["talents"].get(int(r["abilityId"]), (0, 0))
        out["talents"][int(r["abilityId"])] = (m + int(r.get("matchCount") or 0), w + int(r.get("winCount") or 0))
    for r in hs.get("laneOutcome") or []:
        prev = out["lanes"].get(int(r["heroId2"]), (0, 0, 0, 0))
        add = (int(r.get("matchCount") or 0), int(r.get("winCount") or 0), int(r.get("drawCount") or 0),
               int(r.get("lossCount") or 0))
        out["lanes"][int(r["heroId2"])] = tuple(a + b for a, b in zip(prev, add))
    return out

# Fase según el minuto MEDIO de compra (mismos cortes que engine/counters.phase_for)
PHASE_KEYS = ((12, "early_game_items"), (28, "mid_game_items"), (999, "late_game_items"))


def item_popularity(hero_id: int, bracket: int = 0) -> dict:
    """Lo que se compra con el héroe en tu rango, en el formato de OpenDota itemPopularity
    ({start_game_items|early|mid|late: {item_id: partidas}}) más '_details' {item_id: (fracción, minuto, winrate)}.
    Verificado con datos reales el 2026-11-25 (instance 0 = primera compra; time = minuto)."""
    brackets = [BRACKETS[bracket]] if bracket in BRACKETS else None
    data = cached_query(f"stratz_items_{hero_id}_{bracket}", ITEMS_GQL, {"heroId": int(hero_id), "brackets": brackets},
                        24 * HOUR)
    hs = data.get("heroStats") or {}
    agg: dict[int, list[float]] = {}
    for r in hs.get("itemFullPurchase") or []:
        if r.get("instance", 0) != 0 or not r.get("itemId"):
            continue
        a = agg.setdefault(int(r["itemId"]), [0, 0, 0.0])
        a[0] += int(r.get("matchCount") or 0)
        a[1] += int(r.get("winCount") or 0)
        a[2] += float(r.get("time") or 0) * int(r.get("matchCount") or 0)
    start_rows = [r for r in hs.get("itemStartingPurchase") or [] if r.get("instance", 0) == 0 and r.get("itemId")]
    starting: dict[int, int] = {}
    start_wins: dict[int, int] = {}
    for r in start_rows:  # con varios tramos de rango llega una fila por tramo: se suman
        starting[int(r["itemId"])] = starting.get(int(r["itemId"]), 0) + int(r.get("matchCount") or 0)
        start_wins[int(r["itemId"])] = start_wins.get(int(r["itemId"]), 0) + int(r.get("winCount") or 0)
    for r in hs.get("itemBootPurchase") or []:  # las botas no vienen en itemFullPurchase
        if not r.get("itemId"):
            continue
        a = agg.setdefault(int(r["itemId"]), [0, 0, 0.0])
        n = int(r.get("matchCount") or 0)
        a[0] += n
        a[1] += int(r.get("winCount") or 0)
        a[2] += float(r.get("timeAverage") or 0) / 60 * n  # timeAverage va en segundos
    # partidas del héroe ≈ el objeto más comprado (casi todos compran tangos al salir); nunca menos que eso
    total = max(max(starting.values(), default=0), max((a[0] for a in agg.values()), default=0))
    scope = {"HERALD_GUARDIAN": "Herald-Guardian", "CRUSADER_ARCHON": "Crusader-Archon",
             "LEGEND_ANCIENT": "Legend-Ancient", "DIVINE_IMMORTAL": "Divine-Immortal"}.get(
        BRACKETS.get(bracket, ""), "todos los rangos")
    out = {"start_game_items": {str(k): v for k, v in starting.items()},
           "early_game_items": {}, "mid_game_items": {}, "late_game_items": {}, "_details": {}, "_total": total,
           "_scope": scope,
           "_details_start": {str(k): (v / total if total else 0.0, 0.0, start_wins[k] / v if v else 0.0)
                              for k, v in starting.items()}}
    for item_id, (matches, wins, tsum) in agg.items():
        if not matches:
            continue
        minute = tsum / matches
        key = next(k for limit, k in PHASE_KEYS if minute < limit)
        out[key][str(item_id)] = matches
        out["_details"][str(item_id)] = (min(1.0, matches / total) if total else 0.0, minute, wins / matches)
    return out


# ---------- builds reales (guías de STRATZ: partidas GANADAS de buenos jugadores con ese héroe) ----------
GUIDE_GQL = """
query Guides($heroId: Short!, $against: Short, $with: Short, $take: Int) {
  heroStats { guide(heroId: $heroId, againstHeroId: $against, withHeroId: $with, take: 1) {
    guides(take: $take) { matchId } } }
}"""
MATCH_FIELDS = ("id durationSeconds gameMode players { heroId isVictory position isRadiant "
                "stats { itemPurchases { itemId time } } }")
MATCH_BATCH = 10   # STRATZ no deja pedir más partidas de golpe (y matches(ids) es solo para administradores)


def hero_builds(hero_id: int, against: int | None = None, with_hero: int | None = None, take: int = 30,
                ttl: float = 86400, on_batch=None) -> list[dict]:
    """Builds reales de tu héroe: [{match, win, minutes, position, enemies, allies, purchases: [[item_id, minuto]]}].
    Con 'against'/'with_hero', solo partidas contra/con ese héroe. Se guardan un día (y se borran con cada parche).
    STRATZ tiene unas 80-110 partidas por héroe contra un enemigo concreto. on_batch(hechas, total) da el avance."""
    name = f"stratz_builds_{hero_id}_{against or 0}_{with_hero or 0}_{take}"   # con 'take': una pequeña no vale por una grande
    hit = read_cached(name)
    import time
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        data = query(GUIDE_GQL, {"heroId": int(hero_id), "against": against, "with": with_hero, "take": take})
        lists = (data.get("heroStats") or {}).get("guide") or []
        ids = [g["matchId"] for gl in lists for g in (gl.get("guides") or []) if g.get("matchId")][:take]
        out = []
        if on_batch:
            on_batch(0, len(ids))
        for i in range(0, len(ids), MATCH_BATCH):
            body = " ".join(f"m{j}: match(id: {int(mid)}) {{ {MATCH_FIELDS} }}"
                            for j, mid in enumerate(ids[i:i + MATCH_BATCH]))
            for m in query("query { " + body + " }").values():
                row = _build_row(m, hero_id)
                if row:
                    out.append(row)
            if on_batch:
                on_batch(min(i + MATCH_BATCH, len(ids)), len(ids))
    except StratzError:
        if hit:
            return hit[1]
        raise
    write_cached(name, out)
    return out


def _build_row(match: dict | None, hero_id: int) -> dict | None:
    if not match:
        return None
    me = next((p for p in match.get("players") or [] if p.get("heroId") == hero_id), None)
    if not me:
        return None
    purchases = [[int(e["itemId"]), round(e["time"] / 60, 1)]
                 for e in ((me.get("stats") or {}).get("itemPurchases") or []) if e.get("itemId")]
    side = me.get("isRadiant")
    return {"match": match.get("id"), "win": bool(me.get("isVictory")), "position": me.get("position") or "",
            "minutes": round((match.get("durationSeconds") or 0) / 60), "mode": match.get("gameMode") or "",
            "enemies": [p["heroId"] for p in match["players"] if p.get("isRadiant") != side],
            "allies": [p["heroId"] for p in match["players"] if p.get("isRadiant") == side and p is not me],
            "purchases": purchases}


def introspect(names=("HeroStatsQuery", "HeroMatchupType", "HeroDryadType", "RankBracketBasicEnum")) -> dict:
    """Campos reales de los tipos que usamos (para comprobar las consultas cuando haya clave)."""
    out = {}
    for name in names:
        data = query('query T($n: String!) { __type(name: $n) { name kind fields { name args { name } } '
                     'enumValues { name } } }', {"n": name})
        out[name] = data.get("__type")
    return out


def check(key: str) -> str:
    """Prueba de la clave (botón "Probar" de los ajustes): una consulta pequeña de verdad."""
    data = query(MATCHUP_GQL, {"heroId": 8, "brackets": None}, key=key)
    rows = ((data.get("heroStats") or {}).get("matchUp") or [{}])
    block = rows[0] if isinstance(rows, list) and rows else {}
    return f"STRATZ responde: {len(block.get('vs') or [])} enfrentamientos de Juggernaut"


__all__ = ["KEY_PAGE", "StratzError", "check", "hero_builds", "introspect", "matchup", "query", "token"]
