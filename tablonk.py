"""
TablonK
===================
Herramienta de escritorio para Windows hecha con Tkinter (solo libreria
estandar: no hace falta instalar nada aparte de Python 3).

Funciones principales:
- Ventana sin bordes nativos, con botones propios de minimizar y cerrar.
- Notas tipo post-it organizadas en una cuadricula de celdas independientes:
  al redimensionar una nota se ajusta el ancho de su columna y el alto de
  su fila; el resto de la rejilla se reacomoda pero NO se reescala.
- Barra de estilo colapsable: color del post-it, modo claro/oscuro,
  tipo y tamano de letra, negrita, cursiva, subrayado y tachado.
- Todo se guarda automaticamente en config.json, en la misma carpeta
  que este script.

Ejecutar con:  python tablonk.py
(Requiere Python 3.7+; en Windows, tkinter ya viene incluido.)
"""

import tkinter as tk
from tkinter import ttk, colorchooser
from tkinter import font as tkfont
import json
import os
import sys
import uuid

# ----------------------------------------------------------------------
# Configuracion y constantes
# ----------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # Empaquetado con PyInstaller (u similar): usa la carpeta donde esta
    # el .exe, no la carpeta temporal donde se descomprime en cada arranque.
    SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

GAP = 12                  # separacion entre celdas de la cuadricula, en px
MIN_COL_W = 140
MIN_ROW_H = 110
DEFAULT_COL_W = 220
DEFAULT_ROW_H = 180
MAX_COLS = 4               # columnas visibles de la cuadricula (ajustable)
TITLEBAR_H = 34
TOOLBAR_H = 46
HEADER_H = 18               # cabecera (asa) de cada post-it
GRIP_SIZE = 14

NOTE_COLORS = [
    "#FFF59D",  # amarillo
    "#FFCC80",  # naranja
    "#F48FB1",  # rosa
    "#A5D6A7",  # verde
    "#90CAF9",  # azul
    "#CE93D8",  # morado
]

PALETTES = {
    "light": {
        "app_bg": "#eef0f2",
        "titlebar_bg": "#dfe3e7",
        "toolbar_bg": "#e9ebee",
        "board_bg": "#e4e7ea",
        "text": "#20242a",
        "muted_text": "#5b6470",
        "button_bg": "#ffffff",
        "button_hover": "#dbe4f4",
        "accent": "#3d7bd9",
        "border": "#c7ccd1",
        "close_hover": "#e81123",
    },
    "dark": {
        "app_bg": "#1c1e22",
        "titlebar_bg": "#25282d",
        "toolbar_bg": "#25282d",
        "board_bg": "#17191c",
        "text": "#e7e9ec",
        "muted_text": "#9aa3ad",
        "button_bg": "#33373d",
        "button_hover": "#3d434b",
        "accent": "#5b9bf5",
        "border": "#3a3f45",
        "close_hover": "#e81123",
    },
}

