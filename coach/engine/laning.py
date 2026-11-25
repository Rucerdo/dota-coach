"""Tu línea en directo: quién va contigo, contra quién y cómo enfrentarlos.

- Rivales y compañero: el reparto de líneas del mapa (engine/mapwatch).
- Cómo suele salir la línea contra cada rival: STRATZ laneOutcome (tu héroe contra él).
- Cómo os va juntos a ti y a tu compañero: winrate de la pareja (STRATZ/OpenDota synergy).
- Si el rival está a la vista o cuánto lleva sin verse: posiciones de GSI (solo lo que muestra tu minimapa).
- Un consejo por rival según su perfil (hero_traits.json) y, con IA, consejos para esa línea concreta.
"""
from dataclasses import dataclass, field

from ..data.gamedata import GameData, Hero
from .counters import TRAITS

# rasgo del rival → consejo para la fase de líneas (el primero que aplique, por importancia)
LANE_TIPS = [
    ("invis", "Se hace invisible: lleva Dust o pide un Sentry y retrocede si desaparece."),
    ("targeted_ult", "Su definitiva va a un objetivo: desde su nivel 6, no te quedes solo con poca vida."),
    ("magic_burst", "Mucho daño mágico de golpe: no te quedes con poca vida a su alcance; Magic Stick y "
                    "Infused Raindrops ayudan."),
    ("disables", "Tiene control: quedaos cerca el uno del otro para cubriros y llevad TP para salvar al otro."),
    ("physical_burst", "Pega fuerte con ataques: no intercambies golpes a lo loco; armadura (Ring of Protection) "
                       "y regeneración."),
    ("heal", "Se cura: juntad el daño en el mismo momento; Urn o anticuración si se alarga."),
    ("escape", "Escurridizo: guardad el control para cuando use su escape."),
    ("illusions", "Ilusiones: localiza al real antes de gastar hechizos."),
    ("summons", "Invocaciones: matadlas o negadlas, dan mucho oro y experiencia."),
    ("evasion", "Evasión: no fíes el intercambio a tus ataques; usa hechizos."),
    ("tanky", "Muy resistente: no forcéis el asesinato pronto, ganad la línea a base de farmeo."),
    ("mana_burn", "Quema maná: no gastes todo tu maná pronto; Clarity o Soul Ring si hace falta."),
    ("buffs", "Usa mejoras que se pueden disipar: guarda tu disipación para cuando las active."),
]


@dataclass
class Opponent:
    hero: Hero
    outcome: tuple[float, float, float, int] | None = None   # contra ti: (ganas, igualada, pierdes, partidas)
    seen_ago: int | None = None                                # segundos sin verse (None = no se sabe)
    visible: bool = False
    tip: str = ""


@dataclass
class LaneReport:
    lane: str
    me: Hero
    partners: list[Hero] = field(default_factory=list)
    opponents: list[Opponent] = field(default_factory=list)
    partner_wr: dict[str, tuple[float, int]] = field(default_factory=dict)   # compañero → (winrate juntos, partidas)
    ai_tips: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple:
        return self.lane, self.me.id, tuple(sorted(h.id for h in self.partners)), \
            tuple(sorted(o.hero.id for o in self.opponents))


def lane_tip(hero: Hero) -> str:
    traits = set(TRAITS.get(hero.loc, []))
    return next((tip for trait, tip in LANE_TIPS if trait in traits), "")


def build_report(gd: GameData, mapwatch, me: Hero, clock: int, details: dict | None = None,
                 synergy_rows: list[dict] | None = None) -> LaneReport | None:
    """None si todavía no se sabe en qué línea vas."""
    lane = mapwatch.my_lane() if mapwatch else None
    if not lane or me is None:
        return None
    info = mapwatch.lanes()[lane]
    rep = LaneReport(lane, me, partners=[h for h in info.allies if h.id != me.id])
    lanes = (details or {}).get("lanes") or {}
    for h in info.enemies:
        o = Opponent(h, tip=lane_tip(h))
        row = lanes.get(h.id)
        if row and sum(row[1:]) >= 30:
            total = sum(row[1:])
            o.outcome = (row[1] / total, row[2] / total, row[3] / total, row[0])
        seen = mapwatch.last_seen.get(h.name)
        if seen:
            o.seen_ago = max(0, clock - seen[0])
            o.visible = o.seen_ago <= 2
        rep.opponents.append(o)
    by_id = {int(r["hero_id"]): r for r in synergy_rows or []}
    for p in rep.partners:
        r = by_id.get(p.id)
        if r and r.get("games", 0) >= 20:
            rep.partner_wr[p.loc] = (r["wins"] / r["games"], r["games"])
    return rep


def lane_context(rep: LaneReport, gd: GameData) -> str:
    """Texto para pedir a la IA consejos de esa línea."""
    lines = [f"Lane: {rep.lane}. Me: {rep.me.loc}. "
             f"Lane partner(s): {', '.join(h.loc for h in rep.partners) or 'none (solo lane)'}."]
    for o in rep.opponents:
        traits = ", ".join(TRAITS.get(o.hero.loc, []))
        res = (f"lane outcome vs me: win {o.outcome[0]:.0%}, draw {o.outcome[1]:.0%}, lose {o.outcome[2]:.0%}"
               if o.outcome else "no lane data")
        lines.append(f"Opponent {o.hero.loc} (traits: {traits or '?'}; {res})")
    for name, (wr, games) in rep.partner_wr.items():
        lines.append(f"Me + {name} win together {wr:.0%} ({games} games)")
    return "\n".join(lines)
