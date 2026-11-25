"""Sugerencias de objetos sin IA: rasgos de los enemigos → objetos que los counterean,
más lo que realmente se compra con tu héroe (OpenDota), anotado con los cambios del parche actual."""
import json
import logging
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

# Objetos que resuelven lo mismo: de cada grupo solo se sugiere el de más prioridad
ALTERNATIVES = [{"item_dust", "item_gem"}, {"item_orchid", "item_bloodthorn"}]

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


def suggest_items(gd: GameData, my_hero: Hero | None, enemies: list[Hero], owned: list[str] = (),
                  role: str = "auto", meta=None, popularity: dict | None = None, limit: int = 6
                  ) -> list[ItemSuggestion]:
    role = item_role(my_hero, role)
    allowed = ROLE_ITEMS[role]
    owned_set = set(owned)
    sugg: dict[str, ItemSuggestion] = {}

    def add(name: str, weight: float, reason: str):
        item = gd.item(name)
        if not item or name in owned_set:
            return  # objeto retirado del juego o ya comprado
        s = sugg.setdefault(name, ItemSuggestion(name, item.loc, item.cost, 0.0))
        s.priority += weight
        s.reasons.append(reason)

    for trait, heroes in enemy_traits(enemies).items():
        for name, kind, why in COUNTER_ITEMS.get(trait, []):
            if kind not in allowed:
                continue
            weight = TRAIT_WEIGHT.get(trait, 1.0) * (1 + EXTRA_HERO_FACTOR * (len(heroes) - 1))
            add(name, weight, f"{why} ({', '.join(heroes)})")

    if popularity:  # lo que más se compra con tu héroe a mitad/final de partida
        for phase, weight in (("early_game_items", 0.4), ("mid_game_items", 0.6), ("late_game_items", 0.4)):
            counts = popularity.get(phase) or {}
            total = sum(counts.values()) or 1
            for item_id, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:4]:
                it = gd.items.get(int(item_id))
                if it and it.cost >= 500:
                    add(it.name, weight * POPULARITY_WEIGHT * n / total, f"popular en {my_hero.loc if my_hero else 'tu héroe'}")

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

    out, used_groups = [], set()
    for s in sorted(sugg.values(), key=lambda s: s.priority, reverse=True):
        group = next((i for i, g in enumerate(ALTERNATIVES) if s.item in g), None)
        if group is not None:
            if group in used_groups:
                continue
            used_groups.add(group)
        out.append(s)
    return out[:limit]
