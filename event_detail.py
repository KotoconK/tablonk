"""Panel inferior de la seccion Eventos: muestra el evento seleccionado.

Es de solo lectura. Para modificarlo se usa el boton Editar.
"""

import os
import tkinter as tk

import project_files as pf
from events_store import PRIORITY_COLORS, parse_iso
from icons import get_icon, swatch
from rich_notes import RichText
from ui_common import MONTHS, UI_FONT, WEEKDAYS, FlatButton, alert, blend, ink_on


def describe_when(event):
    s, e = parse_iso(event["start"]), parse_iso(event["end"])
    if not s:
        return ""

    def day(d):
        return f"{WEEKDAYS[d.weekday()]} {d.day} de {MONTHS[d.month - 1]} de {d.year}"
    timed = not event["all_day"] and event["start_time"]
    if e and e != s:
        text = f"Del {day(s)}"
        if timed:
            text += f", {event['start_time']}"
        text += f" al {day(e)}"
        if timed and event["end_time"]:
            text += f", {event['end_time']}"
        return text
    text = day(s).capitalize()
    if timed:
        text += f", de {event['start_time']}" + (f" a {event['end_time']}" if event["end_time"] else "")
    else:
        text += ", todo el día"
    return text


class EventDetail(tk.Frame):
    def __init__(self, master, app, store, on_edit, on_calendar):
        super().__init__(master, bd=0)
        self.app = app
        self.store = store
        self.on_edit = on_edit
        self.on_calendar = on_calendar
        self.event_id = None
        self._tinted = []

        self.empty = tk.Label(self, font=(UI_FONT, 10), justify="center")
        self.content = tk.Frame(self)

        # Cabecera con el color del tipo
        self.header = tk.Frame(self.content)
        self.header.pack(fill="x")
        self.actions = tk.Frame(self.header)
        self.actions.pack(side="right", anchor="n", padx=(8, 14), pady=12)
        self.edit_btn = FlatButton(self.actions, app, text="Editar", icon="edit", kind="accent",
                                   padx=10, pady=4, font=(UI_FONT, 9, "bold"),
                                   tooltip="Abrir la ficha de edición (F2)",
                                   command=lambda: self.event_id and self.on_edit(self.event_id))
        self.edit_btn.pack(side="right", padx=(4, 0))
        self.cal_btn = FlatButton(self.actions, app, icon="calendar", padx=6, pady=4,
                                  tooltip="Ver en el calendario",
                                  command=lambda: self.event_id and self.on_calendar(self.event_id))
        self.cal_btn.pack(side="right", padx=2)
        self.pin_btn = FlatButton(self.actions, app, icon="pin", padx=6, pady=4,
                                  tooltip="Fijar en la barra lateral", command=self._toggle_pin)
        self.pin_btn.pack(side="right", padx=2)
        titles = tk.Frame(self.header)
        titles.pack(side="left", fill="x", expand=True, padx=(18, 0), pady=(10, 12))
        self.titles = titles
        self.type_lbl = tk.Label(titles, font=(UI_FONT, 9, "bold"), anchor="w")
        self.type_lbl.pack(fill="x")
        self.name_lbl = tk.Label(titles, font=(UI_FONT, 15, "bold"), anchor="w", justify="left")
        self.name_lbl.pack(fill="x")
        self.header.bind("<Configure>", self._wrap_title)

        # Datos
        self.meta = tk.Frame(self.content)
        self.meta.pack(fill="x", padx=18, pady=(10, 4))

        # Adjuntos (abajo, siempre visibles) y notas (ocupan el resto)
        self.att_frame = tk.Frame(self.content)
        self.att_frame.pack(side="bottom", fill="x", padx=18, pady=(0, 12))
        self.notes_wrap = tk.Frame(self.content)
        self.notes_wrap.pack(fill="both", expand=True, padx=18, pady=(4, 8))
        self.notes = RichText(self.notes_wrap, app, editable=False, height=4)
        self.no_notes = tk.Label(self.notes_wrap, font=(UI_FONT, 9), anchor="w", justify="left")
        self.update_theme()
        self.show([])

    # ------------------------------------------------------------ tema
    def update_theme(self):
        p = self.app.palette()
        for w in (self, self.content):
            w.configure(bg=p["app_bg"])
        self.empty.configure(bg=p["app_bg"], fg=p["muted_text"])
        for b in (self.edit_btn, self.cal_btn, self.pin_btn):
            b.restyle()
        self.notes.restyle()
        if self.event_id:
            self.show([self.event_id])

    def _wrap_title(self, event):
        width = max(120, event.width - self.actions.winfo_width() - 50)
        self.name_lbl.configure(wraplength=width)

    # ------------------------------------------------------------ mostrar
    def show(self, ids):
        ids = [i for i in ids if self.store.get(i)]
        if len(ids) != 1:
            self.event_id = None
            self.content.pack_forget()
            if ids:
                text = f"{len(ids)} eventos seleccionados."
            elif self.store.items:
                text = ("Selecciona un evento para ver su contenido.\n"
                        "Para modificarlo, usa Editar.")
            else:
                text = ""
            self.empty.configure(text=text)
            self.empty.pack(fill="both", expand=True)
            return
        self.empty.pack_forget()
        self.content.pack(fill="both", expand=True)
        self.event_id = ids[0]
        self._render(self.store.get(ids[0]))

    def _render(self, ev):
        p = self.app.palette()
        dark = self.app.theme == "dark"
        color = self.store.type_color(ev["type_id"])
        fg = ink_on(color)
        body = blend(color, p["app_bg"], 0.55 if dark else 0.72)
        body_fg = ink_on(body)
        muted = blend(body_fg, body, 0.38)
        for w in (self.header, self.titles, self.actions):
            w.configure(bg=color)
        self.type_lbl.configure(bg=color, fg=blend(fg, color, 0.3),
                                text=self.store.type_name(ev["type_id"]))
        self.name_lbl.configure(bg=color, fg=fg, text=ev["name"])
        self.pin_btn.set_icon("pin_filled" if ev["pinned"] else "pin")
        self.pin_btn.set_tooltip("Desfijar" if ev["pinned"] else "Fijar en la barra lateral")
        for w in (self.content, self.meta, self.notes_wrap, self.att_frame):
            w.configure(bg=body)

        # Datos en pares etiqueta / valor
        for w in self.meta.winfo_children():
            w.destroy()
        pairs = [("Cuándo", describe_when(ev), None),
                 ("Prioridad", ev["priority"], PRIORITY_COLORS.get(ev["priority"])),
                 ("Estado", ev["status"], None)]
        for col in self.store.custom_columns():
            value = ev["custom"].get(col["key"], "")
            if value:
                pairs.append((col["label"], value, None))
        columns = 4
        for c in range(columns + 1):
            self.meta.grid_columnconfigure(c, weight=1 if c == columns else 0)
        for n, (label, value, dot) in enumerate(pairs):
            r, c = divmod(n, columns)
            cell = tk.Frame(self.meta, bg=body)
            cell.grid(row=r * 2, column=c, sticky="nw", padx=(0, 28), pady=(0, 6))
            tk.Label(cell, text=label, bg=body, fg=muted, font=(UI_FONT, 8, "bold"),
                     anchor="w").pack(anchor="w")
            row = tk.Frame(cell, bg=body)
            row.pack(anchor="w")
            if dot:
                img = swatch(self, dot, 10, radius=5, border="#00000000")
                if img:
                    tk.Label(row, image=img, bg=body).pack(side="left", padx=(0, 5))
            tk.Label(row, text=value, bg=body, fg=body_fg, font=(UI_FONT, 10),
                     anchor="w", justify="left", wraplength=420).pack(side="left")

        # Notas
        self.notes.pack_forget()
        self.no_notes.pack_forget()
        if ev.get("notes_rich") or ev.get("notes"):
            self.notes.restyle()
            self.notes.load(ev.get("notes_rich"), ev.get("notes", ""))
            self.notes.pack(fill="both", expand=True)
        else:
            self.no_notes.configure(bg=body, fg=muted,
                                    text="Sin notas. Con Editar puedes añadir texto con formato, "
                                         "listas, enlaces, imágenes y archivos adjuntos.")
            self.no_notes.pack(fill="x")

        # Adjuntos
        for w in self.att_frame.winfo_children():
            w.destroy()
        attachments = ev.get("attachments", [])
        if attachments:
            head = tk.Frame(self.att_frame, bg=body)
            head.pack(fill="x", pady=(2, 4))
            img = get_icon(self, "paperclip", muted, 14)
            if img:
                tk.Label(head, image=img, bg=body).pack(side="left", padx=(0, 4))
            tk.Label(head, text=f"Adjuntos ({len(attachments)})", bg=body, fg=muted,
                     font=(UI_FONT, 8, "bold")).pack(side="left")
            flow = tk.Frame(self.att_frame, bg=body, height=34)
            flow.pack(fill="x")
            chips = [self._chip(flow, att) for att in attachments]
            flow.bind("<Configure>", lambda e, f=flow, c=chips: self._reflow(f, c))
            self.after_idle(lambda f=flow, c=chips: self._reflow(f, c))

    @staticmethod
    def _reflow(flow, chips):
        """Coloca los adjuntos en filas que se ajustan al ancho disponible."""
        if not flow.winfo_exists():
            return
        width = max(flow.winfo_width(), 200)
        x = y = row_h = 0
        for chip in chips:
            w, h = chip.winfo_reqwidth(), chip.winfo_reqheight()
            if x and x + w > width:
                x, y = 0, y + row_h + 6
                row_h = 0
            chip.place(x=x, y=y)
            x += w + 6
            row_h = max(row_h, h)
        flow.configure(height=y + row_h + 2)

    def _chip(self, parent, att):
        p = self.app.palette()
        chip = tk.Frame(parent, bg=p["button_bg"], highlightthickness=1,
                        highlightbackground=p["border"], cursor="hand2")
        icon = get_icon(self, "image" if pf.is_image(att["name"]) else "file", p["muted_text"], 16)
        widgets = [chip]
        if icon:
            lbl = tk.Label(chip, image=icon, bg=p["button_bg"], cursor="hand2")
            lbl.pack(side="left", padx=(6, 4), pady=4)
            widgets.append(lbl)
        name = tk.Label(chip, text=att["name"], bg=p["button_bg"], fg=p["text"],
                        font=(UI_FONT, 9), cursor="hand2")
        name.pack(side="left")
        size = tk.Label(chip, text=pf.human_size(att.get("size")), bg=p["button_bg"],
                        fg=p["muted_text"], font=(UI_FONT, 8), cursor="hand2")
        size.pack(side="left", padx=(6, 8))
        widgets += [name, size]
        for w in widgets:
            w.bind("<Button-1>", lambda e, a=att: self._open(a))
            w.bind("<Button-3>", lambda e, a=att: self._chip_menu(e, a))
            w.bind("<Enter>", lambda e: [x.configure(bg=p["button_hover"]) for x in widgets])
            w.bind("<Leave>", lambda e: [x.configure(bg=p["button_bg"]) for x in widgets])
        return chip

    def _path(self, att):
        path = pf.resolve(self.app, att["path"])
        if not path or not os.path.isfile(path):
            alert(self.app, "Adjunto", "No se encuentra el archivo.",
                  f"Debería estar en {att['path']} dentro de la carpeta del proyecto.", "warning")
            return None
        return path

    def _open(self, att):
        path = self._path(att)
        if path:
            try:
                pf.open_path(path)
            except OSError as exc:
                alert(self.app, "Adjunto", "No se pudo abrir el archivo.", str(exc), "warning")

    def _chip_menu(self, event, att):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Abrir", command=lambda: self._open(att))
        menu.add_command(label="Mostrar en la carpeta", command=lambda: (
            (lambda p: p and pf.show_in_folder(p))(self._path(att))))
        menu.tk_popup(event.x_root, event.y_root)

    def _toggle_pin(self):
        if self.event_id:
            self.store.toggle_pin(self.event_id)
