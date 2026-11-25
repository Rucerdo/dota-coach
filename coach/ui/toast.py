"""Notificaciones flotantes: tarjetas redondeadas que entran con un deslizamiento y un fundido y se van solas.

Dónde salen:
  - "game" (por defecto): encima de Dota, centradas justo debajo de la barra de retratos de la parte de arriba,
    apiladas hacia abajo. No capturan el ratón ni el foco (se puede seguir jugando y haciendo clic a través) y
    necesitan Dota en "Ventana sin bordes".
  - "panel": en la esquina superior derecha del panel de partida (también si Dota no está abierto).
"""
import ctypes
import tkinter as tk

import customtkinter as ctk

KEY = "#010203"            # color "transparente" para redondear las esquinas
LEVELS = {                 # nivel → (color de la franja, color del icono)
    "danger": ("#E5534B", "#FF8A80"),
    "warn": ("#F0A530", "#FFD180"),
    "info": ("#4FC3F7", "#B3E5FC"),
}
WIDTH, GAP = 360, 8
PANEL_TOP, PANEL_RIGHT = 108, 18
GAME_TOP = 74              # px por debajo del borde superior de Dota (a 1080 de alto): justo bajo los retratos
SHOW_MS, MAX_TOASTS = 6500, 3
STEP_MS, STEPS = 16, 14

GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TOPMOST = (
    0x80000, 0x20, 0x80, 0x08000000, 0x8)


def _font(size, weight="normal"):
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


def _click_through(win: tk.Toplevel):
    """Que la ventana no reciba clics ni foco (para no molestar mientras se juega)."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
                              | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
    except (AttributeError, OSError):
        pass


class Toast:
    def __init__(self, manager: "ToastManager", title: str, text: str, level: str, icon: str, over_game: bool):
        self.manager, self.closing, self.over_game = manager, False, over_game
        bar, icon_color = LEVELS.get(level, LEVELS["info"])
        self.win = tk.Toplevel(manager.root)
        self.win.title("Dota Coach · aviso")  # que nunca se confunda con la ventana "Dota 2" al buscarla
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=KEY)
        try:
            self.win.attributes("-transparentcolor", KEY)
            self.win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        card = ctk.CTkFrame(self.win, fg_color="#161D28", bg_color=KEY, corner_radius=14, border_width=1,
                            border_color=bar, width=WIDTH, height=10)  # alto: el del contenido
        card.pack(fill="both", expand=True)
        card.grid_columnconfigure(2, weight=1)
        ctk.CTkFrame(card, fg_color=bar, width=5, height=10, corner_radius=3).grid(
            row=0, column=0, rowspan=2, sticky="ns", padx=(10, 0), pady=10)
        ctk.CTkLabel(card, text=icon, font=_font(22), text_color=icon_color, width=34).grid(
            row=0, column=1, rowspan=2, padx=(10, 4), pady=8)
        ctk.CTkLabel(card, text=title, font=_font(14, "bold"), text_color="#F4F6F9", anchor="w").grid(
            row=0, column=2, sticky="sw", padx=(2, 14), pady=(10, 0))
        ctk.CTkLabel(card, text=text, font=_font(12), text_color="#C3CCD6", anchor="w", justify="left",
                     wraplength=WIDTH - 90).grid(row=1, column=2, sticky="nw", padx=(2, 14), pady=(0, 10))
        if over_game:
            self.win.update_idletasks()
            _click_through(self.win)
        else:
            for w in (self.win, card, *card.winfo_children()):
                w.bind("<Button-1>", lambda _e: self.close())
        self.win.update_idletasks()
        self.height = self.win.winfo_reqheight()
        self.x = self.y = 0

    # ---------- animación ----------
    def slide_in(self, x: int, y: int):
        """Sobre el juego baja desde arriba; sobre el panel entra desde la derecha."""
        self.x, self.y = x, y
        sx, sy = (x, y - 24) if self.over_game else (x + 60, y)

        def step(i=0):
            if self.closing or not self.win.winfo_exists():
                return
            ease = 1 - (1 - i / STEPS) ** 3
            self.win.geometry(f"{WIDTH}x{self.height}+{int(sx + (x - sx) * ease)}+{int(sy + (y - sy) * ease)}")
            self._alpha(0.96 * ease)
            if i < STEPS:
                self.win.after(STEP_MS, step, i + 1)
        step()
        self.win.after(SHOW_MS, self.close)

    def move_to(self, x: int, y: int):
        start_y = self.y

        def step(i=0):
            if not self.win.winfo_exists():
                return
            self.y = int(start_y + (y - start_y) * (1 - (1 - i / STEPS) ** 3))
            self.win.geometry(f"{WIDTH}x{self.height}+{x}+{self.y}")
            if i < STEPS:
                self.win.after(STEP_MS, step, i + 1)
        step()

    def close(self):
        if self.closing:
            return
        self.closing = True

        def step(i=0):
            if not self.win.winfo_exists():
                return
            self._alpha(0.96 * (1 - i / STEPS))
            if i < STEPS:
                self.win.after(STEP_MS, step, i + 1)
            else:
                self.win.destroy()
                self.manager.removed(self)
        step()

    def _alpha(self, a: float):
        try:
            self.win.attributes("-alpha", max(0.0, min(1.0, a)))
        except tk.TclError:
            pass


class ToastManager:
    def __init__(self, root: tk.Misc, placement: str = "game"):
        self.root, self.placement, self.toasts = root, placement, []

    def _game_anchor(self) -> tuple[int, int] | None:
        try:
            from ..vision.topbar import dota_client_rect
            client = dota_client_rect()
        except Exception:
            client = None
        if not client:
            return None
        x0, y0, w, h = client
        return int(x0 + w / 2 - WIDTH / 2), int(y0 + GAME_TOP * h / 1080)

    def _anchor(self) -> tuple[tuple[int, int], bool]:
        """(x, y) de la primera notificación y si va encima del juego."""
        if self.placement == "game":
            spot = self._game_anchor()
            if spot:
                return spot, True
        x = self.root.winfo_rootx() + self.root.winfo_width() - WIDTH - PANEL_RIGHT
        return (x, self.root.winfo_rooty() + PANEL_TOP), False

    def show(self, title: str, text: str, level: str = "info", icon: str = "●"):
        while len([t for t in self.toasts if not t.closing]) >= MAX_TOASTS:
            next(t for t in self.toasts if not t.closing).close()
        (x, y), over_game = self._anchor()
        toast = Toast(self, title, text, level, icon, over_game)
        offset = sum(t.height + GAP for t in self.toasts if not t.closing)
        self.toasts.append(toast)
        toast.slide_in(x, y + offset)

    def removed(self, toast: Toast):
        if toast in self.toasts:
            self.toasts.remove(toast)
        (x, y), _ = self._anchor()
        for t in self.toasts:
            if not t.closing:
                t.move_to(x, y)
                y += t.height + GAP
