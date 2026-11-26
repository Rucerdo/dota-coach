"""Reconoce los héroes de la barra superior del HUD comparándolos con los retratos oficiales (experimental).

La barra muestra los 10 retratos en orden de jugador: Radiant 0-4 a la izquierda del reloj y Dire 5-9
a la derecha. Las medidas (a 1080 px de alto, relativas al centro) son las del traductor y se pueden
ajustar con la clave 'topbar' de la configuración.

Comparación: cada recorte y cada retrato se reducen a 32x20, se normalizan por canal y se comparan con
correlación (NCC). Se acepta el mejor si supera un umbral y saca margen al segundo, y solo cuando sale
igual en dos lecturas seguidas (evita falsos positivos con menús, muertes o la tienda abierta).

Cosméticos (arcanas, personas): cambian el retrato de la barra y el CDN de Valve solo tiene el retrato
por defecto. Por eso cada héroe puede tener varias plantillas:
  - oficiales: cache/hero_img/<héroe>.png
  - aprendidas: cache/hero_img_learned/<héroe>/*.png (recortes reales del HUD)
Se aprenden solas por descarte: si en un bando queda UN hueco sin reconocer y UN héroe conocido de ese
bando sin asignar (minimapa, escrito a mano o tu propio héroe por GSI), ese recorte es de ese héroe.
Los recortes que no se reconocen se guardan en cache/hero_img_unknown/ para etiquetarlos a mano
(`coach vision label <archivo> <héroe>`). Ante la duda, el héroe queda como desconocido: nunca se adivina.
"""
import ctypes
import ctypes.wintypes as wt
import logging
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageGrab, ImageStat

from .. import config
from ..data.cache import download_file
from ..data.gamedata import CDN, GameData, Hero

log = logging.getLogger(__name__)
user32 = ctypes.windll.user32

# Retrato completo de cada hueco a 1080 px de alto (calibrado buscando la máxima correlación en capturas
# reales a 1920x1080, HUD de 2026): ~66x35 px, la imagen oficial entera. Es más ancho que la separación
# entre huecos porque los bordes inclinados tapan parte de cada retrato.
DEFAULT_TOPBAR = {
    "radiant_first_center": -383,
    "dire_first_center": 135,
    "pitch": 62.1,
    "half_width": 33,
    "top": 4,
    "bottom": 39,
}
# Barra superior de la SELECCIÓN DE HÉROES (fase de estrategia): retratos el doble de grandes y en otra posición;
# como en partida, Radiant a la izquierda y Dire a la derecha. Calibrado con una captura real a 1920x1080
# (10/10 reconocidos, 0.92-0.97).
DRAFT_TOPBAR = {
    "radiant_first_center": -692,
    "dire_first_center": 194,
    "pitch": 124.2,
    "half_width": 59,
    "top": 8,
    "bottom": 68,
}

# Parte del retrato que se compara, en fracciones (izq, arriba, der, abajo): la franja de arriba, con la cara.
# Abajo el HUD pinta encima la insignia de rango (en una esquina) y el rombo verde (en el centro), y los
# bordes laterales van inclinados y muestran el retrato vecino. Se aplica igual al recorte y a la plantilla.
COMPARE_REGION = (0.08, 0.03, 0.92, 0.58)
SIZE = (32, 14)
GRAY_SATURATION = 40  # por debajo, el retrato está en gris (héroe muerto): se compara en escala de grises
# Capturas reales (1080p): aciertos 0.79-0.96 con margen >= 0.35; dudosos con margen 0.01-0.03.
MIN_SCORE = 0.60
MIN_MARGIN = 0.10


# ---------- captura ----------
def dota_client_rect() -> tuple[int, int, int, int] | None:
    hwnd = user32.FindWindowW(None, "Dota 2")
    if not hwnd:
        return None
    rect = wt.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    return (pt.x, pt.y, w, h) if h >= 400 else None


def tile_box(player_id: int, client: tuple[int, int, int, int], cfg: dict) -> tuple[int, int, int, int]:
    x0, y0, w, h = client
    s = h / 1080.0
    if player_id < 5:
        cx = cfg["radiant_first_center"] + cfg["pitch"] * player_id
    else:
        cx = cfg["dire_first_center"] + cfg["pitch"] * (player_id - 5)
    cx = x0 + w / 2 + cx * s
    hw = cfg["half_width"] * s
    return int(cx - hw), int(y0 + cfg["top"] * s), int(cx + hw), int(y0 + cfg["bottom"] * s)


def looks_valid(img: Image.Image) -> bool:
    stat = ImageStat.Stat(img.convert("L"))
    return stat.mean[0] > 18 and stat.stddev[0] > 14


