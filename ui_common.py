"""Componentes de interfaz compartidos por TablonK Advance.

- Dialogos propios (confirmar, avisar, pedir texto) que SIEMPRE aparecen
  centrados en la pantalla donde esta la ventana de la aplicacion.
- Dialogos nativos (color, abrir/guardar archivo, carpeta) anclados al
  centro de esa misma pantalla.
- Botones planos con icono, ayuda emergente, campos de fecha y hora y una
  paleta de colores emergente.
"""

import calendar as _cal
import datetime as _dt
import sys
import tkinter as tk
from tkinter import colorchooser, filedialog, ttk

from icons import get_icon, swatch

UI_FONT = "Segoe UI"

MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre")
MONTHS_SHORT = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago",
                "sep", "oct", "nov", "dic")
WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
WEEKDAYS_SHORT = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
WEEKDAYS_MIN = ("L", "M", "X", "J", "V", "S", "D")

# Paleta pastel para los tipos de evento (fondos claros con texto oscuro).
TYPE_COLORS = (
    "#F6B4A8", "#F9C98F", "#F7E08A", "#CDE69A", "#A8DDB5", "#9ED9D4",
    "#A9CBF5", "#B8B8F2", "#D3B3EE", "#F2B3D6", "#E6C9A8", "#CBD3DC",
    "#E57373", "#FFB74D", "#81C784", "#4DB6AC", "#64B5F6", "#9575CD",
)


# ----------------------------------------------------------------------
# Color
# ----------------------------------------------------------------------
def _rgb(color):
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def is_hex(color):
    if not isinstance(color, str) or not color.startswith("#") or len(color) != 7:
        return False
    try:
        _rgb(color)
        return True
    except ValueError:
        return False


def blend(a, b, amount):
    """Mezcla a hacia b. amount=0 -> a; amount=1 -> b."""
    ar, ag, ab = _rgb(a)
    br, bg, bb = _rgb(b)
    mix = lambda x, y: max(0, min(255, round(x + (y - x) * amount)))
    return "#{:02x}{:02x}{:02x}".format(mix(ar, br), mix(ag, bg), mix(ab, bb))


def ink_on(background):
    """Texto oscuro o claro segun el brillo del fondo."""
    try:
        r, g, b = _rgb(background)
    except (ValueError, AttributeError):
        return "#1d232b"
    return "#1d232b" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#f7f8fa"


# ----------------------------------------------------------------------
# Posicionamiento
# ----------------------------------------------------------------------
def work_area(app):
    """Rectangulo util del monitor donde esta la ventana principal."""
    getter = getattr(app, "_screen_work_area", None)
    if getter is not None:
        try:
            return getter()
        except Exception:
            pass
    return 0, 0, app.winfo_screenwidth(), app.winfo_screenheight()


