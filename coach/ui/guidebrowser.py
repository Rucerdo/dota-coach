"""Buscador de guías: builds reales (partidas ganadas, STRATZ) de un héroe, para elegir la que quieras seguir.

Se abre desde el panel ("Guías…" en la build por fases). Por defecto, las de tu héroe ordenadas por parecido a tu
partida (enemigos y aliados en común, misma posición); se puede buscar cualquier otro héroe (p. ej. en la selección
de héroes, antes de elegir). La guía elegida se guarda por héroe y se puede cambiar o quitar en cualquier momento.
"""
import queue
import threading
from typing import Callable

import customtkinter as ctk

import time

from ..engine.guides import Guide, coincidences, rank, similarity

BG, CARD, CARD2 = "#14181F", "#1C222C", "#252D39"
TEXT, MUTED, ACCENT, GREEN, GOLD = "#E8ECF1", "#8D97A5", "#E5534B", "#5FD17A", "#E6B450"
MAX_ROWS = 40


def _font(size, weight="normal"):
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


class GuideBrowser(ctk.CTkToplevel):
    def __init__(self, master, gd, images, fetch: Callable[[int], list[Guide]],
                 choose: Callable[[Guide | None], None], current: Callable[[], Guide | None],
                 context: Callable[[], tuple[int | None, set[int], set[int], str]], shop: dict | None = None):
        """fetch(hero_id) → guías (puede tardar: va en otro hilo). context() → (tu héroe, enemigos, aliados,
        posición) para ordenar por parecido."""
        super().__init__(master, fg_color=BG)
        self.shop = shop or {}
        self.gd, self.images, self.fetch, self._choose, self.current, self.context = \
            gd, images, fetch, choose, current, context
        self.title("Dota Coach · Guías")
        self.geometry(self._geometry(master))
        self.minsize(760, 480)
        self.q: queue.Queue = queue.Queue()
        self.guides: list[Guide] = []
        self.hero_id: int | None = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        top = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        ctk.CTkLabel(top, text="Héroe", font=_font(12, "bold"), text_color=MUTED).pack(side="left", padx=(12, 6),
                                                                                       pady=10)
        names = sorted(h.loc for h in gd.heroes.values())
        self.hero_box = ctk.CTkComboBox(top, values=names, width=220, command=lambda _: self.load())
        self.hero_box.pack(side="left", pady=10)
        self.hero_box.bind("<Return>", lambda _: self.load())
        ctk.CTkButton(top, text="Buscar", width=80, command=self.load, fg_color=CARD2,
                      hover_color="#323C4B").pack(side="left", padx=8)
        self.mode = ctk.CTkSegmentedButton(top, values=["Parecidas a tu partida", "Todas"],
                                           command=lambda _: self.render())
        self.mode.set("Parecidas a tu partida")
        self.mode.pack(side="left", padx=8)
        self.status = ctk.CTkLabel(top, text="", font=_font(11), text_color=MUTED)
        self.status.pack(side="right", padx=12)
        # progreso de la búsqueda (con lo que se va pidiendo)
        self.prog = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        self.prog.grid_columnconfigure(0, weight=1)
        self.prog_bar = ctk.CTkProgressBar(self.prog, height=10, progress_color=GREEN, fg_color=CARD2)
        self.prog_bar.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        self.prog_text = ctk.CTkLabel(self.prog, text="", font=_font(11), text_color=MUTED, anchor="w")
        self.prog_text.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.last_partial = 0.0

        cur = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        cur.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        cur.grid_columnconfigure(0, weight=1)
        self.cur_label = ctk.CTkLabel(cur, text="", font=_font(12), text_color=TEXT, anchor="w", justify="left")
        self.cur_label.grid(row=0, column=0, sticky="ew", padx=12, pady=8)
        self.clear_btn = ctk.CTkButton(cur, text="Quitar guía", width=110, fg_color=CARD2, hover_color="#323C4B",
                                       command=lambda: self.choose(None))
        self.clear_btn.grid(row=0, column=1, padx=12, pady=8)
        # tienda de Dota: sustituir la guía por defecto del héroe por la elegida (y poder deshacerlo)
        shop_row = ctk.CTkFrame(cur, fg_color="transparent")
        shop_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 8))
        self.shop_btn = ctk.CTkButton(shop_row, text="Sustituir la guía por defecto de Dota", width=250,
                                      fg_color=GREEN, text_color="#0E1116", hover_color="#3B8F50",
                                      command=self._shop_export)
        self.shop_btn.pack(side="left")
        self.restore_btn = ctk.CTkButton(shop_row, text="Restaurar la guía de Valve", width=190, fg_color=CARD2,
                                         hover_color="#323C4B", command=self._shop_restore)
        self.restore_btn.pack(side="left", padx=8)
        self.shop_label = ctk.CTkLabel(shop_row, text="", font=_font(11), text_color=MUTED, anchor="w",
                                       justify="left", wraplength=420)
        self.shop_label.pack(side="left", padx=8)
        self.shop_busy = False

        self.list = ctk.CTkScrollableFrame(self, fg_color=BG)
        self.list.grid(row=3, column=0, sticky="nsew", padx=12, pady=(6, 12))
        self.list.grid_columnconfigure(0, weight=1)
        self.rows: list[ctk.CTkFrame] = []

        me = context()[0]
        hero = gd.heroes.get(me) if me else None
        if hero:
            self.hero_box.set(hero.loc)
            self.load()
        else:
            self.hero_box.set("")
            self.status.configure(text="Elige un héroe")
        self._update_current()
        self.after(200, self._poll)
        self.transient(master)   # siempre delante del panel (aunque el panel esté "siempre encima")
        self.after(150, self._to_front)

    def _to_front(self):
        try:
            if bool(self.master.attributes("-topmost")):
                self.attributes("-topmost", True)
        except Exception:
            pass
        self.lift()
        self.focus_force()

    @staticmethod
    def _geometry(master) -> str:
        try:
            x, y = master.winfo_rootx(), master.winfo_rooty()
            return f"980x760+{x + 60}+{y + 60}"
        except Exception:
            return "980x760"

    # ---------- datos ----------
    def load(self):
        hero = self.gd.hero(self.hero_box.get().strip())
        if not hero:
            self.status.configure(text="No encuentro ese héroe")
            return
        self.hero_id = hero.id
        self.guides = []
        self.render()
        self.status.configure(text=f"Buscando guías de {hero.loc}…")
        self.prog.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        self.prog_bar.set(0)
        self.prog_text.configure(text="Preparando la búsqueda…")

        def progress(done, total, text, partial):
            self.q.put(("progress", (hero.id, done, total, text, partial), None))

        def job():
            try:
                self.q.put((hero.id, self.fetch(hero.id, progress), None))
            except Exception as ex:
                self.q.put((hero.id, [], ex))
        threading.Thread(target=job, daemon=True).start()

    def _poll(self):
        try:
            while True:
                hero_id, guides, err = self.q.get_nowait()
                if hero_id == "progress":
                    hid, done, total, text, partial = guides
                    if hid != self.hero_id:
                        continue
                    self.prog_bar.set(done / total if total else 0)
                    if partial is not None:
                        self.partial_count = len(partial)
                    self.prog_text.configure(text=f"{done}/{total} partidas · {text} · "
                                                  f"{getattr(self, 'partial_count', 0)} guías")
                    # resultados según llegan (sin repintar a cada paso: como mucho cada 1.5 s)
                    if partial and time.time() - self.last_partial > 1.5:
                        self.last_partial = time.time()
                        self.guides = partial
                        self.render()
                    continue
                if hero_id == "shop":
                    self.shop_busy = False
                    self._update_shop()
                    self.shop_label.configure(text=f"No se pudo: {err}" if err else guides,
                                              text_color="#E5534B" if err else GREEN)
                    continue
                if hero_id != self.hero_id:
                    continue  # respuesta de una búsqueda anterior
                self.guides = guides
                self.prog.grid_remove()
                name = self.gd.heroes[hero_id].loc
                self.status.configure(text=f"No se pudieron cargar ({err})" if err else
                                      f"{len(guides)} guías de {name} (partidas ganadas · STRATZ)")
                self.render()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(200, self._poll)

    # ---------- pintar ----------
    def _update_current(self):
        self._update_shop()
        g = self.current()
        if g is None:
            self.cur_label.configure(text="Sin guía: la build se arma con las estadísticas, tus enemigos y las "
                                          "builds ganadoras parecidas a lo que vas comprando.", text_color=MUTED)
            self.clear_btn.configure(state="disabled")
            return
        hero = self.gd.heroes.get(g.hero_id)
        items = " → ".join(self.gd.item(n).loc for n in g.items if self.gd.item(n))
        kind = "Guía adaptada" if g.source == "adaptada" else "Guía elegida"
        self.cur_label.configure(text=f"{kind} ({hero.loc if hero else '?'}"
                                      f"{' · ' + g.role if g.role else ''}): {items}", text_color=TEXT)
        self.clear_btn.configure(state="normal")

    def choose(self, guide: Guide | None):
        self._choose(guide)
        self._update_current()
        self.render()

    # ---------- tienda de Dota ----------
    def _shop_hero(self) -> int | None:
        g = self.current()
        return g.hero_id if g else self.hero_id

    def _update_shop(self):
        if not self.shop:
            self.shop_btn.configure(state="disabled", fg_color=CARD2, text_color=MUTED)
            self.restore_btn.configure(state="disabled")
            self.shop_label.configure(text="")
            return
        hero_id = self._shop_hero()
        hero = self.gd.heroes.get(hero_id) if hero_id else None
        try:
            ours, gid = self.shop["status"](hero_id) if hero else (False, None)
        except Exception:
            ours, gid = False, None
        g = self.current()
        same = ours and g is not None and gid == g.id
        if self.shop_busy:
            return
        can = g is not None and not same
        self.shop_btn.configure(state="normal" if can else "disabled",
                                fg_color=GREEN if can else CARD2, text_color="#0E1116" if can else MUTED,
                                text="✓ Guía ya en la tienda de Dota" if same else
                                "Actualizar la guía de Dota" if ours else "Sustituir la guía por defecto de Dota")
        self.restore_btn.configure(state="normal" if ours else "disabled")
        name = hero.loc if hero else "este héroe"
        if same:
            text = f"En la tienda de Dota ya está esta guía para {name} (objetos, habilidades y talentos)."
        elif ours:
            text = f"La tienda de Dota tiene otra guía del coach para {name}."
        else:
            text = f"La tienda de Dota tiene la guía de Valve para {name}."
        self.shop_label.configure(text=text)

    def _shop_run(self, job, done_text):
        self.shop_busy = True
        self.shop_btn.configure(state="disabled")
        self.restore_btn.configure(state="disabled")
        self.shop_label.configure(text="Escribiendo…")

        def run():
            try:
                job()
                self.q.put(("shop", done_text, None))
            except Exception as ex:
                self.q.put(("shop", None, ex))
        threading.Thread(target=run, daemon=True).start()

    def _shop_export(self):
        g = self.current()
        if g is not None:
            self._shop_run(lambda: self.shop["export"](g), "Hecho. Dota lee las guías al arrancar: la verás en la "
                                                          "tienda cuando reinicies Dota.")

    def _shop_restore(self):
        hero_id = self._shop_hero()
        if hero_id:
            self._shop_run(lambda: self.shop["restore"](hero_id), "Restaurada la guía de Valve.")

    def render(self):
        self._update_shop()
        for r in self.rows:
            r.destroy()
        self.rows = []
        me, enemies, allies, position, *rest = self.context()
        weights = rest[0] if rest else None
        guides = self.guides
        if self.hero_id == me and self.mode.get().startswith("Parecidas"):
            guides = [g for g in rank(guides, enemies, allies, position, weights)]
        else:
            guides = sorted(guides, key=lambda g: len(g.core), reverse=True)
        cur = self.current()
        for i, g in enumerate(guides[:MAX_ROWS]):
            self.rows.append(self._row(i, g, cur is not None and cur.id == g.id,
                                       similarity(g, enemies, allies, position, weights)
                                       if self.hero_id == me else 0,
                                       enemies, allies))

    def _row(self, i: int, g: Guide, chosen: bool, sim: float, enemies: set[int], allies: set[int]):
        f = ctk.CTkFrame(self.list, fg_color=CARD, corner_radius=8, border_width=1 if chosen else 0,
                         border_color=GREEN)
        f.grid(row=i, column=0, sticky="ew", pady=(0, 6))
        f.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(f, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 2))
        title = " · ".join(x for x in (g.role.capitalize() if g.role else "", f"{g.minutes} min" if g.minutes else "",
                                       "ganada") if x)
        ctk.CTkLabel(head, text=title, font=_font(12, "bold"), text_color=TEXT).pack(side="left")
        for label, ids, mark in (("vs", g.enemies, enemies), ("con", g.allies, allies)):
            if not ids:
                continue
            ctk.CTkLabel(head, text=label, font=_font(10), text_color=MUTED).pack(side="left", padx=(12, 4))
            for hid in ids:
                hero = self.gd.heroes.get(hid)
                if not hero:
                    continue
                img = self.images.hero(hero, (34, 19))
                lbl = ctk.CTkLabel(head, text="" if img else hero.loc[:2], image=img, width=34, height=19,
                                   fg_color=GREEN if hid in mark else CARD2, corner_radius=3)
                lbl.pack(side="left", padx=1)
        e_in, a_in = coincidences(g, enemies, allies)
        if e_in + a_in:
            parts = [f"{e_in} enemigo{'s' if e_in != 1 else ''}" if e_in else "",
                     f"{a_in} aliado{'s' if a_in != 1 else ''}" if a_in else ""]
            ctk.CTkLabel(head, text=f"{e_in + a_in} en común ({' + '.join(p for p in parts if p)})",
                         font=_font(10, "bold"), text_color=GREEN).pack(side="left", padx=10)
        strip = ctk.CTkFrame(f, fg_color="transparent")
        strip.grid(row=1, column=0, sticky="w", padx=10, pady=(2, 8))
        for j, (name, minute) in enumerate(g.core[:12]):
            box = ctk.CTkFrame(strip, fg_color="transparent")
            box.grid(row=0, column=j, padx=(0, 4))
            item = self.gd.item(name)
            img = self.images.item(name.removeprefix("item_"), (44, 32))
            ctk.CTkLabel(box, text="" if img else (item.loc[:3] if item else "?"), image=img, width=44, height=32,
                         fg_color=CARD2, corner_radius=4).pack()
            ctk.CTkLabel(box, text=f"{minute:.0f}'" if minute else "", font=_font(9), text_color=MUTED,
                         height=12).pack()
        btn = ctk.CTkButton(f, text="✓ Elegida" if chosen else "Seguir esta guía", width=130,
                            fg_color=GREEN if chosen else ACCENT, hover_color="#3B8F50" if chosen else "#C2413A",
                            text_color="#0E1116" if chosen else TEXT, command=lambda g=g: self.choose(g))
        btn.grid(row=0, column=1, rowspan=2, padx=10)
        return f
