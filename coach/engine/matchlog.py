"""Registro de tu partida y análisis al acabar (y el historial de tus partidas).

Durante la partida (cada ~2 s): oro, últimos golpes, nivel y posición; cada muerte (dónde y qué enemigos se veían
cerca); cuándo compras cada objeto importante. Al acabar: un informe con tus percentiles frente a tu héroe
(OpenDota), muertes por zona, las que llegaron sin ningún enemigo a la vista (ganks desde la niebla), últimos
golpes al minuto 10 y tiempos de objetos. Se guarda en %APPDATA%/DotaCoach/matches/ para el historial.
"""
import json
import logging
import math
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import config
from ..data.gamedata import GameData
from ..gsi import GameState
from .benchmarks import METRICS, describe, percentile
from .mapwatch import ZONE_LABELS, zone

log = logging.getLogger(__name__)

SAMPLE_EVERY = 2
MIN_REPORT_SECONDS = 5 * 60     # partidas más cortas no merecen informe
MAJOR_ITEM_COST = 1000          # objetos cuyo tiempo de compra interesa
NEAR = 2500


def matches_dir() -> Path:
    return config.APP_DIR / "matches"


@dataclass
class Death:
    clock: int
    zone: str
    x: int
    y: int
    enemies_near: list[str] = field(default_factory=list)   # héroes enemigos visibles cerca justo antes


@dataclass
class MatchReport:
    hero: str                       # nombre para mostrar
    hero_id: int
    team: str
    result: str                     # win | loss | unknown
    duration: int
    kills: int
    deaths: int
    assists: int
    last_hits: int
    gpm: int
    xpm: int
    lh_at_10: int | None
    items: list[tuple[str, int]]    # (nombre, segundo de compra)
    death_list: list[Death]
    percentiles: dict[str, float]
    notes: list[str]
    ai_notes: list[str] = field(default_factory=list)
    finished_at: float = 0.0

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "MatchReport":
        d = dict(d)
        d["death_list"] = [Death(**x) for x in d.get("death_list", [])]
        d["items"] = [tuple(x) for x in d.get("items", [])]
        return cls(**d)

    def summary(self) -> str:
        res = {"win": "Victoria", "loss": "Derrota"}.get(self.result, "Partida")
        return (f"{res} con {self.hero} · {self.duration // 60} min · {self.kills}/{self.deaths}/{self.assists} · "
                f"{self.gpm} oro/min")


class MatchLog:
    def __init__(self, gd: GameData):
        self.gd = gd
        self.reset()

    def reset(self):
        self.st: GameState | None = None
        self.last_sample = -999
        self.samples: list[tuple[int, int, int, int]] = []   # (reloj, oro neto aprox., últimos golpes, nivel)
        self.deaths: list[Death] = []
        self.items: dict[str, int] = {}
        self.lh_at_10: int | None = None
        self.last_alive_pos: tuple[int, int] | None = None
        self.near_before: list[str] = []
        self.prev_deaths = 0
        self.finished = False

    def update(self, st: GameState):
        if not st.in_game or self.finished:
            return
        if self.st is None:
            self.prev_deaths = st.deaths
        self.st = st
        me = next((u for u in st.units if u.me), None)
        if st.alive and me:
            self.last_alive_pos = (me.x, me.y)
            self.near_before = [u.name for u in st.units if u.enemy and math.hypot(u.x - me.x, u.y - me.y) < NEAR]
        if st.deaths > self.prev_deaths:
            x, y = self.last_alive_pos or (st.x or 0, st.y or 0)
            names = [self._name(n) for n in self.near_before]
            self.deaths.append(Death(st.clock, zone(x, y), x, y, names))
            self.prev_deaths = st.deaths
        for name in st.all_items:
            it = self.gd.item(name)
            if name not in self.items and it and (it.cost >= MAJOR_ITEM_COST or "boots" in name or "treads" in name):
                self.items[name] = max(0, st.clock)
        if self.lh_at_10 is None and st.clock >= 600:
            self.lh_at_10 = st.last_hits
        if st.clock - self.last_sample >= SAMPLE_EVERY:
            self.last_sample = st.clock
            self.samples.append((st.clock, st.gold, st.last_hits, st.level))

    def _name(self, unit: str) -> str:
        h = self.gd.hero(unit)
        return h.loc if h else unit.removeprefix("npc_dota_hero_")

    @property
    def worth_reporting(self) -> bool:
        return self.st is not None and self.st.clock >= MIN_REPORT_SECONDS and not self.finished

    def finish(self, bench: dict | None = None) -> MatchReport | None:
        st = self.st
        if not self.worth_reporting:
            return None
        self.finished = True
        hero = self.gd.hero(st.hero)
        minutes = max(1.0, st.clock / 60)
        result = "unknown" if not st.win_team else ("win" if st.win_team == st.team else "loss")
        pct = {}
        if bench:
            for metric, value in (("gold_per_min", st.gpm), ("xp_per_min", st.xpm),
                                  ("last_hits_per_min", st.last_hits / minutes)):
                p = percentile(value, bench.get(metric, []))
                if p is not None:
                    pct[metric] = p
        report = MatchReport(
            hero=hero.loc if hero else st.hero, hero_id=hero.id if hero else st.hero_id, team=st.team, result=result,
            duration=st.clock, kills=st.kills, deaths=st.deaths, assists=st.assists, last_hits=st.last_hits,
            gpm=st.gpm, xpm=st.xpm, lh_at_10=self.lh_at_10,
            items=[(self.gd.item(n).loc, t) for n, t in sorted(self.items.items(), key=lambda kv: kv[1])],
            death_list=self.deaths, percentiles=pct, notes=[], finished_at=time.time())
        report.notes = observations(report, bench)
        return report


