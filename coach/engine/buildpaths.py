"""Build adaptativa: lo que compraron DESPUÉS los jugadores que siguieron un camino parecido al tuyo.

Fuente: guías de STRATZ (partidas ganadas de buenos jugadores con tu héroe, con cada compra y su minuto). De cada
partida se saca su camino de objetos importantes (≥1000 de oro, en orden). En directo se compara con lo que llevas
comprado (en el orden en que lo compraste) y con tus enemigos y aliados:

  parecido = 0.2 + (objetos tuyos que esa build compró en el mismo orden) / (los que llevas)
             + 0.25 por enemigo en común + 0.1 por aliado en común

Las builds más parecidas votan su siguiente objeto que aún no tienes (el inmediato vale 1 y el de después 0.5). El
resultado entra en suggest_items igual que las "partidas parecidas" (parámetro standard), así que se adapta a cada
compra y sigue respetando fases, inventario y counters.
"""
from dataclasses import dataclass, field

from ..data.gamedata import GameData
from .counters import STANDALONE, excluded_by_inventory, owned_closure

CORE_MIN_COST = 1000
TOP_BUILDS = 12
ENEMY_BONUS, ALLY_BONUS = 0.25, 0.1


@dataclass
class RealBuild:
    match: int
    core: list[tuple[str, float]]          # (item_*, minuto) en orden de compra
    enemies: set[int] = field(default_factory=set)
    allies: set[int] = field(default_factory=set)
    win: bool = True


def core_sequence(gd: GameData, purchases) -> list[tuple[str, float]]:
    """Objetos importantes en el orden en que se compraron (sin componentes baratos, consumibles ni repetidos)."""
    out, seen = [], set()
    for item_id, minute in purchases:
        item = gd.items.get(int(item_id))
        if not item or item.name in seen or item.cost < CORE_MIN_COST:
            continue
        if not item.components and item.name not in STANDALONE:
            continue  # p. ej. Ultimate Orb suelto: es un paso hacia otra cosa
        seen.add(item.name)
        out.append((item.name, float(minute)))
    return out


def _lcs(a: list[str], b: list[str]) -> int:
    """Cuántos de 'a' aparecen en 'b' en el mismo orden (subsecuencia común más larga)."""
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


class BuildPaths:
    def __init__(self, gd: GameData):
        self.gd = gd
        self.builds: dict[int, RealBuild] = {}

    def __len__(self):
        return len(self.builds)

    def add(self, rows: list[dict]):
        for r in rows or []:
            if not r.get("win", True) or r.get("match") in self.builds:
                continue
            core = core_sequence(self.gd, r.get("purchases") or [])
            if len(core) >= 2:
                self.builds[r["match"]] = RealBuild(r["match"], core, set(r.get("enemies") or []),
                                                    set(r.get("allies") or []))

    def ranked(self, bought: list[str], enemies: set[int], allies: set[int]) -> list[tuple[float, RealBuild]]:
        mine = [b for b in bought if b]
        out = []
        for b in self.builds.values():
            names = [n for n, _ in b.core]
            score = 0.2 + (_lcs(mine, names) / len(mine) if mine else 0.8)
            score += ENEMY_BONUS * len(enemies & b.enemies) + ALLY_BONUS * len(allies & b.allies)
            out.append((score, b))
        out.sort(key=lambda sb: sb[0], reverse=True)
        if not out:
            return []
        best = out[0][0]
        return [sb for sb in out if sb[0] >= 0.6 * best][:TOP_BUILDS]

    def suggest(self, owned: list[str], bought: list[str], enemies: set[int], allies: set[int],
                enemy_names: dict[int, str] | None = None) -> dict[str, tuple[float, str]]:
        """{item_*: (fracción 0-1, motivo)} para suggest_items(standard=...)."""
        top = self.ranked(bought, enemies, allies)
        if not top:
            return {}
        owned = [o for o in owned if o]
        closure = owned_closure(self.gd, owned)
        votes: dict[str, float] = {}
        count: dict[str, int] = {}
        minutes: dict[str, list[float]] = {}
        against: dict[str, set[int]] = {}
        for score, b in top:
            nxt = [(n, m) for n, m in b.core if not excluded_by_inventory(self.gd, n, owned, closure)][:2]
            for k, (name, minute) in enumerate(nxt):
                votes[name] = votes.get(name, 0.0) + score * (1.0 if k == 0 else 0.5)
                count[name] = count.get(name, 0) + 1
                minutes.setdefault(name, []).append(minute)
                against.setdefault(name, set()).update(enemies & b.enemies)
        total = sum(score for score, _ in top)
        out = {}
        for name, v in votes.items():
            when = sum(minutes[name]) / len(minutes[name])
            why = (f"{count[name]} de {len(top)} builds ganadoras parecidas a la tuya lo compraron después "
                   f"(hacia el minuto {when:.0f})")
            foes = [enemy_names.get(e, "") for e in against[name] if enemy_names and enemy_names.get(e)]
            if foes:
                why += f", también contra {', '.join(sorted(foes)[:2])}"
            out[name] = (min(1.0, v / total), why)
        return out


__all__ = ["BuildPaths", "RealBuild", "core_sequence"]
