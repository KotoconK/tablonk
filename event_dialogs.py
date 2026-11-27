"""Dialogos de eventos: editar evento, editar tipos y personalizar columnas."""

import copy
import os
import tkinter as tk
from tkinter import ttk

from events_store import (CLOSED_STATUSES, NO_TYPE_COLOR, PRIORITIES,
                          PRIORITY_COLORS, STATUSES, new_id, parse_iso)
from icons import get_icon, swatch
import project_files as pf
from rich_notes import RichText, RichToolbar
from ui_common import (TYPE_COLORS, UI_FONT, ColorPopup, DateField, Dialog,
                       FlatButton, ScrollFrame, TimeField, alert, ask_open_filenames,
                       blend, confirm, ink_on, styled_entry)

NO_TYPE_LABEL = "Sin tipo"


# ----------------------------------------------------------------------
# Editar evento
# ----------------------------------------------------------------------
class EventEditor(Dialog):
    """Edicion completa de un evento. El fondo toma el color de su tipo."""

    def __init__(self, app, store, event, is_new, parent=None):
        super().__init__(app, "Nuevo evento" if is_new else "Editar evento", parent,
                         resizable=True)
        self.store = store
        self.event = copy.deepcopy(event)
        self.is_new = is_new
        self._tinted = []            # (widget, rol)
        self._build()
        self._apply_color()

    # ------------------------------------------------------------ UI
    def _tint(self, widget, role="bg"):
        self._tinted.append((widget, role))
        return widget

    def _label(self, parent, text, row, col=0, sticky="w"):
        lbl = self._tint(tk.Label(parent, text=text, font=(UI_FONT, 9), anchor="w"), "label")
        lbl.grid(row=row, column=col, sticky=sticky, padx=(0, 10), pady=5)
        return lbl

    def _build(self):
        app, ev = self.app, self.event
        # Cabecera con el color pleno del tipo y el nombre del evento.
        self.header = self._tint(tk.Frame(self), "header")
        self.header.pack(fill="x")
        self.kind_lbl = self._tint(tk.Label(self.header, font=(UI_FONT, 9, "bold"), anchor="w"),
                                   "header_muted")
        self.kind_lbl.pack(fill="x", padx=20, pady=(16, 2))
        self.name_var = tk.StringVar(value=ev["name"])
        self.name_entry = tk.Entry(self.header, textvariable=self.name_var, relief="flat", bd=0,
                                   font=(UI_FONT, 16, "bold"), highlightthickness=0)
        self._tint(self.name_entry, "header_entry")
        self.name_entry.pack(fill="x", padx=20, pady=(0, 6), ipady=4)
        self.name_line = self._tint(tk.Frame(self.header, height=2), "header_line")
        self.name_line.pack(fill="x", padx=20, pady=(0, 14))

        body = self._tint(tk.Frame(self))
        body.pack(fill="both", expand=True, padx=20, pady=(14, 4))
        body.grid_columnconfigure(1, weight=1)
        r = 0

        # Tipo
        self._label(body, "Tipo", r)
        type_row = self._tint(tk.Frame(body))
        type_row.grid(row=r, column=1, columnspan=3, sticky="w")
        self.type_var = tk.StringVar()
        self.type_cb = ttk.Combobox(type_row, textvariable=self.type_var, state="readonly", width=28)
        self.type_cb.pack(side="left")
        self.type_cb.bind("<<ComboboxSelected>>", lambda e: self._on_type_change())
        FlatButton(type_row, app, text="Editar tipos", icon="tag", padx=8, pady=3,
                   tooltip="Crear, renombrar o cambiar el color de los tipos",
                   command=self._edit_types).pack(side="left", padx=(6, 0))
        self._load_type_choices()
        r += 1

        # Prioridad y estado
        self._label(body, "Prioridad", r)
        pr_row = self._tint(tk.Frame(body))
        pr_row.grid(row=r, column=1, columnspan=3, sticky="w")
        self.priority_var = tk.StringVar(value=ev["priority"])
        ttk.Combobox(pr_row, textvariable=self.priority_var, values=PRIORITIES,
                     state="readonly", width=11).pack(side="left")
        self._tint(tk.Label(pr_row, text="Estado", font=(UI_FONT, 9)), "label").pack(
            side="left", padx=(18, 8))
        self.status_var = tk.StringVar(value=ev["status"])
        ttk.Combobox(pr_row, textvariable=self.status_var, values=STATUSES,
                     state="readonly", width=11).pack(side="left")
        r += 1

        # Fechas
        self._label(body, "Inicio", r)
        start_row = self._tint(tk.Frame(body))
        start_row.grid(row=r, column=1, columnspan=3, sticky="w")
        self.start_field = DateField(start_row, app, parse_iso(ev["start"]),
                                     on_change=self._on_start_change)
        self._tint(self.start_field)
        self.start_field.pack(side="left")
        self.start_time = TimeField(start_row, ev["start_time"])
        self.start_time.pack(side="left", padx=(8, 0))
        r += 1
        self._label(body, "Fin", r)
        end_row = self._tint(tk.Frame(body))
        end_row.grid(row=r, column=1, columnspan=3, sticky="w")
        self.end_field = DateField(end_row, app, parse_iso(ev["end"]))
        self._tint(self.end_field)
        self.end_field.pack(side="left")
        self.end_time = TimeField(end_row, ev["end_time"])
        self.end_time.pack(side="left", padx=(8, 0))
        r += 1

        checks = self._tint(tk.Frame(body))
        checks.grid(row=r, column=1, columnspan=3, sticky="w", pady=(2, 4))
        self.all_day_var = tk.BooleanVar(value=ev["all_day"])
        self.pinned_var = tk.BooleanVar(value=ev["pinned"])
        cb1 = tk.Checkbutton(checks, text="Todo el día", variable=self.all_day_var,
                             font=(UI_FONT, 9), command=self._on_all_day, bd=0,
                             highlightthickness=0)
        cb2 = tk.Checkbutton(checks, text="Fijado en la barra lateral", variable=self.pinned_var,
                             font=(UI_FONT, 9), bd=0, highlightthickness=0)
        self._tint(cb1, "check")
        self._tint(cb2, "check")
        cb1.pack(side="left")
        cb2.pack(side="left", padx=(16, 0))
        r += 1

        # Campos personalizados
        self.custom_vars = {}
        customs = self.store.custom_columns()
        if customs:
            sep = self._tint(tk.Frame(body, height=1), "line")
            sep.grid(row=r, column=0, columnspan=4, sticky="ew", pady=8)
            r += 1
            for col in customs:
                self._label(body, col["label"], r)
                var = tk.StringVar(value=ev["custom"].get(col["key"], ""))
                entry = styled_entry(body, app, width=36, textvariable=var)
                entry.grid(row=r, column=1, columnspan=3, sticky="ew", ipady=3)
                self.custom_vars[col["key"]] = var
                r += 1

        # Notas con formato: barra + texto enriquecido
        self._label(body, "Notas", r, sticky="nw")
        notes_box = tk.Frame(body, bg=app.palette()["border"])
        notes_box.grid(row=r, column=1, columnspan=3, sticky="nsew", pady=5)
        self.notes = RichText(notes_box, app, editable=True, height=9, width=56)
        toolbar = RichToolbar(notes_box, app, self.notes)
        toolbar.pack(side="top", fill="x", padx=1, pady=(1, 0))
        self.notes.pack(side="top", fill="both", expand=True)
        self.notes.load(ev.get("notes_rich"), ev.get("notes", ""))
        body.grid_rowconfigure(r, weight=1)
        r += 1

        # Adjuntos
        self._label(body, "Adjuntos", r, sticky="nw")
        self.attachments = [dict(a) for a in ev.get("attachments", [])]
        att_box = self._tint(tk.Frame(body))
        att_box.grid(row=r, column=1, columnspan=3, sticky="ew", pady=(2, 4))
        self.att_list = self._tint(tk.Frame(att_box))
        self.att_list.pack(side="top", fill="x")
        FlatButton(att_box, app, text="Adjuntar archivos", icon="paperclip", padx=8, pady=3,
                   tooltip="Se copian a la carpeta assets del proyecto",
                   command=self._attach).pack(side="top", anchor="w", pady=(2, 0))
        self._render_attachments()
        r += 1

        self.error_lbl = self._tint(tk.Label(body, text="", font=(UI_FONT, 9), anchor="w"), "error")
        self.error_lbl.grid(row=r, column=1, columnspan=3, sticky="w")

        footer = self._tint(tk.Frame(self))
        footer.pack(side="bottom", fill="x", padx=16, pady=(4, 16), before=body)
        FlatButton(footer, app, text="Guardar", kind="accent", icon="check", padx=14, pady=5,
                   font=(UI_FONT, 9, "bold"), command=self._save).pack(side="right", padx=(6, 0))
        FlatButton(footer, app, text="Cancelar", padx=14, pady=5, font=(UI_FONT, 9, "bold"),
                   command=self.cancel).pack(side="right")
        if not self.is_new:
            FlatButton(footer, app, text="Eliminar", kind="danger", icon="trash", padx=12,
                       pady=5, font=(UI_FONT, 9, "bold"),
                       command=self._delete).pack(side="left")
            FlatButton(footer, app, text="Duplicar", icon="duplicate", padx=12, pady=5,
                       font=(UI_FONT, 9, "bold"), command=self._duplicate
                       ).pack(side="left", padx=(6, 0))

        self.bind("<Control-Return>", lambda e: self._save())
        self.bind("<Control-s>", lambda e: (self._save(), "break")[1])
        self._on_all_day()

    # ------------------------------------------------------- tipos
    def _load_type_choices(self):
        self._type_ids = [None] + [t["id"] for t in self.store.types]
        names = [NO_TYPE_LABEL] + [t["name"] for t in self.store.types]
        self.type_cb.configure(values=names)
        current = self.event.get("type_id")
        if current not in self._type_ids:
            current = None
        self.type_cb.current(self._type_ids.index(current))

    def _selected_type(self):
        idx = self.type_cb.current()
        return self._type_ids[idx] if 0 <= idx < len(self._type_ids) else None

    def _on_type_change(self):
        self.event["type_id"] = self._selected_type()
        self._apply_color()

    def _edit_types(self):
        self.event["type_id"] = self._selected_type()
        TypesEditor(self.app, self.store, parent=self).show()
        if self.winfo_exists():
            self._load_type_choices()
            self.event["type_id"] = self._selected_type()
            self._apply_color()

    def _apply_color(self):
        p = self.app.palette()
        color = self.store.type_color(self.event.get("type_id"))
        dark = self.app.theme == "dark"
        body_bg = blend(color, p["app_bg"], 0.55 if dark else 0.62)
        head_fg = ink_on(color)
        body_fg = ink_on(body_bg)
        muted = blend(body_fg, body_bg, 0.35)
        self.configure(bg=body_bg)
        self.bg = body_bg
        for widget, role in self._tinted:
            try:
                if role == "header":
                    widget.configure(bg=color)
                elif role == "header_muted":
                    widget.configure(bg=color, fg=blend(head_fg, color, 0.3),
                                     text=self.store.type_name(self.event.get("type_id")))
                elif role == "header_entry":
                    widget.configure(bg=color, fg=head_fg, insertbackground=head_fg)
                elif role == "header_line":
                    widget.configure(bg=blend(head_fg, color, 0.55))
                elif role == "label":
                    widget.configure(bg=body_bg, fg=muted)
                elif role == "check":
                    widget.configure(bg=body_bg, fg=body_fg, activebackground=body_bg,
                                     activeforeground=body_fg, selectcolor=p["button_bg"])
                elif role == "line":
                    widget.configure(bg=blend(body_fg, body_bg, 0.8))
                elif role == "error":
                    widget.configure(bg=body_bg, fg=p.get("danger", "#c0392b"))
                else:
                    widget.configure(bg=body_bg)
            except tk.TclError:
                pass

    # ------------------------------------------------------ adjuntos
    def _attach(self):
        paths = ask_open_filenames(self.app, parent=self, title="Adjuntar archivos al evento")
        if not paths:
            return
        errors = []
        for path in paths:
            try:
                size = os.path.getsize(path)
                if size > 200 * 1024 * 1024 and not confirm(
                        self.app, "Adjuntar", f"«{os.path.basename(path)}» ocupa "
                        f"{pf.human_size(size)}.", "Se copiará dentro de la carpeta del "
                        "proyecto. ¿Adjuntarlo igualmente?", ok_text="Adjuntar", parent=self):
                    continue
                rel, size = pf.store_file(self.app, path)
            except OSError as exc:
                errors.append(f"{os.path.basename(path)}: {exc}")
                continue
            if not any(a["path"] == rel for a in self.attachments):
                self.attachments.append({"name": os.path.basename(path), "path": rel, "size": size})
        self._render_attachments()
        if errors:
            alert(self.app, "Adjuntar", "Algunos archivos no se pudieron adjuntar.",
                  "\n".join(errors), "warning", parent=self)

    def _render_attachments(self):
        p = self.app.palette()
        for w in self.att_list.winfo_children():
            w.destroy()
        for att in self.attachments:
            row = tk.Frame(self.att_list, bg=p["button_bg"], highlightthickness=1,
                           highlightbackground=p["border"])
            row.pack(side="top", fill="x", pady=1)
            icon = "image" if pf.is_image(att["name"]) else "file"
            img = get_icon(self, icon, p["muted_text"], 16)
            tk.Label(row, image=img or "", bg=p["button_bg"]).pack(side="left", padx=(6, 4))
            name = tk.Label(row, text=att["name"], bg=p["button_bg"], fg=p["accent"],
                            font=(UI_FONT, 9), cursor="hand2", anchor="w")
            name.pack(side="left")
            name.bind("<Button-1>", lambda e, a=att: self._open_attachment(a))
            tk.Label(row, text=pf.human_size(att.get("size")), bg=p["button_bg"],
                     fg=p["muted_text"], font=(UI_FONT, 8)).pack(side="left", padx=8)
            FlatButton(row, self.app, icon="close", kind="ghost", bg_key="button_bg", padx=3,
                       pady=1, icon_size=12, tooltip="Quitar el adjunto del evento",
                       command=lambda a=att: self._remove_attachment(a)).pack(side="right")

    def _open_attachment(self, att):
        path = pf.resolve(self.app, att["path"])
        if not path or not os.path.isfile(path):
            alert(self.app, "Abrir adjunto", "No se encuentra el archivo.",
                  f"Debería estar en {att['path']} dentro de la carpeta del proyecto.",
                  "warning", parent=self)
            return
        try:
            pf.open_path(path)
        except OSError as exc:
            alert(self.app, "Abrir adjunto", "No se pudo abrir el archivo.", str(exc),
                  "warning", parent=self)

    def _remove_attachment(self, att):
        self.attachments = [a for a in self.attachments if a is not att]
        self._render_attachments()

    # ------------------------------------------------------ fechas
    def _on_start_change(self, day):
        end = self.end_field.get()
        if end is None or end < day:
            self.end_field.set(day)

    def _on_all_day(self):
        state = "disabled" if self.all_day_var.get() else "normal"
        self.start_time.configure(state=state)
        self.end_time.configure(state=state)
        if self.all_day_var.get():
            return
        if not self.start_time.get():
            self.start_time.set("09:00")
        if not self.end_time.get():
            self.end_time.set("10:00")

    # ---------------------------------------------------- acciones
    def _collect(self):
        name = self.name_var.get().strip()
        if not name:
            return None, "Escribe un nombre para el evento."
        start, end = self.start_field.get(), self.end_field.get()
        if start is None:
            return None, "La fecha de inicio no es válida (usa dd/mm/aaaa)."
        if end is None:
            end = start
        if end < start:
            return None, "La fecha de fin no puede ser anterior al inicio."
        all_day = self.all_day_var.get()
        st = et = ""
        if not all_day:
            st, et = self.start_time.value(), self.end_time.value()
            if st is None or et is None:
                return None, "Revisa las horas (formato HH:MM)."
            if not st:
                all_day = True
                et = ""
            elif start == end and et and et <= st:
                return None, "La hora de fin debe ser posterior a la de inicio."
        ev = dict(self.event)
        ev.update({"name": name, "type_id": self._selected_type(),
                   "priority": self.priority_var.get(), "status": self.status_var.get(),
                   "start": start.isoformat(), "end": end.isoformat(),
                   "all_day": all_day, "start_time": st, "end_time": et,
                   "pinned": self.pinned_var.get(),
                   "notes": self.notes.plain_text(),
                   "notes_rich": self.notes.dump(),
                   "attachments": [dict(a) for a in self.attachments],
                   "custom": {k: v.get().strip() for k, v in self.custom_vars.items()
                              if v.get().strip()}})
        return ev, ""

    def _save(self):
        ev, error = self._collect()
        if ev is None:
            self.error_lbl.configure(text=error)
            self.bell()
            return
        self.store.save_event(ev)
        self.result = ("saved", ev["id"])
        self.close()

    def _duplicate(self):
        ev, error = self._collect()
        if ev is None:
            self.error_lbl.configure(text=error)
            return
        self.store.save_event(ev)
        dup = self.store.duplicate_event(ev["id"])
        self.result = ("saved", dup["id"] if dup else ev["id"])
        self.close()

    def _delete(self):
        if confirm(self.app, "Eliminar evento", "¿Eliminar este evento?",
                   f"«{self.event['name'] or 'Sin título'}» desaparecerá del calendario "
                   "y de la tabla.", ok_text="Eliminar", kind="danger", parent=self):
            self.store.delete_event(self.event["id"])
            self.result = ("deleted", self.event["id"])
            self.close()


