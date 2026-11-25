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

# rasgo → [(objeto, rol: core|support|any, motivo)]
COUNTER_ITEMS: dict[str, list[tuple[str, str, str]]] = {
    "evasion": [("item_monkey_king_bar", "core", "ignora la evasión"),
                ("item_bloodthorn", "core", "ataques certeros + silencio")],
    "illusions": [("item_mjollnir", "core", "limpia ilusiones"), ("item_bfury", "core", "cleave contra ilusiones"),
                  ("item_maelstrom", "core", "rebota entre ilusiones")],
    "invis": [("item_dust", "any", "revela invisibles"), ("item_ward_sentry", "any", "detecta invisibles"),
              ("item_gem", "core", "detección permanente")],
    "magic_burst": [("item_black_king_bar", "core", "inmune a la magia"), ("item_pipe", "core", "escudo mágico de equipo"),
                    ("item_glimmer_cape", "support", "resistencia mágica e invisibilidad"),
                    ("item_eternal_shroud", "core", "resistencia mágica")],
    "physical_burst": [("item_ghost", "support", "inmune a ataques físicos"), ("item_force_staff", "support", "escapar o salvar"),
                       ("item_blade_mail", "core", "devuelve el daño"), ("item_heavens_halberd", "core", "desarma al carry"),
                       ("item_solar_crest", "support", "armadura para tu carry"), ("item_shivas_guard", "core", "reduce su velocidad de ataque")],
    "heal": [("item_spirit_vessel", "any", "reduce la curación"), ("item_skadi", "core", "reduce la curación"),
             ("item_shivas_guard", "core", "reduce la curación en área")],
    "summons": [("item_mjollnir", "core", "daño en área a invocaciones"), ("item_bfury", "core", "cleave"),
                ("item_crimson_guard", "core", "bloquea los golpes de las invocaciones")],
    "escape": [("item_orchid", "core", "silencio antes de que escape"), ("item_bloodthorn", "core", "silencio"),
               ("item_sheepstick", "core", "hex: no puede escapar"), ("item_rod_of_atos", "support", "lo enraíza"),
               ("item_abyssal_blade", "core", "stun que atraviesa inmunidad")],
    "disables": [("item_black_king_bar", "core", "inmune a la mayoría de controles"), ("item_lotus_orb", "any", "disipa y refleja"),
                 ("item_manta", "core", "disipa silencios"), ("item_cyclone", "support", "te disipa y te salva")],
    "targeted_ult": [("item_sphere", "core", "bloquea la ulti de objetivo"), ("item_lotus_orb", "any", "refleja la ulti")],
    "buffs": [("item_nullifier", "core", "disipa sus buffs"), ("item_cyclone", "any", "disipa sus buffs"),
              ("item_diffusal_blade", "core", "disipa y ralentiza")],
    "passives": [("item_silver_edge", "core", "rompe (Break) sus pasivas")],
    "tanky": [("item_desolator", "core", "reduce su armadura"), ("item_spirit_vessel", "any", "daño por % de vida")],
    "mana_shield": [("item_diffusal_blade", "core", "quema el maná que le protege"), ("item_nullifier", "core", "anula sus objetos")],
    "mana_burn": [("item_black_king_bar", "core", "aguanta su presión"), ("item_eternal_shroud", "core", "convierte daño en maná")],
}

# Rasgos que obligan a comprar el counter (sin él no puedes ni pegar / ver / matar)
TRAIT_WEIGHT = {"evasion": 1.8, "illusions": 1.4, "invis": 2.0, "heal": 1.2, "targeted_ult": 0.8, "tanky": 0.6}

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
    if configured in ("core", "support"):
        return configured
    if not hero:
        return "core"
    return "support" if "Support" in hero.roles and "Carry" not in hero.roles else "core"


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
    role = player_role(my_hero, role)
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
        for name, item_role, why in COUNTER_ITEMS.get(trait, []):
            if item_role not in ("any", role):
                continue
            add(name, TRAIT_WEIGHT.get(trait, 1.0) * len(heroes), f"{why} ({', '.join(heroes)})")

    if popularity:  # lo que más se compra con tu héroe a mitad/final de partida
        for phase, weight in (("early_game_items", 0.4), ("mid_game_items", 0.6), ("late_game_items", 0.4)):
            counts = popularity.get(phase) or {}
            total = sum(counts.values()) or 1
            for item_id, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:4]:
                it = gd.items.get(int(item_id))
                if it and it.cost >= 500:
                    add(it.name, weight * 8 * n / total, f"popular en {my_hero.loc if my_hero else 'tu héroe'}")

    for name, item_role, why in UTILITY:
        if item_role in ("any", role):
            add(name, 0.2, why)

    if meta is not None:
        for s in sugg.values():
            changes = meta.item_changes(s.loc)
            if changes:
                net = score(changes)
                s.priority += 0.3 * max(-1.0, min(1.0, net))
                review = meta.item_reviews.get(s.loc.lower()) if hasattr(meta, "item_reviews") else None
                s.patch_note = (review or {}).get("summary") or "; ".join(c.text for c in changes[:2])

    return sorted(sugg.values(), key=lambda s: s.priority, reverse=True)[:limit]
