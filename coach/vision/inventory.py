"""Objetos de un enemigo al seleccionarlo (lo que se ve en el HUD de abajo al hacer clic en él).

Calibrado con capturas reales a 1920x1080 (HUD de 2026, el 26-11-2026):
  - casillas del inventario: la primera en (1141, 944), 62x45, separadas 66 (horizontal) y 47 (vertical); filas 0-1
    = inventario, fila 2 = mochila. Reconocidas con 0.79-0.95 y el segundo candidato muy por debajo; las vacías
    son casi lisas (desviación < 20).
  - barra de vida (760-860, 1022-1034): roja = enemigo seleccionado, verde = aliado o tú.
  - QUIÉN es: el NOMBRE encima del retrato (OCR de Windows, vision/ocr.py: LINA, ZEUS, SNIPER leídos bien). El
    retrato y las habilidades se mueven según lo largo que sea el HUD de cada héroe (el inventario no: mismo sitio
    con Lina y con Sniper), así que se lee una franja ancha. Plan B sin OCR: los iconos de habilidades en gris
    (4 casillas de 54 px desde (825, 945), cada 65.5; Lina 0.83 frente a 0.41), solo si el HUD es de ese largo.
De los enemigos NO se ve el enfriamiento (ni de habilidades ni de objetos).
Las posiciones van ancladas al centro de abajo de la pantalla y escalan con la altura.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

REF_W, REF_H = 1920, 1080
SLOT = dict(x=1141, y=944, dx=66, dy=47, w=62, h=45, rows=3, cols=3)
TP_BOX = (1342, 1031, 42, 31)
BAR_BOX = (760, 1022, 860, 1034)
ABILITY = dict(x=825, y=945, dx=65.5, size=54, count=4)
NAME_BOX = (380, 912, 1000, 948)        # franja del nombre (ancha: se mueve con el largo del HUD)
HUD_BOX = (380, 900, 1400, 1080)        # todo lo anterior cabe aquí (lo que se captura)
NAME_MIN = 0.8                          # parecido mínimo entre lo leído y el nombre del héroe

ITEM_REGION = 0.62          # parte de arriba del icono (abajo a la derecha van las cargas)
EMPTY_STD = 20
ITEM_MIN, ITEM_MARGIN = 0.70, 0.08
HERO_MIN, HERO_MARGIN = 0.60, 0.15


def scale_box(box: tuple[int, int, int, int], client: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Caja a 1920x1080 → coordenadas de pantalla (anclado al centro de abajo, escala por la altura)."""
    x0, y0, w, h = client
    s = h / REF_H
    cx = x0 + w / 2

    def X(v):
        return int(round(cx + (v - REF_W / 2) * s))

    def Y(v):
        return int(round(y0 + h - (REF_H - v) * s))
    return X(box[0]), Y(box[1]), X(box[2]), Y(box[3])


def _norm(a: np.ndarray) -> np.ndarray:
    a = a - a.mean()
    return a / (np.linalg.norm(a) + 1e-9)


def _on_black(path: Path) -> Image.Image | None:
    try:
        ic = Image.open(path).convert("RGBA")
    except OSError:
        return None
    bg = Image.new("RGBA", ic.size, (0, 0, 0, 255))
    bg.alpha_composite(ic)
    return bg.convert("RGB")


def item_vec(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.convert("RGB").resize((SLOT["w"], SLOT["h"]))).astype(float)
    return _norm(a[: int(SLOT["h"] * ITEM_REGION)])


def ability_vec(img: Image.Image) -> np.ndarray:
    s = ABILITY["size"]
    a = np.asarray(img.convert("L").resize((s, s))).astype(float)
    return _norm(a[4:-4, 4:-4])


@dataclass
class Selection:
    side: str                                   # enemy | ally | none
    hero_id: int | None = None
    hero_score: float = 0.0
    items: list[str | None] = field(default_factory=list)   # 9 casillas (None = vacía o dudosa)
    backpack_from: int = 6
    by_name: bool = False                       # identificado por el nombre (OCR) y no por las habilidades


