"""Overlay transparente sobre el juego (siempre encima, deja pasar los clics). Basado en el del traductor.
Requiere Dota en 'Ventana sin bordes'."""
import ctypes
import queue
import time
import tkinter as tk
import tkinter.font as tkfont

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TOPMOST = (
    0x80000, 0x20, 0x80, 0x08000000, 0x8)
HWND_TOPMOST, SWP_FLAGS = -1, 0x0001 | 0x0002 | 0x0010

TRANSPARENT = "#010203"
KIND_COLORS = {"item": "#F5C542", "counter": "#FF7A59", "play": "#7FDBFF", "warning": "#FF4D4D", "status": "#9AA0A6"}
KIND_ICONS = {"item": "🛒", "counter": "⚔", "play": "💡", "warning": "⚠", "status": "·"}


class Overlay:
    def __init__(self, master: tk.Misc, cfg: dict):
        self.cfg = dict(cfg)
        self.q: queue.Queue = queue.Queue()
        self.lines: list[tuple[float, str, str]] = []  # (hora, tipo, texto)
        self.win = tk.Toplevel(master)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.config(bg=TRANSPARENT)
        self.win.attributes("-transparentcolor", TRANSPARENT)
        self.canvas = tk.Canvas(self.win, bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._layout()
        self.win.update_idletasks()
        self.hwnd = self._make_click_through()
        self.win.after(100, self._tick)
        self.win.after(2000, self._keep_on_top)

    def _layout(self):
        c = self.cfg
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.w, self.h = int(sw * c["width_frac"]), int(sh * 0.35)
        self.win.geometry(f"{self.w}x{self.h}+{int(sw * c['x_frac'])}+{int(sh * c['y_frac'])}")
        self.canvas.config(width=self.w, height=self.h)
        self.font = tkfont.Font(family=c["font_family"], size=int(c["font_size"]), weight="bold")

    def _make_click_through(self) -> int:
        hwnd = user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                              | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
        return hwnd

    def _keep_on_top(self):
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS)
        self.win.after(2000, self._keep_on_top)

    def configure(self, cfg: dict):
        """Aplica nuevos ajustes (posición, tamaño, letra...) sin recrear la ventana."""
        self.cfg.update(cfg)
        self._layout()
        self._redraw()

    def push(self, kind: str, text: str):
        """Thread-safe."""
        self.q.put((kind, text))

    def _tick(self):
        changed = False
        try:
            while True:
                kind, text = self.q.get_nowait()
                self.lines = (self.lines + [(time.time(), kind, text)])[-int(self.cfg["max_lines"]):]
                changed = True
        except queue.Empty:
            pass
        now = time.time()
        alive = [ln for ln in self.lines if now - ln[0] < float(self.cfg["line_seconds"])]
        if len(alive) != len(self.lines):
            self.lines, changed = alive, True
        if changed:
            self._redraw()
        self.win.after(150, self._tick)

    def _redraw(self):
        self.canvas.delete("all")
        y = 0
        for _, kind, text in self.lines:
            txt = f"{KIND_ICONS.get(kind, '')} {text}"
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (1, 1)):  # contorno legible sobre cualquier fondo
                self.canvas.create_text(4 + dx, y + dy, text=txt, fill="#000001", font=self.font, anchor="nw",
                                        width=self.w - 8)
            item = self.canvas.create_text(4, y, text=txt, fill=KIND_COLORS.get(kind, "#FFFFFF"), font=self.font,
                                           anchor="nw", width=self.w - 8)
            bb = self.canvas.bbox(item)
            y = (bb[3] if bb else y + 20) + 6