def center_window(win, app, width=None, height=None):
    """Coloca 'win' en el centro de la pantalla (no de la ventana)."""
    win.update_idletasks()
    w = width or max(win.winfo_reqwidth(), win.winfo_width() if win.winfo_ismapped() else 0)
    h = height or max(win.winfo_reqheight(), win.winfo_height() if win.winfo_ismapped() else 0)
    sx, sy, sw, sh = work_area(app)
    w, h = min(w, sw - 20), min(h, sh - 20)
    x = sx + max(0, (sw - w) // 2)
    y = sy + max(0, (sh - h) // 2)
    if width or height:
        win.geometry(f"{w}x{h}+{x}+{y}")
    else:
        win.geometry(f"+{x}+{y}")


def place_below(popup, widget, app):
    """Coloca un desplegable bajo 'widget' sin salirse de la pantalla."""
    popup.update_idletasks()
    w, h = popup.winfo_reqwidth(), popup.winfo_reqheight()
    sx, sy, sw, sh = work_area(app)
    x = widget.winfo_rootx()
    y = widget.winfo_rooty() + widget.winfo_height() + 2
    if x + w > sx + sw:
        x = sx + sw - w - 4
    if y + h > sy + sh:
        y = widget.winfo_rooty() - h - 2
    popup.geometry(f"+{max(sx, x)}+{max(sy, y)}")


# ----------------------------------------------------------------------
# Ayuda emergente
# ----------------------------------------------------------------------
class HoverTip:
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.job = None
        self.window = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _enter(self, _event):
        self._hide()
        if self.text:
            self.job = self.widget.after(550, self._show)

    def _show(self):
        self.job = None
        if self.window is not None or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + 6
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        tip = tk.Toplevel(self.widget)
        tip.overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except tk.TclError:
            pass
        tip.geometry(f"+{x}+{y}")
        tk.Label(tip, text=self.text, bg="#273443", fg="white", padx=8, pady=4,
                 font=(UI_FONT, 9)).pack()
        self.window = tip

    def _hide(self, _event=None):
        if self.job is not None:
            try:
                self.widget.after_cancel(self.job)
            except (tk.TclError, ValueError):
                pass
            self.job = None
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None


# ----------------------------------------------------------------------
# Botones planos con icono
# ----------------------------------------------------------------------
class FlatButton(tk.Button):
    """Boton plano con icono opcional que sigue el tema de la aplicacion.

    kind: "default" (fondo de boton), "accent", "ghost" (fondo del
    contenedor, indicado con bg_key), "danger" o "titlebar".
    """

    def __init__(self, parent, app, text="", icon=None, command=None,
                 kind="default", tooltip=None, bg_key="toolbar_bg",
                 icon_size=16, font=None, padx=8, pady=3, width=None,
                 icon_color=None, **kw):
        self.app = app
        self._kind = kind
        self._icon = icon
        self._icon_size = icon_size
        self._icon_color = icon_color
        self._bg_key = bg_key
        self._selected = False
        self._enabled = True
        self._command = command
        self._hover = False
        opts = dict(text=text, bd=0, relief="flat", cursor="hand2",
                    font=font or (UI_FONT, 9), padx=padx, pady=pady,
                    command=self._invoke, compound="left", highlightthickness=0)
        if width is not None:
            opts["width"] = width
        opts.update(kw)
        super().__init__(parent, **opts)
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.tip = HoverTip(self, tooltip) if tooltip else None
        self.restyle()

    def _invoke(self):
        if self._enabled and self._command is not None:
            self._command()

    def configure_command(self, command):
        self._command = command

    def set_tooltip(self, text):
        if self.tip is None:
            self.tip = HoverTip(self, text)
        else:
            self.tip.text = text

    def set_icon(self, icon):
        self._icon = icon
        self.restyle()

    def set_kind(self, kind):
        self._kind = kind
        self.restyle()

    def set_selected(self, selected):
        self._selected = bool(selected)
        self.restyle()

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        self.configure(cursor="hand2" if enabled else "arrow")
        self.restyle()

    def _colors(self):
        p = self.app.palette()
        kind = "accent" if self._selected else self._kind
        if kind == "accent":
            bg, fg = p["accent"], "#FFFFFF"
            hover = blend(p["accent"], "#000000", 0.12)
        elif kind == "ghost":
            bg, fg, hover = p[self._bg_key], p["text"], p["button_hover"]
        elif kind == "danger":
            bg, fg = p["button_bg"], p.get("danger", "#c0392b")
            hover = blend(p["button_bg"], p.get("danger", "#c0392b"), 0.12)
        elif kind == "titlebar":
            bg, fg, hover = p["titlebar_bg"], p["text"], p["button_hover"]
        else:
            bg, fg, hover = p["button_bg"], p["text"], p["button_hover"]
        if not self._enabled:
            fg = p["muted_text"]
            hover = bg
        return bg, fg, hover

    def restyle(self):
        bg, fg, hover = self._colors()
        current = hover if (self._hover and self._enabled) else bg
        image = ""
        if self._icon:
            color = self._icon_color if (self._icon_color and self._enabled
                                         and not self._selected) else fg
            img = get_icon(self, self._icon, color, self._icon_size)
            if img is not None:
                image = img
        self.configure(bg=current, fg=fg, activebackground=hover,
                       activeforeground=fg, image=image,
                       disabledforeground=fg)
        if image and not self.cget("text"):
            self.configure(compound="center")

    def _on_enter(self, _e):
        self._hover = True
        self.restyle()

    def _on_leave(self, _e):
        self._hover = False
        self.restyle()


def styled_entry(parent, app, width=20, textvariable=None, font=None, **kw):
    p = app.palette()
    entry = tk.Entry(parent, width=width, textvariable=textvariable, relief="flat",
                     bd=0, highlightthickness=1, font=font or (UI_FONT, 10),
                     bg=p["button_bg"], fg=p["text"], insertbackground=p["text"],
                     highlightbackground=p["border"], highlightcolor=p["accent"],
                     disabledbackground=p["toolbar_bg"], **kw)
    return entry


def restyle_entry(entry, app):
    p = app.palette()
    entry.configure(bg=p["button_bg"], fg=p["text"], insertbackground=p["text"],
                    highlightbackground=p["border"], highlightcolor=p["accent"])


# ----------------------------------------------------------------------
# Dialogos modales propios
# ----------------------------------------------------------------------
class Dialog(tk.Toplevel):
    """Base de los dialogos: modal, tematizado y centrado en pantalla."""

    def __init__(self, app, title, parent=None, bg=None, resizable=False):
        master = parent if parent is not None else app
        super().__init__(master)
        self.withdraw()
        self.app = app
        self.result = None
        self.bg = bg or app.palette()["app_bg"]
        self.title(title)
        self.configure(bg=self.bg)
        self.resizable(resizable, resizable)
        try:
            self.transient(master)
        except tk.TclError:
            pass
        icon = getattr(app, "_icon_path", None)
        if icon and sys.platform == "win32":
            try:
                self.iconbitmap(icon)
            except tk.TclError:
                pass
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda e: self.cancel())

    def cancel(self):
        self.close()

    def close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def show(self, width=None, height=None, focus=None):
        previous_grab = None
        try:
            previous_grab = self.grab_current()
        except (tk.TclError, KeyError):
            previous_grab = None
        center_window(self, self.app, width, height)
        self.deiconify()
        self.lift()
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.focus_force()
        if focus is not None:
            focus.focus_set()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.wait_window()
        if previous_grab is not None and previous_grab is not self:
            try:
                if previous_grab.winfo_exists():
                    previous_grab.grab_set()
                    previous_grab.focus_force()
            except tk.TclError:
                pass
        return self.result


_KIND_ICON = {"info": "info", "warning": "warning", "error": "error",
              "question": "question", "danger": "trash"}


def _kind_color(app, kind):
    p = app.palette()
    return {"warning": "#d08a18", "error": p.get("danger", "#c0392b"),
            "danger": p.get("danger", "#c0392b")}.get(kind, p["accent"])


class MessageDialog(Dialog):
    def __init__(self, app, title, message, detail="", kind="info",
                 buttons=(("Aceptar", True, "accent"),), parent=None):
        super().__init__(app, title, parent)
        p = app.palette()
        body = tk.Frame(self, bg=self.bg)
        body.pack(fill="both", expand=True, padx=22, pady=(20, 10))
        img = get_icon(self, _KIND_ICON.get(kind, "info"), _kind_color(app, kind), 30, 1.8)
        if img is not None:
            tk.Label(body, image=img, bg=self.bg).pack(side="left", anchor="n", padx=(0, 14))
        text = tk.Frame(body, bg=self.bg)
        text.pack(side="left", fill="both", expand=True)
        tk.Label(text, text=message, bg=self.bg, fg=p["text"], justify="left",
                 font=(UI_FONT, 11, "bold"), wraplength=330, anchor="w").pack(anchor="w")
        if detail:
            tk.Label(text, text=detail, bg=self.bg, fg=p["muted_text"], justify="left",
                     font=(UI_FONT, 9), wraplength=330, anchor="w").pack(anchor="w", pady=(6, 0))
        bar = tk.Frame(self, bg=self.bg)
        bar.pack(fill="x", padx=18, pady=(8, 16))
        self.buttons = []
        for label, value, style in reversed(buttons):
            btn = FlatButton(bar, app, text=label, kind=style, bg_key="app_bg",
                             padx=16, pady=5, font=(UI_FONT, 9, "bold"),
                             command=lambda v=value: self._choose(v))
            btn.pack(side="right", padx=(6, 0))
            self.buttons.append((value, btn))
        self.minsize(380, 1)

    def _choose(self, value):
        self.result = value
        self.close()


def confirm(app, title, message, detail="", ok_text="Aceptar",
            cancel_text="Cancelar", kind="question", parent=None):
    """Pregunta Si/No. Teclas: Enter/S/Y confirman; Esc/N cancelan."""
    style = "danger" if kind == "danger" else "accent"
    dlg = MessageDialog(app, title, message, detail, kind,
                        ((cancel_text, False, "default"), (ok_text, True, style)),
                        parent)
    dlg.result = False
    accept = lambda e=None: dlg._choose(True)
    reject = lambda e=None: dlg._choose(False)
    for key in ("<Return>", "<KP_Enter>", "<Key-y>", "<Key-Y>", "<Key-s>", "<Key-S>"):
        dlg.bind(key, accept)
    for key in ("<Key-n>", "<Key-N>", "<Escape>"):
        dlg.bind(key, reject)
    dlg.protocol("WM_DELETE_WINDOW", reject)
    return bool(dlg.show())


def alert(app, title, message, detail="", kind="info", parent=None):
    dlg = MessageDialog(app, title, message, detail, kind, parent=parent)
    dlg.bind("<Return>", lambda e: dlg._choose(True))
    dlg.show()


def ask_string(app, title, prompt, initial="", ok_text="Aceptar", parent=None):
    dlg = Dialog(app, title, parent)
    p = app.palette()
    tk.Label(dlg, text=prompt, bg=dlg.bg, fg=p["text"], font=(UI_FONT, 10),
             anchor="w").pack(fill="x", padx=20, pady=(18, 6))
    var = tk.StringVar(value=initial)
    entry = styled_entry(dlg, app, width=38, textvariable=var)
    entry.pack(fill="x", padx=20, ipady=4)
    entry.select_range(0, "end")
    bar = tk.Frame(dlg, bg=dlg.bg)
    bar.pack(fill="x", padx=16, pady=16)

    def ok(_e=None):
        dlg.result = var.get().strip()
        dlg.close()
    FlatButton(bar, app, text=ok_text, kind="accent", padx=16, pady=5,
               font=(UI_FONT, 9, "bold"), command=ok).pack(side="right", padx=(6, 0))
    FlatButton(bar, app, text="Cancelar", padx=16, pady=5, font=(UI_FONT, 9, "bold"),
               command=dlg.cancel).pack(side="right")
    dlg.bind("<Return>", ok)
    return dlg.show(focus=entry)


# ----------------------------------------------------------------------
# Dialogos nativos centrados en pantalla
# ----------------------------------------------------------------------
class _NativeAnchor:
    """Ventana invisible en el centro de la pantalla que hace de 'padre'.

    Windows situa los dialogos comunes (color, abrir, guardar) respecto a su
    ventana propietaria; al darle una propietaria invisible y centrada, el
    dialogo nativo aparece en el centro de la pantalla.
    """

    def __init__(self, app, parent, w=640, h=440):
        self.app, self.parent, self.w, self.h = app, parent, w, h
        self.win = None

    def __enter__(self):
        owner = self.parent if self.parent is not None else self.app
        if sys.platform != "win32":
            return owner
        try:
            win = tk.Toplevel(owner)
            win.overrideredirect(True)
            win.attributes("-alpha", 0.0)
            win.attributes("-topmost", True)
            sx, sy, sw, sh = work_area(self.app)
            win.geometry(f"{self.w}x{self.h}+{sx + (sw - self.w) // 2}+{sy + (sh - self.h) // 2}")
            win.update_idletasks()
            self.win = win
            return win
        except tk.TclError:
            return owner

    def __exit__(self, *exc):
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
        return False


def ask_color(app, initial="#ffffff", title="Elegir color", parent=None):
    with _NativeAnchor(app, parent, 460, 330) as owner:
        try:
            result = colorchooser.askcolor(color=initial, title=title, parent=owner)
        except tk.TclError:
            result = colorchooser.askcolor(title=title, parent=owner)
    return result[1] if result and result[1] else None


def ask_open_filename(app, parent=None, **kw):
    with _NativeAnchor(app, parent, 820, 520) as owner:
        return filedialog.askopenfilename(parent=owner, **kw)


def ask_saveas_filename(app, parent=None, **kw):
    with _NativeAnchor(app, parent, 820, 520) as owner:
        return filedialog.asksaveasfilename(parent=owner, **kw)


def ask_directory(app, parent=None, **kw):
    with _NativeAnchor(app, parent, 420, 470) as owner:
        return filedialog.askdirectory(parent=owner, **kw)


# ----------------------------------------------------------------------
# Desplegables (popups anclados a un control)
# ----------------------------------------------------------------------
class Popup(tk.Toplevel):
    """Ventana emergente sin bordes que se cierra al pulsar fuera."""

    def __init__(self, app, anchor_widget, on_close=None):
        super().__init__(anchor_widget)
        self.withdraw()
        self.app = app
        self.anchor_widget = anchor_widget
        self.on_close = on_close
        self._prev_grab = None
        p = app.palette()
        self.overrideredirect(True)
        self.configure(bg=p["border"])
        self.inner = tk.Frame(self, bg=p["button_bg"])
        self.inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.bind("<Escape>", lambda e: self.close())

    def open(self):
        place_below(self, self.anchor_widget, self.app)
        self.deiconify()
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.lift()
        try:
            self._prev_grab = self.grab_current()
        except (tk.TclError, KeyError):
            self._prev_grab = None
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_force()
        self.bind("<ButtonPress>", self._maybe_close, add="+")

    def _maybe_close(self, event):
        x, y = event.x_root, event.y_root
        x0, y0 = self.winfo_rootx(), self.winfo_rooty()
        if not (x0 <= x < x0 + self.winfo_width() and y0 <= y < y0 + self.winfo_height()):
            self.close()

    def close(self):
        if not self.winfo_exists():
            return
        try:
            self.grab_release()
        except tk.TclError:
            pass
        prev = self._prev_grab
        self.destroy()
        if prev is not None:
            try:
                if prev.winfo_exists():
                    prev.grab_set()
            except tk.TclError:
                pass
        if self.on_close:
            self.on_close()


class ColorPopup(Popup):
    """Paleta de colores con opcion de color personalizado."""

    def __init__(self, app, anchor_widget, current, callback, colors=TYPE_COLORS):
        super().__init__(app, anchor_widget)
        p = app.palette()
        self.callback = callback
        grid = tk.Frame(self.inner, bg=p["button_bg"])
        grid.pack(padx=8, pady=(8, 4))
        cols = 6
        for i, color in enumerate(colors):
            img = swatch(self, color, 24, checked=(color.lower() == (current or "").lower()),
                         check_color=ink_on(color))
            lbl = tk.Label(grid, image=img, bg=p["button_bg"], cursor="hand2", bd=0)
            lbl.grid(row=i // cols, column=i % cols, padx=2, pady=2)
            lbl.bind("<Button-1>", lambda e, c=color: self._pick(c))
        FlatButton(self.inner, app, text="Personalizado...", icon="palette",
                   kind="ghost", bg_key="button_bg",
                   command=self._custom).pack(fill="x", padx=6, pady=(0, 6))
        self.current = current

    def _pick(self, color):
        self.close()
        self.callback(color)

    def _custom(self):
        current = self.current or "#A9CBF5"
        parent = self.anchor_widget.winfo_toplevel()
        self.close()
        color = ask_color(self.app, current, "Color personalizado", parent=parent)
        if color:
            self.callback(color)


class DatePopup(Popup):
    def __init__(self, app, anchor_widget, value, callback):
        super().__init__(app, anchor_widget)
        self.callback = callback
        self.value = value
        base = value or _dt.date.today()
        self.year, self.month = base.year, base.month
        self.body = tk.Frame(self.inner, bg=app.palette()["button_bg"])
        self.body.pack(padx=8, pady=8)
        self._build()

    def _build(self):
        app = self.app
        p = app.palette()
        for w in self.body.winfo_children():
            w.destroy()
        head = tk.Frame(self.body, bg=p["button_bg"])
        head.grid(row=0, column=0, columnspan=7, sticky="ew", pady=(0, 4))
        FlatButton(head, app, icon="chevron_left", kind="ghost", bg_key="button_bg",
                   padx=3, command=lambda: self._shift(-1)).pack(side="left")
        FlatButton(head, app, icon="chevron_right", kind="ghost", bg_key="button_bg",
                   padx=3, command=lambda: self._shift(1)).pack(side="right")
        tk.Label(head, text=f"{MONTHS[self.month - 1].capitalize()} {self.year}",
                 bg=p["button_bg"], fg=p["text"], font=(UI_FONT, 10, "bold")
                 ).pack(side="left", expand=True)
        for i, name in enumerate(WEEKDAYS_MIN):
            tk.Label(self.body, text=name, width=3, bg=p["button_bg"], fg=p["muted_text"],
                     font=(UI_FONT, 8, "bold")).grid(row=1, column=i)
        today = _dt.date.today()
        weeks = _cal.Calendar(0).monthdatescalendar(self.year, self.month)
        for r, week in enumerate(weeks):
            for c, day in enumerate(week):
                selected = day == self.value
                bg = p["accent"] if selected else p["button_bg"]
                fg = "#FFFFFF" if selected else (p["text"] if day.month == self.month
                                                 else p["muted_text"])
                font = (UI_FONT, 9, "bold" if day == today else "normal")
                lbl = tk.Label(self.body, text=str(day.day), width=3, bg=bg, fg=fg,
                               font=font, cursor="hand2", pady=2)
                if day == today and not selected:
                    lbl.configure(fg=p["accent"])
                lbl.grid(row=r + 2, column=c, padx=1, pady=1)
                lbl.bind("<Button-1>", lambda e, d=day: self._pick(d))
                hover = p["button_hover"]
                if not selected:
                    lbl.bind("<Enter>", lambda e, l=lbl: l.configure(bg=hover))
                    lbl.bind("<Leave>", lambda e, l=lbl, b=bg: l.configure(bg=b))
        FlatButton(self.body, app, text="Hoy", kind="ghost", bg_key="button_bg",
                   command=lambda: self._pick(today)).grid(row=9, column=0, columnspan=7,
                                                         sticky="ew", pady=(4, 0))

    def _shift(self, delta):
        m = self.month - 1 + delta
        self.year += m // 12
        self.month = m % 12 + 1
        self._build()

    def _pick(self, day):
        self.close()
        self.callback(day)


def format_date(day):
    return day.strftime("%d/%m/%Y") if day else ""


def parse_date(text):
    text = (text or "").strip()
    if not text:
        return None
    for sep in ("/", "-", "."):
        text = text.replace(sep, "/")
    parts = text.split("/")
    try:
        if len(parts[0]) == 4:              # aaaa/mm/dd
            y, m, d = (int(x) for x in parts[:3])
        else:
            d, m = int(parts[0]), int(parts[1])
            y = int(parts[2]) if len(parts) > 2 and parts[2] else _dt.date.today().year
            if y < 100:
                y += 2000
        return _dt.date(y, m, d)
    except (ValueError, IndexError):
        return None


def parse_time(text):
    """'9' -> 09:00, '930' -> 09:30, '9:5' -> 09:05. Devuelve 'HH:MM' o ''."""
    text = (text or "").strip().replace(".", ":").replace("h", ":")
    if not text:
        return ""
    try:
        if ":" in text:
            h, m = text.split(":", 1)
            h, m = int(h or 0), int(m or 0)
        elif len(text) <= 2:
            h, m = int(text), 0
        else:
            h, m = int(text[:-2]), int(text[-2:])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    except ValueError:
        pass
    return None


TIME_CHOICES = tuple(f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45))


class DateField(tk.Frame):
    """Campo de fecha dd/mm/aaaa con calendario desplegable."""

    def __init__(self, parent, app, value=None, on_change=None, bg=None):
        p = app.palette()
        super().__init__(parent, bg=bg or p["app_bg"])
        self.app = app
        self.on_change = on_change
        self.var = tk.StringVar(value=format_date(value))
        self.entry = styled_entry(self, app, width=11, textvariable=self.var)
        self.entry.pack(side="left", ipady=3)
        self.button = FlatButton(self, app, icon="calendar", padx=4, pady=2,
                                 tooltip="Elegir en el calendario", command=self._open)
        self.button.pack(side="left", padx=(3, 0))
        self.entry.bind("<FocusOut>", self._normalize)
        self.entry.bind("<Return>", self._normalize)

    def _normalize(self, _e=None):
        day = parse_date(self.var.get())
        if day is not None:
            self.var.set(format_date(day))
            if self.on_change:
                self.on_change(day)

    def _open(self):
        DatePopup(self.app, self.entry, self.get(), self.set_and_notify).open()

    def set_and_notify(self, day):
        self.set(day)
        if self.on_change:
            self.on_change(day)

    def get(self):
        return parse_date(self.var.get())

    def set(self, day):
        self.var.set(format_date(day))

    def set_enabled(self, enabled):
        self.entry.configure(state="normal" if enabled else "disabled")
        self.button.set_enabled(enabled)


class TimeField(ttk.Combobox):
    def __init__(self, parent, value="", width=6):
        super().__init__(parent, values=TIME_CHOICES, width=width)
        self.set(value or "")
        self.bind("<FocusOut>", self._normalize)
        self.bind("<Return>", self._normalize)
        self.bind("<<ComboboxSelected>>", self._normalize)

    def _normalize(self, _e=None):
        value = parse_time(self.get())
        if value is not None:
            self.set(value)

    def value(self):
        result = parse_time(self.get())
        return result if result is not None else None


class ScrollFrame(tk.Frame):
    """Marco con desplazamiento vertical; el contenido va en self.body."""

    def __init__(self, parent, app, bg_key="app_bg", max_height=None):
        p = app.palette()
        super().__init__(parent, bg=p[bg_key])
        self.app = app
        self.bg_key = bg_key
        self.max_height = max_height
        self.canvas = tk.Canvas(self, bg=p[bg_key], highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.body = tk.Frame(self.canvas, bg=p[bg_key])
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.bind_all_wheel(self.canvas)
        self.bind_all_wheel(self.body)

    def bind_all_wheel(self, widget):
        widget.bind("<MouseWheel>", self._wheel, add="+")
        widget.bind("<Button-4>", lambda e: self._scroll(-2), add="+")
        widget.bind("<Button-5>", lambda e: self._scroll(2), add="+")

    def bind_children_wheel(self, widget=None):
        for child in (widget or self.body).winfo_children():
            self.bind_all_wheel(child)
            self.bind_children_wheel(child)

    def _wheel(self, event):
        self._scroll(int(-1 * (event.delta / 120)) * 2)

    def _scroll(self, units):
        top, bottom = self.canvas.yview()
        if top <= 0 and bottom >= 1:
            return
        self.canvas.yview_scroll(units, "units")

    def _on_body(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        h = self.body.winfo_reqheight()
        if self.max_height:
            self.canvas.configure(height=min(h, self.max_height))
        top, bottom = self.canvas.yview()
        needs = h > self.canvas.winfo_height() + 1
        if needs and not self.bar.winfo_ismapped():
            self.bar.pack(side="right", fill="y")
        elif not needs and self.bar.winfo_ismapped():
            self.bar.pack_forget()

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)
        self._on_body()

    def restyle(self):
        p = self.app.palette()
        self.configure(bg=p[self.bg_key])
        self.canvas.configure(bg=p[self.bg_key])
        self.body.configure(bg=p[self.bg_key])


def ask_open_filenames(app, parent=None, **kw):
    with _NativeAnchor(app, parent, 820, 520) as owner:
        return filedialog.askopenfilenames(parent=owner, **kw)
