"""Sugerencias de objetos sin IA: rasgos de los enemigos → objetos que los counterean,
más lo que realmente se compra con tu héroe (OpenDota), anotado con los cambios del parche actual."""
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ..data.gamedata import GameData, Hero
from ..data.patches import score

log = logging.getLogger(__name__)

TRAITS: dict[str, list[str]] = {
    k: v for k, v in json.loads((Path(__file__).with_name("hero_traits.json")).read_text(encoding="utf-8")).items()
    if not k.startswith("_")
}

TRAIT_LABELS = {
    "evasion": "evasión", "illusions": "ilusiones", "invis": "invisibilidad", "magic_burst": "daño mágico",
    "physical_burst": "daño físico", "heal": "curación", "summons": "invocaciones", "escape": "movilidad",
    "disables": "control (stuns/silencios)", "targeted_ult": "ulti de un objetivo", "buffs": "buffs disipables",
    "passives": "pasivas rompibles", "tanky": "mucha vida", "mana_shield": "escudo de maná", "mana_burn": "quema de maná",
}

# Para qué perfil sirve cada counter:
#   carry   → objetos de golpe (posición 1)        core → cualquier core (mid, offlane o carry)
#   tank    → objetos de equipo/aguante de offlane  support / any
# Qué perfiles puede comprar cada rol del jugador:
ROLE_ITEMS = {"carry": {"carry", "core", "any"}, "core": {"carry", "core", "tank", "any"}, "support": {"support", "any"}}

# rasgo → [(objeto, perfil, motivo)]
COUNTER_ITEMS: dict[str, list[tuple[str, str, str]]] = {
    "evasion": [("item_monkey_king_bar", "carry", "ignora la evasión"),
                ("item_bloodthorn", "core", "ataques certeros + silencio")],
    "illusions": [("item_mjollnir", "carry", "limpia ilusiones"), ("item_bfury", "carry", "cleave contra ilusiones"),
                  ("item_maelstrom", "carry", "rebota entre ilusiones")],
    "invis": [("item_dust", "any", "revela invisibles"), ("item_ward_sentry", "support", "detecta invisibles"),
              ("item_gem", "core", "detección permanente")],
    "magic_burst": [("item_black_king_bar", "core", "inmune a la magia"), ("item_pipe", "tank", "escudo mágico de equipo"),
                    ("item_glimmer_cape", "support", "resistencia mágica e invisibilidad"),
                    ("item_eternal_shroud", "tank", "resistencia mágica")],
    "physical_burst": [("item_ghost", "support", "inmune a ataques físicos"), ("item_force_staff", "support", "escapar o salvar"),
                       ("item_blade_mail", "tank", "devuelve el daño"), ("item_heavens_halberd", "tank", "desarma al carry"),
                       ("item_solar_crest", "support", "armadura para tu carry"),
                       ("item_shivas_guard", "tank", "reduce su velocidad de ataque"),
                       ("item_butterfly", "carry", "evasión contra sus golpes")],
    "heal": [("item_spirit_vessel", "any", "reduce la curación"), ("item_skadi", "carry", "reduce la curación"),
             ("item_shivas_guard", "tank", "reduce la curación en área")],
    "summons": [("item_mjollnir", "carry", "daño en área a invocaciones"), ("item_bfury", "carry", "cleave"),
                ("item_crimson_guard", "tank", "bloquea los golpes de las invocaciones")],
    "escape": [("item_orchid", "core", "silencio antes de que escape"), ("item_bloodthorn", "core", "silencio"),
               ("item_sheepstick", "core", "hex: no puede escapar"), ("item_rod_of_atos", "support", "lo enraíza"),
               ("item_abyssal_blade", "carry", "stun que atraviesa inmunidad")],
    "disables": [("item_black_king_bar", "core", "inmune a la mayoría de controles"), ("item_lotus_orb", "tank", "disipa y refleja"),
                 ("item_manta", "carry", "disipa silencios"), ("item_cyclone", "support", "te disipa y te salva")],
    "targeted_ult": [("item_sphere", "core", "bloquea la ulti de objetivo"), ("item_lotus_orb", "tank", "refleja la ulti")],
    "buffs": [("item_nullifier", "carry", "disipa sus buffs"), ("item_cyclone", "support", "disipa sus buffs"),
              ("item_diffusal_blade", "carry", "disipa y ralentiza")],
    "passives": [("item_silver_edge", "core", "rompe (Break) sus pasivas")],
    "tanky": [("item_desolator", "carry", "reduce su armadura"), ("item_spirit_vessel", "any", "daño por % de vida")],
    "mana_shield": [("item_diffusal_blade", "carry", "quema el maná que le protege"), ("item_nullifier", "carry", "anula sus objetos")],
    "mana_burn": [("item_black_king_bar", "core", "aguanta su presión"), ("item_eternal_shroud", "tank", "convierte daño en maná")],
}

