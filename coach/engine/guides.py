"""Guías: builds reales (partidas ganadas de buenos jugadores, STRATZ) que el jugador elige y sigue.

- Buscador: guías de un héroe, generales y contra/con los héroes de tu partida, ordenadas por parecido.
- Guía elegida: marca la siguiente compra (el siguiente objeto de la guía que aún no tienes).
- Si te sales de la guía (compras algo importante que no está en ella), se propone una guía ADAPTADA: lo que
  llevas + cómo siguieron las builds ganadoras que hicieron lo mismo (engine/buildpaths). El jugador la acepta o
  sigue con la suya; si la rechaza, no se vuelve a proponer por esa misma compra.
"""
from dataclasses import asdict, dataclass, field

from ..data.gamedata import GameData
from .buildpaths import BuildPaths, _lcs, core_sequence

POSITIONS = {"POSITION_1": "carry", "POSITION_2": "mid", "POSITION_3": "offlane", "POSITION_4": "support (4)",
             "POSITION_5": "support (5)"}


@dataclass
class Guide:
    id: str                                  # id de la partida ("adapted-…" para las adaptadas)
    hero_id: int
    core: list[tuple[str, float]]            # (item_*, minuto) en orden
    enemies: list[int] = field(default_factory=list)
    allies: list[int] = field(default_factory=list)
    position: str = ""
    minutes: int = 0
    source: str = "STRATZ"                   # STRATZ | adaptada
    note: str = ""

    @property
    def items(self) -> list[str]:
        return [n for n, _ in self.core]

    @property
    def role(self) -> str:
        return POSITIONS.get(self.position, "")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["core"] = [list(x) for x in self.core]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Guide":
        d = dict(d)
        d["core"] = [(str(n), float(m)) for n, m in d.get("core") or []]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def guides_from_rows(gd: GameData, hero_id: int, rows: list[dict]) -> list[Guide]:
    out, seen = [], set()
    for r in rows or []:
        if not r.get("win", True) or r.get("match") in seen:
            continue
        core = core_sequence(gd, r.get("purchases") or [])
        if len(core) < 3:
            continue
        seen.add(r.get("match"))
        out.append(Guide(str(r.get("match")), hero_id, core, list(r.get("enemies") or []),
                         list(r.get("allies") or []), r.get("position") or "", int(r.get("minutes") or 0)))
    return out


def similarity(g: Guide, enemies: set[int], allies: set[int], position: str = "") -> float:
    """Para ordenar el buscador: enemigos en común (lo que más pesa), aliados y misma posición."""
    return len(enemies & set(g.enemies)) + 0.4 * len(allies & set(g.allies)) + (0.5 if position and
                                                                                 g.position == position else 0)


def rank(guides: list[Guide], enemies: set[int], allies: set[int], position: str = "") -> list[Guide]:
    return sorted(guides, key=lambda g: (similarity(g, enemies, allies, position), len(g.core)), reverse=True)


@dataclass
class Deviation:
    item: str                    # lo que compraste fuera de la guía
    suggestion: str              # lo siguiente según las builds ganadoras que hicieron lo mismo
    guide_next: str | None       # lo siguiente de tu guía
    reason: str
    adapted: Guide


class GuideFollower:
    def __init__(self, gd: GameData):
        self.gd = gd
        self.guide: Guide | None = None
        self.dismissed: set[str] = set()     # desvíos ya rechazados ("seguir con mi guía")

    def choose(self, guide: Guide | None):
        self.guide = guide
        self.dismissed.clear()

    def next_items(self, owned_ever: set[str], limit: int = 2) -> list[str]:
        """Los siguientes objetos de la guía que aún no has comprado nunca."""
        if not self.guide:
            return []
        return [n for n in self.guide.items if n not in owned_ever][:limit]

    def progress(self, owned_ever: set[str]) -> tuple[int, int]:
        if not self.guide:
            return 0, 0
        return sum(1 for n in self.guide.items if n in owned_ever), len(self.guide.items)

    def deviation(self, bought: list[str], owned: list[str], paths: BuildPaths, enemies: set[int],
                  allies: set[int]) -> Deviation | None:
        """Compraste algo importante que tu guía no lleva: qué hicieron después los que compraron lo mismo."""
        if not self.guide or not len(paths):
            return None
        off = [b for b in bought if b not in self.guide.items]
        if not off or off[-1] in self.dismissed:
            return None
        votes = paths.suggest(owned, bought, enemies, allies)
        if not votes:
            return None
        best = max(votes, key=lambda k: votes[k][0])
        ranked = paths.ranked(bought, enemies, allies)
        tail: list[tuple[str, float]] = []
        if ranked:
            mine = set(bought)
            tail = [(n, m) for n, m in ranked[0][1].core if n not in mine]
        adapted = Guide(f"adapted-{self.guide.id}", self.guide.hero_id,
                        [(n, 0.0) for n in bought] + tail, self.guide.enemies, self.guide.allies,
                        self.guide.position, self.guide.minutes, source="adaptada",
                        note=f"Tu camino ({', '.join(self.gd.item(n).loc for n in bought if self.gd.item(n))}) "
                             f"+ cómo siguieron las builds ganadoras parecidas")
        nxt = self.next_items(set(owned) | set(bought), 1)
        return Deviation(off[-1], best, nxt[0] if nxt else None, votes[best][1], adapted)

    def accept(self, dev: Deviation):
        self.guide = dev.adapted

    def dismiss(self, dev: Deviation):
        self.dismissed.add(dev.item)

    def matches_path(self, bought: list[str]) -> float:
        """Qué parte de lo que llevas comprado sigue la guía (0-1)."""
        if not self.guide or not bought:
            return 1.0
        return _lcs(bought, self.guide.items) / len(bought)


__all__ = ["Deviation", "Guide", "GuideFollower", "guides_from_rows", "rank", "similarity"]
