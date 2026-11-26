"""Lo que muestra el panel de partida, calculado fuera de la interfaz (se puede probar sin Tk).

build_view() se llama desde el hilo de GSI (puede tardar la primera vez: popularidad de OpenDota) y el panel
solo pinta el resultado.
"""
from dataclasses import dataclass, field

from ..data.gamedata import Hero
from ..data.patches import Change
from ..engine.counters import (PHASES, TRAIT_LABELS, PlanStep, build_plan, counters_for, enemy_traits, item_role,
                               next_purchase, phase_for, purchase_order)
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
    owned: bool = False        # ya comprado: se queda en su fase con un tick

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
    hotkey: str = ""                                   # Ctrl+F1…F5 para marcar su definitiva
    slot: int | None = None                            # hueco 0-4 de su bando, si la visión lo ha reconocido
    items: list[str] = field(default_factory=list)     # objetos vistos al seleccionarlo (item_*)
    items_ago: int | None = None                       # segundos desde que se vieron
    ult_name: str = ""                                 # icono de Valve (p. ej. enigma_black_hole)
    ult_loc: str = ""
    ult_left: tuple[int, int] | None = None            # segundos que le faltan (mín, máx); None = sin marcar


@dataclass
class GuideInfo:
    id: str
    source: str
    role: str
    minutes: int
    done: int
    total: int
    items: list[tuple[str, bool]]      # (nombre del objeto, ya comprado)
    note: str = ""


@dataclass
class DeviationInfo:
    item: str               # lo que compraste fuera de la guía
    item_loc: str
    suggestion: str         # lo que hicieron las builds ganadoras parecidas
    suggestion_loc: str
    guide_next: str | None
    guide_next_loc: str
    reason: str


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
    turbo: bool = False                 # partida turbo (detectada por el oro pasivo)
    guide: GuideInfo | None = None      # la guía elegida (si es de tu héroe)
    deviation: DeviationInfo | None = None   # te has salido de la guía: propuesta para adaptarla
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
              owned: list[str] = (), items: list[str] = ()) -> HeroCard:
    card = HeroCard(hero, [TRAIT_LABELS.get(t, t) for t in enemy_traits([hero], {hero.id: list(items)})],
                    items=list(items))
    if gd is not None:
        card.counters = [c for c in (_card(gd, n, why) for n, why in
                                     counters_for(gd, hero, my_hero, role, owned, items=list(items))) if c]
    hm = meta.hero(hero) if meta is not None else None
    if hm:
        card.winrate = hm.winrate if hm.picks else None
        card.trend, card.verdict = hm.trend, hm.verdict
    return card


INVENTORY_SLOTS = [f"slot{i}" for i in range(9)] + ["neutral0", "teleport0"]


def build_view(advisor, meta, st: GameState, build_size: int = 6, mapwatch=None, ults=None,
               enemy_slots: list | None = None, ult_keys: bool = False,
               confirmed_slots: dict[int, int] | None = None) -> MatchView:
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
    v.phase, v.turbo = phase_for(st.clock, st.turbo), st.turbo
    guide = advisor.active_guide() if hasattr(advisor, "active_guide") else None
    if guide:
        done, total = advisor.follower.progress(advisor.ever_owned)
        v.guide = GuideInfo(guide.id, guide.source, guide.role, guide.minutes, done, total,
                            [(advisor.gd.item(n).loc if advisor.gd.item(n) else n, n in advisor.ever_owned)
                             for n in guide.items], guide.note)
        dev = advisor.guide_deviation(st)
        if dev:
            gi = advisor.gd.item
            v.deviation = DeviationInfo(dev.item, gi(dev.item).loc if gi(dev.item) else dev.item, dev.suggestion,
                                        gi(dev.suggestion).loc if gi(dev.suggestion) else dev.suggestion,
                                        dev.guide_next, (gi(dev.guide_next).loc if dev.guide_next and
                                                         gi(dev.guide_next) else ""), dev.reason)
    if hero:
        for phase in PHASES:
            sugg = advisor.suggestions(st, phase=phase, limit=build_size)
            if phase != "start":  # al salir se compra todo a la vez
                sugg = purchase_order(sugg)
            pending = [ItemCard(s.item, s.loc, s.cost, list(dict.fromkeys(s.reasons)), s.patch_note, s.remaining)
                       for s in sugg]
            done = [ItemCard(n, advisor.gd.item(n).loc, advisor.gd.item(n).cost, [], owned=True)
                    for n in advisor.done_in_phase(phase, [s.item for s in sugg]) if advisor.gd.item(n)]
            # lo comprado se queda en su fase con un tick (no desaparece); siempre caben al menos 3 pendientes
            keep = max(min(3, len(pending)), build_size - len(done))
            pending = pending[:keep]
            done = done[-(build_size - len(pending)):] if build_size > len(pending) else []
            v.phase_builds[phase] = done + pending
        owned = st.all_items
        for cards in v.phase_builds.values():
            for c in cards:
                c.plan = build_plan(advisor.gd, c.name, owned)
        cards = [c for c in v.phase_builds.get(v.phase, []) if not c.owned]
        v.next_item, v.build = (cards[0] if cards else None), cards[1:]
        nxt = advisor.follower.next_items(advisor.ever_owned, 1) if guide else []
        if nxt and advisor.gd.item(nxt[0]):
            # con guía, la siguiente compra es la de la guía (aunque por precio parezca de otra fase)
            it = advisor.gd.item(nxt[0])
            minute = dict(guide.core).get(nxt[0], 0)
            why = [f"tu guía: paso {v.guide.done + 1} de {v.guide.total}" +
                   (f" (en la partida original, minuto {minute:.0f})" if minute else "")]
            v.next_item = ItemCard(it.name, it.loc, it.cost, why, plan=build_plan(advisor.gd, it.name, owned))
            v.build = [c for c in cards if c.name != it.name]
        if v.next_item:
            v.buy_now = next_purchase(v.next_item.plan, st.gold)
        hm = meta.hero(hero) if meta is not None else None
        v.my_changes = list(hm.changes) if hm else []
    role = advisor.cfg.get("role", "auto")
    # en el orden de la barra superior (el de los atajos Ctrl+F1…F5)
    order = [h for h in (enemy_slots or []) if h] or list(advisor.enemies.values())
    seen_items = getattr(advisor, "enemy_items", {})
    v.enemies = [hero_card(h, meta, advisor.gd, hero, role, st.all_items, seen_items.get(h.id, ())) for h in order]
    for card in v.enemies:
        at = getattr(advisor, "enemy_items_at", {}).get(card.hero.id)
        card.items_ago = max(0, st.clock - at) if at is not None else None
    for i, card in enumerate(v.enemies):
        card.slot = (confirmed_slots or {}).get(card.hero.id)
        if ult_keys and enemy_slots:
            pos = next((j for j, h in enumerate(enemy_slots) if h and h.id == card.hero.id), None)
            card.hotkey = f"Ctrl+F{pos + 1}" if pos is not None else ""
        if ults is not None:
            ult = ults.ult_info_cached(card.hero) if hasattr(ults, "ult_info_cached") else None
            timer = ults.get(card.hero, st.clock)
            ult = timer.ult if timer else ult
            if ult:
                card.ult_name, card.ult_loc = ult.name, ult.loc
            if timer:
                card.ult_left = timer.remaining(st.clock)
    v.allies = [h for h in advisor.allies.values() if not hero or h.id != hero.id]
    return v
