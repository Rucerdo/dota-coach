"""Captura de la ventana de Dota, no de la pantalla.

Con Dota delante se copia la pantalla (rápido y fiable). Si hay algo encima (el menú de inicio, otra ventana...),
se pide la imagen a la propia ventana de Dota con PrintWindow (PW_RENDERFULLCONTENT, Windows 8.1+). Si Windows
devuelve una imagen negra (algunos modos de pantalla de DirectX), se devuelve None: mejor no mostrar nada nuevo que
mostrar lo que tapa a Dota.
"""
import ctypes
import ctypes.wintypes as wt
import logging

from PIL import Image, ImageGrab

log = logging.getLogger(__name__)

PW_CLIENTONLY, PW_RENDERFULLCONTENT = 0x1, 0x2
SRCCOPY, DIB_RGB_COLORS = 0x00CC0020, 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


def _user32():
    return ctypes.windll.user32


def dota_hwnd() -> int:
    try:
        return _user32().FindWindowW(None, "Dota 2") or 0
    except (AttributeError, OSError):
        return 0


def dota_in_front(hwnd: int | None = None) -> bool:
    hwnd = hwnd or dota_hwnd()
    try:
        return bool(hwnd) and _user32().GetForegroundWindow() == hwnd
    except (AttributeError, OSError):
        return False


def print_window(hwnd: int) -> Image.Image | None:
    """La zona de cliente de la ventana, pintada por la propia ventana (aunque esté tapada)."""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    rect = wt.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    hdc = user32.GetDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        if not user32.PrintWindow(hwnd, mem, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            return None
        info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)  # -h: de arriba abajo
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), DIB_RGB_COLORS):
            return None
        return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)


def screen_grab(box: tuple[int, int, int, int]) -> Image.Image | None:
    """Solo esa zona de la pantalla (BitBlt): ~8 ms para el minimapa, frente a ~55 ms de ImageGrab con todos los
    monitores (copia el escritorio entero y luego recorta)."""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    x, y, w, h = box[0], box[1], box[2] - box[0], box[3] - box[1]
    if w <= 0 or h <= 0:
        return None
    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        if not gdi32.BitBlt(mem, 0, 0, w, h, hdc, x, y, SRCCOPY):
            return None
        info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), DIB_RGB_COLORS):
            return None
        return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(0, hdc)


def is_blank(img: Image.Image) -> bool:
    lo, hi = img.convert("L").getextrema()
    return hi < 12


def grab_dota(box: tuple[int, int, int, int], client: tuple[int, int, int, int]) -> Image.Image | None:
    """box: zona en coordenadas de pantalla; client: (x, y, ancho, alto) de la ventana de Dota en pantalla."""
    hwnd = dota_hwnd()
    if not hwnd:
        return None
    try:
        if dota_in_front(hwnd):
            return screen_grab(box) or ImageGrab.grab(box, all_screens=True)
        full = print_window(hwnd)
    except OSError:
        log.exception("no se pudo capturar Dota")
        return None
    if full is None:
        return None
    x0, y0 = client[0], client[1]
    crop = full.crop((box[0] - x0, box[1] - y0, box[2] - x0, box[3] - y0))
    return None if is_blank(crop) else crop
