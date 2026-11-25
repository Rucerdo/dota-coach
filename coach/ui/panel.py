"""Panel de partida (ventana aparte, al estilo de Dota Plus) en formato apaisado:

  cabecera ─ tu héroe, estadísticas, reloj y estado
  izquierda ─ tu inventario, siguiente compra (con sus componentes) y build por fases
  centro ─ líneas, enemigos (rasgos, meta y qué comprar contra cada uno) y partidas parecidas
  derecha ─ minimapa, últimos consejos y tu héroe en el parche

Todo cabe sin scroll en ~1400x880: los textos largos van en tooltips.

Es la ventana principal del modo en directo: cerrarla detiene el coach. Todo llega por post() desde otros hilos
y se pinta en el hilo de Tk. Los widgets se crean una vez y solo se reconfiguran cuando su valor cambia: nada se
destruye y se vuelve a crear, así que no parpadea.
"""
import logging
import queue
import threading
import time
import tkinter as tk

import customtkinter as ctk
from PIL import Image

from .. import config
from ..data.cache import download_file
from ..data.gamedata import CDN, Hero
from ..engine.benchmarks import describe
from ..engine.counters import PHASE_LABELS, PHASES
from ..engine.timers import upcoming
from .toast import ToastManager
from .view import HeroCard, ItemCard, MatchView

log = logging.getLogger(__name__)

BG, CARD, CARD2 = "#0E1217", "#1A212A", "#222B36"
TEXT, MUTED, ACCENT = "#E6EAEE", "#8B96A3", "#C8402B"
GREEN, YELLOW, RED, CYAN, GOLD = "#5FCF80", "#F2C94C", "#E5534B", "#4FC3F7", "#F5C542"
KIND_COLORS = {"item": GOLD, "counter": "#FF7A59", "play": CYAN, "warning": RED, "status": MUTED, "map": RED,
               "timer": "#B39DDB"}
KIND_LABELS = {"item": "COMPRA", "counter": "COUNTER", "play": "JUEGO", "warning": "AVISO", "status": "INFO",
               "map": "MAPA", "timer": "TIEMPO"}
TIMER_SHORT = {"bounty": "Recompensa", "power": "Poder", "wisdom": "Sabiduría", "lotus": "Loto", "stack": "Stack",
               "daynight": "Día/noche"}
VERDICT_COLORS = {"buff": GREEN, "nerf": RED}
# Tono del panel: neutro fuera de partida, cálido de día y azulado de noche (transición suave)
PALETTES = {
    "neutral": {"bg": "#0E1217", "card": "#1A212A", "header": "#1A212A", "clock": "#E6EAEE"},
    "day": {"bg": "#13110D", "card": "#221D16", "header": "#2A2219", "clock": "#F5C542"},
    "night": {"bg": "#090E1A", "card": "#121A2B", "header": "#152038", "clock": "#9FC3FF"},
}
TOAST_ICONS = {"mia": "?", "near": "⚔", "tp": "↯", "tower": "♜", "streak": "☠", "patch": "⚑"}
MAX_TIPS = 60


def _mix(a: str, b: str, t: float) -> str:
    a_, b_ = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a_, b_))
TIP_ROWS = 5


def font(size=13, weight="normal"):
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


def fmt_clock(seconds: int) -> str:
    sign = "-" if seconds < 0 else ""
    seconds = abs(int(seconds))
    return f"{sign}{seconds // 60}:{seconds % 60:02d}"


def panel_geometry(saved: str, default_size: str = "1400x880") -> str:
    """La geometría guardada; si era la del panel vertical antiguo (estrecho), se amplía conservando la posición
    (p. ej. en el segundo monitor)."""
    import re
    m = re.fullmatch(r"(\d+)x(\d+)([+-]-?\d+[+-]-?\d+)?", saved.strip())
    if not m:
        return default_size
    if int(m.group(1)) >= 1000:
        return saved
    return default_size + (m.group(3) or "")


# ================= utilidades de widgets =================
_last: dict[int, dict] = {}


def setw(widget, **kw):
    """configure() solo con lo que ha cambiado (evita redibujos y parpadeos)."""
    prev = _last.setdefault(id(widget), {})
    changed = {k: v for k, v in kw.items() if prev.get(k, object()) is not v and prev.get(k, object()) != v}
    if changed:
        widget.configure(**changed)
        prev.update(changed)


def show(widget, visible: bool, **grid):
    """Coloca u oculta con grid. Se mira si está COLOCADO (winfo_manager), no si se ve (winfo_ismapped): Tk
    desmapea lo que queda fuera de la vista y eso hacía recolocarlo sin parar (parpadeo)."""
    placed = bool(widget.winfo_manager())
    if visible and not placed:
        widget.grid(**grid) if grid else widget.grid()
    elif not visible and placed:
        widget.grid_remove()


def pack_show(widget, visible: bool, **pack):
    placed = bool(widget.winfo_manager())
    if visible and not placed:
        widget.pack(**pack)
    elif not visible and placed:
        widget.pack_forget()