def edit_event(app, store, event_id, parent=None):
    event = store.get(event_id)
    if event is None:
        return None
    return EventEditor(app, store, event, False, parent).show(width=640)


def create_event(app, store, day=None, start_time="", end_time="", type_id=None, parent=None):
    event = store.new_event(day, start_time, end_time, type_id)
    dlg = EventEditor(app, store, event, True, parent)
    return dlg.show(width=640, focus=dlg.name_entry)


# ----------------------------------------------------------------------
# Editar tipos
# ----------------------------------------------------------------------
class TypesEditor(Dialog):
    def __init__(self, app, store, parent=None):
        super().__init__(app, "Tipos de evento", parent)
        self.store = store
        self.work = copy.deepcopy(store.types)
        self.vars = {}
        p = app.palette()
        tk.Label(self, text="Tipos de evento", bg=self.bg, fg=p["text"],
                 font=(UI_FONT, 13, "bold"), anchor="w").pack(fill="x", padx=20, pady=(18, 0))
        tk.Label(self, text="El color de cada tipo se usa como fondo del evento en el "
                            "calendario, la tabla y la ficha de edición.",
                 bg=self.bg, fg=p["muted_text"], font=(UI_FONT, 9), anchor="w",
                 justify="left", wraplength=420).pack(fill="x", padx=20, pady=(2, 10))
        self.scroll = ScrollFrame(self, app, "app_bg", max_height=330)
        self.scroll.pack(fill="both", expand=True, padx=16)
        FlatButton(self, app, text="Añadir tipo", icon="plus", kind="ghost", bg_key="app_bg",
                   command=self._add).pack(anchor="w", padx=16, pady=(6, 0))
        footer = tk.Frame(self, bg=self.bg)
        footer.pack(fill="x", padx=16, pady=16)
        FlatButton(footer, app, text="Guardar", kind="accent", icon="check", padx=14, pady=5,
                   font=(UI_FONT, 9, "bold"), command=self._save).pack(side="right", padx=(6, 0))
        FlatButton(footer, app, text="Cancelar", padx=14, pady=5, font=(UI_FONT, 9, "bold"),
                   command=self.cancel).pack(side="right")
        self.bind("<Return>", lambda e: self._save())
        self._rows()

    def _sync_names(self):
        for t in self.work:
            var = self.vars.get(t["id"])
            if var is not None:
                t["name"] = var.get()

    def _rows(self):
        app, p = self.app, self.app.palette()
        body = self.scroll.body
        for w in body.winfo_children():
            w.destroy()
        self.vars = {}
        if not self.work:
            tk.Label(body, text="No hay tipos. Añade uno para clasificar los eventos.",
                     bg=self.bg, fg=p["muted_text"], font=(UI_FONT, 9)).pack(pady=12)
        for t in self.work:
            row = tk.Frame(body, bg=self.bg)
            row.pack(fill="x", pady=3)
            img = swatch(self, t["color"], 26)
            sw = tk.Label(row, image=img, bg=self.bg, cursor="hand2")
            sw.pack(side="left", padx=(4, 8))
            sw.bind("<Button-1>", lambda e, tt=t, w=sw: self._pick_color(tt, w))
            var = tk.StringVar(value=t["name"])
            self.vars[t["id"]] = var
            styled_entry(row, app, width=28, textvariable=var).pack(side="left", ipady=3)
            n = self.store.count_by_type(t["id"])
            tk.Label(row, text=f"{n} evento" + ("" if n == 1 else "s"), bg=self.bg,
                     fg=p["muted_text"], font=(UI_FONT, 8), width=10, anchor="w"
                     ).pack(side="left", padx=8)
            FlatButton(row, app, icon="trash", kind="ghost", bg_key="app_bg", padx=4,
                       tooltip="Eliminar tipo",
                       command=lambda tt=t: self._remove(tt)).pack(side="right", padx=(0, 4))
        self.scroll.bind_children_wheel()
        self.update_idletasks()

    def _pick_color(self, t, widget):
        self._sync_names()

        def apply(color):
            t["color"] = color
            self._rows()
        ColorPopup(self.app, widget, t["color"], apply).open()

    def _add(self):
        self._sync_names()
        used = {t["color"].lower() for t in self.work}
        color = next((c for c in TYPE_COLORS if c.lower() not in used), TYPE_COLORS[0])
        self.work.append({"id": new_id("t"), "name": "Nuevo tipo", "color": color})
        self._rows()
        self.after(30, lambda: self.scroll.canvas.yview_moveto(1.0))

    def _remove(self, t):
        self._sync_names()
        n = self.store.count_by_type(t["id"])
        if n and not confirm(self.app, "Eliminar tipo", f"¿Eliminar «{t['name']}»?",
                             f"{n} evento{'s' if n != 1 else ''} pasará"
                             f"{'n' if n != 1 else ''} a «{NO_TYPE_LABEL}». "
                             "Los eventos no se borran.",
                             ok_text="Eliminar tipo", kind="danger", parent=self):
            return
        self.work = [x for x in self.work if x["id"] != t["id"]]
        self._rows()

    def _save(self):
        self._sync_names()
        for t in self.work:
            t["name"] = t["name"].strip()
            if not t["name"]:
                alert(self.app, "Tipos de evento", "Hay un tipo sin nombre.",
                      "Escribe un nombre o elimínalo antes de guardar.", "warning", parent=self)
                return
        self.store.set_types(self.work)
        self.result = True
        self.close()