def tiles_from_image(img: Image.Image, cfg: dict | None = None) -> dict[int, Image.Image]:
    """Los 10 recortes de una captura completa de la ventana de Dota (p. ej. una captura F12 de Steam)."""
    cfg = {**DEFAULT_TOPBAR, **(cfg or {})}
    client = (0, 0, img.width, img.height)
    return {pid: img.crop(tile_box(pid, client, cfg)) for pid in range(10)}


def capture_tiles(cfg: dict | None = None) -> dict[int, Image.Image]:
    client = dota_client_rect()
    if not client:
        return {}
    cfg = {**DEFAULT_TOPBAR, **(cfg or {})}
    boxes = {pid: tile_box(pid, client, cfg) for pid in range(10)}
    left = min(b[0] for b in boxes.values())
    top = min(b[1] for b in boxes.values())
    right = max(b[2] for b in boxes.values())
    bottom = max(b[3] for b in boxes.values())
    from .wincap import grab_dota
    strip = grab_dota((left, top, right, bottom), client)   # de la ventana de Dota (aunque algo la tape)
    if strip is None:
        return {}
    return {pid: strip.crop((b[0] - left, b[1] - top, b[2] - left, b[3] - top)) for pid, b in boxes.items()}


# ---------- comparación ----------
def _region(img: Image.Image, region: tuple[float, float, float, float]) -> Image.Image:
    w, h = img.size
    l, t, r, b = region
    return img.convert("RGB").crop((round(l * w), round(t * h), round(r * w), round(b * h)))


def _normalize(a: np.ndarray) -> np.ndarray:
    a = (a - a.mean(axis=0)) / (a.std(axis=0) + 1e-6)
    v = a.reshape(-1)
    return v / (np.linalg.norm(v) + 1e-6)


def _vector(img: Image.Image, region=COMPARE_REGION) -> np.ndarray:
    """Retrato completo (plantilla o recorte del HUD) → vector de color normalizado por canal (NCC)."""
    small = _region(img, region).resize(SIZE, Image.BILINEAR)
    return _normalize(np.asarray(small, dtype=np.float32).reshape(-1, 3))


def _gray_vector(img: Image.Image, region=COMPARE_REGION) -> np.ndarray:
    small = _region(img, region).convert("L").resize(SIZE, Image.BILINEAR)
    return _normalize(np.asarray(small, dtype=np.float32).reshape(-1, 1))


def is_gray(img: Image.Image) -> bool:
    """Retrato desaturado: el HUD pinta así a los héroes muertos."""
    return ImageStat.Stat(_region(img, COMPARE_REGION).convert("HSV")).mean[1] < GRAY_SATURATION


def official_dir() -> Path:
    return config.CACHE_DIR / "hero_img"


def learned_dir() -> Path:
    return config.CACHE_DIR / "hero_img_learned"


def unknown_dir() -> Path:
    return config.CACHE_DIR / "hero_img_unknown"


