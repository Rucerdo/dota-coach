"""Notas de parche oficiales de Valve, convertidas en cambios estructurados (buff / nerf / neutro).

Fuente: https://www.dota2.com/datafeed/patchnoteslist y /patchnotes?version=X (JSON oficial).

Cada línea de las notas se clasifica con heurísticas:
  "Cooldown decreased from 20 to 16"        → buff  (menos es mejor)
  "Damage increased from 100 to 120"        → buff
  "Mana Cost rescaled from 100/110 to 90/120" → se compara la media
  "Base Armor decreased by 1"               → nerf
Las heurísticas no entienden todo (reworks, cambios de mecánica): para eso está el análisis con IA
(coach/data/meta.py), que relee las notas y da un veredicto por héroe / objeto.
"""
import html
import logging
import re
from dataclasses import dataclass

from .cache import cached_json
from .gamedata import VALVE, GameData

log = logging.getLogger(__name__)

HOUR = 3600

# Estadísticas en las que un número MÁS BAJO es mejor para quien tiene la habilidad / el objeto
LOWER_IS_BETTER = re.compile(
    r"cooldown|mana cost|health cost|gold cost|\bcost\b|cast point|cast time|attack point|base attack time|"
    r"\bbat\b|attack time|delay|respawn|charge restore|replenish time|recharge|channel time|fade time|"
    r"self[- ]damage|self[- ]slow|buyback|activation time|transformation time", re.I)
FROM_TO = re.compile(r"\b(increased|decreased|reduced|lowered|raised|rescaled|changed|adjusted)\s+from\s+(.+?)\s+to\s+(.+)$", re.I)
BY_AMOUNT = re.compile(r"\b(increased|decreased|reduced|lowered|raised)\s+by\s+([\d.]+)", re.I)
NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")  # "110-130" son dos números positivos, no 110 y -130
REDUCTION = re.compile(r"(cooldown|cost|mana cost|delay)\s+(reduction|decrease)\b", re.I)  # más reducción = mejor
WEAK_POSITIVE = re.compile(r"\bnow (also )?(grants|provides|gives|has|applies|pierces|deals)\b|\bno longer (has a|costs|requires|breaks|interrupted)\b|new innate|added", re.I)
WEAK_NEGATIVE = re.compile(r"\bno longer\b|\bremoved\b|\bnow (requires|costs)\b", re.I)
REWORK = re.compile(r"rework|replaced with|new ability|reworked|redesigned", re.I)


@dataclass
class Change:
    version: str
    kind: str          # hero | item | neutral_item | general | creep
    target: str        # nombre del héroe / objeto ("" en los generales)
    target_id: int
    detail: str        # habilidad, "Talents", "Hero" o título de la sección
    text: str
    direction: float   # +1 buff, -1 nerf, ±0.5 probable, 0 neutro / desconocido
    rework: bool = False

    @property
    def tag(self) -> str:
        if self.rework:
            return "REWORK"
        return "BUFF" if self.direction > 0 else "NERF" if self.direction < 0 else "·"


def _clean(note: str) -> str:
    note = re.sub(r"<[^>]+>", "", note or "")
    return html.unescape(note).strip()


def _mean(text: str) -> float | None:
    nums = [float(n) for n in NUM.findall(text)]
    return sum(nums) / len(nums) if nums else None


def classify(text: str) -> tuple[float, bool]:
    """(dirección, es_rework) de una línea de notas de parche, desde el punto de vista de quien la recibe."""
    rework = bool(REWORK.search(text))
    polarity = -1.0 if LOWER_IS_BETTER.search(text) and not REDUCTION.search(text) else 1.0
    m = FROM_TO.search(text)
    if m:
        verb, before, after = m.group(1).lower(), _mean(m.group(2)), _mean(m.group(3))
        if before is not None and after is not None and before != after:
            return (1.0 if after > before else -1.0) * polarity, rework
        if verb in ("increased", "raised"):
            return polarity, rework
        if verb in ("decreased", "reduced", "lowered"):
            return -polarity, rework
        return 0.0, rework
    m = BY_AMOUNT.search(text)
    if m:
        up = m.group(1).lower() in ("increased", "raised")
        return (1.0 if up else -1.0) * polarity, rework
    if WEAK_POSITIVE.search(text):
        return 0.5, rework
    if WEAK_NEGATIVE.search(text):
        return -0.5, rework
    return 0.0, rework


