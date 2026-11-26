"""Copia en directo del minimapa para el panel de partida (lo mismo que ves en pantalla, más grande y en el
monitor externo).

Posición medida en capturas reales a 1920x1080 con el HUD por defecto (minimapa a la izquierda, tamaño
normal): esquina superior izquierda en (10, 843) y 228 px de lado. Escala con la altura de la ventana. Con
otro tamaño de minimapa o con el minimapa a la derecha se ajusta con la clave 'minimap' de la configuración
(mismas claves que DEFAULT_MINIMAP) y se comprueba con `coach vision minimap <captura>`.
"""
import logging
import threading
from typing import Callable

from PIL import Image

from .topbar import dota_client_rect

log = logging.getLogger(__name__)

DEFAULT_MINIMAP = {
    "left": 10,        # px desde el borde izquierdo (a 1080 de alto)
    "bottom": 8,       # px desde el borde inferior hasta el lado de abajo del mapa
    "size": 228,       # lado del mapa
    "right_side": False,  # minimapa a la derecha (opción del HUD)
}


def minimap_box(client: tuple[int, int, int, int], cfg: dict | None = None) -> tuple[int, int, int, int]:
    cfg = {**DEFAULT_MINIMAP, **(cfg or {})}
    x0, y0, w, h = client
    s = h / 1080.0
    size = cfg["size"] * s
    left = x0 + w - cfg["left"] * s - size if cfg["right_side"] else x0 + cfg["left"] * s
    bottom = y0 + h - cfg["bottom"] * s
    return int(left), int(bottom - size), int(left + size), int(bottom)


def minimap_from_image(img: Image.Image, cfg: dict | None = None) -> Image.Image:
    """El minimapa de una captura completa de la ventana de Dota."""
    return img.crop(minimap_box((0, 0, img.width, img.height), cfg))


def capture_minimap(cfg: dict | None = None) -> Image.Image | None:
    client = dota_client_rect()
    if not client:
        return None
    from .wincap import grab_dota
    return grab_dota(minimap_box(client, cfg), client)   # de la ventana de Dota: no lo que haya encima


class MinimapFeed:
    """Captura el minimapa cada 'interval' segundos mientras 'active' está puesto y se lo pasa a on_frame."""

    def __init__(self, on_frame: Callable[[Image.Image], None], cfg: dict | None = None, interval: float = 0.1):
        self.on_frame, self.cfg, self.interval = on_frame, cfg, interval
        self.active = threading.Event()
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            if self.active.is_set():
                frame = capture_minimap(self.cfg)
                if frame is not None:
                    try:
                        self.on_frame(frame)
                    except Exception:
                        log.exception("error con el fotograma del minimapa")
            from .wincap import dota_in_front
            # con Dota delante la copia cuesta ~8 ms (10 por segundo por defecto); si está tapado se lee la ventana
            # entera de Dota (~45 ms): entonces solo 4 por segundo
            self._stop.wait(self.interval if dota_in_front() else max(self.interval, 0.25))

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def stop(self):
        self._stop.set()
