"""Héroes, objetos y habilidades del parche actual, con búsqueda por nombre, alias y nombre interno.

Fuentes (sin clave):
- Valve datafeed (www.dota2.com/datafeed): ids y nombres oficiales de héroes, objetos y habilidades.
- OpenDota (api.opendota.com): coste de objetos, roles de héroes, alias de la comunidad e imágenes.
"""
import logging
import re
import unicodedata
from dataclasses import dataclass, field

from .cache import cached_json

log = logging.getLogger(__name__)

VALVE = "https://www.dota2.com/datafeed"
OPENDOTA = "https://api.opendota.com/api"
CDN = "https://cdn.cloudflare.steamstatic.com"
DAY = 86400


@dataclass
class Hero:
    id: int
    name: str                 # npc_dota_hero_antimage
    loc: str                  # Anti-Mage
    roles: list[str] = field(default_factory=list)
    attack_type: str = ""     # Melee | Ranged
    aliases: list[str] = field(default_factory=list)
    img: str = ""             # ruta en el CDN de Steam

    @property
    def short(self) -> str:
        return self.name.removeprefix("npc_dota_hero_")


@dataclass
class Item:
    id: int
    name: str                 # item_black_king_bar
    loc: str                  # Black King Bar
    cost: int = 0
    neutral_tier: int = -1

    @property
    def short(self) -> str:
        return self.name.removeprefix("item_")


# Apodos de héroes que no siempre vienen en los alias de OpenDota → nombre corto interno
HERO_ALIASES = {
    "jugg": "juggernaut", "jug": "juggernaut", "void": "faceless_void", "fv": "faceless_void",
    "wr": "windrunner", "ta": "templar_assassin", "kotl": "keeper_of_the_light", "veno": "venomancer",
    "venge": "vengefulspirit", "vs": "vengefulspirit", "timber": "shredder", "brew": "brewmaster",
    "sniper": "sniper", "storm": "storm_spirit", "ember": "ember_spirit", "earth": "earth_spirit",
    "void spirit": "void_spirit", "bs": "bloodseeker", "seeker": "bloodseeker", "naga": "naga_siren",
    "lone": "lone_druid", "ld": "lone_druid", "shaman": "shadow_shaman", "rhasta": "shadow_shaman",
    "ww": "winter_wyvern", "wyvern": "winter_wyvern", "underlord": "abyssal_underlord", "pango": "pangolier",
    "mk": "monkey_king", "dw": "dark_willow", "pl": "phantom_lancer", "tb": "terrorblade", "ck": "chaos_knight",
    "bb": "bristleback", "ench": "enchantress", "doom": "doom_bringer", "zeus": "zuus", "necro": "necrolyte",
    "wd": "witch_doctor", "sd": "shadow_demon", "sk": "sand_king", "es": "earthshaker", "ogre": "ogre_magi",
    "tide": "tidehunter", "nyx": "nyx_assassin", "spec": "spectre", "apparition": "ancient_apparition",
    "bounty": "bounty_hunter", "brood": "broodmother", "cent": "centaur", "clock": "rattletrap",
    "gyro": "gyrocopter", "invo": "invoker", "lesh": "leshrac", "mag": "magnataur", "morph": "morphling",
    "nature": "furion", "prophet": "furion", "shaker": "earthshaker", "sky": "skywrath_mage",
    "skywrath": "skywrath_mage", "bara": "spirit_breaker", "wraith": "skeleton_king", "dusa": "medusa",
    "gondar": "bounty_hunter", "grim": "grimstroke", "primal": "primal_beast", "alch": "alchemist",
    "arc": "arc_warden", "bat": "batrider", "beast": "beastmaster", "drow": "drow_ranger", "dawn": "dawnbreaker",
    "elder": "elder_titan", "omni": "omniknight", "terror": "terrorblade", "dazz": "dazzle", "veng": "vengefulspirit",
}

