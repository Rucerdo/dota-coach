"""Partidas parecidas a la tuya (OpenDota findMatches) y con qué objetos terminaron los que GANARON.

Se busca tu héroe contra el mayor número posible de tus enemigos actuales; si no hay bastantes partidas, se
van quitando enemigos (primero los últimos detectados). De las partidas públicas sin analizar OpenDota solo da
el inventario final (no el orden de compra), que es lo que se resume.
"""
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from ..data import opendota
from ..data.gamedata import GameData, Hero

log = logging.getLogger(__name__)

MIN_MATCHES = 5
MAX_ENEMIES = 3           # con más, la búsqueda de OpenDota tarda demasiado y casi nunca encuentra partidas
MAX_DETAILS = 10          # detalles de partida que se piden como mucho (límite gratuito de OpenDota)
MIN_DURATION = 15 * 60    # las partidas muy cortas (abandonos, rendiciones) no enseñan una build
SLOTS = [f"item_{i}" for i in range(6)] + [f"backpack_{i}" for i in range(3)]


@dataclass
class SimilarMatch:
    match_id: int
    win: bool
    duration: int
    items: list[str]               # item_* del inventario final de tu héroe


@dataclass
class SimilarBuilds:
    hero: Hero
    vs: list[Hero]                 # enemigos que coinciden en la búsqueda
    matches: list[SimilarMatch] = field(default_factory=list)
    top_items: list[tuple[str, int]] = field(default_factory=list)  # (item_*, en cuántas victorias)
    names: dict[str, str] = field(default_factory=dict)              # item_* → nombre para mostrar

    @property
    def wins(self) -> int:
        return sum(m.win for m in self.matches)


def _final_items(gd: GameData, player: dict) -> list[str]:
    out = []
    for slot in SLOTS:
        it = gd.items.get(int(player.get(slot) or 0))
        if it and it.cost >= 500 and it.name not in out:  # sin consumibles ni objetos baratos
            out.append(it.name)
    return out


def find_similar(gd: GameData, hero: Hero, enemies: list[Hero],
                 find: Callable[[list[int], list[int]], list[dict]] = opendota.find_matches,
                 details: Callable[[int], dict] = opendota.match_details) -> SimilarBuilds | None:
    if not hero or not enemies:
        return None
    rows, vs = [], []
    for k in range(min(len(enemies), MAX_ENEMIES), 0, -1):
        vs = enemies[:k]
        try:
            rows = find([hero.id], [h.id for h in vs])
        except Exception as e:  # las búsquedas grandes a veces tardan demasiado: se prueba una más pequeña
            log.warning("OpenDota findMatches (%d enemigos): %s", k, e)
            rows = []
        if len(rows) >= MIN_MATCHES:
            break
    if not rows:
        return None
    result = SimilarBuilds(hero, vs)
    for row in sorted(rows, key=lambda r: r.get("start_time", 0), reverse=True)[:MAX_DETAILS]:
        try:
            m = details(int(row["match_id"]))
        except Exception as e:
            log.warning("OpenDota partida %s: %s", row.get("match_id"), e)
            continue
        if int(m.get("duration") or 0) < MIN_DURATION:
            continue
        player = next((p for p in m.get("players") or [] if p.get("hero_id") == hero.id), None)
        if not player:
            continue
        result.matches.append(SimilarMatch(int(row["match_id"]), bool(player.get("win")),
                                           int(m.get("duration") or 0), _final_items(gd, player)))
    counts = Counter(i for mt in result.matches if mt.win for i in mt.items)
    result.top_items = counts.most_common(6)
    result.names = {n: gd.item(n).loc for m in result.matches for n in m.items if gd.item(n)}
    return result if result.matches else None