class Tooltip:
    """Texto al pasar el ratón (motivos de cada objeto)."""

    def __init__(self, widget):
        self.widget, self.text, self.tip = widget, "", None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _e=None):
        if not self.text or self.tip:
            return
        x, y = self.widget.winfo_rootx() + 10, self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.overrideredirect(True)
        self.tip.attributes("-topmost", True)
        self.tip.geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg=CARD2, fg=TEXT, font=("Segoe UI", 10), justify="left",
                 wraplength=360, padx=8, pady=6).pack()

    def _hide(self, _e=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class ImageStore:
    """Retratos e iconos: del disco si ya están; si no, se descargan en segundo plano (una vez)."""

    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self._pending: set = set()
        self._images: dict = {}
        self.changed = threading.Event()
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        while True:
            url, path = self._q.get()
            if download_file(url, path):
                self.changed.set()

    def _get(self, url: str, path, size: tuple[int, int]):
        key = (str(path), size)
        if key in self._images:
            return self._images[key]
        if path.exists():
            try:
                img = Image.open(path).convert("RGBA")
            except OSError:
                return None
            self._images[key] = ctk.CTkImage(light_image=img, dark_image=img, size=size)
            return self._images[key]
        if path not in self._pending:
            self._pending.add(path)
            self._q.put((url, path))
        return None

    def hero(self, hero: Hero, size=(64, 36)):
        if not hero.img:
            return None
        return self._get(CDN + hero.img.split("?")[0], config.CACHE_DIR / "hero_img" / f"{hero.short}.png", size)

    def ability(self, name: str, size=(28, 28)):
        return self._get(f"{CDN}/apps/dota2/images/dota_react/abilities/{name}.png",
                         config.CACHE_DIR / "ability_img" / f"{name}.png", size)

    def item(self, short: str, size=(44, 32)):
        return self._get(f"{CDN}/apps/dota2/images/dota_react/items/{short}.png",
                         config.CACHE_DIR / "item_img" / f"{short}.png", size)


class Pool:
    """Filas reutilizables: crea las que falten, oculta las que sobren y reconfigura el resto."""

    def __init__(self, factory):
        self.factory, self.rows = factory, []

    def update(self, values: list, setter):
        while len(self.rows) < len(values):
            self.rows.append(self.factory(len(self.rows)))
        for i, row in enumerate(self.rows):
            if i < len(values):
                setter(row, values[i])
                show(row["frame"], True)
            else:
                show(row["frame"], False)


# ================= panel =================
class Panel(ctk.CTk):
    def __init__(self, cfg: dict, patch: str, ai_label: str):
        super().__init__(fg_color=BG)
        ctk.set_appearance_mode("dark")
        self.cfg = cfg
        pcfg = cfg.get("panel", {})
        self.title("Dota Coach")
        self.minsize(1000, 600)
        self._place(pcfg)
        self.attributes("-topmost", bool(pcfg.get("on_top", False)))
        self.patch, self.ai_label = patch, ai_label
        self.q: queue.Queue = queue.Queue()
        self.images = ImageStore()
        self.view: MatchView | None = None
        self.similar = None
        self.draft = None
        self.toast = ToastManager(self, cfg.get("toasts_position", "game"))
        self.theme = "neutral"
        self._theme_colors = dict(PALETTES["neutral"])
        self._themed: list[tuple[object, str]] = [(self, "bg")]
        self.report = None
        self.history = None
        self.view_time = 0.0
        self.item_names: dict[str, str] = {}   # item_* → nombre (para inventario y alijo)
        self.minimap_frame = None      # último fotograma del minimapa (PIL), lo pone otro hilo
        self._minimap_shown = None
        self.similar_state = ""  # "" | "buscando" | "sin datos"
        self.last_state = 0.0
        self.tips: list = []
        self._tips_shown = -1

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        cols = ctk.CTkFrame(self, fg_color="transparent", width=1, height=1)
        cols.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        cols.grid_rowconfigure(0, weight=1)
        self.cols = []
        for i in range(3):
            cols.grid_columnconfigure(i, weight=1, uniform="col")
            sc = ctk.CTkFrame(cols, fg_color="transparent", width=1, height=1)
            sc.grid(row=0, column=i, sticky="nsew", padx=4)
            sc.grid_columnconfigure(0, weight=1)
            self.cols.append(sc)
        self.cards = {}
        # izquierda: tu héroe (draft / compras y habilidades / informe e historial)
        self._build_draft(self._card(0, "draft", "Selección de héroes"))
        self._build_report(self._card(0, "report", "Tu última partida"))
        self._build_history(self._card(0, "history", "Tus partidas"))
        self._build_inventory(self._card(0, "inventory", "Tu inventario"))
        self._build_next(self._card(0, "next", "Siguiente compra"))
        self._build_phases(self._card(0, "phases", "Build por fases"))
        self._build_skills(self._card(0, "skills", "Habilidades y talentos"))
        # centro: la partida (mapa, torres y bajas, consejos)
        # mapa y últimos consejos en la misma fila (el mapa solo ocupa la mitad del ancho)
        top = ctk.CTkFrame(self.cols[1], fg_color="transparent", width=1, height=1)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top.grid_columnconfigure(1, weight=1)
        self._build_map(self._card(1, "map", "Mapa", parent=top, grid=dict(row=0, column=0, sticky="nsew")))
        self._build_tips(self._card(1, "tips", "Últimos consejos", parent=top,
                                    grid=dict(row=0, column=1, sticky="nsew", padx=(8, 0))))
        self._build_battle(self._card(1, "battle", "Torres y bajas"))
        self._build_mylane(self._card(1, "mylane", "Tu línea"))
        # derecha: los rivales y el parche
        self._build_lanes(self._card(2, "lanes", "Líneas"))
        self._build_enemies(self._card(2, "enemies", "Enemigos"))
        self._build_similar(self._card(2, "similar", "Partidas parecidas"))

        self._render()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(250, self._poll)

    def _place(self, pcfg: dict):
        """Por defecto, maximizado en la pantalla secundaria si la hay (el juego va en la principal); con
        panel.screen = "saved", donde se dejó la última vez."""
        if pcfg.get("screen", "secondary") == "secondary":
            from .monitors import list_monitors, preferred_monitor
            mon = preferred_monitor(list_monitors())
            if mon:
                self.geometry(mon.geometry)
                self.after(150, lambda: self.state("zoomed"))
                return
        self.geometry(panel_geometry(pcfg.get("geometry") or ""))

    # ---------- entrada (cualquier hilo) ----------
    def post(self, kind: str, payload=None):
        self.q.put((kind, payload))

    # ---------- estructura ----------
    def _card(self, col: int, key: str, title: str, parent=None, grid: dict | None = None) -> ctk.CTkFrame:
        """Tarjeta con título. Por defecto, debajo de lo que ya haya en la columna 'col'; con parent/grid, donde
        se diga (p. ej. dos tarjetas en la misma fila)."""
        parent = parent if parent is not None else self.cols[col]
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        card.grid(**(grid or dict(row=len(parent.winfo_children()), column=0, sticky="ew", pady=(0, 8))))
        card.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(card, fg_color="transparent", width=1, height=1)
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 2))
        ctk.CTkLabel(head, text=title.upper(), font=font(11, "bold"), text_color=MUTED).pack(side="left")
        extra = ctk.CTkLabel(head, text="", font=font(11), text_color=MUTED)
        extra.pack(side="right")
        body = ctk.CTkFrame(card, fg_color="transparent", width=1, height=1)
        body.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        body.grid_columnconfigure(0, weight=1)
        empty = ctk.CTkLabel(body, text="", font=font(11), text_color=MUTED, wraplength=400, justify="left",
                             anchor="w")
        self.cards[key] = {"body": body, "extra": extra, "empty": empty, "frame": card}
        self._themed.append((card, "card"))
        return body

    def _show_card(self, key: str, visible: bool):
        show(self.cards[key]["frame"], visible)

    def _empty(self, key: str, text: str | None):
        """Muestra u oculta el texto de "sin datos" de una tarjeta."""
        lbl = self.cards[key]["empty"]
        if text:
            setw(lbl, text=text)
            show(lbl, True, row=99, column=0, columnspan=4, sticky="ew")
        else:
            show(lbl, False)

    # ---------- cabecera ----------
    def _build_header(self):
        h = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0)
        h.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self._themed.append((h, "header"))
        h.grid_columnconfigure(2, weight=1)
        self.h_portrait = ctk.CTkLabel(h, text="", width=112, height=63, fg_color=CARD2, corner_radius=6)
        self.h_portrait.grid(row=0, column=0, rowspan=2, padx=(14, 12), pady=12)
        names = ctk.CTkFrame(h, fg_color="transparent", width=1, height=1)
        names.grid(row=0, column=1, rowspan=2, sticky="w")
        self.h_name = ctk.CTkLabel(names, text="Dota Coach", font=font(20, "bold"), text_color=TEXT, anchor="w")
        self.h_name.pack(anchor="w")
        self.h_sub = ctk.CTkLabel(names, text="", font=font(12), text_color=MUTED, anchor="w")
        self.h_sub.pack(anchor="w")

        stats = ctk.CTkFrame(h, fg_color="transparent", width=1, height=1)
        stats.grid(row=0, column=2, rowspan=2, padx=16)
        self.stat_labels = {}
        self.stat_subs = {}
        for i, (key, label) in enumerate([("kda", "V/M/A"), ("lh", "Últimos"), ("gpm", "Oro/min"),
                                          ("gold", "Oro"), ("bb", "Buyback")]):
            box = ctk.CTkFrame(stats, fg_color=CARD2, corner_radius=6, width=92)
            box.grid(row=0, column=i, padx=3)
            val = ctk.CTkLabel(box, text="–", font=font(16, "bold"), text_color=TEXT, width=86)
            val.pack(pady=(6, 0))
            sub = ctk.CTkLabel(box, text=label, font=font(10), text_color=MUTED)
            sub.pack(pady=(0, 6))
            self.stat_labels[key] = val
            self.stat_subs[key] = (sub, label)

        right = ctk.CTkFrame(h, fg_color="transparent", width=1, height=1)
        right.grid(row=0, column=3, rowspan=2, padx=14, sticky="e")
        clock = ctk.CTkFrame(right, fg_color="transparent", width=1, height=1)
        clock.pack(anchor="e")
        self.h_clock = ctk.CTkLabel(clock, text="--:--", font=font(26, "bold"), text_color=TEXT)
        self.h_clock.pack(side="right")
        self.h_day = ctk.CTkLabel(clock, text="", font=font(12), text_color=MUTED)
        self.h_day.pack(side="right", padx=(0, 10))
        self.h_status = ctk.CTkLabel(right, text="", font=font(11), text_color=MUTED)
        self.h_status.pack(anchor="e")
        row2 = ctk.CTkFrame(h, fg_color="transparent", width=1, height=1)
        row2.grid(row=2, column=0, columnspan=4, sticky="ew", padx=14, pady=(0, 8))
        self.h_timers = ctk.CTkLabel(row2, text="", font=font(11), text_color="#B39DDB", anchor="w")
        self.h_patch = ctk.CTkLabel(row2, text="", font=font(11), text_color=MUTED, anchor="e")
        self.h_patch.pack(side="right")
        self.h_patch_tip = Tooltip(self.h_patch)
        self.v_top = tk.BooleanVar(value=bool(self.cfg.get("panel", {}).get("on_top", False)))
        ctk.CTkCheckBox(right, text="Siempre encima", variable=self.v_top, font=font(11), checkbox_width=16,
                        checkbox_height=16, fg_color=ACCENT, hover_color=ACCENT, command=self._toggle_top).pack(
            anchor="e", pady=(4, 0))

    def _toggle_top(self):
        self.attributes("-topmost", bool(self.v_top.get()))

    def _render_header(self):
        v = self.view
        if not self.last_state:
            status, color = "● Esperando a Dota… (si ya estaba abierto, reinícialo tras instalar GSI)", YELLOW
        elif time.time() - self.last_state > 10:
            status, color = "● Sin datos de Dota", YELLOW
        elif v and v.in_game:
            status, color = "● En partida", GREEN
        else:
            status, color = "● Conectado · esperando partida", GREEN
        setw(self.h_status, text=f"{status}   ·   parche {self.patch}   ·   {self.ai_label}", text_color=color)
        if not v:
            return
        if v.hero:
            setw(self.h_name, text=v.hero.loc)
            img = self.images.hero(v.hero, (112, 63))
            setw(self.h_portrait, image=img, text="" if img else v.hero.loc[:2])
        team = {"radiant": "Radiant", "dire": "Dire"}.get(v.team, "")
        sub = [f"Nivel {v.level}" if v.level else "", team, v.role]
        if not v.alive:
            sub.append(f"muerto · reaparece en {v.respawn_seconds}s")
        setw(self.h_sub, text=" · ".join(s for s in sub if s), text_color=MUTED if v.alive else RED)
        setw(self.h_clock, text=fmt_clock(v.clock) if v.in_game else "--:--")
        score = f"   Radiant {v.radiant_score} – {v.dire_score} Dire" if v.in_game else ""
        setw(self.h_day, text=(("☀ día" if v.daytime else "☾ noche") + score) if v.in_game else "")
        setw(self.stat_labels["kda"], text=f"{v.kills}/{v.deaths}/{v.assists}")
        setw(self.stat_labels["lh"], text=str(v.last_hits))
        setw(self.stat_labels["gpm"], text=str(v.gpm))
        setw(self.stat_labels["gold"], text=str(v.gold), text_color=GOLD)
        setw(self.stat_labels["bb"], text=str(v.buyback_cost) if v.buyback_cost else "–",
             text_color=GREEN if v.gold >= v.buyback_cost > 0 else TEXT)
        for key, metric in (("gpm", "gold_per_min"), ("lh", "last_hits_per_min")):
            sub, label = self.stat_subs[key]
            p = v.percentiles.get(metric)
            if p is None:
                setw(sub, text=label, text_color=MUTED)
            else:
                setw(sub, text=f"{label} · {describe(p)}",
                     text_color=GREEN if p >= 0.6 else RED if p <= 0.3 else MUTED)
        if v.in_game and v.clock >= 0:
            clock = v.clock + int(time.time() - self.view_time)  # avanza entre envíos de Dota
            parts = [f"{TIMER_SHORT[t.key]} {fmt_clock(t.seconds_left)}" for t in upcoming(clock)]
            setw(self.h_timers, text="⏱  " + "   ·   ".join(parts))
            pack_show(self.h_timers, True, side="left")
        else:
            pack_show(self.h_timers, False)

    # ---------- tu línea (fase de líneas, en directo) ----------
    def _build_mylane(self, body):
        body.grid_columnconfigure(0, weight=1)
        self.ml_title = ctk.CTkLabel(body, text="", font=font(12, "bold"), text_color=TEXT, anchor="w")
        self.ml_title.grid(row=0, column=0, sticky="w")
        self.ml_partner = ctk.CTkLabel(body, text="", font=font(11), text_color=MUTED, anchor="w")
        self.ml_partner.grid(row=1, column=0, sticky="w", pady=(0, 4))

        def factory(i):
            f = ctk.CTkFrame(body, fg_color=CARD2, corner_radius=6)
            f.grid(row=2 + i, column=0, sticky="ew", pady=(0, 4))
            f.grid_columnconfigure(1, weight=1)
            portrait = ctk.CTkLabel(f, text="", width=52, height=29, fg_color=BG, corner_radius=4)
            portrait.grid(row=0, column=0, rowspan=2, padx=6, pady=4, sticky="nw")
            head = ctk.CTkFrame(f, fg_color="transparent", width=1, height=1)
            head.grid(row=0, column=1, sticky="ew", pady=(3, 0))
            name = ctk.CTkLabel(head, text="", font=font(12, "bold"), text_color=TEXT, height=16)
            name.pack(side="left")
            outcome = ctk.CTkLabel(head, text="", font=font(10), text_color=MUTED, height=16)
            outcome.pack(side="left", padx=(8, 0))
            seen = ctk.CTkLabel(head, text="", font=font(10, "bold"), height=16)
            seen.pack(side="right", padx=(0, 8))
            tip = ctk.CTkLabel(f, text="", font=font(10), text_color=MUTED, anchor="w", justify="left",
                               wraplength=520)
            tip.grid(row=1, column=1, sticky="ew", pady=(0, 4), padx=(0, 8))
            return {"frame": f, "portrait": portrait, "name": name, "outcome": outcome, "seen": seen, "tip": tip}
        self.ml_pool = Pool(factory)
        self.ml_ai = ctk.CTkLabel(body, text="", font=font(11), text_color=CYAN, anchor="w", justify="left",
                                  wraplength=540)
        self.ml_ai.grid(row=20, column=0, sticky="ew", pady=(2, 0))

    def _set_opponent(self, row, o):
        img = self.images.hero(o.hero, (52, 29))
        setw(row["portrait"], image=img, text="" if img else o.hero.loc[:2])
        setw(row["name"], text=o.hero.loc)
        if o.outcome:
            win, draw, lose, _ = o.outcome
            setw(row["outcome"], text=f"contra ti: {win:.0%} ganas · {lose:.0%} pierdes",
                 text_color=GREEN if win > lose + 0.05 else RED if lose > win + 0.05 else MUTED)
        else:
            setw(row["outcome"], text="")
        if o.visible:
            setw(row["seen"], text="\u25cf a la vista", text_color=GREEN)
        elif o.seen_ago is not None:
            setw(row["seen"], text=f"sin ver {o.seen_ago} s", text_color=RED if o.seen_ago >= 20 else YELLOW)
        else:
            setw(row["seen"], text="")
        setw(row["tip"], text=o.tip)

    def _render_mylane(self):
        v = self.view
        rep = v.lane_report if v else None
        has = rep is not None
        self._show_card("mylane", bool(v and v.in_game and not v.drafting))
        show(self.ml_title, has, row=0, column=0, sticky="w")
        show(self.ml_partner, has, row=1, column=0, sticky="w", pady=(0, 4))
        if not has:
            self._empty("mylane", "En cuanto se vea en qué línea vas (primeros minutos) saldrán aquí tus rivales, "
                                  "cómo suele salir ese enfrentamiento y cómo jugarlo.")
            self.ml_pool.update([], self._set_opponent)
            setw(self.ml_ai, text="")
            return
        self._empty("mylane", None)
        names = " + ".join([rep.me.loc, *[h.loc for h in rep.partners]])
        foes = " + ".join(o.hero.loc for o in rep.opponents) or "nadie a la vista"
        setw(self.ml_title, text=f"{rep.lane.capitalize()}: {names}  vs  {foes}")
        if rep.partner_wr:
            setw(self.ml_partner, text=" · ".join(f"Con {n}: {wr:.0%} de victorias juntos ({g} partidas)"
                                                  for n, (wr, g) in rep.partner_wr.items()), text_color=MUTED)
        else:
            setw(self.ml_partner, text="Vas solo en la línea" if not rep.partners else
                 "Con " + ", ".join(h.loc for h in rep.partners))
        self.ml_pool.update(rep.opponents, self._set_opponent)
        setw(self.ml_ai, text="\n".join(f"\u2726 {t}" for t in rep.ai_tips))
        setw(self.cards["mylane"]["extra"], text="con IA" if rep.ai_tips else "fase de líneas")

    # ---------- habilidades y talentos (como en el juego / Dota Plus) ----------
    GRID_LEVELS = 18
    CELL = 16

    def _build_skills(self, body):
        """Rejilla nivel a nivel (qué subir en cada nivel, lo ya subido en verde, tu nivel resaltado) y el árbol de
        talentos (25 arriba, 10 abajo; elegido en dorado, el más elegido con ★)."""
        body.grid_columnconfigure(0, weight=1)
        self.sk_now = ctk.CTkLabel(body, text="", font=font(13, "bold"), text_color=GREEN, anchor="w")
        grid = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
        grid.grid(row=1, column=0, sticky="w", pady=(2, 6))
        self.sk_head = []
        for c in range(self.GRID_LEVELS):
            lbl = ctk.CTkLabel(grid, text=str(c + 1), font=font(8), text_color=MUTED, width=self.CELL, height=12)
            lbl.grid(row=0, column=c + 1, padx=1)
            self.sk_head.append(lbl)
        self.sk_rows = []
        for r in range(5):
            icon = ctk.CTkLabel(grid, text="", width=22, height=22, fg_color=CARD2, corner_radius=4)
            cells = [ctk.CTkLabel(grid, text="", width=self.CELL, height=self.CELL, fg_color=BG, corner_radius=3,
                                  font=font(8, "bold")) for _ in range(self.GRID_LEVELS)]
            self.sk_rows.append({"icon": icon, "tip": Tooltip(icon), "cells": cells, "r": r + 1})
        self.sk_grid = grid
        tree = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
        tree.grid(row=2, column=0, sticky="ew")
        tree.grid_columnconfigure(0, weight=1, uniform="t")
        tree.grid_columnconfigure(2, weight=1, uniform="t")
        self.sk_tree = []
        for i, level in enumerate((25, 20, 15, 10)):
            left = ctk.CTkLabel(tree, text="", font=font(10), fg_color=CARD2, corner_radius=5, height=21,
                                wraplength=240)
            badge = ctk.CTkLabel(tree, text=str(level), font=font(10, "bold"), width=28, height=21,
                                 fg_color="#3A2F14", text_color=GOLD, corner_radius=12)
            right = ctk.CTkLabel(tree, text="", font=font(10), fg_color=CARD2, corner_radius=5, height=21,
                                 wraplength=240)
            left.grid(row=i, column=0, sticky="ew", pady=2)
            badge.grid(row=i, column=1, padx=6, pady=2)
            right.grid(row=i, column=2, sticky="ew", pady=2)
            self.sk_tree.append((level, left, badge, right, Tooltip(left), Tooltip(right)))

    def _render_skills(self):
        from ..engine.skillbuild import suggested_sequence
        v = self.view
        plan = v.skill_plan if v else None
        if not plan:
            self._empty("skills", "Con la clave de STRATZ verás aquí el orden de habilidades y el árbol de talentos "
                                  "de tu héroe." if not (v and v.hero) else "Cargando de STRATZ…")
            show(self.sk_now, False)
            show(self.sk_grid, False)
            for row in self.sk_tree:
                for w in row[1:4]:
                    show(w, False)
            return
        self._empty("skills", None)
        show(self.sk_grid, True, row=1, column=0, sticky="w", pady=(2, 6))
        scope = "en tu rango" if self.cfg.get("rank_bracket", 0) else "en todos los rangos"
        setw(self.cards["skills"]["extra"], text=f"lo habitual {scope} (STRATZ)")
        if v.skill_now:
            setw(self.sk_now, text=f"\u279c Ahora: sube {v.skill_now}")
            show(self.sk_now, True, row=0, column=0, sticky="w")
        else:
            show(self.sk_now, False)
        level_now = v.level or 0
        for c, lbl in enumerate(self.sk_head):
            setw(lbl, text_color=ACCENT if c + 1 == level_now else MUTED)
        # rejilla: la build habitual nivel a nivel; lo que ya llevas subido de cada habilidad, en verde
        seq = suggested_sequence(plan, self.GRID_LEVELS)
        abilities = [*plan.order, *([plan.ultimate] if plan.ultimate else [])]
        have = {a["name"]: a["level"] for a in v.abilities}
        for row, ab in zip(self.sk_rows, abilities + [None] * (len(self.sk_rows) - len(abilities))):
            if ab is None:
                show(row["icon"], False)
                for cell in row["cells"]:
                    show(cell, False)
                continue
            show(row["icon"], True, row=row["r"], column=0, padx=(0, 4), pady=1)
            img = self.images.ability(ab.name, (22, 22))
            setw(row["icon"], image=img, text="" if img else ab.loc[:2])
            row["tip"].text = f"{ab.loc}: llevas {have.get(ab.name, 0)}/{ab.max_level}"
            taken = 0
            for (lvl, what), cell in zip(seq, row["cells"]):
                show(cell, True, row=row["r"], column=lvl, padx=1, pady=1)
                if what == ab.name:
                    taken += 1
                    done = taken <= have.get(ab.name, 0)
                    setw(cell, text=str(taken), fg_color=GREEN if done else ("#5A4A1C" if lvl > level_now else GOLD),
                         text_color=BG if done or lvl <= level_now else GOLD)
                elif what == "talent" and row["r"] == 1:
                    setw(cell, text="T", fg_color="#2A2340", text_color="#B39DDB")
                else:
                    setw(cell, text="", fg_color=CARD2 if lvl == level_now else BG)
        # árbol de talentos: elegido en dorado; si no, ★ en el más elegido
        flags = list(v.talent_flags) + [False] * 8
        by_level = {t.level: (i, t) for i, t in enumerate(plan.talents)}
        tier_of = {10: 0, 15: 1, 20: 2, 25: 3}
        for level, left, badge, right, ltip, rtip in self.sk_tree:
            entry = by_level.get(level)
            for w, col in ((left, 0), (badge, 1), (right, 2)):
                show(w, entry is not None, row=(25 - level) // 5, column=col, sticky="ew" if col != 1 else "",
                     padx=6 if col == 1 else 0, pady=2)
            if not entry:
                continue
            _, t = entry
            tier = tier_of[level]
            chosen = [flags[2 * tier], flags[2 * tier + 1]]
            reached = level_now >= level
            for side, (w, tip) in enumerate(((left, ltip), (right, rtip))):
                name, share = t.options[side] if side < len(t.options) else ("", 0.0)
                star = "\u2605 " if side == t.best and not any(chosen) else ""
                text = f"{star}{name}  {share:.0%}"
                setw(w, text=text if len(text) <= 44 else text[:42] + "…")
                tip.text = f"Nivel {level}: {name}\nLo elige el {share:.0%}"
                if chosen[side]:
                    setw(w, fg_color="#4A3A12", text_color=GOLD)
                elif any(chosen):
                    setw(w, fg_color=BG, text_color="#5C6470")
                elif side == t.best:
                    setw(w, fg_color="#2E2814", text_color=TEXT if reached else "#C9B57A")
                else:
                    setw(w, fg_color=CARD2, text_color=MUTED)
            setw(badge, fg_color="#5A4517" if reached else "#3A2F14")

    # ---------- tono día / noche ----------
    def _render_theme(self):
        v = self.view
        want = ("day" if v.daytime else "night") if v and v.in_game else "neutral"
        if want == self.theme:
            return
        self.theme = want
        start, end = dict(self._theme_colors), PALETTES[want]

        def step(i=1, steps=12):
            t = i / steps
            colors = {k: _mix(start[k], end[k], t) for k in ("bg", "card", "header")}
            for widget, role in self._themed:
                try:
                    widget.configure(fg_color=colors[role])
                except Exception:
                    pass
            self._theme_colors.update(colors)
            if i < steps:
                self.after(50, step, i + 1)
            else:
                self._theme_colors["clock"] = end["clock"]
                setw(self.h_clock, text_color=end["clock"])
        step()

    # ---------- torres y bajas ----------
    def _build_battle(self, body):
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)
        self.b_towers = {}
        for i, lane in enumerate(("top", "mid", "bot")):
            ctk.CTkLabel(body, text=lane.capitalize(), font=font(11, "bold"), text_color=MUTED, width=36,
                         anchor="w", height=20).grid(row=i, column=0, sticky="w")
            strip = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
            strip.grid(row=i, column=1, sticky="w", pady=1)
            self.b_towers[lane] = [ctk.CTkLabel(strip, text="", font=font(10, "bold"), width=70, height=20,
                                                fg_color=CARD2, corner_radius=4) for _ in range(3)]
            for j, lbl in enumerate(self.b_towers[lane]):
                lbl.grid(row=0, column=j, padx=(0, 4))
        self.b_streak = ctk.CTkLabel(body, text="", font=font(11, "bold"), text_color=RED, anchor="w")
        self.b_streak.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def factory(i):
            f = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
            f.grid(row=10 + i, column=0, columnspan=2, sticky="w", pady=1)
            when = ctk.CTkLabel(f, text="", font=font(10), text_color=MUTED, width=38, anchor="w", height=22)
            when.pack(side="left")
            killer, ktip = self._hero_icon(f, (40, 22))
            killer.pack(side="left")
            arrow = ctk.CTkLabel(f, text="→", font=font(12, "bold"), width=22, height=22)
            arrow.pack(side="left")
            victim, vtip = self._hero_icon(f, (40, 22))
            victim.pack(side="left")
            text = ctk.CTkLabel(f, text="", font=font(10), text_color=MUTED, anchor="w", height=22)
            text.pack(side="left", padx=(6, 0))
            return {"frame": f, "when": when, "killer": killer, "ktip": ktip, "arrow": arrow, "victim": victim,
                    "vtip": vtip, "text": text}
        self.kill_pool = Pool(factory)
        self.b_buys = ctk.CTkLabel(body, text="", font=font(10), text_color=MUTED, anchor="w", wraplength=410,
                                   justify="left")
        self.b_buys.grid(row=30, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _set_kill(self, row, k):
        setw(row["when"], text=fmt_clock(k.clock))
        for key, tip, hero in (("killer", "ktip", k.killer), ("victim", "vtip", k.victim)):
            img = self.images.hero(hero, (40, 22)) if hero else None
            setw(row[key], image=img, text="" if img else (hero.loc[:2] if hero else "?"))
            row[tip].text = hero.loc if hero else "desconocido"
        color = RED if k.killer_enemy else GREEN if k.killer_enemy is False else MUTED
        setw(row["arrow"], text_color=color)
        names = f"{k.killer.loc if k.killer else '?'} mató a {k.victim.loc if k.victim else '?'}"
        setw(row["text"], text=names if len(names) <= 40 else names[:38] + "…")

    def _render_battle(self):
        v = self.view
        ev = v.events if v else None
        towers = dict(ev.towers) if ev else {}
        for lane, labels in self.b_towers.items():
            for tier, lbl in zip((1, 2, 3), labels):
                frac = towers.get(f"T{tier} {lane}")
                if frac is None:
                    setw(lbl, text=f"T{tier} –", text_color=MUTED, fg_color=CARD2)
                elif frac <= 0:
                    setw(lbl, text=f"T{tier} caída", text_color="#7A8591", fg_color=BG)
                else:
                    color = GREEN if frac > 0.6 else GOLD if frac > 0.3 else RED
                    setw(lbl, text=f"T{tier} {frac:.0%}", text_color=color, fg_color=CARD2)
        streaks = sorted((ev.streaks if ev else {}).items(), key=lambda kv: -kv[1])
        setw(self.b_streak, text=("Rachas: " + ", ".join(f"{h} {n}" for h, n in streaks[:3])) if streaks else "")
        kills = list(reversed(ev.kills[-4:])) if ev else []
        self.kill_pool.update(kills, self._set_kill)
        buys = ev.purchases[-3:] if ev else []
        setw(self.b_buys, text=("Compras de aliados: " + " · ".join(f"{h}: {i}" for _, h, i in reversed(buys)))
             if buys else "")
        has = bool(towers or kills or buys)
        self._empty("battle", None if has else "Tus torres, quién mata a quién y las rachas aparecerán aquí "
                                               "durante la partida.")
        if v and v.in_game:
            setw(self.cards["battle"]["extra"], text=f"Radiant {v.radiant_score} – {v.dire_score} Dire")

    # ---------- modo de la columna izquierda ----------
    def _render_mode(self):
        v = self.view
        drafting = bool(v and v.drafting)
        playing = bool(v and v.in_game) and not drafting
        idle = not drafting and not playing
        self._show_card("draft", drafting)
        for key in ("inventory", "next", "phases", "skills", "battle"):
            self._show_card(key, playing)
        self._show_card("report", idle and self.report is not None)
        self._show_card("history", idle)

    # ---------- draft ----------
    def _build_draft(self, body):
        body.grid_columnconfigure(1, weight=1)
        self.d_rows = {}
        for i, (key, title) in enumerate((("allies", "Tu equipo"), ("enemies", "Rivales"), ("bans", "Baneados"))):
            ctk.CTkLabel(body, text=title, font=font(11, "bold"), text_color=MUTED, width=76, anchor="w").grid(
                row=i, column=0, sticky="w", pady=2)
            strip = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
            strip.grid(row=i, column=1, sticky="w", pady=2)
            self.d_rows[key] = [self._hero_icon(strip, (48, 27)) for _ in range(5 if key != "bans" else 7)]
        self.d_title = ctk.CTkLabel(body, text="", font=font(12, "bold"), text_color=TEXT, anchor="w")
        self.d_title.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 2))

        def factory(i):
            f = ctk.CTkFrame(body, fg_color=CARD2, corner_radius=6)
            f.grid(row=4 + i, column=0, columnspan=2, sticky="ew", pady=(0, 4))
            f.grid_columnconfigure(1, weight=1)
            portrait = ctk.CTkLabel(f, text="", width=64, height=36, fg_color=BG, corner_radius=4)
            portrait.grid(row=0, column=0, rowspan=2, padx=6, pady=4)
            name = ctk.CTkLabel(f, text="", font=font(13, "bold"), text_color=TEXT, anchor="w", height=18)
            name.grid(row=0, column=1, sticky="w")
            why = ctk.CTkLabel(f, text="", font=font(10), text_color=MUTED, anchor="w", height=16)
            why.grid(row=1, column=1, sticky="w")
            score = ctk.CTkLabel(f, text="", font=font(13, "bold"), text_color=GREEN, width=50)
            score.grid(row=0, column=2, rowspan=2, padx=8)
            return {"frame": f, "portrait": portrait, "name": name, "why": why, "score": score,
                    "tip": Tooltip(why)}
        self.pick_pool = Pool(factory)

    def _set_pick(self, row, p):
        img = self.images.hero(p.hero, (64, 36))
        setw(row["portrait"], image=img, text="" if img else p.hero.loc[:2])
        setw(row["name"], text=p.hero.loc)
        mates = sorted(p.with_.items(), key=lambda kv: -kv[1])
        foes = sorted(p.vs.items(), key=lambda kv: -kv[1])
        bits = []
        if any(v > 0.5 for _, v in mates):
            bits.append("con " + ", ".join(f"{k} {v:+.1f}" for k, v in mates[:2] if v > 0.5))
        if any(v > 0.5 for _, v in foes):
            bits.append("contra " + ", ".join(f"{k} {v:+.1f}" for k, v in foes[:2] if v > 0.5))
        if p.meta_line and len(bits) < 2:
            bits.append(p.meta_line.split(" · ")[0])
        line = " · ".join(bits)
        setw(row["why"], text=line if len(line) <= 64 else line[:62] + "…")
        row["tip"].text = p.line()
        setw(row["score"], text=f"{p.score:+.1f}", text_color=GREEN if p.score > 0 else RED)

    def _render_draft(self):
        d = self.draft
        if not (self.view and self.view.drafting):
            return
        for key, icons in self.d_rows.items():
            heroes = getattr(d, key) if d else []
            self._set_icons(icons, heroes, self.images, {"allies": GREEN, "enemies": RED}.get(key, CARD2))
        if not d:
            self._empty("draft", "Esperando a ver los héroes elegidos…")
            self.pick_pool.update([], self._set_pick)
            setw(self.d_title, text="")
            return
        self._empty("draft", None if d.picks else
                    ("Calculando…" if d.allies or d.enemies else
                     "En cuanto se vean héroes elegidos (de tu equipo o del rival) saldrán aquí los mejores picks."))
        turn = "  ·  ¡te toca elegir!" if d.my_turn else ""
        title = ("Mejores picks con tu equipo y contra el suyo" if d.enemies and d.allies else
                 "Mejores picks contra sus héroes" if d.enemies else
                 "Mejores picks con tu equipo (pick a ciegas)" if d.allies else "Picks fuertes en este parche")
        setw(self.d_title, text=title + turn, text_color=GREEN if d.my_turn else TEXT)
        origin = "datos de GSI" if d.source == "gsi" else "por la barra superior"
        setw(self.cards["draft"]["extra"], text=origin + (f" · estadísticas: {d.stats_source}" if d.stats_source else ""))
        self.pick_pool.update(d.picks[:6], self._set_pick)

    # ---------- informe de la última partida ----------
    def _build_report(self, body):
        self.r_summary = ctk.CTkLabel(body, text="", font=font(13, "bold"), text_color=TEXT, anchor="w",
                                      wraplength=410, justify="left")
        self.r_summary.grid(row=0, column=0, sticky="ew")
        self.r_stats = ctk.CTkLabel(body, text="", font=font(11), text_color=MUTED, anchor="w", wraplength=410,
                                    justify="left")
        self.r_stats.grid(row=1, column=0, sticky="ew", pady=(2, 6))

        def factory(i):
            lbl = ctk.CTkLabel(body, text="", font=font(11), text_color=TEXT, anchor="w", wraplength=410,
                               justify="left")
            lbl.grid(row=10 + i, column=0, sticky="ew", pady=1)
            return {"frame": lbl, "label": lbl}
        self.note_pool = Pool(factory)

    def _render_report(self):
        r = self.report
        if r is None:
            return
        res_color = {"win": GREEN, "loss": RED}.get(r.result, TEXT)
        setw(self.r_summary, text=r.summary(), text_color=res_color)
        pct = ", ".join(f"{label} {describe(r.percentiles[m])}" for m, label in
                        (("gold_per_min", "oro/min"), ("xp_per_min", "XP/min"), ("last_hits_per_min", "golpes/min"))
                        if m in r.percentiles)
        items = ", ".join(f"{name} {fmt_clock(t)}" for name, t in r.items[-5:])
        setw(self.r_stats, text=" · ".join(x for x in (
            f"Últimos golpes al 10': {r.lh_at_10}" if r.lh_at_10 is not None else "", pct, items) if x))
        notes = [("IA", n) for n in r.ai_notes] + [("", n) for n in r.notes]
        self.note_pool.update(notes[:6], lambda row, item: setw(
            row["label"], text=("✦ " if item[0] else "• ") + item[1], text_color=CYAN if item[0] else TEXT))
        setw(self.cards["report"]["extra"], text="con IA" if r.ai_notes else "")

    # ---------- historial ----------
    def _build_history(self, body):
        self.hi_text = ctk.CTkLabel(body, text="", font=font(12), text_color=TEXT, anchor="w", wraplength=410,
                                    justify="left")
        self.hi_text.grid(row=0, column=0, sticky="ew")

    def _render_history(self):
        h = self.history
        if not h:
            self._empty("history", "Aquí verás el resumen de tus partidas cuando juegues alguna con el coach.")
            setw(self.hi_text, text="")
            return
        self._empty("history", None)
        heroes = ", ".join(f"{name} {wins}/{games}" for name, games, wins in h.heroes[:5])
        lines = [f"{h.games} partidas · {h.wins} victorias, {h.losses} derrotas · {h.avg_deaths:.1f} muertes de media",
                 f"Héroes (victorias/partidas): {heroes}"]
        if h.top_death_zone:
            lines.append(f"Donde más mueres: {h.top_death_zone} · sin enemigos a la vista: {h.fog_death_share:.0%}")
        lines += [f"Se repite: {r}" for r in h.recurring]
        setw(self.hi_text, text="\n".join(lines))
        setw(self.cards["history"]["extra"], text=f"últimas {h.games}")

    # ---------- siguiente compra ----------
    def _build_next(self, body):
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(0, weight=0)
        self.n_icon = ctk.CTkLabel(body, text="", width=48, height=35, fg_color=CARD2, corner_radius=4)
        self.n_name = ctk.CTkLabel(body, text="", font=font(15, "bold"), text_color=TEXT, anchor="w", height=20)
        self.n_cost = ctk.CTkLabel(body, text="", font=font(12), text_color=GOLD, anchor="w", height=16)
        self.n_why = ctk.CTkLabel(body, text="", font=font(10), text_color=MUTED, anchor="w", justify="left",
                                  height=16)
        self.n_why_tip = Tooltip(self.n_why)
        self.n_bar = ctk.CTkProgressBar(body, height=10, fg_color=CARD2)
        self.n_state = ctk.CTkLabel(body, text="", font=font(12, "bold"), text_color=TEXT, anchor="w")
        self.n_plan = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
        self.n_buy = ctk.CTkLabel(body, text="", font=font(13, "bold"), text_color=GREEN, anchor="w",
                                  wraplength=360, justify="left")

        def step_factory(i):
            # ficha de una línea: icono · nombre · precio (o "lo llevas")
            box = ctk.CTkFrame(self.n_plan, fg_color=CARD2, corner_radius=6)
            box.grid(row=i // 3, column=i % 3, padx=(0, 5), pady=(0, 4), sticky="ew")
            icon = ctk.CTkLabel(box, text="", width=28, height=21, fg_color=BG, corner_radius=3)
            icon.grid(row=0, column=0, padx=4, pady=3)
            name = ctk.CTkLabel(box, text="", font=font(10, "bold"), text_color=TEXT, anchor="w", height=21)
            name.grid(row=0, column=1, sticky="w", padx=(0, 4))
            cost = ctk.CTkLabel(box, text="", font=font(10), text_color=GOLD, anchor="w", height=21)
            cost.grid(row=0, column=2, sticky="w", padx=(0, 6))
            return {"frame": box, "icon": icon, "name": name, "cost": cost}
        self.plan_pool = Pool(step_factory)
        self.n_widgets = [(self.n_icon, dict(row=0, column=0, rowspan=2, padx=(0, 12), sticky="nw")),
                          (self.n_name, dict(row=0, column=1, sticky="sw")),
                          (self.n_cost, dict(row=1, column=1, sticky="nw")),
                          (self.n_why, dict(row=2, column=0, columnspan=2, sticky="ew", pady=(3, 0))),
                          (self.n_bar, dict(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 1))),
                          (self.n_state, dict(row=4, column=0, columnspan=2, sticky="w"))]
        # el plan y el "compra ahora" se muestran aparte: solo si el objeto tiene componentes

    def _render_next(self):
        v = self.view
        card = v.next_item if v else None
        setw(self.cards["next"]["extra"], text=PHASE_LABELS.get(v.phase, "") if v and v.hero else "")
        for w, grid in self.n_widgets:
            show(w, card is not None, **grid)
        if not card:
            show(self.n_plan, False)
            show(self.n_buy, False)
            self._empty("next", "Cuando elijas héroe verás aquí qué comprar ahora, según la fase de la partida, "
                                "los enemigos y el parche.")
            return
        self._empty("next", None)
        img = self.images.item(card.short, (60, 44))
        setw(self.n_icon, image=img, text="" if img else "?")
        setw(self.n_name, text=card.loc)
        pay = card.cost if card.to_pay is None else card.to_pay
        setw(self.n_cost, text=f"{card.cost} de oro" + (f" · te quedan {pay} (ya llevas parte)" if pay < card.cost
                                                           else ""))
        why = "; ".join(r.replace("\n", " ") for r in card.reasons[:2])
        setw(self.n_why, text=why if len(why) <= 95 else why[:93] + "…")
        self.n_why_tip.text = "\n".join(card.reasons[:3]) + (f"\nParche: {card.patch_note}" if card.patch_note else "")
        missing = max(0, pay - v.gold)
        progress = round(min(1.0, (card.cost - pay + v.gold) / card.cost) if card.cost else 1.0, 2)
        if _last.setdefault(id(self.n_bar), {}).get("p") != progress:
            self.n_bar.set(progress)
            _last[id(self.n_bar)]["p"] = progress
        setw(self.n_bar, progress_color=GREEN if not missing else GOLD)
        if not card.plan:
            setw(self.n_state, text="¡Ya puedes comprarlo!" if not missing else f"Te faltan {missing} de oro",
                 text_color=GREEN if not missing else TEXT)
        self.plan_pool.update(card.plan, self._set_step)
        show(self.n_plan, bool(card.plan), row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        # "compra ahora" / "siguiente" en la misma línea que lo que falta de oro (ahorra una fila)
        state = "¡Ya puedes comprarlo!" if not missing else f"Te faltan {missing} de oro"
        if card.plan and v.buy_now:
            what = "la receta" if v.buy_now.name == "recipe" else v.buy_now.loc
            setw(self.n_state, text=f"{state}   ➜ Compra ahora: {what} ({v.buy_now.to_pay})", text_color=GREEN)
        elif card.plan:
            nxt = next((s for s in card.plan if not s.owned and s.name != "recipe"), None)
            setw(self.n_state, text=state + (f"   · siguiente: {nxt.loc} ({nxt.to_pay})" if nxt else ""),
                 text_color=GREEN if not missing else TEXT)
        show(self.n_buy, False)

    def _set_step(self, row, step):
        if step.name == "recipe":
            setw(row["icon"], image=None, text="Rx")
        else:
            img = self.images.item(step.short, (28, 21))
            setw(row["icon"], image=img, text="" if img else "?")
        label = ("✓ " if step.owned else "") + step.loc
        setw(row["name"], text=label if len(label) <= 18 else label[:17] + "…", text_color=GREEN if step.owned else TEXT)
        if step.owned:
            setw(row["cost"], text="", text_color=GREEN)
        else:
            setw(row["cost"], text=str(step.to_pay) + (f" (de {step.cost})" if step.to_pay < step.cost else ""),
                 text_color=GOLD)

    @staticmethod
    def _plan_text(card) -> str:
        if not card.plan:
            return ""
        parts = [("✓ " if s.owned else "") + (s.loc if s.owned else f"{s.loc} ({s.to_pay})") for s in card.plan]
        return "\nOrden: " + " → ".join(parts)

    # ---------- inventario (como en el juego: 3x3 con la mochila abajo; neutral y TP a la derecha) ----------
    def _build_inventory(self, body):
        body.grid_columnconfigure(1, weight=1)
        grid = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
        grid.grid(row=0, column=0, sticky="nw")
        self.inv_slots = {}
        size, small = (50, 37), (50, 28)
        for i in range(9):
            r, c = divmod(i, 3)
            backpack = i >= 6
            lbl = ctk.CTkLabel(grid, text="", width=(small if backpack else size)[0],
                               height=(small if backpack else size)[1], fg_color=BG if backpack else CARD2,
                               corner_radius=4)
            lbl.grid(row=r, column=c, padx=(0, 4), pady=(4 if backpack else 0, 3))
            self.inv_slots[f"slot{i}"] = (lbl, small if backpack else size, Tooltip(lbl), backpack)
        for r, (slot, label) in enumerate((("neutral0", "Neutral"), ("teleport0", "TP"))):
            lbl = ctk.CTkLabel(grid, text="", width=36, height=36, fg_color=CARD2, corner_radius=18)
            lbl.grid(row=r, column=3, padx=(12, 4), pady=(0, 3))
            ctk.CTkLabel(grid, text=label, font=font(9), text_color=MUTED).grid(row=r, column=4, sticky="w")
            self.inv_slots[slot] = (lbl, (36, 27), Tooltip(lbl), False)
        notes = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
        notes.grid(row=0, column=1, sticky="nw", padx=(12, 0))
        self.inv_transit = ctk.CTkLabel(notes, text="", font=font(10, "bold"), text_color=CYAN, anchor="w",
                                        justify="left", wraplength=170)
        self.inv_transit.pack(anchor="w")
        self.inv_note = ctk.CTkLabel(notes, text="", font=font(10), text_color=MUTED, anchor="w", justify="left",
                                     wraplength=170)
        self.inv_note.pack(anchor="w")

    def _render_inventory(self):
        v = self.view
        slots = dict(v.inventory) if v else {}
        for slot, (lbl, size, tip, backpack) in self.inv_slots.items():
            name = slots.get(slot)
            img = self.images.item(name.removeprefix("item_"), size) if name else None
            setw(lbl, image=img, text="" if img or not name else "?")
            tip.text = (self._loc(name) + (" (mochila)" if backpack else "")) if name else ""
        transit = v.in_transit if v else []
        setw(self.inv_transit, text=("En el courier: " + ", ".join(self._loc(n) for n in transit)) if transit else "")
        stash = v.stash if v else []
        setw(self.inv_note, text=("En el alijo: " + ", ".join(self._loc(n) for n in stash)) if stash else "")

    def _loc(self, name: str) -> str:
        return (self.item_names or {}).get(name) or name.removeprefix("item_").replace("_", " ").title()

    # ---------- líneas ----------
    def _hero_icon(self, parent, size=(52, 29)):
        lbl = ctk.CTkLabel(parent, text="", width=size[0], height=size[1], fg_color=CARD2, corner_radius=3)
        return lbl, Tooltip(lbl)

    def _build_lanes(self, body):
        """Con posiciones: top/mid/bot con aliados contra enemigos. Antes (primeros minutos): los detectados."""
        self.lane_rows = {}
        for i, lane in enumerate(("top", "mid", "bot")):
            label = ctk.CTkLabel(body, text=lane.capitalize(), font=font(12, "bold"), text_color=MUTED, width=64,
                                 anchor="w", height=31)
            allies = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
            vs = ctk.CTkLabel(body, text="vs", font=font(10), text_color=MUTED, height=31)
            enemies = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
            icons = []
            for side, frame in (("a", allies), ("e", enemies)):
                for j in range(3):
                    lbl, tip = self._hero_icon(frame)
                    icons.append((side, j, lbl, tip))
            self.lane_rows[lane] = (i, label, allies, vs, enemies, icons)
        self.lane_outlook = ctk.CTkLabel(body, text="", font=font(11, "bold"), anchor="w")
        self.detected = {}
        for i, (side, title) in enumerate((("a", "Aliados"), ("e", "Enemigos"))):
            label = ctk.CTkLabel(body, text=title, font=font(12, "bold"), text_color=MUTED, width=64, anchor="w",
                                 height=31)
            strip = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
            icons = [self._hero_icon(strip) for _ in range(5)]
            self.detected[side] = (i, label, strip, icons)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(3, weight=1)

    @staticmethod
    def _set_icons(icons, heroes, images, color):
        for j, (lbl, tip) in enumerate(icons):
            if j >= len(heroes):
                pack_show(lbl, False)
                continue
            pack_show(lbl, True, side="left", padx=2)
            h = heroes[j]
            img = images.hero(h, (52, 29))
            setw(lbl, image=img, text="" if img else h.loc[:2], fg_color=color)
            tip.text = h.loc

    def _render_lanes(self):
        v = self.view
        lanes = v.lanes if v else {}
        has_lanes = any(info.allies or info.enemies for info in lanes.values())
        allies = (v.allies + ([v.hero] if v.hero else [])) if v else []
        enemies = [e.hero for e in v.enemies] if v else []
        for lane, (i, label, a_frame, vs, e_frame, icons) in self.lane_rows.items():
            for w, col, kw in ((label, 0, dict(sticky="w")), (a_frame, 1, dict(sticky="e")),
                               (vs, 2, dict(padx=6)), (e_frame, 3, dict(sticky="w"))):
                show(w, has_lanes, row=i, column=col, pady=2, **kw)
            if not has_lanes:
                continue
            info = lanes.get(lane)
            mine = v.my_lane == lane
            setw(label, text=lane.capitalize() + (" · tú" if mine else ""), text_color=ACCENT if mine else MUTED)
            for side in ("a", "e"):
                heroes = (info.allies if side == "a" else info.enemies) if info else []
                self._set_icons([(lbl, tip) for s_, _, lbl, tip in icons if s_ == side], heroes, self.images,
                                GREEN if side == "a" else RED)
        show_detected = not has_lanes and bool(allies or enemies)
        for side, (i, label, strip, icons) in self.detected.items():
            show(label, show_detected, row=10 + i, column=0, sticky="w", pady=2)
            show(strip, show_detected, row=10 + i, column=1, columnspan=3, sticky="w", pady=2)
            if show_detected:
                self._set_icons(icons, allies if side == "a" else enemies, self.images,
                                GREEN if side == "a" else RED)
        outlook = v.lane_outlook if v else None
        if outlook:
            win, draw, loss, games = outlook
            setw(self.lane_outlook, text=f"Tu línea suele acabar: {win:.0%} ganada · {draw:.0%} igualada · "
                                         f"{loss:.0%} perdida  ({games} partidas en STRATZ)",
                 text_color=GREEN if win > loss + 0.05 else RED if loss > win + 0.05 else MUTED)
        show(self.lane_outlook, bool(outlook and has_lanes), row=20, column=0, columnspan=4, sticky="w", pady=(4, 0))
        setw(self.cards["lanes"]["extra"], text="" if has_lanes else "se reparten en los primeros minutos")
        self._empty("lanes", None if (has_lanes or show_detected) else
                    "Se calculan solas en los primeros minutos con las posiciones del mapa.")

    # ---------- build por fases ----------
    def _build_phases(self, body):
        self.ph_rows = {}
        self.ph_strips = {}
        for i, phase in enumerate(PHASES):
            title = ctk.CTkLabel(body, text=PHASE_LABELS[phase], font=font(12, "bold"), text_color=MUTED,
                                 anchor="w")
            title.configure(width=96)
            title.grid(row=i, column=0, sticky="w", pady=2)
            strip = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
            strip.grid(row=i, column=1, sticky="w", pady=2)
            self.ph_strips[phase] = strip
            slots = []
            for j in range(6):
                icon = ctk.CTkLabel(strip, text="", width=42, height=31, fg_color=CARD2, corner_radius=4)
                icon.grid(row=0, column=j, padx=(0, 4))
                slots.append({"frame": icon, "icon": icon, "tip": Tooltip(icon), "col": j})
            self.ph_rows[phase] = (title, slots)

    def _render_phases(self):
        v = self.view
        builds = v.phase_builds if v else {}
        self._empty("phases", None if builds else "Sin héroe todavía.")
        now = PHASES.index(v.phase) if v and v.phase in PHASES else 0
        for i, (phase, (title, slots)) in enumerate(self.ph_rows.items()):
            past = i < now  # las fases que ya pasaron no se enseñan
            show(title, not past)
            show(self.ph_strips[phase], not past)
            current = v is not None and phase == v.phase
            setw(title, text=("▶ " if current else "") + PHASE_LABELS[phase],
                 text_color=ACCENT if current else MUTED)
            cards = builds.get(phase, [])
            for slot, card in zip(slots, cards + [None] * (len(slots) - len(cards))):
                if card is None:
                    show(slot["frame"], False)
                    continue
                show(slot["frame"], True, row=0, column=slot["col"], padx=(0, 4))
                img = self.images.item(card.short, (42, 31))
                setw(slot["icon"], image=img, text="" if img else "?")
                slot["tip"].text = f"{card.loc} · {card.cost} de oro\n" + "\n".join(card.reasons[:3]) + \
                    (f"\nParche: {card.patch_note}" if card.patch_note else "") + self._plan_text(card)

    # ---------- enemigos ----------
    def _build_enemies(self, body):
        body.grid_columnconfigure(1, weight=1)

        def factory(i):
            f = ctk.CTkFrame(body, fg_color=CARD2, corner_radius=6)
            f.grid(row=i, column=0, columnspan=2, sticky="ew", pady=(0, 4))
            f.grid_columnconfigure(1, weight=1)
            portrait = ctk.CTkLabel(f, text="", width=64, height=36, fg_color=BG, corner_radius=4)
            portrait.grid(row=0, column=0, rowspan=2, padx=6, pady=5, sticky="w")
            title = ctk.CTkFrame(f, fg_color="transparent", width=1, height=1)
            title.grid(row=0, column=1, sticky="ew", pady=(3, 0))
            name = ctk.CTkLabel(title, text="", font=font(13, "bold"), text_color=TEXT, height=18)
            name.pack(side="left")
            wr = ctk.CTkLabel(title, text="", font=font(10), text_color=MUTED, height=18)
            wr.pack(side="left", padx=(6, 0))
            verdict = ctk.CTkLabel(title, text="", font=font(10, "bold"), text_color=MUTED, height=18)
            verdict.pack(side="left", padx=(6, 0))
            traits = ctk.CTkLabel(f, text="", font=font(10), text_color=MUTED, anchor="w", height=16)
            traits.grid(row=1, column=1, sticky="ew", pady=(0, 3))
            strip = ctk.CTkFrame(f, fg_color="transparent", width=1, height=1)
            strip.grid(row=0, column=2, rowspan=2, padx=(4, 6))
            counters = []
            for j in range(3):
                icon = ctk.CTkLabel(strip, text="", width=40, height=30, fg_color=BG, corner_radius=3)
                icon.grid(row=0, column=j, padx=(0, 3))
                counters.append({"frame": icon, "icon": icon, "tip": Tooltip(icon), "col": j})
            tips = Tooltip(traits)
            return {"frame": f, "portrait": portrait, "name": name, "wr": wr, "verdict": verdict, "traits": traits,
                    "traits_tip": tips, "counters": counters}
        self.enemy_pool = Pool(factory)

    def _set_enemy(self, row, e: HeroCard):
        img = self.images.hero(e.hero, (80, 45))
        setw(row["portrait"], image=img, text="" if img else e.hero.loc[:2])
        setw(row["name"], text=e.hero.loc)
        if e.winrate is None:
            setw(row["wr"], text="")
        else:
            setw(row["wr"], text=f"{e.winrate:.1%} WR",
                 text_color=GREEN if e.winrate >= 0.52 else RED if e.winrate <= 0.48 else MUTED)
        setw(row["verdict"], text=e.verdict.upper(), text_color=VERDICT_COLORS.get(e.verdict, YELLOW))
        traits = ", ".join(e.traits) or "–"
        setw(row["traits"], text=traits if len(traits) <= 46 else traits[:44] + "…")
        row["traits_tip"].text = traits
        for slot, card in zip(row["counters"], e.counters + [None] * (3 - len(e.counters))):
            if card is None:
                show(slot["frame"], False)
                continue
            show(slot["frame"], True, row=0, column=slot["col"], padx=(0, 3))
            icon = self.images.item(card.short, (40, 30))
            setw(slot["icon"], image=icon, text="" if icon else "?")
            slot["tip"].text = f"Contra {e.hero.loc}: {card.loc} · {card.cost} de oro\n" + \
                (card.reasons[0] if card.reasons else "")

    def _render_enemies(self):
        enemies = self.view.enemies if self.view else []
        setw(self.cards["enemies"]["extra"], text=f"{len(enemies)}/5 detectados")
        self._empty("enemies", None if enemies else "Se detectan solos en la barra superior y el minimapa. También "
                                                    "puedes indicarlos en los ajustes antes de iniciar el coach.")
        self.enemy_pool.update(enemies, self._set_enemy)

    # ---------- mapa ----------
    MAP_SIZE = 300

    def _build_map(self, body):
        self.map_label = ctk.CTkLabel(body, text="", width=self.MAP_SIZE, height=self.MAP_SIZE, fg_color=CARD2,
                                      corner_radius=6)
        self.map_label.grid(row=0, column=0)

    def _render_map(self):
        frame = self.minimap_frame
        if frame is None:
            self._empty("map", "El minimapa aparecerá aquí durante la partida (se lee de la pantalla: juega en "
                               "ventana sin bordes o pantalla completa en ventana).")
            show(self.map_label, False)
            return
        if frame is self._minimap_shown:
            return
        self._minimap_shown = frame
        self._empty("map", None)
        show(self.map_label, True, row=0, column=0)
        img = ctk.CTkImage(light_image=frame, dark_image=frame, size=(self.MAP_SIZE, self.MAP_SIZE))
        self.map_label.configure(image=img)
        self._map_image = img  # que no se libere mientras se muestra

    # ---------- consejos ----------
    def _build_tips(self, body):
        def factory(i):
            f = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
            f.grid(row=i, column=0, sticky="ew", pady=(0, 4))
            f.grid_columnconfigure(1, weight=1)
            meta = ctk.CTkLabel(f, text="", font=font(10, "bold"), anchor="nw", width=78, height=16)
            meta.grid(row=0, column=0, sticky="nw", pady=(1, 0))
            text = ctk.CTkLabel(f, text="", font=font(11), text_color=TEXT, wraplength=260, justify="left",
                                anchor="w")
            text.grid(row=1, column=0, columnspan=2, sticky="ew")
            return {"frame": f, "meta": meta, "text": text}
        self.tip_pool = Pool(factory)

    def _set_tip(self, row, item):
        i, t = item
        label = f"{fmt_clock(t.clock)} {KIND_LABELS.get(t.kind, t.kind.upper())}" + (" ·IA" if t.source == "ai" else "")
        setw(row["meta"], text=label, text_color=KIND_COLORS.get(t.kind, MUTED))
        setw(row["text"], text=t.text, font=font(13 if i == 0 else 12), text_color=TEXT if i == 0 else MUTED)

    def _render_tips(self):
        if self._tips_shown == len(self.tips):
            return
        self._tips_shown = len(self.tips)
        setw(self.cards["tips"]["extra"], text=str(len(self.tips)) if self.tips else "")
        self._empty("tips", None if self.tips else "Los consejos y avisos del mapa aparecerán aquí.")
        self.tip_pool.update(list(enumerate(reversed(self.tips[-TIP_ROWS:]))), self._set_tip)

    # ---------- partidas parecidas ----------
    def _build_similar(self, body):
        self.s_summary = ctk.CTkLabel(body, text="", font=font(11), text_color=TEXT, wraplength=410,
                                      justify="left", anchor="w")
        self.s_strip = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
        self.s_slots = []
        for j in range(6):
            box = ctk.CTkFrame(self.s_strip, fg_color="transparent", width=1, height=1)
            icon = ctk.CTkLabel(box, text="", width=38, height=28, fg_color=CARD2, corner_radius=4)
            icon.pack()
            count = ctk.CTkLabel(box, text="", font=font(9, "bold"), text_color=GREEN, height=12)
            count.pack()
            self.s_slots.append({"frame": box, "icon": icon, "count": count, "tip": Tooltip(icon), "col": j})

        def factory(i):
            f = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
            f.grid(row=10 + i, column=0, sticky="ew", pady=1)
            res = ctk.CTkLabel(f, text="", font=font(11, "bold"), width=70, anchor="w")
            res.pack(side="left")
            icons = []
            for _ in range(6):
                lbl = ctk.CTkLabel(f, text="", width=30, height=22, fg_color=CARD2, corner_radius=3)
                icons.append({"icon": lbl, "tip": Tooltip(lbl)})
            return {"frame": f, "res": res, "icons": icons}
        self.match_pool = Pool(factory)

    def _set_match(self, row, m):
        setw(row["res"], text=f"{'GANA' if m.win else 'pierde'} {m.duration // 60}'",
             text_color=GREEN if m.win else RED)
        for slot, name in zip(row["icons"], m.items[:6] + [None] * (6 - len(m.items[:6]))):
            if name is None:
                pack_show(slot["icon"], False)
                continue
            pack_show(slot["icon"], True, side="left", padx=(0, 3))
            img = self.images.item(name.removeprefix("item_"), (30, 22))
            setw(slot["icon"], image=img, text="" if img else "?")
            slot["tip"].text = self._item_name(name)

    def _item_name(self, name: str) -> str:
        names = self.similar.names if self.similar else {}
        return names.get(name) or name.removeprefix("item_").replace("_", " ").title()

    def _render_similar(self):
        r = self.similar
        has = r is not None
        show(self.s_summary, has, row=0, column=0, sticky="ew")
        show(self.s_strip, has, row=1, column=0, sticky="w", pady=(4, 4))
        if not has:
            setw(self.cards["similar"]["extra"], text="")
            msg = {"buscando": "Buscando partidas parecidas en OpenDota…",
                   "sin datos": "No hay partidas recientes con esta combinación de héroes."}.get(
                self.similar_state, "Cuando haya héroe y enemigos detectados, se buscan partidas recientes con esa "
                                    "combinación y qué compraron los que ganaron.")
            self._empty("similar", msg)
            self.match_pool.update([], self._set_match)
            return
        self._empty("similar", None)
        setw(self.cards["similar"]["extra"], text=f"{r.wins}/{len(r.matches)} ganadas")
        vs = ", ".join(h.loc for h in r.vs)
        setw(self.s_summary, text=f"Contra {vs}: lo que llevaban al final los que ganaron")
        for slot, item in zip(self.s_slots, r.top_items + [None] * (6 - len(r.top_items))):
            if item is None:
                show(slot["frame"], False)
                continue
            name, n = item
            show(slot["frame"], True, row=0, column=slot["col"], padx=(0, 4))
            img = self.images.item(name.removeprefix("item_"), (44, 32))
            setw(slot["icon"], image=img, text="" if img else "?")
            setw(slot["count"], text=f"{n}/{r.wins}")
            slot["tip"].text = f"{self._item_name(name)}: en {n} de {r.wins} victorias"
        self.match_pool.update(r.matches[:3], self._set_match)

    # ---------- parche ----------
    def _build_patch(self, body):
        body.grid_columnconfigure(1, weight=1)

        def factory(i):
            f = ctk.CTkFrame(body, fg_color="transparent", width=1, height=1)
            f.grid(row=i, column=0, columnspan=2, sticky="ew", pady=0)
            f.grid_columnconfigure(1, weight=1)
            tag = ctk.CTkLabel(f, text="", font=font(10, "bold"), width=58, anchor="w", height=18)
            tag.grid(row=0, column=0, sticky="nw")
            text = ctk.CTkLabel(f, text="", font=font(11), text_color=TEXT, anchor="w", height=18)
            text.grid(row=0, column=1, sticky="ew")
            return {"frame": f, "tag": tag, "text": text, "tip": Tooltip(text)}
        self.patch_pool = Pool(factory)

    def _set_change(self, row, ch):
        setw(row["tag"], text=ch.tag, text_color=GREEN if ch.direction > 0 else RED if ch.direction < 0 else MUTED)
        full = f"{ch.detail}: {ch.text}"
        setw(row["text"], text=full if len(full) <= 52 else full[:50] + "…")
        row["tip"].text = full

    def _render_patch(self):
        """Tu héroe en el parche, en una línea de la cabecera (todos los cambios al pasar el ratón)."""
        v = self.view
        changes = v.my_changes if v else []
        if not (v and v.hero and changes):
            setw(self.h_patch, text="Tu héroe no cambia en este parche" if v and v.hero else "")
            self.h_patch_tip.text = ""
            return
        ups = sum(1 for c in changes if c.direction > 0)
        downs = sum(1 for c in changes if c.direction < 0)
        top = max(changes, key=lambda c: abs(c.direction))
        first = f"{top.detail}: {top.text}"
        first = first if len(first) <= 70 else first[:68] + "…"
        tone = GREEN if ups > downs else RED if downs > ups else MUTED
        setw(self.h_patch, text=f"Tu héroe en el parche {self.patch}: ▲{ups} ▼{downs}  ·  {first}",
             text_color=tone)
        more = f"\n… y {len(changes) - 14} más" if len(changes) > 14 else ""
        self.h_patch_tip.text = "\n".join(f"{c.tag:6s} {c.detail}: {c.text}" for c in changes[:14]) + more

    # ---------- bucle ----------
    def _render(self):
        for part in (self._render_mode, self._render_draft, self._render_report, self._render_history,
                     self._render_header, self._render_map, self._render_inventory, self._render_next,
                     self._render_lanes, self._render_phases,
                     self._render_enemies, self._render_tips, self._render_similar, self._render_battle,
                     self._render_patch, self._render_skills, self._render_mylane, self._render_theme):
            try:
                part()
            except Exception:
                log.exception("error pintando el panel (%s)", part.__name__)

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "view":
                    self.view = payload
                    self.last_state = self.view_time = time.time()
                elif kind == "tips":
                    self.tips = (self.tips + list(payload))[-MAX_TIPS:]
                elif kind == "similar":
                    self.similar, self.similar_state = payload, "" if payload else "sin datos"
                elif kind == "similar_searching":
                    self.similar, self.similar_state = None, "buscando"
                elif kind == "toast":
                    self.toast.show(payload.get("title", ""), payload.get("text", ""), payload.get("level", "info"),
                                    TOAST_ICONS.get(payload.get("icon", ""), "●"))
                elif kind == "draft":
                    self.draft = payload
                elif kind == "report":
                    self.report = payload
                elif kind == "history":
                    self.history = payload
                elif kind == "minimap":
                    self.minimap_frame = payload
                elif kind == "reset":
                    self.tips, self.view, self.similar, self.similar_state = [], None, None, ""
                    self.draft = None
                    self._tips_shown = -1
        except queue.Empty:
            pass
        if self.images.changed.is_set():  # llegaron retratos/iconos nuevos: los siguientes setw los pondrán
            self.images.changed.clear()
            self._tips_shown = -1
        self._render()
        self.after(300, self._poll)

    def on_close(self):
        try:
            fresh = config.load()  # no pisar lo que se haya cambiado en los ajustes mientras tanto
            fresh.setdefault("panel", {}).update(geometry=self.geometry(), on_top=bool(self.v_top.get()))
            config.save(fresh)
        except OSError:
            pass
        self.destroy()
