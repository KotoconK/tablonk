"""Seccion Eventos: tabla personalizable con barra lateral de busqueda,
filtros por tipo y prioridad, y eventos fijados."""

import tkinter as tk
from tkinter import ttk

from event_detail import EventDetail
from event_dialogs import ColumnsEditor, TypesEditor, create_event, edit_event
from events_store import (CLOSED_STATUSES, NO_TYPE_COLOR, PRIORITIES,
                          PRIORITY_COLORS, parse_iso)
from icons import get_icon, swatch
from ui_common import UI_FONT, FlatButton, ScrollFrame, blend, confirm, ink_on

SIDEBAR_W = 248


class EventsView(tk.Frame):
    def __init__(self, master, app, store):
        super().__init__(master, bd=0)
        self.app = app
        self.store = store
        self.query = tk.StringVar()
        self.hidden_types = set()        # ids de tipo ocultos (None = "Sin tipo")
        self.hidden_priorities = set()
        self.show_closed = tk.BooleanVar(value=True)
        self.sort_key = "start"
        self.sort_desc = False
        self._dirty = True
        self._buttons = []
        self._row_tags = set()
        self._refresh_job = None
        self._build()
        store.subscribe(self._on_store_changed)
        self.query.trace_add("write", lambda *a: self._schedule_refresh())

    # ---------------------------------------------------------- estado
    def load_state(self, state):
        state = state if isinstance(state, dict) else {}
        self.sort_key = state.get("sort_key", "start")
        self.sort_desc = bool(state.get("sort_desc", False))
        self.hidden_types = set(state.get("hidden_types", []))
        if state.get("hide_untyped"):
            self.hidden_types.add(None)
        self.hidden_priorities = set(state.get("hidden_priorities", []))
        self.show_closed.set(bool(state.get("show_closed", True)))
        try:
            self.detail_ratio = float(state.get("detail_ratio", 0.5))
        except (TypeError, ValueError):
            self.detail_ratio = 0.5
        self._place_sash(force=True)
        self.query.set("")
        self._dirty = True
        self.refresh()

    def state(self):
        return {"sort_key": self.sort_key, "sort_desc": self.sort_desc,
                "hidden_types": [t for t in self.hidden_types if t is not None],
                "hide_untyped": None in self.hidden_types,
                "hidden_priorities": sorted(self.hidden_priorities),
                "show_closed": self.show_closed.get(),
                "detail_ratio": self.detail_ratio}

    # ------------------------------------------------------------- UI
    def _btn(self, parent, **kw):
        b = FlatButton(parent, self.app, **kw)
        self._buttons.append(b)
        return b

    def _build(self):
        p = self.app.palette()
        # ---- barra lateral
        self.sidebar = tk.Frame(self, width=SIDEBAR_W)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.side_sep = tk.Frame(self, width=1)
        self.side_sep.pack(side="left", fill="y")

        search = tk.Frame(self.sidebar)
        search.pack(fill="x", padx=12, pady=(12, 6))
        self.search_box = search
        self.search_wrap = tk.Frame(search, highlightthickness=1)
        self.search_wrap.pack(fill="x")
        self.search_icon = tk.Label(self.search_wrap, bd=0)
        self.search_icon.pack(side="left", padx=(7, 2))
        self.search_entry = tk.Entry(self.search_wrap, textvariable=self.query, relief="flat",
                                     bd=0, font=(UI_FONT, 10), highlightthickness=0)
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.clear_btn = self._btn(self.search_wrap, icon="close", kind="ghost",
                                   bg_key="button_bg", padx=3, icon_size=14,
                                   tooltip="Borrar búsqueda",
                                   command=lambda: (self.query.set(""),
                                                    self.search_entry.focus_set()))
        self.search_entry.bind("<Escape>", lambda e: self.query.set(""))
        self.search_entry.bind("<Down>", lambda e: self._focus_table())
        self.search_entry.bind("<Return>", lambda e: self._focus_table())

        self.side_scroll = ScrollFrame(self.sidebar, self.app, "toolbar_bg")
        self.side_scroll.pack(fill="both", expand=True)

        # ---- zona principal
        self.main = tk.Frame(self)
        self.main.pack(side="left", fill="both", expand=True)
        bar = tk.Frame(self.main, height=46)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        self.toolbar = bar
        self.new_btn = self._btn(bar, text="Nuevo evento", icon="plus", kind="accent",
                                 font=(UI_FONT, 9, "bold"), padx=10, pady=4,
                                 tooltip="Crear un evento (Ctrl+N)", command=self.new_event)
        self.new_btn.pack(side="left", padx=(10, 6), pady=8)
        self.edit_btn = self._btn(bar, text="Editar", icon="edit", padx=8, pady=4,
                                  tooltip="Editar el evento seleccionado (F2)",
                                  command=self.edit_selected)
        self.edit_btn.pack(side="left", padx=2, pady=8)
        self.pin_btn = self._btn(bar, text="Fijar", icon="pin", padx=8, pady=4,
                                 tooltip="Fijar o desfijar en la barra lateral",
                                 command=self.pin_selected)
        self.pin_btn.pack(side="left", padx=2, pady=8)
        self.dup_btn = self._btn(bar, icon="duplicate", padx=6, pady=4,
                                 tooltip="Duplicar", command=self.duplicate_selected)
        self.dup_btn.pack(side="left", padx=2, pady=8)
        self.del_btn = self._btn(bar, icon="trash", padx=6, pady=4,
                                 tooltip="Eliminar (Supr)", command=self.delete_selected)
        self.del_btn.pack(side="left", padx=2, pady=8)
        self.columns_btn = self._btn(bar, text="Columnas", icon="columns", padx=8, pady=4,
                                     tooltip="Mostrar, ocultar, ordenar o crear columnas",
                                     command=self.edit_columns)
        self.columns_btn.pack(side="right", padx=(2, 10), pady=8)
        self.types_btn = self._btn(bar, text="Tipos", icon="tag", padx=8, pady=4,
                                   tooltip="Crear tipos y asignarles color",
                                   command=self.edit_types)
        self.types_btn.pack(side="right", padx=2, pady=8)
        self.count_lbl = tk.Label(bar, font=(UI_FONT, 9))
        self.count_lbl.pack(side="right", padx=12)

        # Zona derecha dividida en horizontal: lista arriba, detalle abajo.
        self.paned = tk.PanedWindow(self.main, orient="vertical", sashwidth=7, bd=0,
                                    sashrelief="flat", opaqueresize=True, sashcursor="sb_v_double_arrow")
        self.paned.pack(side="top", fill="both", expand=True)
        table = tk.Frame(self.paned)
        self.table_frame = table
        self.detail = EventDetail(self.paned, self.app, self.store, on_edit=self._edit,
                                  on_calendar=self.app.show_event_in_calendar)
        self.paned.add(table, minsize=120, stretch="always")
        self.paned.add(self.detail, minsize=150, stretch="always")
        self.detail_ratio = 0.5
        self._sash_placed = False
        self.paned.bind("<Configure>", lambda e: self._place_sash())
        self.paned.bind("<ButtonRelease-1>", self._remember_sash, add="+")
        self.tree = ttk.Treeview(table, style="Events.Treeview", show="tree headings",
                                 selectmode="extended")
        vs = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        table.grid_rowconfigure(0, weight=1)
        table.grid_columnconfigure(0, weight=1)
        self.empty_lbl = tk.Label(table, font=(UI_FONT, 10), justify="center")

        # Clic (o doble clic) solo muestra el evento abajo; editar es con Editar o F2.
        self.tree.bind("<F2>", lambda e: self.edit_selected())
        self.tree.bind("<Delete>", lambda e: (self.delete_selected(), "break")[1])
        self.tree.bind("<Button-3>", self._context_menu)
        self.tree.bind("<ButtonRelease-1>", self._remember_widths, add="+")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._selection_changed())
        self.update_theme()

    def _selection_changed(self):
        self._update_buttons()
        self.detail.show(self._selected_ids())

    def _place_sash(self, force=False):
        h = self.paned.winfo_height()
        if h < 60 or (self._sash_placed and not force):
            return
        self._sash_placed = True
        y = int(h * max(0.2, min(0.8, self.detail_ratio)))
        self.after_idle(lambda: self.paned.sash_place(0, 0, y))

    def _remember_sash(self, _e=None):
        h = self.paned.winfo_height()
        if h > 60:
            try:
                self.detail_ratio = round(self.paned.sash_coord(0)[1] / h, 3)
            except tk.TclError:
                return
            self.app.schedule_save()

    def _focus_table(self):
        children = self.tree.get_children()
        if children:
            self.tree.focus_set()
            if not self.tree.selection():
                self.tree.selection_set(children[0])
                self.tree.focus(children[0])
        return "break"

    # ----------------------------------------------------------- tema
    def update_theme(self):
        p = self.app.palette()
        for w in (self, self.main, self.table_frame):
            w.configure(bg=p["app_bg"])
        self.paned.configure(bg=p["border"])
        self.detail.update_theme()
        for w in (self.sidebar, self.search_box, self.toolbar):
            w.configure(bg=p["toolbar_bg"])
        self.side_sep.configure(bg=p["border"])
        self.side_scroll.restyle()
        self.search_wrap.configure(bg=p["button_bg"], highlightbackground=p["border"],
                                   highlightcolor=p["accent"])
        self.search_icon.configure(bg=p["button_bg"],
                                   image=get_icon(self, "search", p["muted_text"], 16) or "")
        self.search_entry.configure(bg=p["button_bg"], fg=p["text"], insertbackground=p["text"])
        self.count_lbl.configure(bg=p["toolbar_bg"], fg=p["muted_text"])
        self.empty_lbl.configure(bg=p["board_bg"], fg=p["muted_text"])
        for b in self._buttons:
            b.restyle()
        style = ttk.Style(self)
        style.configure("Events.Treeview", background=p["board_bg"], fieldbackground=p["board_bg"],
                        foreground=p["text"], rowheight=28, borderwidth=0,
                        font=(UI_FONT, 10))
        style.map("Events.Treeview",
                  background=[("selected", p["accent"])],
                  foreground=[("selected", "#FFFFFF")])
        style.configure("Events.Treeview.Heading", background=p["toolbar_bg"],
                        foreground=p["text"], relief="flat", font=(UI_FONT, 9, "bold"),
                        borderwidth=1, padding=(6, 5))
        style.map("Events.Treeview.Heading", background=[("active", p["button_hover"])])
        style.layout("Events.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        self._row_tags.clear()
        self._dirty = True
        if self.winfo_ismapped():
            self.refresh()

    # -------------------------------------------------------- refresco
    def _on_store_changed(self):
        self._dirty = True
        if self.winfo_ismapped():
            self._schedule_refresh()

    def _schedule_refresh(self):
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
        self._refresh_job = self.after(60, self.refresh)

    def on_show(self):
        if self._dirty:
            self.refresh()

    def refresh(self):
        self._refresh_job = None
        self._dirty = False
        self._refresh_sidebar()
        self._refresh_table()
        self._update_buttons()
        self.detail.show(self._selected_ids())

    # ------------------------------------------------------ barra lateral
    def _section(self, parent, title, action=None, action_tip=None, icon=None):
        p = self.app.palette()
        head = tk.Frame(parent, bg=p["toolbar_bg"])
        head.pack(fill="x", padx=12, pady=(14, 4))
        if icon:
            img = get_icon(self, icon, p["muted_text"], 14)
            if img:
                tk.Label(head, image=img, bg=p["toolbar_bg"]).pack(side="left", padx=(0, 5))
        tk.Label(head, text=title, bg=p["toolbar_bg"], fg=p["muted_text"],
                 font=(UI_FONT, 9, "bold")).pack(side="left")
        if action:
            FlatButton(head, self.app, icon=action[0], kind="ghost", bg_key="toolbar_bg",
                       padx=2, pady=0, icon_size=14, tooltip=action_tip,
                       command=action[1]).pack(side="right")
        return head

    def _toggle_row(self, parent, label, color, active, command, count=None):
        p = self.app.palette()
        bg = p["toolbar_bg"]
        row = tk.Frame(parent, bg=bg, cursor="hand2")
        row.pack(fill="x", padx=8)
        img = swatch(self, color, 18, checked=active, check_color=ink_on(color)) if active \
            else swatch(self, blend(color, bg, 0.55), 18)
        icon = tk.Label(row, image=img, bg=bg)
        icon.pack(side="left", padx=(4, 8), pady=3)
        text = tk.Label(row, text=label, bg=bg, anchor="w", font=(UI_FONT, 9),
                        fg=p["text"] if active else p["muted_text"])
        text.pack(side="left", fill="x", expand=True)
        widgets = [row, icon, text]
        if count is not None:
            c = tk.Label(row, text=str(count), bg=bg, fg=p["muted_text"], font=(UI_FONT, 8))
            c.pack(side="right", padx=6)
            widgets.append(c)
        for w in widgets:
            w.bind("<Button-1>", lambda e: command())
            w.bind("<Enter>", lambda e: [x.configure(bg=p["button_hover"]) for x in widgets])
            w.bind("<Leave>", lambda e: [x.configure(bg=bg) for x in widgets])
        return row

    def _refresh_sidebar(self):
        p = self.app.palette()
        body = self.side_scroll.body
        for w in body.winfo_children():
            w.destroy()

        # Tipos (clic: mostrar/ocultar; clic derecho: ver solo ese tipo)
        self._section(body, "Tipos", ("edit", self.edit_types), "Editar tipos", "tag")
        entries = [(t["id"], t["name"], t["color"]) for t in self.store.types]
        untyped = self.store.count_by_type(None)
        if untyped or not self.store.types:
            entries.append((None, "Sin tipo", NO_TYPE_COLOR))
        for tid, name, color in entries:
            row = self._toggle_row(body, name, color, tid not in self.hidden_types,
                                   lambda t=tid: self._toggle_type(t),
                                   self.store.count_by_type(tid))
            for w in [row] + row.winfo_children():
                w.bind("<Button-3>", lambda e, t=tid: self._only_type(t))
        links = tk.Frame(body, bg=p["toolbar_bg"])
        links.pack(fill="x", padx=10, pady=(2, 0))
        FlatButton(links, self.app, text="Quitar filtros", kind="ghost", bg_key="toolbar_bg",
                   padx=4, pady=0, font=(UI_FONT, 8), command=self._all_types).pack(side="left")
        tk.Label(links, text="Clic derecho: solo ese tipo", bg=p["toolbar_bg"],
                 fg=p["muted_text"], font=(UI_FONT, 8)).pack(side="right", padx=2)

        # Prioridad
        self._section(body, "Prioridad", icon="filter")
        for name in PRIORITIES:
            self._toggle_row(body, name, PRIORITY_COLORS[name],
                             name not in self.hidden_priorities,
                             lambda n=name: self._toggle_priority(n))
        closed = tk.Frame(body, bg=p["toolbar_bg"])
        closed.pack(fill="x", padx=10, pady=(6, 0))
        tk.Checkbutton(closed, text="Mostrar hechos y cancelados", variable=self.show_closed,
                       command=self._filters_changed, bg=p["toolbar_bg"], fg=p["text"],
                       activebackground=p["toolbar_bg"], activeforeground=p["text"],
                       selectcolor=p["button_bg"], font=(UI_FONT, 9), bd=0,
                       highlightthickness=0).pack(anchor="w")

        # Fijados
        self._section(body, "Fijados", icon="pin_filled")
        pinned = self.store.pinned()
        if not pinned:
            tk.Label(body, text="Fija un evento para tenerlo siempre a mano.",
                     bg=p["toolbar_bg"], fg=p["muted_text"], font=(UI_FONT, 8),
                     wraplength=SIDEBAR_W - 40, justify="left", anchor="w"
                     ).pack(fill="x", padx=14)
        for event in pinned:
            self._pinned_card(body, event)
        tk.Frame(body, bg=p["toolbar_bg"], height=14).pack()
        self.side_scroll.bind_children_wheel()

    def _pinned_card(self, parent, event):
        p = self.app.palette()
        color = self.store.type_color(event["type_id"])
        card = tk.Frame(parent, bg=color, cursor="hand2")
        card.pack(fill="x", padx=12, pady=3)
        fg = ink_on(color)
        name = tk.Label(card, text=event["name"], bg=color, fg=fg, anchor="w",
                        font=(UI_FONT, 9, "bold"), justify="left",
                        wraplength=SIDEBAR_W - 60)
        name.pack(fill="x", padx=(9, 6), pady=(5, 0))
        day = parse_iso(event["start"])
        when = day.strftime("%d/%m/%Y") if day else ""
        if event["start_time"] and not event["all_day"]:
            when += "  " + event["start_time"]
        info = tk.Label(card, text=f"{when}   {event['priority']}", bg=color,
                        fg=blend(fg, color, 0.3), anchor="w", font=(UI_FONT, 8))
        info.pack(fill="x", padx=(9, 6), pady=(0, 5))
        for w in (card, name, info):
            w.bind("<Button-1>", lambda e, i=event["id"]: self.reveal(i))
            w.bind("<Button-3>", lambda e, i=event["id"]: self._pinned_menu(e, i))

    def _pinned_menu(self, event, event_id):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Editar", command=lambda: self._edit(event_id))
        menu.add_command(label="Desfijar", command=lambda: self.store.toggle_pin(event_id))
        menu.add_command(label="Ver en el calendario",
                         command=lambda: self.app.show_event_in_calendar(event_id))
        menu.tk_popup(event.x_root, event.y_root)

    def _toggle_type(self, tid):
        self.hidden_types ^= {tid}
        self._filters_changed()

    def _only_type(self, tid):
        everything = {t["id"] for t in self.store.types} | {None}
        self.hidden_types = everything - {tid}
        self._filters_changed()

    def _all_types(self):
        self.hidden_types.clear()
        self.hidden_priorities.clear()
        self._filters_changed()

    def _toggle_priority(self, name):
        self.hidden_priorities ^= {name}
        self._filters_changed()

    def _filters_changed(self):
        self.refresh()
        self.app.schedule_save()

    # ---------------------------------------------------------- tabla
    def _type_filter(self):
        if not self.hidden_types:
            return None
        allowed = {t["id"] for t in self.store.types} | {None}
        return allowed - self.hidden_types

    def _rows(self):
        prios = set(PRIORITIES) - self.hidden_priorities if self.hidden_priorities else None
        events = self.store.filtered(self.query.get(), self._type_filter(), prios,
                                     self.show_closed.get())
        key = self.sort_key if any(c["key"] == self.sort_key for c in self.store.columns) \
            else "start"
        events.sort(key=lambda e: (self.store.sort_value(e, key),
                                   self.store.sort_key_start(e)), reverse=self.sort_desc)
        return events

    def _tag_for(self, event):
        closed = event["status"] in CLOSED_STATUSES
        tag = f"t_{event['type_id'] or 'none'}{'_c' if closed else ''}"
        if tag not in self._row_tags:
            p = self.app.palette()
            color = self.store.type_color(event["type_id"])
            if closed:
                bg = blend(color, p["board_bg"], 0.55)
                fg = blend(ink_on(color), bg, 0.45)
            else:
                bg, fg = color, ink_on(color)
            self.tree.tag_configure(tag, background=bg, foreground=fg)
            self._row_tags.add(tag)
        return tag

    def _refresh_table(self):
        p = self.app.palette()
        cols = self.store.visible_columns()
        keys = [c["key"] for c in cols]
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        self._row_tags.clear()
        self.tree.configure(columns=keys, displaycolumns=keys)
        pin_img = get_icon(self, "pin_filled", "#1d232b", 14)  # filas pastel: tinta oscura
        head_pin = get_icon(self, "pin", p["muted_text"], 14)
        self.tree.heading("#0", image=head_pin or "", text="" if head_pin else "F")
        self.tree.column("#0", width=34, minwidth=34, stretch=False, anchor="center")
        for i, col in enumerate(cols):
            img = ""
            if col["key"] == self.sort_key:
                img = get_icon(self, "chevron_down" if self.sort_desc else "chevron_up",
                               p["text"], 12) or ""
            self.tree.heading(col["key"], text=col["label"], image=img, anchor="w",
                              command=lambda k=col["key"]: self._sort_by(k))
            self.tree.column(col["key"], width=col["width"], minwidth=60,
                             stretch=(i == len(cols) - 1), anchor="w")
        rows = self._rows()
        # se regeneran las etiquetas para que los colores sigan a los tipos
        for event in rows:
            values = [self.store.cell_text(event, k) for k in keys]
            self.tree.insert("", "end", iid=event["id"], values=values,
                             image=(pin_img if event["pinned"] and pin_img else ""),
                             text=("" if pin_img or not event["pinned"] else "*"),
                             tags=(self._tag_for(event),))
        keep = [i for i in selected if self.tree.exists(i)]
        if keep:
            self.tree.selection_set(keep)
        total = len(self.store.items)
        shown = len(rows)
        self.count_lbl.configure(text=(f"{shown} de {total} eventos" if shown != total
                                       else f"{total} evento" + ("" if total == 1 else "s")))
        if not rows:
            msg = ("Aún no hay eventos.\nCrea el primero con «Nuevo evento»."
                   if not total else "Ningún evento coincide con la búsqueda o los filtros.")
            self.empty_lbl.configure(text=msg)
            self.empty_lbl.place(relx=0.5, rely=0.42, anchor="center")
        else:
            self.empty_lbl.place_forget()

    def _sort_by(self, key):
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, False
        self._refresh_table()
        self.app.schedule_save()

    def _remember_widths(self, _e=None):
        region = self.tree.identify_region(_e.x, _e.y) if _e is not None else ""
        if region not in ("separator", "heading"):
            return
        changed = False
        for col in self.store.visible_columns():
            try:
                w = int(self.tree.column(col["key"], "width"))
            except tk.TclError:
                continue
            if w != col["width"]:
                self.store.set_column_width(col["key"], w)
                changed = True
        if changed:
            self.app.schedule_save()

    def _selected_ids(self):
        return [i for i in self.tree.selection() if self.store.get(i)]

    def _update_buttons(self):
        ids = self._selected_ids()
        one = len(ids) == 1
        self.edit_btn.set_enabled(one)
        self.dup_btn.set_enabled(one)
        self.del_btn.set_enabled(bool(ids))
        self.pin_btn.set_enabled(bool(ids))
        if ids:
            pinned = all(self.store.get(i)["pinned"] for i in ids)
            self.pin_btn.configure(text="Desfijar" if pinned else "Fijar")
            self.pin_btn.set_icon("pin" if pinned else "pin_filled")
        else:
            self.pin_btn.configure(text="Fijar")
            self.pin_btn.set_icon("pin")

    # -------------------------------------------------------- acciones
    def reveal(self, event_id):
        if not self.tree.exists(event_id):
            # el evento esta oculto por los filtros: se quitan
            self.query.set("")
            self.hidden_types.clear()
            self.hidden_priorities.clear()
            self.show_closed.set(True)
            self.refresh()
        if self.tree.exists(event_id):
            self.tree.selection_set(event_id)
            self.tree.focus(event_id)
            self.tree.see(event_id)
            self.tree.focus_set()
            self._selection_changed()

    def _edit(self, event_id):
        result = edit_event(self.app, self.store, event_id)
        if result and result[0] == "saved":
            self.after(80, lambda: self.reveal(result[1]))

    def new_event(self, day=None):
        result = create_event(self.app, self.store, day)
        if result and result[0] == "saved":
            self.after(80, lambda: self.reveal(result[1]))

    def edit_selected(self):
        ids = self._selected_ids()
        if len(ids) == 1:
            self._edit(ids[0])

    def pin_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        target = not all(self.store.get(i)["pinned"] for i in ids)
        for i in ids:
            self.store.get(i)["pinned"] = target
        self.store.changed()

    def duplicate_selected(self):
        ids = self._selected_ids()
        if len(ids) == 1:
            dup = self.store.duplicate_event(ids[0])
            if dup:
                self.after(80, lambda: self.reveal(dup["id"]))

    def delete_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        if len(ids) == 1:
            name = self.store.get(ids[0])["name"]
            msg, detail = "¿Eliminar este evento?", f"«{name}» desaparecerá del calendario y de la tabla."
        else:
            msg, detail = f"¿Eliminar {len(ids)} eventos?", "Esta acción no se puede deshacer."
        if confirm(self.app, "Eliminar evento", msg, detail, ok_text="Eliminar", kind="danger"):
            self.store.items = [e for e in self.store.items if e["id"] not in ids]
            self.store.changed()

    def edit_types(self):
        TypesEditor(self.app, self.store).show()

    def edit_columns(self):
        ColumnsEditor(self.app, self.store).show()

    def _context_menu(self, event):
        item = self.tree.identify_row(event.y)
        menu = tk.Menu(self, tearoff=0)
        if item:
            if item not in self.tree.selection():
                self.tree.selection_set(item)
            self.tree.focus(item)
            ev = self.store.get(item)
            menu.add_command(label="Editar", command=lambda: self._edit(item))
            menu.add_command(label="Desfijar" if ev and ev["pinned"] else "Fijar",
                             command=self.pin_selected)
            menu.add_command(label="Duplicar", command=self.duplicate_selected)
            menu.add_command(label="Ver en el calendario",
                             command=lambda: self.app.show_event_in_calendar(item))
            menu.add_separator()
            menu.add_command(label="Eliminar", command=self.delete_selected)
        else:
            menu.add_command(label="Nuevo evento", command=self.new_event)
            menu.add_command(label="Columnas...", command=self.edit_columns)
        menu.tk_popup(event.x_root, event.y_root)

