"""Ventana de ajustes (CustomTkinter, mismo estilo que el traductor).

Todo se guarda al momento en config.json. El modo en directo se lanza como proceso aparte (con su consola,
donde también se ven los consejos): lee la configuración al arrancar, así que los cambios se aplican al
reiniciarlo.
"""
import copy
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from .. import config, dota
from ..ai import KEY_PAGES, PROVIDER_IDS, make_provider, needs_key, provider_label, set_ai, stored_key

log = logging.getLogger(__name__)

BG, CARD, CARD2 = "#0E1217", "#1A212A", "#222B36"
TEXT, MUTED, ACCENT, ACCENT_HOVER = "#E6EAEE", "#8B96A3", "#C8402B", "#A9331F"
GREEN, YELLOW, RED = "#5FCF80", "#F2C94C", "#E5534B"

ROLES = {"auto": "Automático (según el héroe)", "carry": "Carry (posición 1)", "core": "Core (mid / offlane)",
         "support": "Support"}
BRACKETS = ["Todos", "Herald", "Guardian", "Crusader", "Archon", "Legend", "Ancient", "Divine", "Immortal"]
PROVIDERS = ["none", *PROVIDER_IDS]
ROOT = Path(__file__).resolve().parents[2]


def font(size=13, weight="normal"):
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


def windowless_python(executable: str | None = None) -> str:
    """pythonw.exe (sin ventana de consola) junto al Python actual, si existe."""
    exe = Path(executable or sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return str(pythonw if pythonw.exists() else exe)


def live_command(enemies: str = "") -> list[str]:
    """Orden para lanzar el modo en directo SIN consola (con pythonw o desde el .exe empaquetado)."""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "run"]
    else:
        cmd = [windowless_python(), str(ROOT / "run.py"), "run"]
    return cmd + (["--enemies", enemies] if enemies.strip() else [])


