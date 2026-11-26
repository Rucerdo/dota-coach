"""Cuenta atrás de las definitivas enemigas ENCIMA del juego, justo debajo del retrato de cada enemigo en la barra
superior (solo los que has marcado con Ctrl+F1…F5).

Como las notificaciones: ventanitas sin bordes, siempre encima, que no reciben clics ni foco. Solo se ven con Dota
en primer plano (en "Ventana sin bordes") y solo bajo los retratos que la visión ha reconocido de verdad (si no, el
rótulo podría quedar bajo otro héroe).
"""
import ctypes
import tkinter as tk

from .toast import KEY, _click_through

COLORS = {"cd": ("#1B2B1E", "#7CE38B"), "maybe": ("#2E2614", "#FFD166"), "ready": ("#3A1716", "#FF6B6B")}
# Bajo el retrato el HUD pinta las barras de vida/maná (hasta ~52 px a 1080) y, si está muerto, el tiempo de
# reaparición (hasta ~65): el rótulo va justo debajo para no tapar nada (medido en una captura real a 1920x1080)
BAR_TOP = 67
BAR_HEIGHT = 16


def _fmt(s: int) -> str:
    return f"{s // 60}:{s % 60:02d}" if s >= 60 else f"{s}"


def badge_text(lo: int, hi: int) -> tuple[str, str]:
    """(texto, estado): 'cd' en enfriamiento, 'maybe' puede estar lista, 'ready' lista."""
    if hi <= 0:
        return "LISTA", "ready"
    if lo <= 0:
        return f"≤{_fmt(hi)}", "maybe"
    return (_fmt(lo) if lo == hi else f"{_fmt(lo)}-{_fmt(hi)}"), "cd"


def dota_in_front() -> bool:
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "Dota 2")
        return bool(hwnd) and user32.GetForegroundWindow() == hwnd
    except (AttributeError, OSError):
        return False


class Badge:
    def __init__(self, root: tk.Misc):
        self.win = tk.Toplevel(root)
        self.win.title("Dota Coach · definitiva")   # nunca "Dota 2" (se busca esa ventana por el título)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=KEY)
        try:
            self.win.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(self.win, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.win.withdraw()
        self.win.update_idletasks()
        _click_through(self.win)
        self.shown, self.last = False, None

    def show(self, box: tuple[int, int, int, int], text: str, state: str):
        x, y, w, h = box
        key = (box, text, state)
        if key != self.last:
            bg, fg = COLORS[state]
            c = self.canvas
            c.delete("all")
            c.configure(width=w, height=h)
            r = h // 2
            c.create_oval(0, 0, 2 * r, h, fill=bg, outline=fg)
            c.create_oval(w - 2 * r - 1, 0, w - 1, h, fill=bg, outline=fg)
            c.create_rectangle(r, 0, w - r - 1, h, fill=bg, outline="")
            c.create_line(r, 0, w - r - 1, 0, fill=fg)
            c.create_line(r, h - 1, w - r - 1, h - 1, fill=fg)
            c.create_text(w // 2, h // 2, text=text, fill=fg, font=("Segoe UI", max(8, int(h * 0.55)), "bold"))
            self.win.geometry(f"{w}x{h}+{x}+{y}")
            self.last = key
        if not self.shown:
            self.win.deiconify()
            self.win.attributes("-topmost", True)
            self.shown = True

    def hide(self):
        if self.shown:
            self.win.withdraw()
            self.shown = False

    def destroy(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class UltBadges:
    def __init__(self, root: tk.Misc, topbar_cfg: dict | None = None, enabled: bool = True,
                 client_rect=None, in_front=dota_in_front):
        from ..vision.topbar import DEFAULT_TOPBAR, dota_client_rect
        self.root, self.enabled = root, enabled
        self.cfg = {**DEFAULT_TOPBAR, **(topbar_cfg or {})}
        self.client_rect = client_rect or dota_client_rect
        self.in_front = in_front
        self.badges: dict[int, Badge] = {}       # player_id → rótulo

    def box(self, player_id: int, client) -> tuple[int, int, int, int]:
        from ..vision.topbar import tile_box
        x1, _, x2, _ = tile_box(player_id, client, self.cfg)
        s = client[3] / 1080.0
        return (x1 + int(3 * s), client[1] + int(BAR_TOP * s), max(20, x2 - x1 - int(6 * s)),
                max(14, int(BAR_HEIGHT * s)))

    def update(self, view):
        """view: MatchView. Pinta los rótulos de los enemigos marcados cuyo hueco se conoce."""
        wanted: dict[int, tuple[str, str]] = {}
        if self.enabled and view is not None and view.in_game and view.team in ("radiant", "dire"):
            first = 5 if view.team == "radiant" else 0
            for e in view.enemies:
                if e.ult_left is not None and e.slot is not None:
                    wanted[first + e.slot] = badge_text(*e.ult_left)
        client = self.client_rect() if wanted else None
        if not client or not self.in_front():
            for b in self.badges.values():
                b.hide()
            return
        for pid, (text, state) in wanted.items():
            badge = self.badges.get(pid) or self.badges.setdefault(pid, Badge(self.root))
            badge.show(self.box(pid, client), text, state)
        for pid, b in self.badges.items():
            if pid not in wanted:
                b.hide()

    def destroy(self):
        for b in self.badges.values():
            b.destroy()
        self.badges.clear()