class InventoryReader:
    def __init__(self, item_dir: Path, ability_dir: Path, ocr=None):
        """ocr(imagen) → [palabras] (por defecto, el OCR de Windows)."""
        self.item_dir, self.ability_dir = Path(item_dir), Path(ability_dir)
        if ocr is None:
            from . import ocr as winocr
            ocr = (lambda img: [w for w, _ in winocr.read_words(img)]) if winocr.available() else None
        self.ocr = ocr
        self.items: dict[str, np.ndarray] = {}
        self.heroes: dict[int, list[np.ndarray]] = {}

    def load_items(self, names: list[str]):
        """names: item_* (sus iconos ya descargados en item_dir)."""
        for n in names:
            short = n.removeprefix("item_")
            if n in self.items:
                continue
            img = _on_black(self.item_dir / f"{short}.png")
            if img is not None:
                self.items[n] = item_vec(img)

    def load_hero(self, hero_id: int, ability_names: list[str]):
        vecs = []
        for n in ability_names:
            img = _on_black(self.ability_dir / f"{n}.png")
            if img is not None:
                vecs.append(ability_vec(img))
        if vecs:
            self.heroes[hero_id] = vecs

    # ---------- lectura de una captura de HUD_BOX (ya recortada y a escala 1080) ----------
    @staticmethod
    def _crop(hud: Image.Image, x: float, y: float, w: float, h: float) -> Image.Image:
        ox, oy = HUD_BOX[0], HUD_BOX[1]
        return hud.crop((int(x - ox), int(y - oy), int(x - ox + w), int(y - oy + h)))

    def side(self, hud: Image.Image) -> str:
        r, g, b = np.asarray(self._crop(hud, BAR_BOX[0], BAR_BOX[1], BAR_BOX[2] - BAR_BOX[0],
                                        BAR_BOX[3] - BAR_BOX[1]).convert("RGB")).reshape(-1, 3).mean(axis=0)
        if r > 100 and r > 1.6 * g:
            return "enemy"
        if g > 100 and g > 1.4 * r:
            return "ally"
        return "none"

    def hero(self, hud: Image.Image, candidates: list[int]) -> tuple[int | None, float]:
        slots = [ability_vec(self._crop(hud, ABILITY["x"] + i * ABILITY["dx"], ABILITY["y"], ABILITY["size"],
                                        ABILITY["size"])) for i in range(ABILITY["count"])]
        scores = []
        for hid in candidates:
            vecs = self.heroes.get(hid)
            if vecs:
                scores.append((float(np.mean([max(float((s * v).sum()) for v in vecs) for s in slots])), hid))
        scores.sort(reverse=True)
        if not scores:
            return None, 0.0
        best, hid = scores[0]
        second = scores[1][0] if len(scores) > 1 else 0.0
        return (hid, best) if best >= HERO_MIN and best - second >= HERO_MARGIN else (None, best)

    def read_items(self, hud: Image.Image) -> list[str | None]:
        out = []
        for r in range(SLOT["rows"]):
            for c in range(SLOT["cols"]):
                crop = self._crop(hud, SLOT["x"] + c * SLOT["dx"], SLOT["y"] + r * SLOT["dy"], SLOT["w"], SLOT["h"])
                if np.asarray(crop.convert("L")).std() < EMPTY_STD:
                    out.append(None)
                    continue
                v = item_vec(crop)
                scores = sorted(((float((v * t).sum()), n) for n, t in self.items.items()), reverse=True)[:2]
                if scores and scores[0][0] >= ITEM_MIN and \
                        scores[0][0] - (scores[1][0] if len(scores) > 1 else 0) >= ITEM_MARGIN:
                    out.append(scores[0][1])
                else:
                    out.append(None)
        return out

    def name(self, hud: Image.Image, enemies: list, everyone: list = ()) -> tuple[object | None, float]:
        """El héroe por su nombre: primero entre los enemigos conocidos y, si no, entre todos (enemigo nuevo)."""
        if self.ocr is None:
            return None, 0.0
        from .ocr import match_hero
        words = self.ocr(self._crop(hud, NAME_BOX[0], NAME_BOX[1], NAME_BOX[2] - NAME_BOX[0],
                                    NAME_BOX[3] - NAME_BOX[1]))
        hero, score = match_hero(words, enemies)
        if hero is not None and score >= NAME_MIN:
            return hero, score
        hero, score = match_hero(words, everyone)
        return (hero, score) if hero is not None and score >= 0.9 else (None, score)

    def read(self, hud: Image.Image, enemies: list, everyone: list = ()) -> Selection:
        """hud: recorte de HUD_BOX a escala 1080. enemies/everyone: héroes (Hero)."""
        side = self.side(hud)
        if side != "enemy":
            return Selection(side)
        hero, score = self.name(hud, enemies, everyone)
        if hero is not None:
            return Selection("enemy", hero.id, score, self.read_items(hud), by_name=True)
        hid, score = self.hero(hud, [h.id for h in enemies])
        if hid is None:
            return Selection("enemy", None, score)
        return Selection("enemy", hid, score, self.read_items(hud))


def hud_from_image(img: Image.Image) -> Image.Image:
    """De una captura completa de Dota (cualquier resolución) al recorte HUD_BOX a escala 1080."""
    box = scale_box(HUD_BOX, (0, 0, img.width, img.height))
    crop = img.crop(box)
    size = (HUD_BOX[2] - HUD_BOX[0], HUD_BOX[3] - HUD_BOX[1])
    return crop if crop.size == size else crop.resize(size)


def capture_hud() -> Image.Image | None:
    from .topbar import dota_client_rect
    from .wincap import dota_in_front, screen_grab
    client = dota_client_rect()
    if not client or not dota_in_front():
        return None   # solo con Dota delante (lo que ves tú)
    box = scale_box(HUD_BOX, client)
    img = screen_grab(box)
    if img is None:
        return None
    size = (HUD_BOX[2] - HUD_BOX[0], HUD_BOX[3] - HUD_BOX[1])
    return img if img.size == size else img.resize(size)


__all__ = ["InventoryReader", "Selection", "capture_hud", "hud_from_image", "scale_box"]