# ----------------------------------------------------------------------
# Personalizar columnas
# ----------------------------------------------------------------------
class ColumnsEditor(Dialog):
    def __init__(self, app, store, parent=None):
        super().__init__(app, "Columnas de la tabla", parent)
        self.store = store
        self.work = copy.deepcopy(store.columns)
        p = app.palette()
        tk.Label(self, text="Columnas de la tabla", bg=self.bg, fg=p["text"],
                 font=(UI_FONT, 13, "bold"), anchor="w").pack(fill="x", padx=20, pady=(18, 0))
        tk.Label(self, text="Muestra, oculta, renombra y ordena las columnas. Las columnas "
                            "nuevas aparecen también como campos en la ficha del evento.",
                 bg=self.bg, fg=p["muted_text"], font=(UI_FONT, 9), anchor="w",
                 justify="left", wraplength=440).pack(fill="x", padx=20, pady=(2, 10))
        self.scroll = ScrollFrame(self, app, "app_bg", max_height=360)
        self.scroll.pack(fill="both", expand=True, padx=16)
        FlatButton(self, app, text="Añadir columna", icon="plus", kind="ghost", bg_key="app_bg",
                   command=self._add).pack(anchor="w", padx=16, pady=(6, 0))
        footer = tk.Frame(self, bg=self.bg)
        footer.pack(fill="x", padx=16, pady=16)
        FlatButton(footer, app, text="Guardar", kind="accent", icon="check", padx=14, pady=5,
                   font=(UI_FONT, 9, "bold"), command=self._save).pack(side="right", padx=(6, 0))
        FlatButton(footer, app, text="Cancelar", padx=14, pady=5, font=(UI_FONT, 9, "bold"),
                   command=self.cancel).pack(side="right")
        self._rows()

    def _sync(self):
        for col in self.work:
            if "_label" in col:
                col["label"] = col["_label"].get()
                col["visible"] = True if col["key"] == "name" else col["_visible"].get()

    def _rows(self):
        app, p = self.app, self.app.palette()
        body = self.scroll.body
        for w in body.winfo_children():
            w.destroy()
        last = len(self.work) - 1
        for i, col in enumerate(self.work):
            row = tk.Frame(body, bg=self.bg)
            row.pack(fill="x", pady=2)
            col["_visible"] = tk.BooleanVar(value=col["visible"])
            chk = tk.Checkbutton(row, variable=col["_visible"], bg=self.bg,
                                 activebackground=self.bg, selectcolor=p["button_bg"],
                                 bd=0, highlightthickness=0)
            if col["key"] == "name":
                chk.configure(state="disabled")
            chk.pack(side="left", padx=(2, 6))
            col["_label"] = tk.StringVar(value=col["label"])
            styled_entry(row, app, width=26, textvariable=col["_label"]).pack(side="left", ipady=3)
            tk.Label(row, text="propia" if not col["builtin"] else "", width=7,
                     bg=self.bg, fg=p["muted_text"], font=(UI_FONT, 8)).pack(side="left")
            trash = FlatButton(row, app, icon="trash", kind="ghost", bg_key="app_bg", padx=3,
                               tooltip="Eliminar columna y sus datos",
                               command=lambda c=col: self._remove(c))
            trash.pack(side="right")
            if col["builtin"]:
                trash.set_enabled(False)
                trash.set_tooltip("Las columnas básicas solo se pueden ocultar")
            down = FlatButton(row, app, icon="chevron_down", kind="ghost", bg_key="app_bg",
                              padx=2, tooltip="Bajar", command=lambda k=i: self._move(k, 1))
            up = FlatButton(row, app, icon="chevron_up", kind="ghost", bg_key="app_bg",
                            padx=2, tooltip="Subir", command=lambda k=i: self._move(k, -1))
            down.pack(side="right")
            up.pack(side="right")
            up.set_enabled(i > 0)
            down.set_enabled(i < last)
        self.scroll.bind_children_wheel()

    def _move(self, index, delta):
        self._sync()
        j = index + delta
        if 0 <= j < len(self.work):
            self.work[index], self.work[j] = self.work[j], self.work[index]
            self._rows()

    def _add(self):
        self._sync()
        self.work.append({"key": new_id("c_"), "label": "Nuevo campo", "visible": True,
                          "width": 150, "builtin": False})
        self._rows()
        self.after(30, lambda: self.scroll.canvas.yview_moveto(1.0))

    def _remove(self, col):
        self._sync()
        used = sum(1 for e in self.store.items if e["custom"].get(col["key"]))
        if used and not confirm(self.app, "Eliminar columna", f"¿Eliminar «{col['label']}»?",
                                f"Se borrará este dato en {used} evento"
                                f"{'s' if used != 1 else ''}.",
                                ok_text="Eliminar columna", kind="danger", parent=self):
            return
        self.work = [c for c in self.work if c["key"] != col["key"]]
        self._rows()

    def _save(self):
        self._sync()
        clean = []
        for col in self.work:
            label = col["label"].strip() or ("Campo" if not col["builtin"] else col["key"])
            clean.append({"key": col["key"], "label": label, "visible": col["visible"],
                          "width": col.get("width", 150), "builtin": col["builtin"]})
        self.store.set_columns(clean)
        self.result = True
        self.close()


def priority_dot(master, priority, size=10):
    return swatch(master, PRIORITY_COLORS.get(priority, "#8A949E"), size, radius=size // 2,
                  border="#00000000")


__all__ = ["EventEditor", "TypesEditor", "ColumnsEditor", "edit_event", "create_event",
           "priority_dot", "NO_TYPE_LABEL", "CLOSED_STATUSES", "NO_TYPE_COLOR", "get_icon"]