class SettingsApp(ctk.CTk):
    def __init__(self, cfg: dict):
        super().__init__(fg_color=BG)
        ctk.set_appearance_mode("dark")
        self.cfg = cfg
        self.title("Dota Coach · Ajustes")
        self.geometry("820x760")
        self.minsize(720, 560)
        self.proc: subprocess.Popen | None = None
        self.preview = None  # overlay de prueba

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 6))
        ctk.CTkLabel(head, text="DOTA", font=font(24, "bold"), text_color=ACCENT).pack(side="left")
        ctk.CTkLabel(head, text="  Coach", font=font(20, "bold"), text_color=TEXT).pack(side="left")
        self.sc = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.sc.grid(row=1, column=0, sticky="nsew", padx=(18, 8), pady=(0, 14))
        self.sc.grid_columnconfigure(0, weight=1)
        self._row = 0

        self._build_coach()
        self._build_ai()
        self._build_game()
        self._build_dota()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(1000, self._poll_process)

    # ================= utilidades =================
    def _update(self, change):
        """Aplica 'change(cfg)' sobre la configuración del DISCO y la guarda. Así esta ventana nunca pisa con
        valores viejos lo que se cambió en otra ventana o desde la línea de órdenes."""
        fresh = config.load()
        change(fresh)
        config.save(fresh)
        self.cfg.clear()
        self.cfg.update(fresh)

    def set(self, path: str, value):
        """Cambia 'a.b' en la configuración y la guarda."""
        *parents, last = path.split(".")

        def change(cfg):
            d = cfg
            for k in parents:
                d = d.setdefault(k, {})
            d[last] = value
        self._update(change)

    def _section(self, title: str, desc: str = "") -> ctk.CTkFrame:
        c = ctk.CTkFrame(self.sc, fg_color=CARD, corner_radius=12)
        c.grid(row=self._row, column=0, sticky="ew", pady=(0, 14), padx=(0, 6))
        c.grid_columnconfigure(1, weight=1)
        self._row += 1
        ctk.CTkLabel(c, text=title.upper(), font=font(11, "bold"), text_color=MUTED).grid(
            row=0, column=0, columnspan=2, padx=16, pady=(14, 2), sticky="w")
        if desc:
            ctk.CTkLabel(c, text=desc, font=font(12), text_color=MUTED, wraplength=640, justify="left").grid(
                row=1, column=0, columnspan=2, padx=16, pady=(0, 6), sticky="w")
        return c

    def _label(self, parent, row: int, text: str):
        ctk.CTkLabel(parent, text=text, font=font(13), text_color=TEXT).grid(
            row=row, column=0, padx=16, pady=7, sticky="w")

    def _menu(self, parent, row: int, values: list[str], current: str, command, width=300):
        var = tk.StringVar(value=current)
        ctk.CTkOptionMenu(parent, values=values, variable=var, width=width, fg_color=CARD2, button_color=CARD2,
                          button_hover_color=ACCENT, dropdown_font=font(12), command=command).grid(
            row=row, column=1, padx=16, pady=7, sticky="w")
        return var

    def _switch(self, parent, row: int, text: str, path: str, value: bool, on_change=None):
        var = tk.BooleanVar(value=value)

        def changed():
            self.set(path, bool(var.get()))
            if on_change:
                on_change()
        ctk.CTkSwitch(parent, text=text, variable=var, progress_color=ACCENT, font=font(13), command=changed).grid(
            row=row, column=0, columnspan=2, padx=16, pady=7, sticky="w")
        return var

    def _slider(self, parent, row: int, text: str, path: str, lo, hi, steps: int, fmt: str, integer: bool,
                on_change=None):
        self._label(parent, row, text)
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=1, padx=16, sticky="ew")
        *parents, last = path.split(".")
        d = self.cfg
        for k in parents:
            d = d[k]
        val = ctk.CTkLabel(box, text=fmt.format(d[last]), width=56, font=font(12), text_color=MUTED)
        val.pack(side="right")

        def moved(v):
            v = int(round(v)) if integer else round(v, 3)
            val.configure(text=fmt.format(v))
            self.set(path, v)
            if on_change:
                on_change()
        s = ctk.CTkSlider(box, from_=lo, to=hi, number_of_steps=steps, command=moved, button_color=ACCENT,
                          progress_color=ACCENT, button_hover_color=ACCENT_HOVER)
        s.set(d[last])
        s.pack(side="left", fill="x", expand=True, padx=(0, 10))

    def _button(self, parent, text: str, command, primary=False, width=150):
        return ctk.CTkButton(parent, text=text, width=width, command=command,
                             fg_color=ACCENT if primary else CARD2, hover_color=ACCENT_HOVER if primary else ACCENT)

    # ================= coach en directo =================
    def _build_coach(self):
        c = self._section("Coach en directo", "Lanza el coach: escucha la partida (GSI), lee la pantalla (barra "
                          "superior y minimapa) y lo muestra todo en el panel de partida, una ventana aparte (ideal "
                          "en un segundo monitor). Nada se dibuja encima del juego. Los cambios de ajustes se "
                          "aplican al reiniciarlo.")
        self._label(c, 2, "Enemigos (opcional)")
        self.e_enemies = ctk.CTkEntry(c, height=32, fg_color=CARD2, border_color=CARD2,
                                      placeholder_text="p. ej. pa, lion, tide — si no, se detectan solos")
        self.e_enemies.grid(row=2, column=1, padx=16, pady=7, sticky="ew")
        self._build_autostart(c, 3)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.grid(row=5, column=0, columnspan=2, padx=16, pady=(6, 16), sticky="w")
        self.btn_live = self._button(row, "Iniciar coach", self._toggle_live, primary=True)
        self.btn_live.pack(side="left", padx=(0, 8))
        self._button(row, "Carpeta de datos", lambda: os.startfile(config.APP_DIR)).pack(side="left", padx=(0, 12))
        self.live_status = ctk.CTkLabel(row, text="● Detenido", font=font(12), text_color=MUTED)
        self.live_status.pack(side="left")

    def _build_autostart(self, c, row: int):
        """Abrir el coach solo al lanzar Dota: se guarda en el arranque de Windows del usuario, no en config.json."""
        from .. import autostart
        try:
            enabled = autostart.is_enabled()
        except OSError:
            enabled = False
        var = tk.BooleanVar(value=enabled)

        def changed():
            try:
                autostart.set_enabled(bool(var.get()))
                self.live_status.configure(text="● Se abrirá solo con Dota" if var.get() else "● Detenido",
                                           text_color=GREEN if var.get() else MUTED)
            except OSError as ex:
                var.set(not var.get())
                self.live_status.configure(text=f"● No se pudo cambiar el arranque: {ex}", text_color=RED)
        ctk.CTkSwitch(c, text="Abrir el coach automáticamente al lanzar Dota (y cerrarlo al salir)", variable=var,
                      progress_color=ACCENT, font=font(13), command=changed).grid(
            row=row, column=0, columnspan=2, padx=16, pady=7, sticky="w")

    def _toggle_live(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            return
        self._save_ai_fields()
        # nunca una ventana de consola: todo se ve en el panel y queda en coach.log
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            cwd = None if getattr(sys, "frozen", False) else str(ROOT)
            self.proc = subprocess.Popen(live_command(self.e_enemies.get()), cwd=cwd, creationflags=flags)
        except OSError as ex:
            self.live_status.configure(text=f"● No se pudo iniciar: {ex}", text_color=RED)
            return
        self._refresh_live()

    def _poll_process(self):
        self._refresh_live()
        self.after(1000, self._poll_process)

    def _refresh_live(self):
        running = bool(self.proc and self.proc.poll() is None)
        self.btn_live.configure(text="Detener coach" if running else "Iniciar coach",
                                fg_color=CARD2 if running else ACCENT)
        if running:
            self.live_status.configure(text="● En marcha", text_color=GREEN)
        elif self.proc is not None:
            code = self.proc.returncode
            normal = code in (0, 1, 15, -15)  # salida normal o detenido desde aquí
            self.live_status.configure(text="● Detenido" if normal else f"● Se cerró con error ({code})",
                                       text_color=MUTED if normal else RED)

    # ================= IA =================
    def _build_ai(self):
        c = self._section("Inteligencia artificial", "Opcional: sin IA el coach funciona con reglas y estadísticas. "
                          "Con IA los consejos tienen en cuenta toda la partida. La clave se guarda cifrada con tu "
                          "usuario de Windows.")
        ai = self.cfg["ai"]
        self._label(c, 2, "Proveedor")
        self.v_provider = self._menu(c, 2, [provider_label(p) for p in PROVIDERS],
                                     provider_label(ai.get("provider", "none")), self._on_provider)
        self.ai_fields = {}
        for i, (key, label, show) in enumerate([("key", "Clave de API", "•"), ("model", "Modelo", None),
                                                ("base_url", "URL del servidor", None)], start=3):
            lbl = ctk.CTkLabel(c, text=label, font=font(13), text_color=TEXT)
            lbl.grid(row=i, column=0, padx=16, pady=5, sticky="w")
            ent = ctk.CTkEntry(c, height=32, fg_color=CARD2, border_color=CARD2, **({"show": show} if show else {}))
            ent.grid(row=i, column=1, padx=16, pady=5, sticky="ew")
            ent.bind("<FocusOut>", lambda _e: self._save_ai_fields())
            self.ai_fields[key] = (lbl, ent)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.grid(row=6, column=0, columnspan=2, padx=16, pady=(8, 4), sticky="w")
        self.btn_key_page = self._button(row, "Conseguir clave", self._open_key_page)
        self.btn_key_page.pack(side="left", padx=(0, 8))
        self.btn_test = self._button(row, "Probar", self._test_ai, primary=True, width=110)
        self.btn_test.pack(side="left")
        self.ai_status = ctk.CTkLabel(c, text="", font=font(12), text_color=MUTED, wraplength=640, justify="left")
        self.ai_status.grid(row=7, column=0, columnspan=2, padx=16, pady=(4, 16), sticky="w")
        self._load_ai_fields()

    def _provider_id(self) -> str:
        return self.cfg["ai"].get("provider", "none")

    def _load_ai_fields(self):
        pid = self._provider_id()
        enabled = pid != "none"
        self.v_provider.set(provider_label(pid))
        values = {"key": stored_key(self.cfg, pid) if enabled else "",
                  "model": self.cfg["ai"].get("model", "") if enabled else "",
                  "base_url": self.cfg["ai"].get("base_url", "") if pid == "custom" else ""}
        for key, (lbl, ent) in self.ai_fields.items():
            ent.delete(0, "end")
            ent.insert(0, values[key])
            visible = enabled and (key != "base_url" or pid == "custom")
            for w in (lbl, ent):
                (w.grid if visible else w.grid_remove)()
        if enabled:
            default = "claude-opus-5-5" if pid == "claude" else "el que elija el proveedor"
            self.ai_fields["model"][1].configure(placeholder_text=f"vacío = automático ({default})")
            self.ai_fields["key"][0].configure(text="Clave de API" if needs_key(pid) else "Clave (opcional)")
        if pid == "custom":
            self.ai_fields["base_url"][1].configure(placeholder_text="http://127.0.0.1:11434/v1")
        self.btn_key_page.configure(state="normal" if pid in KEY_PAGES else "disabled")
        self.btn_test.configure(state="normal" if enabled else "disabled")
        self.ai_status.configure(text="", text_color=MUTED)
        self._shown_provider, self._ai_loaded = pid, self._ai_values()

    def _on_provider(self, label: str):
        pid = next(p for p in PROVIDERS if provider_label(p) == label)
        if pid == self._shown_provider:
            return
        self._save_ai_fields()
        self._update(lambda cfg: set_ai(cfg, pid))
        self._load_ai_fields()

    def _ai_values(self) -> tuple[str, str, str]:
        return tuple(self.ai_fields[k][1].get().strip() for k in ("key", "model", "base_url"))

    def _save_ai_fields(self):
        """Guarda la clave/modelo/URL solo si se han editado en esta ventana."""
        pid = self._shown_provider
        if pid == "none" or self._ai_values() == self._ai_loaded:
            return
        key, model, url = self._ai_values()
        self._update(lambda cfg: set_ai(cfg, pid, key=key, model=model, base_url=url if pid == "custom" else None))
        self._ai_loaded = self._ai_values()
        self.ai_status.configure(text="Guardado.", text_color=MUTED)

    def _open_key_page(self):
        page = KEY_PAGES.get(self._shown_provider)
        if page:
            webbrowser.open(page)

    def _test_ai(self):
        self._save_ai_fields()
        pid = self._shown_provider
        test_cfg = set_ai(copy.deepcopy(config.load()), pid)  # el proveedor que se ve en esta ventana
        if needs_key(pid) and pid != "claude" and not stored_key(test_cfg, pid):
            self.ai_status.configure(text="Falta la clave de API.", text_color=YELLOW)
            return
        provider = make_provider(test_cfg)
        if provider is None:
            self.ai_status.configure(text="Falta la clave de API.", text_color=YELLOW)
            return
        self.ai_status.configure(text="Probando…", text_color=MUTED)
        self.btn_test.configure(state="disabled")
        q: queue.Queue = queue.Queue()

        def run():
            t0 = time.time()
            try:
                out = provider.complete("Responde en una frase corta, en español.",
                                        "Saluda a un jugador de Dota 2 y dale un consejo de una línea.",
                                        effort="low", max_tokens=300, timeout=45)
                q.put((True, f"{provider.label} · {provider.resolved_model()} · {time.time() - t0:.1f} s\n{out}"))
            except Exception as ex:  # cualquier fallo se muestra tal cual: es una prueba
                q.put((False, str(ex)))
        threading.Thread(target=run, daemon=True).start()

        def poll():
            try:
                ok, text = q.get_nowait()
            except queue.Empty:
                self.after(200, poll)
                return
            self.btn_test.configure(state="normal")
            self.ai_status.configure(text=("✓ " if ok else "✗ ") + text, text_color=GREEN if ok else RED)
        self.after(200, poll)

    # ================= partida =================
    def _build_game(self):
        c = self._section("Partida")
        self._label(c, 2, "Tu rol")
        self._menu(c, 2, list(ROLES.values()), ROLES.get(self.cfg.get("role", "auto"), ROLES["auto"]),
                   lambda v: self.set("role", next(k for k, n in ROLES.items() if n == v)))
        self._label(c, 3, "Rango (para el meta)")
        self._menu(c, 3, BRACKETS, BRACKETS[int(self.cfg.get("rank_bracket", 0))],
                   lambda v: self.set("rank_bracket", BRACKETS.index(v)), width=200)
        self._switch(c, 4, "Reconocer héroes de la barra superior (visión)", "vision", self.cfg.get("vision", True))
        self._switch(c, 5, "Leer los consejos en voz alta (útil para los avisos de gank)", "tts",
                     self.cfg.get("tts", False))
        self._switch(c, 9, "Avisos del mapa: enemigo desaparecido de tu línea, ganks y TPs", "map_alerts",
                     self.cfg.get("map_alerts", True))
        self._slider(c, 6, "Consejo periódico (0 = nunca)", "advisor.periodic_minutes", 0, 15, 15, "{} min", True)
        self._slider(c, 7, "Mínimo entre consultas a la IA", "advisor.min_seconds_between_ai", 15, 180, 33, "{} s",
                     True)
        self._slider(c, 8, "Consejos por aviso", "advisor.max_tips", 1, 4, 3, "{}", True)
        self._switch(c, 11, "Avisos de runas y temporizadores (según tu rol)", "timer_alerts",
                     self.cfg.get("timer_alerts", True))
        self._switch(c, 12, "Notificaciones flotantes encima del juego, bajo los retratos (ganks, TPs, torres, "
                            "rachas)", "toasts",
                     self.cfg.get("toasts", True))
        ctk.CTkLabel(c, text="").grid(row=13, column=0, pady=2)

    # ================= overlay =================
    def _build_overlay(self):
        c = self._section("Overlay", "Los consejos aparecen encima del juego, sin bloquear los clics.")
        sliders = [("Posición horizontal", "x_frac", 0, 0.9, 90, "{:.0%}", False),
                   ("Posición vertical", "y_frac", 0, 0.9, 90, "{:.0%}", False),
                   ("Ancho", "width_frac", 0.15, 0.6, 45, "{:.0%}", False),
                   ("Tamaño de letra", "font_size", 9, 24, 15, "{}", True),
                   ("Segundos en pantalla", "line_seconds", 5, 60, 55, "{} s", True),
                   ("Líneas como máximo", "max_lines", 1, 8, 7, "{}", True)]
        for i, (text, key, lo, hi, steps, fmt, integer) in enumerate(sliders, start=2):
            self._slider(c, i, text, f"overlay.{key}", lo, hi, steps, fmt, integer, on_change=self._update_preview)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.grid(row=9, column=0, columnspan=2, padx=16, pady=(8, 16), sticky="w")
        self._button(row, "Vista previa", self._show_preview, primary=True).pack(side="left")

    def _show_preview(self):
        from .overlay import Overlay
        if self.preview is None:
            self.preview = Overlay(self, self.cfg["overlay"])
        self.preview.configure(self.cfg["overlay"])
        for kind, text in [("status", "Vista previa del overlay"),
                           ("counter", "Contra Phantom Assassin: Monkey King Bar"),
                           ("item", "Con 2300 de oro: Black King Bar"),
                           ("warning", "Riki es invisible: compra Dust")]:
            self.preview.push(kind, text)

    def _update_preview(self):
        if self.preview is not None:
            self.preview.configure(self.cfg["overlay"])

    # ================= Dota 2 =================
    def _build_dota(self):
        c = self._section("Dota 2", "El coach recibe los datos de la partida con la integración oficial de Valve "
                          "(Game State Integration). Tras instalarla, reinicia Dota 2 una vez.")
        self._label(c, 2, "Carpeta de Dota 2")
        self.e_dota = ctk.CTkEntry(c, height=32, fg_color=CARD2, border_color=CARD2,
                                   placeholder_text="…\\steamapps\\common\\dota 2 beta")
        self.e_dota.grid(row=2, column=1, padx=16, pady=7, sticky="ew")
        current = dota.normalize(self.cfg.get("dota_dir")) or dota.find_dota_dir()
        if current:
            self.e_dota.insert(0, str(current))
        self.e_dota.bind("<FocusOut>", lambda _e: self._use_dota(self.e_dota.get()))
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.grid(row=3, column=0, columnspan=2, padx=16, pady=(6, 4), sticky="w")
        for text, cmd in [("Examinar…", self._browse_dota), ("Detectar", self._detect_dota),
                          ("Instalar GSI", lambda: self._gsi(True)), ("Quitar GSI", lambda: self._gsi(False))]:
            self._button(row, text, cmd, width=120).pack(side="left", padx=(0, 8))
        self.dota_status = ctk.CTkLabel(c, text="", font=font(12), text_color=MUTED, wraplength=640, justify="left")
        self.dota_status.grid(row=4, column=0, columnspan=2, padx=16, pady=(4, 16), sticky="w")
        self._refresh_dota()

    def _dota_dir(self) -> Path | None:
        return dota.normalize(self.e_dota.get().strip())

    def _refresh_dota(self):
        d = self._dota_dir()
        if not d:
            self.dota_status.configure(text="No encuentro Dota 2: indica la carpeta 'dota 2 beta'.", text_color=YELLOW)
        elif dota.is_installed(d, self.cfg["gsi_port"]):
            self.dota_status.configure(text=f"✓ Integración instalada (puerto {self.cfg['gsi_port']}).",
                                       text_color=GREEN)
        else:
            self.dota_status.configure(text="La integración GSI no está instalada.", text_color=YELLOW)

    def _use_dota(self, folder: str):
        d = dota.normalize(folder)
        if d and str(d) != self.cfg.get("dota_dir"):
            self.set("dota_dir", str(d))
        self.e_dota.delete(0, "end")
        self.e_dota.insert(0, str(d) if d else folder)
        self._refresh_dota()

    def _browse_dota(self):
        folder = filedialog.askdirectory(title="Carpeta 'dota 2 beta'")
        if folder:
            self._use_dota(folder)

    def _detect_dota(self):
        d = dota.find_dota_dir()
        if d:
            self._use_dota(str(d))
        else:
            self.dota_status.configure(text="No lo encuentro en las bibliotecas de Steam.", text_color=YELLOW)

    def _gsi(self, install: bool):
        d = self._dota_dir()
        if not d:
            self._refresh_dota()
            return
        try:
            if install:
                dota.install(d, self.cfg["gsi_port"])
            else:
                dota.uninstall(d)
        except OSError as ex:
            self.dota_status.configure(text=f"No se pudo: {ex}", text_color=RED)
            return
        self._refresh_dota()
        if not install:
            self.dota_status.configure(text="Integración quitada.", text_color=MUTED)

    # ================= cierre =================
    def on_close(self):
        self._save_ai_fields()
        self.destroy()


def run_settings(cfg: dict):
    SettingsApp(cfg).mainloop()