# Rasgos que obligan a comprar el counter (sin él no puedes ni pegar / ver / matar)
TRAIT_WEIGHT = {"evasion": 1.8, "illusions": 1.4, "invis": 3.0, "heal": 1.2, "targeted_ult": 0.8, "tanky": 0.6}
# Cada enemigo extra con el mismo rasgo suma menos: un counter imprescindible contra uno solo (MKB, Dust)
# no debe quedar por detrás de uno genérico contra tres.
EXTRA_HERO_FACTOR = 0.4

# Carries de posición 1: compran objetos de golpe, no de equipo. OpenDota marca "Carry" a medio roster
# (Axe, Tidehunter, Zeus...), así que la lista es a mano. Editable.
HARD_CARRIES = {
    "Alchemist", "Anti-Mage", "Arc Warden", "Chaos Knight", "Clinkz", "Drow Ranger", "Faceless Void", "Gyrocopter",
    "Juggernaut", "Kez", "Lifestealer", "Luna", "Lycan", "Medusa", "Meepo", "Monkey King", "Morphling", "Muerta",
    "Naga Siren", "Phantom Assassin", "Phantom Lancer", "Razor", "Riki", "Slark", "Sniper", "Spectre", "Sven",
    "Terrorblade", "Troll Warlord", "Ursa", "Weaver", "Wraith King",
}

# Peso de lo que se compra con tu héroe (OpenDota) frente a los counters
POPULARITY_WEIGHT = 12

# Partidas parecidas (tu héroe contra estos enemigos): lo que llevaban los ganadores es lo "estándar" y manda;
# lo que no respalda ni eso ni la popularidad de tu héroe pierde peso (salvo la detección: siempre hace falta).
STANDARD_WEIGHT = 6.0
UNBACKED_FACTOR = 0.7
ALWAYS_NEEDED = {"item_dust", "item_ward_sentry", "item_gem"}

# Objetos que resuelven lo mismo: de cada grupo solo se sugiere el de más prioridad
ALTERNATIVES = [{"item_dust", "item_gem"}, {"item_orchid", "item_bloodthorn"}]

# Fases de la partida: cada una pesa lo que se compra en ese momento (OpenDota) y castiga lo que no cabe en su
# presupuesto (al empezar no tiene sentido sugerir una BKB).
PHASES = ["start", "early", "mid", "late"]
PHASE_LABELS = {"start": "Inicio", "early": "Early (0-12)", "mid": "Mid (12-28)", "late": "Late (28+)"}
PHASE_BUDGET = {"start": 600, "early": 2500, "mid": 5500, "late": None}
PHASE_MAX_COST = {"start": 1000}  # tope estricto solo al salir: en early los counters grandes son el objetivo
PHASE_POPULARITY = {
    "start": {"start_game_items": 1.0},
    "early": {"early_game_items": 1.0, "mid_game_items": 0.25},
    "mid": {"mid_game_items": 1.0, "early_game_items": 0.2, "late_game_items": 0.4},
    "late": {"late_game_items": 1.0, "mid_game_items": 0.5},
    None: {"early_game_items": 0.4, "mid_game_items": 0.6, "late_game_items": 0.4},  # sin fase: toda la partida
}


# Objetos básicos que también se compran sueltos a mitad de partida (no son "solo un componente")
STANDALONE = {"item_blink", "item_gem", "item_aghanims_shard", "item_smoke_of_deceit", "item_dust",
              "item_ward_observer", "item_ward_sentry", "item_tpscroll"}


# Botas: solo se llevan unas. Con unas ya mejoradas, solo tienen sentido sus mejoras (Arcane → Greaves...).
BOOTS = {"item_boots", "item_phase_boots", "item_power_treads", "item_tranquil_boots", "item_arcane_boots",
         "item_guardian_greaves", "item_travel_boots", "item_travel_boots_2", "item_boots_of_bearing"}
UPGRADE_WEIGHT = 2.0       # completar algo con lo que ya llevas
UPGRADE_MIN_COST = 1200    # objetos de este precio o más marcan una "ruta" (Maelstrom → Mjollnir)