# Abreviaturas de la comunidad → nombre interno del objeto
ITEM_ALIASES = {
    "bkb": "black_king_bar", "mkb": "monkey_king_bar", "bf": "bfury", "battlefury": "bfury",
    "blink": "blink", "aghs": "ultimate_scepter", "aghanim": "ultimate_scepter", "shard": "aghanims_shard",
    "sb": "invis_sword", "shadowblade": "invis_sword", "silver": "silver_edge", "hex": "sheepstick",
    "scythe": "sheepstick", "euls": "cyclone", "eul": "cyclone", "linkens": "sphere", "linken": "sphere",
    "lotus": "lotus_orb", "vessel": "spirit_vessel", "urn": "urn_of_shadows", "mjol": "mjollnir",
    "mjolnir": "mjollnir", "deso": "desolator", "daedalus": "greater_crit", "crit": "lesser_crit",
    "skadi": "skadi", "shivas": "shivas_guard", "basher": "basher", "abyssal": "abyssal_blade",
    "manta": "manta", "butter": "butterfly", "halberd": "heavens_halberd", "atos": "rod_of_atos",
    "force": "force_staff", "glimmer": "glimmer_cape", "pipe": "pipe", "mek": "mekansm", "gg": "guardian_greaves",
    "greaves": "guardian_greaves", "travels": "travel_boots", "bots": "travel_boots", "treads": "power_treads",
    "phase": "phase_boots", "arcanes": "arcane_boots", "tranqs": "tranquil_boots", "wand": "magic_wand",
    "stick": "magic_stick", "midas": "hand_of_midas", "radi": "radiance", "refresher": "refresher",
    "octarine": "octarine_core", "nullifier": "nullifier", "diffu": "diffusal_blade", "diffusal": "diffusal_blade",
    "bloodthorn": "bloodthorn", "orchid": "orchid", "satanic": "satanic", "heart": "heart", "ac": "assault",
    "sny": "sange_and_yasha", "kny": "kaya_and_sange", "yk": "yasha_and_kaya", "dagon": "dagon",
    "ethereal": "ethereal_blade", "ghost": "ghost", "bm": "blade_mail", "blademail": "blade_mail",
    "crimson": "crimson_guard", "solar": "solar_crest", "dust": "dust", "sentry": "ward_sentry",
    "obs": "ward_observer", "gem": "gem", "smoke": "smoke_of_deceit", "tp": "tpscroll", "maelstrom": "maelstrom",
    "witch": "witch_blade", "harpoon": "harpoon", "pike": "hurricane_pike", "eblade": "ethereal_blade",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


class GameData:
    def __init__(self, heroes: list[Hero], items: list[Item], abilities: dict[int, str] | None = None):
        self.heroes = {h.id: h for h in heroes}
        self.items = {i.id: i for i in items}
        self.abilities = abilities or {}
        self._hero_index: dict[str, Hero] = {}
        for h in heroes:
            for key in [h.loc, h.short, h.name, *h.aliases]:
                self._hero_index.setdefault(_norm(key), h)
        by_short = {h.short: h for h in heroes}
        for alias, short in HERO_ALIASES.items():
            if short in by_short:
                self._hero_index.setdefault(_norm(alias), by_short[short])
        self._items_by_name = {i.name: i for i in items}
        self._item_index: dict[str, Item] = {}
        for i in items:
            for key in (i.loc, i.short, i.name):
                self._item_index.setdefault(_norm(key), i)
        for alias, short in ITEM_ALIASES.items():
            item = self._items_by_name.get(f"item_{short}")
            if item:
                self._item_index.setdefault(_norm(alias), item)

    # ---------- búsqueda ----------
    def hero(self, text: str | int | None) -> Hero | None:
        if text is None:
            return None
        if isinstance(text, int):
            return self.heroes.get(text)
        return self._hero_index.get(_norm(text))

    def item(self, text: str | None) -> Item | None:
        if not text:
            return None
        return self._items_by_name.get(text) or self._item_index.get(_norm(text))

    def parse_heroes(self, text: str) -> tuple[list[Hero], list[str]]:
        """'pa, lion, cm' → ([Phantom Assassin, Lion, Crystal Maiden], [no reconocidos])."""
        found, unknown = [], []
        for part in re.split(r"[,;/]+", text or ""):
            part = part.strip()
            if not part:
                continue
            h = self.hero(part)
            (found.append(h) if h else unknown.append(part))
        return found, unknown

    # ---------- carga ----------
    @classmethod
    def load(cls) -> "GameData":
        herolist = cached_json("valve_herolist", f"{VALVE}/herolist", 3 * DAY, {"language": "english"})
        itemlist = cached_json("valve_itemlist", f"{VALVE}/itemlist", 3 * DAY, {"language": "english"})
        abilities_raw = cached_json("valve_abilitylist", f"{VALVE}/abilitylist", 3 * DAY, {"language": "english"})
        od_heroes = cached_json("od_const_heroes", f"{OPENDOTA}/constants/heroes", 3 * DAY)
        od_items = cached_json("od_const_items", f"{OPENDOTA}/constants/items", 3 * DAY)
        try:
            stats = cached_json("od_herostats", f"{OPENDOTA}/heroStats", 6 * 3600)
        except Exception:
            stats = []
        aliases = {s.get("id"): s.get("aliases") or [] for s in stats if isinstance(s, dict)}

        heroes = []
        for h in herolist["result"]["data"]["heroes"]:
            od = od_heroes.get(str(h["id"]), {})
            heroes.append(Hero(id=h["id"], name=h["name"], loc=h["name_english_loc"] or h["name_loc"],
                               roles=od.get("roles") or [], attack_type=od.get("attack_type", ""),
                               aliases=aliases.get(h["id"], []), img=od.get("img", "")))
        items = []
        for i in itemlist["result"]["data"]["itemabilities"]:
            if not i.get("name_english_loc") or i["name"].startswith("item_recipe"):
                continue
            od = od_items.get(i["name"].removeprefix("item_"), {})
            items.append(Item(id=i["id"], name=i["name"], loc=i["name_english_loc"],
                              cost=int(od.get("cost") or 0), neutral_tier=int(i.get("neutral_item_tier", -1))))
        abilities = {a["id"]: a["name_english_loc"] or a["name"]
                     for a in abilities_raw["result"]["data"]["itemabilities"] if a.get("id")}
        log.info("datos del juego: %d héroes, %d objetos, %d habilidades", len(heroes), len(items), len(abilities))
        return cls(heroes, items, abilities)
