"""Lo que muestra el panel de partida, calculado fuera de la interfaz (se puede probar sin Tk).

build_view() se llama desde el hilo de GSI (puede tardar la primera vez: popularidad de OpenDota) y el panel
solo pinta el resultado.
"""
from dataclasses import dataclass, field

from ..data.gamedata import Hero
from ..data.patches import Change
from ..engine.counters import (PHASES, TRAIT_LABELS, PlanStep, build_plan, counters_for, enemy_traits, item_role,
                               next_purchase, phase_for)
from ..gsi import GameState

ROLE_LABELS = {"carry": "carry", "core": "core", "support": "support"}


@dataclass
class ItemCard:
    name: str            # item_black_king_bar
    loc: str
    cost: int
    reasons: list[str]
    patch_note: str = ""
    to_pay: int | None = None   # descontando componentes que ya llevas (None = el precio entero)
    plan: list[PlanStep] = field(default_factory=list)  # componentes: los que llevas ✓ y el orden del resto

    @property
    def short(self) -> str:
        return self.name.removeprefix("item_")


@dataclass
class HeroCard:
    hero: Hero
    traits: list[str] = field(default_factory=list)  # etiquetas en español
    winrate: float | None = None
    trend: float = 0.0
    verdict: str = ""                                  # buff | nerf | mixto | ...
    counters: list[ItemCard] = field(default_factory=list)  # qué comprar contra ESTE héroe


@dataclass
class MatchView:
    in_game: bool = False
    game_state: str = ""
    hero: Hero | None = None
    role: str = ""
    team: str = ""
    level: int = 0
    clock: int = 0
    clock_text: str = "0:00"
    daytime: bool = True
    alive: bool = True
    respawn_seconds: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    last_hits: int = 0
    gold: int = 0
    gpm: int = 0
    buyback_cost: int = 0
    items: list[str] = field(default_factory=list)
    inventory: list[tuple[str, str | None]] = field(default_factory=list)  # (casilla, item_* o None)
    stash: list[str] = field(default_factory=list)
    in_transit: list[str] = field(default_factory=list)   # en el courier
    buy_now: PlanStep | None = None   # el siguiente componente que ya puedes pagar
    lanes: dict = field(default_factory=dict)  # top/mid/bot → LaneInfo (aliados y enemigos)
    my_lane: str | None = None
    skill_plan: object = None      # SkillPlan (orden de habilidades y talentos habituales)
    skill_now: str | None = None   # qué subir ahora si hay un punto sin gastar
    abilities: list[dict] = field(default_factory=list)   # tus habilidades (GSI): nombre interno y nivel
    talent_flags: list[bool] = field(default_factory=list)
    lane_outlook: tuple | None = None  # (ganar, empatar, perder, partidas) contra tus rivales de línea
    lane_report: object = None     # LaneReport: tu línea en detalle (rivales, compañero, consejos)
    percentiles: dict[str, float] = field(default_factory=dict)  # oro/min, XP/min, últimos golpes/min (0-1)
    events: object = None          # EventsState: torres de tu bando, asesinatos, rachas, compras de aliados
    radiant_score: int = 0
    dire_score: int = 0
    drafting: bool = False
    phase: str = "start"
    next_item: ItemCard | None = None
    build: list[ItemCard] = field(default_factory=list)          # resto de la fase actual
    phase_builds: dict[str, list[ItemCard]] = field(default_factory=dict)  # start/early/mid/late
    enemies: list[HeroCard] = field(default_factory=list)
    allies: list[Hero] = field(default_factory=list)
    my_changes: list[Change] = field(default_factory=list)


def _card(gd, name: str, reason: str) -> ItemCard | None:
    it = gd.item(name)
    return ItemCard(it.name, it.loc, it.cost, [reason]) if it else None


def hero_card(hero: Hero, meta, gd=None, my_hero: Hero | None = None, role: str = "auto",
              owned: list[str] = ()) -> HeroCard:
    card = HeroCard(hero, [TRAIT_LABELS.get(t, t) for t in enemy_traits([hero])])
    if gd is not None:
        card.counters = [c for c in (_card(gd, n, why) for n, why in counters_for(gd, hero, my_hero, role, owned))
                         if c]
    hm = meta.hero(hero) if meta is not None else None
    if hm:
        card.winrate = hm.winrate if hm.picks else None
        card.trend, card.verdict = hm.trend, hm.verdict
    return card


INVENTORY_SLOTS = [f"slot{i}" for i in range(9)] + ["neutral0", "teleport0"]


def build_view(advisor, meta, st: GameState, build_size: int = 6, mapwatch=None) -> MatchView:
    hero = advisor.my_hero(st)
    v = MatchView(
        in_game=st.in_game, game_state=st.game_state, hero=hero, team=st.team, level=st.level, clock=st.clock,
        clock_text=st.clock_text, daytime=st.daytime, alive=st.alive, respawn_seconds=st.respawn_seconds,
        kills=st.kills, deaths=st.deaths, assists=st.assists, last_hits=st.last_hits, gold=st.gold, gpm=st.gpm,
        buyback_cost=st.buyback_cost, items=list(st.all_items),
        role=ROLE_LABELS.get(item_role(hero, advisor.cfg.get("role", "auto")), ""),
        inventory=[(slot, st.slots.get(slot)) for slot in INVENTORY_SLOTS],
        radiant_score=st.radiant_score, dire_score=st.dire_score,
        abilities=list(st.abilities), talent_flags=list(st.talent_flags),
        stash=[st.slots[k] for k in sorted(st.slots) if k.startswith("stash")],
        in_transit=list(st.in_transit),
    )
    if mapwatch is not None:
        v.lanes, v.my_lane = mapwatch.lanes(), mapwatch.my_lane()
    v.phase = phase_for(st.clock)
    if hero:
        for phase in PHASES:
            sugg = advisor.suggestions(st, phase=phase, limit=build_size)
            v.phase_builds[phase] = [ItemCard(s.item, s.loc, s.cost, list(dict.fromkeys(s.reasons)), s.patch_note,
                                              s.remaining) for s in sugg]
        owned = st.all_items
        for cards in v.phase_builds.values():
            for c in cards:
                c.plan = build_plan(advisor.gd, c.name, owned)
        cards = v.phase_builds.get(v.phase, [])
        v.next_item, v.build = (cards[0] if cards else None), cards[1:]
        if v.next_item:
            v.buy_now = next_purchase(v.next_item.plan, st.gold)
        hm = meta.hero(hero) if meta is not None else None
        v.my_changes = list(hm.changes) if hm else []
    role = advisor.cfg.get("role", "auto")
    v.enemies = [hero_card(h, meta, advisor.gd, hero, role, st.all_items) for h in list(advisor.enemies.values())]
    v.allies = [h for h in advisor.allies.values() if not hero or h.id != hero.id]
    return v
