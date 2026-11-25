"""Orden de habilidades y talentos habituales de tu héroe (STRATZ, tu rango) y cómo va tu línea.

- Habilidades y talentos del héroe: datafeed oficial de Valve (herodata): ids, si es la definitiva, nivel máximo y los
  8 talentos en orden (de dos en dos: niveles 10, 15, 20 y 25). Los ids coinciden con los de STRATZ.
- Orden: las habilidades normales se maximizan en el orden habitual (nivel del héroe en que se suelen maximizar, la
  moda de STRATZ); la definitiva, en cuanto se pueda (6, 12, 18).
- Talentos: en cada nivel, el más elegido de la pareja.
"""
import re
from dataclasses import dataclass, field

from ..data.cache import cached_json
from ..data.gamedata import VALVE
from ..gsi import GameState

TALENT_LEVELS = (10, 15, 20, 25)
ULT_LEVELS = (6, 12, 18)


@dataclass
class Ability:
    id: int
    name: str            # interno: juggernaut_blade_fury (es lo que manda GSI)
    loc: str
    ultimate: bool
    max_level: int


@dataclass
class TalentChoice:
    level: int
    pick: str            # el más elegido
    share: float         # fracción de los que eligen en ese nivel
    other: str
    options: list[tuple[str, float]] = field(default_factory=list)  # las dos, en el orden de Valve (izq., der.)
    best: int = 0                                                    # índice de la más elegida


@dataclass
class SkillPlan:
    order: list[Ability] = field(default_factory=list)      # habilidades normales, de primera a última en maximizar
    ultimate: Ability | None = None
    talents: list[TalentChoice] = field(default_factory=list)

    def summary(self) -> str:
        parts = [" → ".join(a.loc for a in self.order)]
        if self.ultimate:
            parts.append(f"{self.ultimate.loc} en 6/12/18")
        return " · ".join(p for p in parts if p)


def clean_talent(text: str) -> str:
    """'-{s:bonus_AbilityCooldown}s Blade Fury Cooldown' → '-Xs Blade Fury Cooldown'."""
    return re.sub(r"\{s:[^}]+\}", "X", text or "").strip()


def valve_hero(hero_id: int) -> dict:
    data = cached_json(f"valve_herodata_{hero_id}", f"{VALVE}/herodata", 3 * 86400,
                       {"language": "english", "hero_id": hero_id})
    heroes = ((data or {}).get("result") or {}).get("data", {}).get("heroes") or []
    return heroes[0] if heroes else {}


def build_plan(hero: dict, details: dict) -> SkillPlan:
    """hero: herodata de Valve; details: stratz.hero_details()."""
    abilities = [Ability(int(a["id"]), a["name"], a.get("name_loc") or a["name"], a.get("type") == 1,
                         int(a.get("max_level") or 0)) for a in hero.get("abilities") or []]
    plan = SkillPlan(ultimate=next((a for a in abilities if a.ultimate), None))
    normal = [a for a in abilities if not a.ultimate and a.max_level >= 3]   # las innatas (máx. 1) no se suben

    def maxed_at(a: Ability) -> float:
        levels = (details.get("max_level") or {}).get(a.id) or {}
        return max(levels.items(), key=lambda kv: kv[1])[0] if levels else 99
    plan.order = sorted(normal, key=maxed_at)
    talents = hero.get("talents") or []
    picks = details.get("talents") or {}
    for i, level in enumerate(TALENT_LEVELS):
        pair = talents[2 * i:2 * i + 2]
        if len(pair) < 2:
            continue
        counts = [picks.get(int(t["id"]), (0, 0))[0] for t in pair]
        if not sum(counts):
            continue
        best = 0 if counts[0] >= counts[1] else 1
        options = [(clean_talent(t.get("name_loc")), c / sum(counts)) for t, c in zip(pair, counts)]
        plan.talents.append(TalentChoice(level, options[best][0], options[best][1], options[1 - best][0],
                                         options, best))
    return plan


def suggested_sequence(plan: SkillPlan, max_level: int = 18) -> list[tuple[int, str]]:
    """Qué se sube en cada nivel del 1 al max_level: [(nivel, nombre interno | "talent" | "attr")]."""
    from types import SimpleNamespace
    levels: dict[str, int] = {}
    out = []
    by_loc = {a.loc: a for a in [*plan.order, *([plan.ultimate] if plan.ultimate else [])]}
    for lvl in range(1, max_level + 1):
        if lvl in TALENT_LEVELS:
            out.append((lvl, "talent"))
            continue
        fake = SimpleNamespace(level=lvl, abilities=[{"name": n, "level": v} for n, v in levels.items()])
        loc = next_skill(plan, fake)
        a = by_loc.get(loc) if loc else None
        if a is None:
            out.append((lvl, "attr"))
            continue
        levels[a.name] = levels.get(a.name, 0) + 1
        out.append((lvl, a.name))
    return out


def next_skill(plan: SkillPlan, st: GameState) -> str | None:
    """Qué habilidad subir ahora (nombre para mostrar), siguiendo el orden habitual."""
    if not plan.order and not plan.ultimate:
        return None
    current = {a["name"]: a["level"] for a in st.abilities}
    ult = plan.ultimate
    if ult and st.level in ULT_LEVELS and current.get(ult.name, 0) < ULT_LEVELS.index(st.level) + 1:
        return ult.loc
    cap = (st.level + 1) // 2  # una habilidad normal no puede pasar de la mitad del nivel (redondeando arriba)
    for a in plan.order:
        lvl = current.get(a.name, 0)
        if lvl < min(a.max_level, cap):
            # al principio se coge un punto en cada una antes de maximizar (lo habitual)
            if st.level <= 3:
                fresh = next((b for b in plan.order if current.get(b.name, 0) == 0), None)
                return (fresh or a).loc
            return a.loc
    return None


def talent_for(plan: SkillPlan, level: int) -> TalentChoice | None:
    return next((t for t in plan.talents if t.level == level), None)


def lane_outlook(details: dict, opponents: list[int]) -> tuple[float, float, float, int] | None:
    """(ganar, empatar, perder, partidas) de la línea contra esos rivales (suma de sus emparejamientos)."""
    lanes = details.get("lanes") or {}
    m = w = d = loss = 0
    for hid in opponents:
        row = lanes.get(int(hid))
        if row:
            m, w, d, loss = m + row[0], w + row[1], d + row[2], loss + row[3]
    total = w + d + loss
    if total < 50:
        return None
    return w / total, d / total, loss / total, m