DEMO_TEXT = (
    "Hola, holita! ✨\n"
    "- Arrastra una nota desde su franja superior para moverla.\n"
    "- Tira de la esquina inferior derecha para cambiar su tamano.\n"
    "- Pulsa + Nota para crear notas nuevas.\n"
    "- Selecciona una nota y usa la barra de arriba para cambiar su "
    "color, letra, negrita, cursiva, subrayado o tachado."
)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def contrast_text_color(hex_color):
    """Devuelve negro o blanco segun el brillo del color de fondo."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#1a1a1a" if luminance > 0.55 else "#f5f5f5"


def darken(hex_color, factor):
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = _clamp(int(r * factor), 0, 255)
    g = _clamp(int(g * factor), 0, 255)
    b = _clamp(int(b * factor), 0, 255)
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def _default_config(with_demo):
    notes = []
    if with_demo:
        notes.append({
            "id": uuid.uuid4().hex[:8],
            "row": 0, "col": 0,
            "text": DEMO_TEXT,
            "color": NOTE_COLORS[0],
            "font_family": "Segoe UI",
            "font_size": 11,
            "bold": False, "italic": False, "underline": False, "strike": False,
        })
    return {
        "theme": "light",
        "toolbar_collapsed": False,
        "window": {"x": 120, "y": 100, "width": 900, "height": 640},
        "grid": {"col_widths": {}, "row_heights": {}},
        "notes": notes,
    }


def load_config():
    """Carga config.json si existe; si no, crea una configuracion por defecto."""
    if not os.path.exists(CONFIG_PATH):
        return _default_config(with_demo=True)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("config.json no contiene un objeto JSON valido")
        return data
    except (json.JSONDecodeError, ValueError, OSError):
        try:
            os.replace(CONFIG_PATH, CONFIG_PATH + ".bak")
        except OSError:
            pass
        return _default_config(with_demo=False)


# ----------------------------------------------------------------------
# Post-it individual
# ----------------------------------------------------------------------
class PostIt(tk.Frame):
    def __init__(self, master, app, note_id, row, col, text, color,
                 font_family, font_size, bold, italic, underline, strike):
        super().__init__(master, bg=color, highlightthickness=1,
                          highlightbackground=app.palette()["border"])
        self.app = app
        self.note_id = note_id
        self.row = row
        self.col = col
        self.color = color
        self.font_family = font_family
        self.font_size = font_size
        self.bold = bold
        self.italic = italic
        self.underline = underline
        self.strike = strike
        self.selected = False

        header_color = darken(color, 0.82)
        text_color = contrast_text_color(color)

        self.header = tk.Frame(self, height=HEADER_H, bg=header_color, cursor="fleur")
        self.header.pack(side="top", fill="x")
        self.header.pack_propagate(False)

        self.delete_btn = tk.Button(
            self.header, text="x", bd=0, relief="flat",
            bg=header_color, fg=text_color, activebackground=header_color,
            font=("Segoe UI", 9), cursor="arrow", command=self._on_delete,
        )
        self.delete_btn.pack(side="right", padx=2)

        self.font_obj = tkfont.Font(
            family=font_family, size=font_size,
            weight="bold" if bold else "normal",
            slant="italic" if italic else "roman",
            underline=1 if underline else 0,
            overstrike=1 if strike else 0,
        )

        self.text_widget = tk.Text(
            self, wrap="word", bd=0, padx=8, pady=6, undo=True,
            bg=color, fg=text_color, insertbackground=text_color,
            font=self.font_obj, relief="flat", highlightthickness=0,
        )
        self.text_widget.insert("1.0", text)
        self.text_widget.pack(side="top", fill="both", expand=True)

        self.grip = tk.Label(self, text="◢", bg=header_color, fg=text_color,
                              cursor="size_nw_se", font=("Segoe UI", 8))
        self.grip.place(relx=1.0, rely=1.0, anchor="se", width=GRIP_SIZE, height=GRIP_SIZE)
        self.grip.lift()

        self._bind_events()

    def _bind_events(self):
        self.header.bind("<ButtonPress-1>", self._on_drag_start)
        self.header.bind("<B1-Motion>", self._on_drag_motion)
        self.header.bind("<ButtonRelease-1>", self._on_drag_end)
        self.text_widget.bind("<FocusIn>", lambda e: self.app.set_active_note(self))
        self.text_widget.bind("<KeyRelease>", lambda e: self.app.schedule_save())
        self.text_widget.bind("<FocusOut>", lambda e: self.app.schedule_save())
        self.grip.bind("<ButtonPress-1>", self._on_resize_start)
        self.grip.bind("<B1-Motion>", self._on_resize_motion)
        self.grip.bind("<ButtonRelease-1>", self._on_resize_end)

    # ---- estilo ----
    def apply_font(self):
        self.font_obj.configure(
            family=self.font_family, size=self.font_size,
            weight="bold" if self.bold else "normal",
            slant="italic" if self.italic else "roman",
            underline=1 if self.underline else 0,
            overstrike=1 if self.strike else 0,
        )

    def set_color(self, hex_color):
        self.color = hex_color
        header_color = darken(hex_color, 0.82)
        text_color = contrast_text_color(hex_color)
        self.configure(bg=hex_color)
        self.header.configure(bg=header_color)
        self.delete_btn.configure(bg=header_color, fg=text_color, activebackground=header_color)
        self.text_widget.configure(bg=hex_color, fg=text_color, insertbackground=text_color)
        self.grip.configure(bg=header_color, fg=text_color)

    def set_selected(self, is_selected):
        self.selected = is_selected
        p = self.app.palette()
        if is_selected:
            self.configure(highlightthickness=2, highlightbackground=p["accent"])
        else:
            self.configure(highlightthickness=1, highlightbackground=p["border"])

    def refresh_theme(self):
        self.set_selected(self.selected)

    def to_dict(self):
        return {
            "id": self.note_id,
            "row": self.row,
            "col": self.col,
            "text": self.text_widget.get("1.0", "end-1c"),
            "color": self.color,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "bold": self.bold,
            "italic": self.italic,
            "underline": self.underline,
            "strike": self.strike,
        }

    # ---- arrastrar para mover ----
    def _on_drag_start(self, event):
        self.app.set_active_note(self)
        self._drag_root = (event.x_root, event.y_root)
        self._drag_origin = (self.winfo_x(), self.winfo_y())
        self.lift()

    def _on_drag_motion(self, event):
        dx = event.x_root - self._drag_root[0]
        dy = event.y_root - self._drag_root[1]
        self.place(x=self._drag_origin[0] + dx, y=self._drag_origin[1] + dy)

    def _on_drag_end(self, event):
        bx = self.winfo_x() + self.winfo_width() // 2
        by = self.winfo_y() + self.winfo_height() // 2
        target_row, target_col = self.app.nearest_cell(bx, by)
        self.app.move_note(self, target_row, target_col)
        self.app.schedule_save()

    # ---- arrastrar para redimensionar ----
    def _on_resize_start(self, event):
        self.app.set_active_note(self)
        self._resize_root = (event.x_root, event.y_root)
        self._resize_start_size = (
            self.app.col_widths.get(self.col, DEFAULT_COL_W),
            self.app.row_heights.get(self.row, DEFAULT_ROW_H),
        )

    def _on_resize_motion(self, event):
        dx = event.x_root - self._resize_root[0]
        dy = event.y_root - self._resize_root[1]
        new_w = max(MIN_COL_W, self._resize_start_size[0] + dx)
        new_h = max(MIN_ROW_H, self._resize_start_size[1] + dy)
        self.app.col_widths[self.col] = new_w
        self.app.row_heights[self.row] = new_h
        self.app.relayout()

    def _on_resize_end(self, event):
        self.app.schedule_save()

    def _on_delete(self):
        self.app.delete_note(self)


# ----------------------------------------------------------------------
# Aplicacion principal
# ----------------------------------------------------------------------
class StickyBoardApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.config_data = load_config()
        self.theme = self.config_data.get("theme", "light")
        self.toolbar_collapsed = self.config_data.get("toolbar_collapsed", False)

        grid_cfg = self.config_data.get("grid", {})
        self.col_widths = {int(k): v for k, v in grid_cfg.get("col_widths", {}).items()}
        self.row_heights = {int(k): v for k, v in grid_cfg.get("row_heights", {}).items()}

        self.grid_map = {}       # (row, col) -> PostIt
        self.active_note = None
        self._save_job = None

        self.default_font_family = self._pick_default_font()

        self.title("TablonK")
        self.overrideredirect(True)
        self._configure_ttk_style()

        win = self.config_data.get("window", {})
        w = win.get("width", 900)
        h = win.get("height", 640)
        x = win.get("x", 120)
        y = win.get("y", 100)
        x, y = self._clamp_to_screen(x, y, w, h)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(520, 380)
        self.configure(bg=self.palette()["app_bg"])

        self._build_titlebar()
        self._build_toolbar()
        self._build_board_area()
        self._build_window_grip()

        self._load_notes_from_config()
        self.apply_theme_to_all()
        self.relayout()

        if self.toolbar_collapsed:
            self.toolbar_frame.pack_forget()
            self.toggle_toolbar_btn.configure(text="▼")

        self.bind("<Map>", self._on_map)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- utilidades ----------------
    def palette(self):
        return PALETTES[self.theme]

    def _pick_default_font(self):
        try:
            families = set(tkfont.families())
        except tk.TclError:
            families = set()
        for candidate in ("Segoe UI", "Calibri", "Arial", "Helvetica"):
            if candidate in families:
                return candidate
        return "TkDefaultFont"

    def _clamp_to_screen(self, x, y, w, h):
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = _clamp(x, 0, max(0, sw - 100))
        y = _clamp(y, 0, max(0, sh - 100))
        return x, y

    def _configure_ttk_style(self):
        p = self.palette()
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TCombobox", fieldbackground=p["button_bg"],
                         background=p["button_bg"], foreground=p["text"])
        style.map("TCombobox", fieldbackground=[("readonly", p["button_bg"])],
                   foreground=[("readonly", p["text"])])
        style.configure("TSpinbox", fieldbackground=p["button_bg"],
                         background=p["button_bg"], foreground=p["text"])
        style.configure("Vertical.TScrollbar", background=p["toolbar_bg"],
                         troughcolor=p["app_bg"], arrowcolor=p["text"])
        style.configure("Horizontal.TScrollbar", background=p["toolbar_bg"],
                         troughcolor=p["app_bg"], arrowcolor=p["text"])

    # ---------------- construccion de la interfaz ----------------
    def _build_titlebar(self):
        p = self.palette()
        bar = tk.Frame(self, height=TITLEBAR_H, bg=p["titlebar_bg"])
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        self.titlebar_frame = bar

        self.title_lbl = tk.Label(bar, text="📌 TablonK", bg=p["titlebar_bg"],
                                   fg=p["text"], font=("Segoe UI", 10, "bold"), padx=10)
        self.title_lbl.pack(side="left")

        for w in (bar, self.title_lbl):
            w.bind("<ButtonPress-1>", self._start_move_window)
            w.bind("<B1-Motion>", self._do_move_window)
            w.bind("<ButtonRelease-1>", lambda e: self.schedule_save())

        self.close_btn = tk.Button(bar, text="×", bd=0, relief="flat", width=4,
                                    bg=p["titlebar_bg"], fg=p["text"],
                                    font=("Segoe UI", 11), cursor="arrow", command=self.on_close)
        self.close_btn.pack(side="right", fill="y")
        self.close_btn.bind("<Enter>", lambda e: self.close_btn.configure(
            bg=self.palette()["close_hover"], fg="white"))
        self.close_btn.bind("<Leave>", lambda e: self.close_btn.configure(
            bg=self.palette()["titlebar_bg"], fg=self.palette()["text"]))

        self.min_btn = tk.Button(bar, text="─", bd=0, relief="flat", width=4,
                                  bg=p["titlebar_bg"], fg=p["text"],
                                  font=("Segoe UI", 10), cursor="arrow", command=self.minimize)
        self.min_btn.pack(side="right", fill="y")
        self.min_btn.bind("<Enter>", lambda e: self.min_btn.configure(
            bg=self.palette()["button_hover"]))
        self.min_btn.bind("<Leave>", lambda e: self.min_btn.configure(
            bg=self.palette()["titlebar_bg"]))

        self.toggle_toolbar_btn = tk.Button(
            bar, text=("▼" if self.toolbar_collapsed else "▲"), bd=0, relief="flat", width=4,
            bg=p["titlebar_bg"], fg=p["text"], font=("Segoe UI", 9),
            cursor="arrow", command=self.toggle_toolbar)
        self.toggle_toolbar_btn.pack(side="right", fill="y")
        self.toggle_toolbar_btn.bind("<Enter>", lambda e: self.toggle_toolbar_btn.configure(
            bg=self.palette()["button_hover"]))
        self.toggle_toolbar_btn.bind("<Leave>", lambda e: self.toggle_toolbar_btn.configure(
            bg=self.palette()["titlebar_bg"]))

    def _build_toolbar(self):
        p = self.palette()
        bar = tk.Frame(self, height=TOOLBAR_H, bg=p["toolbar_bg"])
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        self.toolbar_frame = bar
        self.toolbar_theme_widgets = []
        self.toolbar_separators = []

        self.add_btn = tk.Button(bar, text="+ Nota", bd=0, relief="flat",
                                  bg=p["button_bg"], fg=p["text"], padx=8,
                                  font=("Segoe UI", 9, "bold"), cursor="hand2",
                                  command=lambda: self.add_note())
        self.add_btn.pack(side="left", padx=(8, 10), pady=8)

        sep1 = tk.Frame(bar, width=1, bg=p["border"])
        sep1.pack(side="left", fill="y", pady=8, padx=4)
        self.toolbar_separators.append(sep1)

        self.color_swatch_buttons = []
        for c in NOTE_COLORS:
            b = tk.Button(bar, bg=c, activebackground=c, width=2, bd=0,
                          relief="flat", cursor="hand2", state="disabled",
                          command=lambda c=c: self.set_active_color(c))
            b.pack(side="left", padx=2, pady=8)
            self.color_swatch_buttons.append(b)

        self.more_color_btn = tk.Button(bar, text="🎨", bd=0, relief="flat",
                                         bg=p["button_bg"], fg=p["text"], width=2,
                                         cursor="hand2", state="disabled",
                                         command=self.pick_custom_color)
        self.more_color_btn.pack(side="left", padx=(4, 10), pady=8)

        sep2 = tk.Frame(bar, width=1, bg=p["border"])
        sep2.pack(side="left", fill="y", pady=8, padx=4)
        self.toolbar_separators.append(sep2)

        lbl_font = tk.Label(bar, text="Letra:", bg=p["toolbar_bg"], fg=p["text"],
                             font=("Segoe UI", 9))
        lbl_font.pack(side="left", padx=(6, 2))
        self.toolbar_theme_widgets.append(lbl_font)

        try:
            families = sorted({f for f in tkfont.families() if not f.startswith("@")})
        except tk.TclError:
            families = [self.default_font_family]
        if not families:
            families = [self.default_font_family]

        self.font_family_var = tk.StringVar(value=self.default_font_family)
        self.font_family_cb = ttk.Combobox(bar, textvariable=self.font_family_var,
                                            values=families, width=16, state="disabled")
        self.font_family_cb.pack(side="left", padx=2, pady=8)
        self.font_family_cb.bind("<<ComboboxSelected>>", self._on_font_family_change)

        self.font_size_var = tk.StringVar(value="11")
        self.font_size_sp = ttk.Spinbox(bar, from_=6, to=72, width=3,
                                         textvariable=self.font_size_var, state="disabled",
                                         command=self._on_font_size_change)
        self.font_size_sp.pack(side="left", padx=(6, 10), pady=8)
        self.font_size_sp.bind("<Return>", self._on_font_size_change)
        self.font_size_sp.bind("<FocusOut>", self._on_font_size_change)

        b_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        i_font = tkfont.Font(family="Segoe UI", size=10, slant="italic")
        u_font = tkfont.Font(family="Segoe UI", size=10, underline=1)
        s_font = tkfont.Font(family="Segoe UI", size=10, overstrike=1)

        self.bold_var = tk.BooleanVar(value=False)
        self.italic_var = tk.BooleanVar(value=False)
        self.underline_var = tk.BooleanVar(value=False)
        self.strike_var = tk.BooleanVar(value=False)

        self.chk_bold = tk.Checkbutton(bar, text="B", font=b_font, variable=self.bold_var,
                                        command=self.toggle_bold, indicatoron=False, width=2,
                                        bd=0, bg=p["toolbar_bg"], fg=p["text"],
                                        activebackground=p["toolbar_bg"], selectcolor=p["button_hover"],
                                        state="disabled", cursor="hand2")
        self.chk_italic = tk.Checkbutton(bar, text="I", font=i_font, variable=self.italic_var,
                                          command=self.toggle_italic, indicatoron=False, width=2,
                                          bd=0, bg=p["toolbar_bg"], fg=p["text"],
                                          activebackground=p["toolbar_bg"], selectcolor=p["button_hover"],
                                          state="disabled", cursor="hand2")
        self.chk_underline = tk.Checkbutton(bar, text="U", font=u_font, variable=self.underline_var,
                                             command=self.toggle_underline, indicatoron=False, width=2,
                                             bd=0, bg=p["toolbar_bg"], fg=p["text"],
                                             activebackground=p["toolbar_bg"], selectcolor=p["button_hover"],
                                             state="disabled", cursor="hand2")
        self.chk_strike = tk.Checkbutton(bar, text="S", font=s_font, variable=self.strike_var,
                                          command=self.toggle_strike, indicatoron=False, width=2,
                                          bd=0, bg=p["toolbar_bg"], fg=p["text"],
                                          activebackground=p["toolbar_bg"], selectcolor=p["button_hover"],
                                          state="disabled", cursor="hand2")
        for chk in (self.chk_bold, self.chk_italic, self.chk_underline, self.chk_strike):
            chk.pack(side="left", padx=1, pady=8)

        self.theme_btn = tk.Button(bar, text=("🌙" if self.theme == "light" else "☀"),
                                    bd=0, relief="flat", bg=p["toolbar_bg"], fg=p["text"],
                                    font=("Segoe UI", 10), cursor="hand2", command=self.toggle_theme)
        self.theme_btn.pack(side="right", padx=10, pady=8)

    def _build_board_area(self):
        p = self.palette()
        container = tk.Frame(self, bg=p["app_bg"])
        container.pack(side="top", fill="both", expand=True)
        self.board_container = container

        self.canvas = tk.Canvas(container, bg=p["board_bg"], highlightthickness=0)
        vscroll = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        hscroll = ttk.Scrollbar(container, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.board_frame = tk.Frame(self.canvas, bg=p["board_bg"])
        self.canvas.create_window((0, 0), window=self.board_frame, anchor="nw")

        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))
        self.canvas.bind("<Button-3>", self._on_board_right_click)
        self.board_frame.bind("<Button-3>", self._on_board_right_click)

    def _build_window_grip(self):
        p = self.palette()
        grip = tk.Label(self, text="◢", bg=p["toolbar_bg"], fg=p["text"],
                         cursor="size_nw_se", font=("Segoe UI", 9))
        grip.place(relx=1.0, rely=1.0, anchor="se", width=16, height=16)
        grip.lift()
        grip.bind("<ButtonPress-1>", self._start_resize_window)
        grip.bind("<B1-Motion>", self._do_resize_window)
        grip.bind("<ButtonRelease-1>", lambda e: self.schedule_save())
        self.window_grip = grip

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_board_right_click(self, event):
        bx = event.x_root - self.board_frame.winfo_rootx()
        by = event.y_root - self.board_frame.winfo_rooty()
        row, col = self.nearest_cell(bx, by)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Nueva nota aqui", command=lambda: self.add_note(row, col))
        menu.tk_popup(event.x_root, event.y_root)

    # ---------------- ventana: mover / redimensionar / minimizar ----------------
    def _start_move_window(self, event):
        self._move_root = (event.x_root, event.y_root)
        self._move_origin = (self.winfo_x(), self.winfo_y())

    def _do_move_window(self, event):
        dx = event.x_root - self._move_root[0]
        dy = event.y_root - self._move_root[1]
        self.geometry(f"+{self._move_origin[0] + dx}+{self._move_origin[1] + dy}")

    def _start_resize_window(self, event):
        self._rw_root = (event.x_root, event.y_root)
        self._rw_start = (self.winfo_width(), self.winfo_height())

    def _do_resize_window(self, event):
        dx = event.x_root - self._rw_root[0]
        dy = event.y_root - self._rw_root[1]
        new_w = max(520, self._rw_start[0] + dx)
        new_h = max(380, self._rw_start[1] + dy)
        self.geometry(f"{new_w}x{new_h}")

    def minimize(self):
        self.overrideredirect(False)
        self.state("iconic")

    def _on_map(self, event):
        if self.state() == "normal":
            self.overrideredirect(True)

    def on_close(self):
        self.save_now()
        self.destroy()

    # ---------------- cuadricula ----------------
    def next_free_cell(self):
        row = 0
        while True:
            for col in range(MAX_COLS):
                if (row, col) not in self.grid_map:
                    return row, col
            row += 1

    def compute_offsets(self, extra_rows=0):
        col_x = [0]
        for c in range(MAX_COLS):
            col_x.append(col_x[-1] + self.col_widths.get(c, DEFAULT_COL_W) + GAP)
        max_row = max((r for (r, c) in self.grid_map.keys()), default=0)
        row_y = [0]
        for r in range(max_row + 1 + extra_rows):
            row_y.append(row_y[-1] + self.row_heights.get(r, DEFAULT_ROW_H) + GAP)
        return col_x, row_y, max_row

    def nearest_cell(self, bx, by):
        col_x, row_y, max_row = self.compute_offsets(extra_rows=1)
        best_col = min(range(MAX_COLS), key=lambda c: abs(bx - (col_x[c] + col_x[c + 1]) / 2))
        best_row = min(range(max_row + 2), key=lambda r: abs(by - (row_y[r] + row_y[r + 1]) / 2))
        return best_row, best_col

    def relayout(self):
        col_x, row_y, max_row = self.compute_offsets(extra_rows=0)
        for (row, col), note in self.grid_map.items():
            w = self.col_widths.get(col, DEFAULT_COL_W)
            h = self.row_heights.get(row, DEFAULT_ROW_H)
            note.place(x=col_x[col], y=row_y[row], width=w, height=h)
        total_w = col_x[-1]
        total_h = row_y[-1]
        self.board_frame.configure(width=total_w, height=total_h)
        self.canvas.configure(scrollregion=(0, 0, total_w, total_h))

    def move_note(self, note, target_row, target_col):
        old_key = (note.row, note.col)
        new_key = (target_row, target_col)
        if new_key == old_key:
            self.relayout()
            return
        occupant = self.grid_map.get(new_key)
        del self.grid_map[old_key]
        if occupant is not None:
            occupant.row, occupant.col = old_key
            self.grid_map[old_key] = occupant
        note.row, note.col = new_key
        self.grid_map[new_key] = note
        self.relayout()

    # ---------------- notas: crear / borrar / seleccionar ----------------
    def add_note(self, target_row=None, target_col=None):
        if target_row is None or target_col is None or (target_row, target_col) in self.grid_map:
            target_row, target_col = self.next_free_cell()
        color = NOTE_COLORS[len(self.grid_map) % len(NOTE_COLORS)]
        note = PostIt(self.board_frame, self, uuid.uuid4().hex[:8],
                      target_row, target_col, "", color,
                      self.default_font_family, 11, False, False, False, False)
        self.grid_map[(target_row, target_col)] = note
        self.relayout()
        self.set_active_note(note)
        note.text_widget.focus_set()
        self.schedule_save()

    def delete_note(self, note):
        key = (note.row, note.col)
        if self.grid_map.get(key) is note:
            del self.grid_map[key]
        if self.active_note is note:
            self.set_active_note(None)
        note.destroy()
        self.relayout()
        self.schedule_save()

    def set_active_note(self, note):
        if self.active_note is note:
            return
        if self.active_note is not None:
            self.active_note.set_selected(False)
        self.active_note = note
        if note is not None:
            note.set_selected(True)
        self._sync_toolbar_from_active()

    def _sync_toolbar_from_active(self):
        note = self.active_note
        enabled = note is not None
        cb_state = "readonly" if enabled else "disabled"
        sp_state = "normal" if enabled else "disabled"
        btn_state = "normal" if enabled else "disabled"
        self.font_family_cb.configure(state=cb_state)
        self.font_size_sp.configure(state=sp_state)
        for chk in (self.chk_bold, self.chk_italic, self.chk_underline, self.chk_strike):
            chk.configure(state=btn_state)
        for b in self.color_swatch_buttons:
            b.configure(state=btn_state)
        self.more_color_btn.configure(state=btn_state)
        if enabled:
            self.font_family_var.set(note.font_family)
            self.font_size_var.set(str(note.font_size))
            self.bold_var.set(note.bold)
            self.italic_var.set(note.italic)
            self.underline_var.set(note.underline)
            self.strike_var.set(note.strike)
        else:
            self.font_family_var.set("")
            self.font_size_var.set("")
            self.bold_var.set(False)
            self.italic_var.set(False)
            self.underline_var.set(False)
            self.strike_var.set(False)

    # ---------------- controles de estilo ----------------
    def _on_font_family_change(self, event=None):
        if not self.active_note:
            return
        self.active_note.font_family = self.font_family_var.get()
        self.active_note.apply_font()
        self.schedule_save()

    def _on_font_size_change(self, event=None):
        if not self.active_note:
            return
        try:
            size = int(self.font_size_var.get())
        except ValueError:
            return
        size = _clamp(size, 6, 72)
        self.font_size_var.set(str(size))
        self.active_note.font_size = size
        self.active_note.apply_font()
        self.schedule_save()

    def toggle_bold(self):
        if not self.active_note:
            return
        self.active_note.bold = self.bold_var.get()
        self.active_note.apply_font()
        self.schedule_save()

    def toggle_italic(self):
        if not self.active_note:
            return
        self.active_note.italic = self.italic_var.get()
        self.active_note.apply_font()
        self.schedule_save()

    def toggle_underline(self):
        if not self.active_note:
            return
        self.active_note.underline = self.underline_var.get()
        self.active_note.apply_font()
        self.schedule_save()

    def toggle_strike(self):
        if not self.active_note:
            return
        self.active_note.strike = self.strike_var.get()
        self.active_note.apply_font()
        self.schedule_save()

    def set_active_color(self, hex_color):
        if not self.active_note:
            return
        self.active_note.set_color(hex_color)
        self.schedule_save()

    def pick_custom_color(self):
        if not self.active_note:
            return
        result = colorchooser.askcolor(color=self.active_note.color,
                                        title="Elige un color de post-it")
        if result and result[1]:
            self.set_active_color(result[1])

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.theme_btn.configure(text=("🌙" if self.theme == "light" else "☀"))
        self.apply_theme_to_all()
        self.schedule_save()

    def toggle_toolbar(self):
        self.toolbar_collapsed = not self.toolbar_collapsed
        if self.toolbar_collapsed:
            self.toolbar_frame.pack_forget()
            self.toggle_toolbar_btn.configure(text="▼")
        else:
            self.toolbar_frame.pack(fill="x", after=self.titlebar_frame)
            self.toggle_toolbar_btn.configure(text="▲")
        self.schedule_save()

    def apply_theme_to_all(self):
        p = self.palette()
        self.configure(bg=p["app_bg"])
        self.titlebar_frame.configure(bg=p["titlebar_bg"])
        self.title_lbl.configure(bg=p["titlebar_bg"], fg=p["text"])
        self.close_btn.configure(bg=p["titlebar_bg"], fg=p["text"])
        self.min_btn.configure(bg=p["titlebar_bg"], fg=p["text"])
        self.toggle_toolbar_btn.configure(bg=p["titlebar_bg"], fg=p["text"])

        self.toolbar_frame.configure(bg=p["toolbar_bg"])
        for w in self.toolbar_theme_widgets:
            w.configure(bg=p["toolbar_bg"], fg=p["text"])
        for s in self.toolbar_separators:
            s.configure(bg=p["border"])
        self.theme_btn.configure(bg=p["toolbar_bg"], fg=p["text"])
        self.add_btn.configure(bg=p["button_bg"], fg=p["text"])
        self.more_color_btn.configure(bg=p["button_bg"], fg=p["text"])
        for chk in (self.chk_bold, self.chk_italic, self.chk_underline, self.chk_strike):
            chk.configure(bg=p["toolbar_bg"], fg=p["text"],
                          activebackground=p["toolbar_bg"], selectcolor=p["button_hover"])

        self.board_container.configure(bg=p["app_bg"])
        self.canvas.configure(bg=p["board_bg"])
        self.board_frame.configure(bg=p["board_bg"])
        self.window_grip.configure(bg=p["toolbar_bg"], fg=p["text"])

        self._configure_ttk_style()

        for note in self.grid_map.values():
            note.refresh_theme()

    # ---------------- carga y guardado ----------------
    def _load_notes_from_config(self):
        for nd in self.config_data.get("notes", []):
            row = nd.get("row", 0)
            col = nd.get("col", 0)
            if (row, col) in self.grid_map:
                row, col = self.next_free_cell()
            note = PostIt(
                self.board_frame, self,
                nd.get("id", uuid.uuid4().hex[:8]),
                row, col,
                nd.get("text", ""),
                nd.get("color", NOTE_COLORS[0]),
                nd.get("font_family", self.default_font_family),
                nd.get("font_size", 11),
                nd.get("bold", False),
                nd.get("italic", False),
                nd.get("underline", False),
                nd.get("strike", False),
            )
            self.grid_map[(row, col)] = note

    def schedule_save(self):
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(600, self.save_now)

    def gather_config(self):
        return {
            "theme": self.theme,
            "toolbar_collapsed": self.toolbar_collapsed,
            "window": {
                "x": self.winfo_x(), "y": self.winfo_y(),
                "width": self.winfo_width(), "height": self.winfo_height(),
            },
            "grid": {"col_widths": self.col_widths, "row_heights": self.row_heights},
            "notes": [note.to_dict() for note in self.grid_map.values()],
        }

    def save_now(self):
        self._save_job = None
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.gather_config(), f, ensure_ascii=False, indent=2)
        except OSError:
            pass


if __name__ == "__main__":
    app = StickyBoardApp()
    app.mainloop()
