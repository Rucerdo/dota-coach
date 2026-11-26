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
GAME_WIDTH = 300           # encima del juego, más estrechas: van en fila
GAME_VISIBLE = 3           # como mucho 3 a la vez; las demás esperan su turno (cinta de sushi)
STAGGER_MS = 900           # si llegan varias de golpe, entran (y por tanto salen) una detrás de otra
MAX_AGE = 8.0              # segundos: un aviso que lleva más esperando (cola, panel ocupado) ya no se enseña
PANEL_TOP, PANEL_RIGHT = 108, 18
GAME_TOP = 100             # px por debajo del borde superior de Dota (a 1080 de alto): bajo los retratos y
                           # los rótulos de definitivas (ui/ultbadges.py, hasta 83)
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
        self.width = GAME_WIDTH if over_game else WIDTH
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
                            border_color=bar, width=self.width, height=10)  # alto: el del contenido
        card.pack(fill="both", expand=True)
        card.grid_columnconfigure(2, weight=1)
        ctk.CTkFrame(card, fg_color=bar, width=5, height=10, corner_radius=3).grid(
            row=0, column=0, rowspan=2, sticky="ns", padx=(10, 0), pady=10)
        ctk.CTkLabel(card, text=icon, font=_font(22), text_color=icon_color, width=34).grid(
            row=0, column=1, rowspan=2, padx=(10, 4), pady=8)
        ctk.CTkLabel(card, text=title, font=_font(14, "bold"), text_color="#F4F6F9", anchor="w").grid(
            row=0, column=2, sticky="sw", padx=(2, 14), pady=(10, 0))
        ctk.CTkLabel(card, text=text, font=_font(12), text_color="#C3CCD6", anchor="w", justify="left",
                     wraplength=self.width - 90).grid(row=1, column=2, sticky="nw", padx=(2, 14), pady=(0, 10))
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
        """Entra desde la derecha (encima del juego, como en una cinta: las demás se corren a la izquierda)."""
        self.x, self.y = x, y
        sx, sy = x + 60, y

        def step(i=0):
            if self.closing or not self.win.winfo_exists():
                return
            ease = 1 - (1 - i / STEPS) ** 3
            self.win.geometry(f"{self.width}x{self.height}+{int(sx + (x - sx) * ease)}+{int(sy + (y - sy) * ease)}")
            self._alpha(0.96 * ease)
            if i < STEPS:
                self.win.after(STEP_MS, step, i + 1)
        step()
        self.win.after(SHOW_MS, self.close)

    def move_to(self, x: int, y: int):
        start_x, start_y = self.x, self.y

        def step(i=0):
            if not self.win.winfo_exists():
                return
            ease = 1 - (1 - i / STEPS) ** 3
            self.x = int(start_x + (x - start_x) * ease)
            self.y = int(start_y + (y - start_y) * ease)
            self.win.geometry(f"{self.width}x{self.height}+{self.x}+{self.y}")
            if i < STEPS:
                self.win.after(STEP_MS, step, i + 1)
        step()

    def slide_out_left(self):
        """Sale por la izquierda mientras se desvanece."""
        start_x = self.x

        def step(i=0):
            if self.win.winfo_exists() and i <= STEPS:
                self.win.geometry(f"{self.width}x{self.height}+{int(start_x - 60 * i / STEPS)}+{self.y}")
                self.win.after(STEP_MS, step, i + 1)
        step()
        self.close()

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
    """Encima del juego: una fila centrada bajo los retratos, como mucho GAME_VISIBLE a la vez. La nueva entra por la
    derecha, las demás se corren a la izquierda y, si llegan muchas de golpe, esperan su turno en una cola (como una
    cinta de sushi) en vez de llenar la pantalla. En el panel: apiladas en la esquina, como siempre."""

    def __init__(self, root: tk.Misc, placement: str = "game"):
        self.root, self.placement, self.toasts = root, placement, []
        self.queue: list[tuple] = []
        self.last_entry = 0.0
        self.pumping = False

    def _game_client(self):
        try:
            from ..vision.topbar import dota_client_rect
            return dota_client_rect()
        except Exception:
            return None

    def _active(self) -> list[Toast]:
        return [t for t in self.toasts if not t.closing]

    def _over_game(self) -> bool:
        return self.placement == "game" and self._game_client() is not None

    def show(self, title: str, text: str, level: str = "info", icon: str = "●", created: float | None = None):
        import time
        created = time.time() if created is None else created
        if time.time() - created > MAX_AGE:
            return  # p. ej. "te vienen a gankear" de hace 15 s: ya no tiene sentido
        over_game = self._over_game()
        if over_game:
            import time
            wait = STAGGER_MS / 1000 - (time.time() - self.last_entry)
            if len(self._active()) >= GAME_VISIBLE or wait > 0 or self.queue:
                self.queue.append((title, text, level, icon, created))
                self._pump_later(max(wait, 0))
                return
            self.last_entry = time.time()
        else:
            while len(self._active()) >= MAX_TOASTS:
                self._active()[0].close()
        toast = Toast(self, title, text, level, icon, over_game)
        self.toasts.append(toast)
        self._layout(new=toast)

    def _row_positions(self, toasts: list[Toast]) -> list[tuple[int, int]]:
        client = self._game_client()
        if not client:
            return []
        x0, y0, w, h = client
        total = sum(t.width for t in toasts) + GAP * (len(toasts) - 1)
        x, y = int(x0 + w / 2 - total / 2), int(y0 + GAME_TOP * h / 1080)
        out = []
        for t in toasts:
            out.append((x, y))
            x += t.width + GAP
        return out

    def _layout(self, new: Toast | None = None):
        active = self._active()
        if active and active[0].over_game:
            spots = self._row_positions(active)
            if spots:
                for t, (x, y) in zip(active, spots):
                    if t is new:
                        t.slide_in(x, y)
                    else:
                        t.move_to(x, y)
                return
        x = self.root.winfo_rootx() + self.root.winfo_width() - WIDTH - PANEL_RIGHT
        y = self.root.winfo_rooty() + PANEL_TOP
        for t in active:
            if t is new:
                t.slide_in(x, y)
            else:
                t.move_to(x, y)
            y += t.height + GAP

    def _pump_later(self, seconds: float):
        if not self.pumping:
            self.pumping = True
            self.root.after(int(seconds * 1000) + 30, self._pump)

    def _pump(self):
        """Saca la siguiente de la cola en cuanto hay sitio (y ha pasado el intervalo desde la anterior)."""
        import time
        self.pumping = False
        self.queue = [q for q in self.queue if time.time() - q[4] <= MAX_AGE]   # los caducados se tiran
        if not self.queue:
            return
        if not self._over_game():
            while self.queue:
                t = self.queue.pop(0)
                self.placement, saved = "panel", self.placement
                self.show(*t)
                self.placement = saved
            return
        wait = STAGGER_MS / 1000 - (time.time() - self.last_entry)
        if len(self._active()) < GAME_VISIBLE and wait <= 0:
            title, text, level, icon, _created = self.queue.pop(0)
            self.last_entry = time.time()
            toast = Toast(self, title, text, level, icon, True)
            self.toasts.append(toast)
            self._layout(new=toast)
        if self.queue:
            self._pump_later(max(wait, 0.25))

    def removed(self, toast: Toast):
        if toast in self.toasts:
            self.toasts.remove(toast)
        self._layout()
        if self.queue:
            self._pump_later(0)