def components_of(gd: GameData, name: str, _seen: set | None = None) -> set[str]:
    """Todos los componentes de un objeto, a cualquier profundidad (Mjollnir → Maelstrom → Mithril Hammer...)."""
    seen = set() if _seen is None else _seen
    item = gd.item(name)
    for c in (item.components if item else []):
        if c not in seen:
            seen.add(c)
            components_of(gd, c, seen)
    return seen


def owned_closure(gd: GameData, owned) -> set[str]:
    """Lo que llevas más todo aquello con lo que ya está fabricado (Tranquil Boots ⇒ Boots of Speed)."""
    out = set(owned)
    for name in owned:
        out |= components_of(gd, name)
    return out


def excluded_by_inventory(gd: GameData, name: str, owned, closure: set[str]) -> bool:
    if name in closure:
        return True  # ya lo llevas, o ya está dentro de algo que llevas
    owned_boots = BOOTS.intersection(owned) - {"item_boots"}
    if name in BOOTS and owned_boots:
        return not (owned_boots & components_of(gd, name))  # otras botas: no; sus mejoras: sí
    return False


def phase_for(clock_seconds: int) -> str:
    minute = clock_seconds / 60
    return "start" if minute < 0 else "early" if minute < 12 else "mid" if minute < 28 else "late"


# Lo básico de cualquier partida, con prioridad baja
UTILITY = [("item_magic_wand", "any", "barato y salva vidas contra hechizos"), ("item_ward_observer", "support", "visión")]


@dataclass
class ItemSuggestion:
    item: str                       # item_*
    loc: str
    cost: int
    priority: float
    reasons: list[str] = field(default_factory=list)
    patch_note: str = ""
    remaining: int | None = None    # lo que falta pagar descontando componentes que ya llevas

    @property
    def to_pay(self) -> int:
        return self.cost if self.remaining is None else self.remaining

    def line(self) -> str:
        why = "; ".join(dict.fromkeys(self.reasons))
        extra = f" · parche: {self.patch_note}" if self.patch_note else ""
        return f"{self.loc} ({self.cost} oro): {why}{extra}"


def player_role(hero: Hero | None, configured: str = "auto") -> str:
    """core | support (para el draft). Un carry configurado cuenta como core."""
    if configured in ("core", "support"):
        return configured
    if configured == "carry":
        return "core"
    if not hero:
        return "core"
    return "support" if "Support" in hero.roles and "Carry" not in hero.roles else "core"


def item_role(hero: Hero | None, configured: str = "auto") -> str:
    """Perfil de compra del jugador: carry | core | support."""
    if configured in ("carry", "core", "support"):
        return configured
    role = player_role(hero)
    return "carry" if role == "core" and hero and hero.loc in HARD_CARRIES else role


def enemy_traits(enemies: list[Hero]) -> dict[str, list[str]]:
    """rasgo → héroes enemigos que lo tienen."""
    out: dict[str, list[str]] = {}
    for h in enemies:
        for t in TRAITS.get(h.loc, []):
            out.setdefault(t, []).append(h.loc)
    return out


PHASE_BY_COST = ((2500, "early"), (5500, "mid"), (10 ** 9, "late"))  # sin datos de cuándo se compra


def native_phase(gd: GameData, name: str, popularity: dict | None = None) -> str:
    """La fase a la que pertenece un objeto: cuándo se suele comprar con tu héroe (STRATZ: minuto medio; OpenDota:
    la fase en que más se compra) o, sin datos, por su precio. Cada objeto sale en UNA sola fase."""
    item = gd.item(name)
    pop = popularity or {}
    if item is not None:
        key = str(item.id)
        if key in (pop.get("start_game_items") or {}) and item.cost <= PHASE_MAX_COST["start"]:
            share = ((pop.get("_details_start") or {}).get(key) or (1.0,))[0]
            if share >= 0.2:
                return "start"
        detail = (pop.get("_details") or {}).get(key)
        if detail:
            return phase_for(int(detail[1] * 60))
        counts = {ph: (pop.get(k) or {}).get(key, 0) for ph, k in
                  (("early", "early_game_items"), ("mid", "mid_game_items"), ("late", "late_game_items"))}
        if any(counts.values()):
            return max(counts.items(), key=lambda kv: kv[1])[0]
    cost = item.cost if item else 0
    return next(ph for limit, ph in PHASE_BY_COST if cost <= limit)