# ---------- descarga ----------

def patch_list() -> list[dict]:
    data = cached_json("valve_patchlist", f"{VALVE}/patchnoteslist", 6 * HOUR, {"language": "english"})
    return sorted(data.get("patches") or [], key=lambda p: p.get("patch_timestamp", 0))


def fetch_patch(version: str, latest: bool = False) -> dict:
    ttl = 6 * HOUR if latest else 30 * 24 * HOUR  # los parches antiguos no cambian
    return cached_json(f"valve_patch_{version}", f"{VALVE}/patchnotes", ttl,
                       {"version": version, "language": "english"})


def base_version(v: str) -> str:
    """'7.42a' → '7.42'."""
    m = re.match(r"\d+\.\d+", v or "")
    return m.group(0) if m else v


def current_cycle(patches: list[dict] | None = None) -> list[str]:
    """Versiones del ciclo actual: el último parche grande y sus letras (7.42, 7.42a...)."""
    patches = patches if patches is not None else patch_list()
    if not patches:
        return []
    latest = base_version(patches[-1]["patch_number"])
    return [p["patch_number"] for p in patches if base_version(p["patch_number"]) == latest]


# ---------- interpretación ----------

def parse_patch(raw: dict, gd: GameData) -> list[Change]:
    version = raw.get("patch_number") or raw.get("patch_name") or "?"
    out: list[Change] = []

    def add(kind, target, tid, detail, notes):
        for n in notes or []:
            text = _clean(n.get("note", ""))
            if not text or n.get("hide_dot"):
                continue
            if n.get("info"):
                text = f"{text} ({_clean(n['info'])})"
            direction, rework = classify(text)
            out.append(Change(version, kind, target, tid, detail, text, direction, rework))

    for g in raw.get("general_notes") or []:
        add("general", "", 0, g.get("title", "General"), g.get("generic"))

    for h in raw.get("heroes") or []:
        hero = gd.hero(h.get("hero_id"))
        name = hero.loc if hero else f"hero#{h.get('hero_id')}"
        add("hero", name, h.get("hero_id", 0), "Hero", h.get("hero_notes"))
        for a in h.get("abilities") or []:
            add("hero", name, h.get("hero_id", 0), gd.abilities.get(a.get("ability_id"), "Ability"),
                a.get("ability_notes"))
        add("hero", name, h.get("hero_id", 0), "Talents", h.get("talent_notes"))

    for kind in ("items", "neutral_items"):
        for it in raw.get(kind) or []:
            if it.get("is_general_note") or it.get("ability_id", -1) < 0:
                add("general", "", 0, it.get("title", kind), it.get("ability_notes"))
                continue
            item = gd.items.get(it["ability_id"])
            name = item.loc if item else gd.abilities.get(it["ability_id"], f"item#{it['ability_id']}")
            add("item" if kind == "items" else "neutral_item", name, it["ability_id"], name, it.get("ability_notes"))

    for c in raw.get("neutral_creeps") or []:
        add("creep", c.get("localized_name", ""), 0, c.get("localized_name", ""), c.get("neutral_creep_notes"))
    return out


def score(changes: list[Change]) -> float:
    """Saldo de buffs - nerfs (los reworks cuentan como neutros)."""
    return sum(c.direction for c in changes if not c.rework)


def load_cycle(gd: GameData) -> tuple[list[str], list[Change]]:
    """Cambios del ciclo de parches actual (p. ej. 7.42 + 7.42a), del más antiguo al más reciente."""
    patches = patch_list()
    versions = current_cycle(patches)
    changes: list[Change] = []
    for i, v in enumerate(versions):
        try:
            changes += parse_patch(fetch_patch(v, latest=(i == len(versions) - 1)), gd)
        except Exception:
            log.exception("no se pudo leer el parche %s", v)
    return versions, changes