def observations(r: MatchReport, bench: dict | None = None) -> list[str]:
    """Lo que más llama la atención de la partida, con reglas (la IA, si la hay, añade su resumen aparte)."""
    notes = []
    fog = [d for d in r.death_list if not d.enemies_near]
    if r.death_list:
        if len(fog) >= 2:
            notes.append(f"{len(fog)} de tus {len(r.death_list)} muertes llegaron sin ningún enemigo a la vista: "
                         "te pillaron desde la niebla. Mira más el minimapa y pide wards en tus zonas de farmeo.")
        zones = Counter(d.zone for d in r.death_list)
        z, n = zones.most_common(1)[0]
        if n >= 2 and z != "base":
            notes.append(f"Moriste {n} veces en {ZONE_LABELS.get(z, z)}: ahí te están esperando.")
        early = [d for d in r.death_list if d.clock < 10 * 60]
        if len(early) >= 3:
            notes.append(f"{len(early)} muertes antes del minuto 10: la fase de líneas se te hizo cuesta arriba.")
    if bench and r.lh_at_10 is not None:
        p = percentile(r.lh_at_10 / 10, bench.get("last_hits_per_min", []))
        if p is not None and p < 0.3:
            notes.append(f"{r.lh_at_10} últimos golpes al minuto 10 ({describe(p)} para {r.hero}): practica el farmeo "
                         "en línea.")
    for metric, p in r.percentiles.items():
        if p >= 0.8:
            notes.append(f"Buen {METRICS.get(metric, metric)}: {describe(p)} para {r.hero}.")
        elif p <= 0.2:
            label = METRICS.get(metric, metric)
            notes.append(f"{label[0].upper() + label[1:]} bajo: {describe(p)} para {r.hero}.")
    return notes


# ---------------- guardar / historial ----------------
def save(report: MatchReport) -> Path:
    folder = matches_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = time.strftime("%Y%m%d-%H%M%S", time.localtime(report.finished_at or time.time()))
    path = folder / f"{name}_{report.hero.replace(' ', '_').lower()}.json"
    path.write_text(json.dumps(report.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_reports(limit: int | None = None) -> list[MatchReport]:
    files = sorted(matches_dir().glob("*.json"), reverse=True)
    out = []
    for f in files[:limit] if limit else files:
        try:
            out.append(MatchReport.from_json(json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError, TypeError):
            log.warning("informe no válido: %s", f)
    return out


@dataclass
class History:
    games: int
    wins: int
    losses: int
    avg_deaths: float
    heroes: list[tuple[str, int, int]]   # (héroe, partidas, victorias)
    fog_death_share: float               # fracción de muertes sin enemigos a la vista
    top_death_zone: str
    recurring: list[str]                 # notas que se repiten en varias partidas


def history(reports: list[MatchReport]) -> History | None:
    if not reports:
        return None
    wins = sum(r.result == "win" for r in reports)
    losses = sum(r.result == "loss" for r in reports)
    by_hero: dict[str, list[MatchReport]] = {}
    for r in reports:
        by_hero.setdefault(r.hero, []).append(r)
    heroes = sorted(((h, len(rs), sum(x.result == "win" for x in rs)) for h, rs in by_hero.items()),
                    key=lambda t: t[1], reverse=True)
    deaths = [d for r in reports for d in r.death_list]
    zones = Counter(d.zone for d in deaths if d.zone != "base")
    kinds = Counter()
    for r in reports:
        if sum(1 for d in r.death_list if not d.enemies_near) >= 2:
            kinds["Te pillan desde la niebla (muertes sin enemigos a la vista)"] += 1
        if sum(1 for d in r.death_list if d.clock < 600) >= 3:
            kinds["Muchas muertes en la fase de líneas"] += 1
        if any("últimos golpes al minuto 10" in n for n in r.notes):
            kinds["Pocos últimos golpes al minuto 10"] += 1
    recurring = [k for k, n in kinds.most_common() if n >= max(2, len(reports) // 3)]
    return History(
        games=len(reports), wins=wins, losses=losses,
        avg_deaths=sum(r.deaths for r in reports) / len(reports), heroes=heroes,
        fog_death_share=(sum(1 for d in deaths if not d.enemies_near) / len(deaths)) if deaths else 0.0,
        top_death_zone=ZONE_LABELS.get(zones.most_common(1)[0][0], "") if zones else "",
        recurring=recurring)