def suggest_items(gd: GameData, my_hero: Hero | None, enemies: list[Hero], owned: list[str] = (),
                  role: str = "auto", meta=None, popularity: dict | None = None, limit: int = 6,
                  phase: str | None = None, standard: dict[str, tuple[float, str]] | None = None,
                  strict: bool = False) -> list[ItemSuggestion]:
    """phase: start | early | mid | late (o None para toda la partida). strict: solo los objetos de ESA fase
    (native_phase), para que la build por fases no repita objetos ni meta los caros al principio.
    standard: {item_*: (fracción 0-1, texto)} de partidas parecidas (lo que llevaban los que ganaron)."""
    role = item_role(my_hero, role)
    allowed = ROLE_ITEMS[role]
    owned = [o for o in owned if o]
    closure = owned_closure(gd, owned)
    sugg: dict[str, ItemSuggestion] = {}

    def add(name: str, weight: float, reason: str):
        item = gd.item(name)
        if not item or excluded_by_inventory(gd, name, owned, closure):
            return  # objeto retirado del juego, ya comprado o sin sentido con lo que llevas
        s = sugg.setdefault(name, ItemSuggestion(name, item.loc, item.cost, 0.0))
        s.priority += weight
        s.reasons.append(reason)

    for trait, heroes in enemy_traits(enemies).items():
        for name, kind, why in COUNTER_ITEMS.get(trait, []):
            if kind not in allowed:
                continue
            weight = TRAIT_WEIGHT.get(trait, 1.0) * (1 + EXTRA_HERO_FACTOR * (len(heroes) - 1))
            add(name, weight, f"{why} ({', '.join(heroes)})")

    if popularity:  # lo que más se compra con tu héroe en esta fase de la partida
        min_cost = 1 if phase == "start" else 500  # al salir sí cuentan tangos, ramas...
        for key, weight in PHASE_POPULARITY[phase].items():
            counts = popularity.get(key) or {}
            total = sum(counts.values()) or 1
            for item_id, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]:
                it = gd.items.get(int(item_id))
                bare_component = (it is not None and not it.components and it.name not in STANDALONE
                                  and it.name in getattr(gd, "component_names", ()))
                if phase in ("mid", "late") and bare_component:
                    continue  # p. ej. Broadsword: a estas alturas se compra para fabricar otra cosa
                if it and it.cost >= min_cost:
                    details = popularity.get("_details_start" if key == "start_game_items" else "_details") or {}
                    detail = details.get(str(item_id))
                    who = my_hero.loc if my_hero else "tu héroe"
                    scope = popularity.get("_scope", "")
                    where = f" ({scope})" if scope else ""
                    if detail and key == "start_game_items":
                        reason = f"lo compra al salir el {detail[0]:.0%} de los {who}{where}"
                    elif detail:
                        reason = (f"lo compra el {detail[0]:.0%} de los {who}{where}, hacia el minuto "
                                  f"{detail[1]:.0f} ({detail[2]:.0%} de victorias)")
                    else:
                        reason = f"popular en {who}"
                    add(it.name, weight * POPULARITY_WEIGHT * n / total, reason)

    backed = {name for name, s in sugg.items()
              if any(r.startswith(("popular en", "lo compra el")) for r in s.reasons)}
    if standard:
        for name, (share, label) in standard.items():
            if share > 0:
                add(name, STANDARD_WEIGHT * share, label)
                backed.add(name)
        for name, s in sugg.items():
            if name not in backed and name not in ALWAYS_NEEDED:
                s.priority *= UNBACKED_FACTOR

    # Seguir la ruta del jugador: lo que se fabrica con un objeto importante que ya lleva (aunque no esté en
    # ninguna lista) y, en todo lo sugerido, descontar del precio lo que ya tiene hecho.
    routes = [o for o in owned if (gd.item(o) and gd.item(o).cost >= UPGRADE_MIN_COST)]
    if routes:
        for item in list(gd.items.values()):
            used = [o for o in routes if o in item.components]
            if used and item.cost > 0:
                add(item.name, UPGRADE_WEIGHT * 0.6, f"se completa con tu {gd.item(used[0]).loc}")
    for s in sugg.values():
        inside = components_of(gd, s.item) & set(owned)
        if inside:
            done = sum(gd.item(c).cost for c in inside if gd.item(c))
            s.remaining = max(0, s.cost - done)
            s.priority += UPGRADE_WEIGHT * min(1.0, done / s.cost if s.cost else 0)

    for name, kind, why in UTILITY:
        if kind in allowed:
            add(name, 0.2, why)

    if meta is not None:
        for s in sugg.values():
            changes = meta.item_changes(s.loc)
            if changes:
                net = score(changes)
                s.priority += 0.3 * max(-1.0, min(1.0, net))
                review = meta.item_reviews.get(s.loc.lower()) if hasattr(meta, "item_reviews") else None
                s.patch_note = (review or {}).get("summary") or "; ".join(c.text for c in changes[:2])

    if strict and phase:
        sugg = {k: s for k, s in sugg.items()
                if k in ALWAYS_NEEDED or native_phase(gd, k, popularity) == phase}
    cap = PHASE_MAX_COST.get(phase)
    if cap:
        sugg = {k: s for k, s in sugg.items() if s.to_pay <= cap}
    budget = PHASE_BUDGET.get(phase)
    if budget:
        for s in sugg.values():
            if s.cost > budget:
                s.priority *= (budget / s.cost) ** 2

    out, used_groups = [], set()
    for s in sorted(sugg.values(), key=lambda s: s.priority, reverse=True):
        group = next((i for i, g in enumerate(ALTERNATIVES) if s.item in g), None)
        if group is not None:
            if group in used_groups:
                continue
            used_groups.add(group)
        out.append(s)
    return out[:limit]