class HeroMatcher:
    """Varias plantillas por héroe (oficial + aprendidas). 'ids[i]' es el héroe de la fila i de la matriz."""

    def __init__(self, gd: GameData, region: tuple[float, float, float, float] = COMPARE_REGION):
        self.gd, self.region = gd, region
        self.ids: list[int] = []
        self.matrix: np.ndarray | None = None
        self.gray: np.ndarray | None = None  # las mismas plantillas en escala de grises
        self._lock = threading.Lock()

    def _vectors(self, img: Image.Image) -> tuple[np.ndarray, np.ndarray]:
        """(color, gris). Una plantilla en gris (recorte de un muerto) solo vale para comparar con grises:
        su vector de color se anula para que no puntúe contra retratos en color."""
        vec, gvec = _vector(img, self.region), _gray_vector(img, self.region)
        return (np.zeros_like(vec) if is_gray(img) else vec), gvec

    def load(self, download: bool = True) -> int:
        """Retratos oficiales (se descargan una vez) + plantillas aprendidas."""
        vecs, grays, ids = [], [], []
        for h in self.gd.heroes.values():
            path = official_dir() / f"{h.short}.png"
            if download and h.img:
                path = download_file(CDN + h.img.split("?")[0], path) or path
            paths = [path] + sorted((learned_dir() / h.short).glob("*.png"))
            for p in paths:
                if not p.exists():
                    continue
                try:
                    vec, gvec = self._vectors(Image.open(p))
                    vecs.append(vec)
                    grays.append(gvec)
                    ids.append(h.id)
                except OSError:
                    continue
        with self._lock:
            self.ids = ids
            self.matrix = np.stack(vecs) if vecs else None
            self.gray = np.stack(grays) if grays else None
        log.info("plantillas de retratos: %d (%d héroes)", len(ids), len(set(ids)))
        return len(ids)

    def learn(self, hero: Hero, tile: Image.Image) -> Path | None:
        """Guarda un recorte real del HUD como plantilla del héroe (p. ej. con su arcana)."""
        if not looks_valid(tile):
            return None
        vec, gvec = self._vectors(tile)
        gray = is_gray(tile)
        with self._lock:
            known = self.gray if gray else self.matrix
            if known is not None:
                rows = [i for i, hid in enumerate(self.ids) if hid == hero.id]
                if rows and float(np.max(known[rows] @ (gvec if gray else vec))) > 0.92:
                    return None  # ya hay una plantilla casi idéntica
            folder = learned_dir() / hero.short
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{int(time.time() * 1000)}.png"
            tile.convert("RGB").save(path)
            self.ids.append(hero.id)
            self.matrix = vec[None, :] if self.matrix is None else np.vstack([self.matrix, vec])
            self.gray = gvec[None, :] if self.gray is None else np.vstack([self.gray, gvec])
        log.info("plantilla aprendida para %s: %s", hero.loc, path.name)
        return path

    def ranked(self, tile: Image.Image) -> list[tuple[int, float]]:
        """[(hero_id, mejor puntuación de sus plantillas)] de mayor a menor; vacío si el recorte no vale."""
        gray = is_gray(tile)
        with self._lock:
            matrix, ids = (self.gray if gray else self.matrix), list(self.ids)
        if matrix is None or not looks_valid(tile):
            return []
        scores = matrix @ (_gray_vector if gray else _vector)(tile, self.region)
        best_per_hero: dict[int, float] = {}
        for hid, s in zip(ids, scores):
            if s > best_per_hero.get(hid, -2.0):
                best_per_hero[hid] = float(s)
        return sorted(best_per_hero.items(), key=lambda kv: kv[1], reverse=True)

    def match(self, tile: Image.Image) -> tuple[Hero | None, float, float]:
        """(héroe, puntuación, margen sobre el mejor OTRO héroe)."""
        ranked = self.ranked(tile)
        if not ranked:
            return None, 0.0, 0.0
        best_id, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        if best < MIN_SCORE or best - second < MIN_MARGIN:
            return None, best, best - second
        return self.gd.heroes.get(best_id), best, best - second


SIDES = {"radiant": range(0, 5), "dire": range(5, 10)}