def counters_for(gd: GameData, enemy: Hero, my_hero: Hero | None = None, role: str = "auto",
                 owned: list[str] = (), limit: int = 3) -> list[tuple[str, str]]:
    """Los objetos que mejor counterean a UN enemigo para tu rol: [(item_*, motivo)], los ya comprados fuera."""
    allowed = ROLE_ITEMS[item_role(my_hero, role)]
    owned = [o for o in owned if o]
    closure = owned_closure(gd, owned)
    best: dict[str, tuple[float, str]] = {}
    for trait in TRAITS.get(enemy.loc, []):
        for name, kind, why in COUNTER_ITEMS.get(trait, []):
            if kind not in allowed or not gd.item(name) or excluded_by_inventory(gd, name, owned, closure):
                continue
            weight = TRAIT_WEIGHT.get(trait, 1.0)
            if weight > best.get(name, (0.0, ""))[0]:
                best[name] = (weight, why)
    ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)
    out, used_groups = [], set()
    for name, (_, why) in ranked:
        group = next((i for i, g in enumerate(ALTERNATIVES) if name in g), None)
        if group is not None and group in used_groups:
            continue
        if group is not None:
            used_groups.add(group)
        out.append((name, why))
    return out[:limit]


@dataclass
class PlanStep:
    name: str            # item_* o "recipe"
    loc: str
    cost: int
    owned: bool = False
    to_pay: int = 0      # lo que falta de este paso (un componente a medias ya tiene parte pagada)

    @property
    def short(self) -> str:
        return self.name.removeprefix("item_")


def build_plan(gd: GameData, item_name: str, owned: list[str]) -> list[PlanStep]:
    """Cómo fabricar un objeto con lo que llevas: primero lo que ya tienes (✓), luego lo que falta de más barato a
    más caro (antes empiezas a notar las estadísticas) y la receta al final. Vacío si no tiene componentes."""
    item = gd.item(item_name)
    if not item or not item.components:
        return []
    inv = Counter(o for o in owned if o)
    have, missing = [], []
    for c in item.components:
        comp = gd.item(c)
        if not comp:
            continue
        if inv[c] > 0:
            inv[c] -= 1
            have.append(PlanStep(c, comp.loc, comp.cost, owned=True))
            continue
        paid = 0
        for sub in comp.components:  # componente a medias (p. ej. Perseverance con un Ring of Health)
            if inv[sub] > 0 and gd.item(sub):
                inv[sub] -= 1
                paid += gd.item(sub).cost
        missing.append(PlanStep(c, comp.loc, comp.cost, to_pay=max(0, comp.cost - paid)))
    recipe = item.cost - sum(gd.item(c).cost for c in item.components if gd.item(c))
    steps = have + sorted(missing, key=lambda s: s.to_pay)
    if recipe > 0:
        steps.append(PlanStep("recipe", "Receta", recipe, to_pay=recipe))
    return steps


def next_purchase(plan: list[PlanStep], gold: int) -> PlanStep | None:
    """El primer paso pendiente del plan que ya puedes pagar. La receta, solo cuando ya tienes todo lo demás
    (comprarla antes no da nada)."""
    pending = [s for s in plan if not s.owned]
    parts = [s for s in pending if s.name != "recipe"]
    if not parts:
        return next((s for s in pending if s.to_pay <= gold), None)
    return next((s for s in parts if s.to_pay <= gold), None)