class TopbarScanner:
    """Cada 'interval' segundos lee la barra superior y avisa de los héroes confirmados (2 lecturas iguales).

    known_heroes(side) → héroes que se sabe que están en ese bando por otras vías (minimapa, a mano, GSI):
    se usan para aprender por descarte los retratos que no se reconocen (arcanas, personas)."""

    def __init__(self, matcher: HeroMatcher, on_heroes: Callable[[dict[int, Hero]], None],
                 topbar_cfg: dict | None = None, interval: float = 8.0,
                 known_heroes: Callable[[str], list[Hero]] = lambda side: []):
        self.matcher, self.on_heroes, self.cfg, self.interval = matcher, on_heroes, topbar_cfg, interval
        self.known_heroes = known_heroes
        self.confirmed: dict[int, Hero] = {}
        self.tiles: dict[int, Image.Image] = {}
        self._last: dict[int, int] = {}
        self._saved_unknown: set[int] = set()
        self._unmatched: set[int] = set()
        self._stop = threading.Event()
        self.active = threading.Event()  # solo se escanea durante una partida o la selección de héroes
        self.mode = "game"               # game | draft (otra disposición de la barra: ver DRAFT_TOPBAR)

    def process(self, tiles: dict[int, Image.Image]) -> dict[int, Hero]:
        """Procesa una lectura de los 10 recortes. Devuelve los héroes confirmados nuevos por slot."""
        self.tiles = tiles
        self._unmatched = set()
        new = {}
        for pid, tile in tiles.items():
            hero, _, _ = self.matcher.match(tile)
            if not hero:
                self._last.pop(pid, None)
                self._unmatched.add(pid)
                continue
            if self._last.get(pid) == hero.id and self.confirmed.get(pid) != hero:
                self.confirmed[pid] = hero
                new[pid] = hero
            self._last[pid] = hero.id
        new.update(self.resolve_by_elimination())
        self._save_unknown()
        return new

    def resolve_by_elimination(self) -> dict[int, Hero]:
        """Un hueco sin reconocer + un héroe conocido sin asignar en el mismo bando → es ese, y se aprende."""
        new = {}
        for side, slots in SIDES.items():
            open_slots = [p for p in slots if p not in self.confirmed and p in self.tiles
                          and looks_valid(self.tiles[p])]
            assigned = {self.confirmed[p].id for p in slots if p in self.confirmed}
            pending = {h.id: h for h in self.known_heroes(side) if h.id not in assigned}
            if len(open_slots) == 1 and len(pending) == 1:
                pid, hero = open_slots[0], next(iter(pending.values()))
                self.confirmed[pid] = hero
                new[pid] = hero
                self.matcher.learn(hero, self.tiles[pid])
        return new

    def _save_unknown(self):
        """Guarda una vez por partida cada retrato no reconocido, para etiquetarlo después."""
        for pid in self._unmatched:
            tile = self.tiles.get(pid)
            if tile is None or pid in self.confirmed or pid in self._saved_unknown or not looks_valid(tile):
                continue
            unknown_dir().mkdir(parents=True, exist_ok=True)
            tile.convert("RGB").save(unknown_dir() / f"{int(time.time())}_slot{pid}.png")
            self._saved_unknown.add(pid)

    def set_mode(self, mode: str):
        """Cambia entre la barra de partida y la de la selección. Lo confirmado se olvida: son recortes de otra
        pantalla y conviene volver a confirmarlos."""
        if mode != self.mode:
            self.mode = mode
            self.reset()

    def layout(self) -> dict | None:
        return {**DRAFT_TOPBAR, **(self.cfg or {}).get("draft", {})} if self.mode == "draft" else self.cfg

    def scan_once(self) -> dict[int, Hero]:
        tiles = capture_tiles(self.layout())
        return self.process(tiles) if tiles else {}

    def reset(self):
        self.confirmed.clear()
        self._last.clear()
        self.tiles = {}
        self._saved_unknown.clear()

    def run(self):
        while not self._stop.is_set():
            if self.active.is_set():
                try:
                    new = self.scan_once()
                    if new:
                        self.on_heroes(dict(self.confirmed))
                except Exception:
                    log.exception("error leyendo la barra superior")
            self._stop.wait(self.interval if self.mode == "game" else min(self.interval, 3.0))

    def start(self):
        if self.matcher.matrix is None:
            self.matcher.load()
        threading.Thread(target=self.run, daemon=True).start()

    def stop(self):
        self._stop.set()


def label_tile(path: Path, hero: Hero) -> Path:
    """Etiqueta a mano un recorte guardado (p. ej. de hero_img_unknown) como plantilla de 'hero'."""
    dest = learned_dir() / hero.short / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.open(path).convert("RGB").save(dest)
    if path.parent == unknown_dir():
        path.unlink(missing_ok=True)
    return dest


def diagnose(matcher: "HeroMatcher", img: Image.Image, cfg: dict | None = None,
             expect: list[Hero | None] | None = None) -> list[dict]:
    """Analiza una captura guardada: por cada hueco, los 3 mejores candidatos, si se aceptaría y si acierta."""
    rows = []
    for pid, tile in tiles_from_image(img, cfg).items():
        ranked = matcher.ranked(tile)
        hero, score, margin = matcher.match(tile)
        want = expect[pid] if expect and pid < len(expect) else None
        want_rank = next((i for i, (hid, _) in enumerate(ranked) if want and hid == want.id), None)
        rows.append({
            "slot": pid, "valid": looks_valid(tile), "hero": hero, "score": score, "margin": margin,
            "top": [(matcher.gd.heroes.get(hid), sc) for hid, sc in ranked[:3]],
            "expected": want, "expected_rank": want_rank,
            "expected_score": ranked[want_rank][1] if want_rank is not None else None,
            "ok": None if want is None else (hero is not None and hero.id == want.id),
        })
    return rows


def strip_image(tiles: dict[int, Image.Image]) -> Image.Image:
    """Los 10 recortes uno al lado del otro, con un hueco entre bandos."""
    w, h = tiles[0].size
    out = Image.new("RGB", (w * 10 + 45, h), "black")
    for pid, t in tiles.items():
        out.paste(t.resize((w, h)), (pid * w + (45 if pid >= 5 else 0), 0))
    return out


def save_debug_strip(path: Path, cfg: dict | None = None) -> Path | None:
    """Guarda los 10 recortes de la pantalla actual (para comprobar la calibración)."""
    tiles = capture_tiles(cfg)
    if not tiles:
        return None
    strip_image(tiles).save(path)
    return path


__all__ = ["HeroMatcher", "TopbarScanner", "capture_tiles", "diagnose", "save_debug_strip", "tiles_from_image"]
