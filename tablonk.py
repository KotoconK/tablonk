"""
TablonK Advance
===============
Herramienta de escritorio para Windows hecha con Tkinter y Pillow.

Secciones: Notas y tareas, Pizarra, Calendario (dia/semana/mes/año) y
Eventos (tabla personalizable con busqueda, filtros por tipo y fijados).
Los tipos de evento tienen color propio, que se usa como fondo del evento
en el calendario, la tabla y la ficha de edicion. La aplicacion se puede
actualizar desde Configuracion con las releases publicadas en GitHub.

Funciones principales:
- Ventana sin bordes nativos, con minimizar, maximizar/restaurar y cerrar,
  y con icono visible en la barra de tareas en todo momento.
- Notas tipo post-it organizadas en una cuadricula de celdas independientes:
  al redimensionar una nota se ajusta el ancho de su columna y el alto de
  su fila; el resto de la rejilla se reacomoda pero NO se reescala. Las
  filas pueden hacerse muy bajas (notas-titulo, cabeceras de columna, etc.).
- Notas de tipo Tarea: una frase con una casilla de estado que atenua su
  color cuando se marca como hecha.
- Barra de estilo colapsable: color del post-it, modo claro/oscuro,
  tipo y tamano de letra, negrita, cursiva, subrayado, tachado y listas
  de puntos.
- Desplegable "Proyecto" en la barra para cambiar entre distintos
  config.json guardados en otras carpetas, con historial para no tener
  que volver a indicar la ruta cada vez.
- Todo se guarda automaticamente en el config.json del proyecto activo.

Ejecutar con:  python tablonk.py
(Requiere Python 3.10+ y Pillow.)
"""

import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
import ctypes
import json
import os
import sys
import uuid
import tempfile

import ui_common as ui
import updater
from calendar_view import CalendarView
from events_store import EventStore
from events_view import EventsView
from icons import get_icon
from settings_view import SettingsDialog, check_in_background, load_settings, save_settings
from version import APP_ID, APP_NAME, APP_VERSION
from whiteboard import Whiteboard

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
PROJECTS_REGISTRY_PATH = os.path.join(SCRIPT_DIR, "tablonk_proyectos.json")

GAP = 12                  # separacion entre celdas de la cuadricula, en px
MIN_COL_W = 140
MIN_ROW_H = 36             # bajo aposta: permite notas-titulo muy finas
DEFAULT_COL_W = 220
DEFAULT_ROW_H = 180
MAX_COLS = 4               # columnas visibles de la cuadricula (ajustable)
TITLEBAR_H = 34
MIN_WIN_W = 760
MIN_WIN_H = 460
RESIZE_CURSOR = "size_nw_se" if sys.platform == "win32" else "bottom_right_corner"
TOOLBAR_H = 46
HEADER_H = 18               # cabecera (asa) de cada post-it
GRIP_SIZE = 14
TASK_DONE_MUTE = 0.5        # cuanto se funde el texto de una tarea hecha hacia el fondo (0-1)

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
        "danger": "#c0392b",
    },
    "dark": {
        # Tema oscuro suave / grafito: menos contraste para que el texto
        # no se perciba tan duro sobre fondos casi negros.
        "app_bg": "#25282d",
        "titlebar_bg": "#2e3238",
        "toolbar_bg": "#30353b",
        "board_bg": "#202328",
        "text": "#d6d9dd",
        "muted_text": "#949ca6",
        "button_bg": "#3a3f46",
        "button_hover": "#464c54",
        "accent": "#7aa2d6",
        "border": "#444a53",
        "close_hover": "#e05260",
        "danger": "#e0707b",
    },
}

DEMO_TEXT = (
    "Hola, holita!\n"
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


def blend_colors(hex_a, hex_b, amount):
    """Mezcla hex_a hacia hex_b. amount=0 -> hex_a; amount=1 -> hex_b."""
    a = hex_a.lstrip("#")
    b = hex_b.lstrip("#")
    ar, ag, ab = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
    br, bg2, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
    r = _clamp(int(ar + (br - ar) * amount), 0, 255)
    g = _clamp(int(ag + (bg2 - ag) * amount), 0, 255)
    bl = _clamp(int(ab + (bb - ab) * amount), 0, 255)
    return "#{:02x}{:02x}{:02x}".format(r, g, bl)


def _style_tag_name(b, i, u, s):
    return "style_{}{}{}{}".format(int(b), int(i), int(u), int(s))


def _default_config(with_demo):
    notes = []
    if with_demo:
        notes.append({
            "id": uuid.uuid4().hex[:8],
            "row": 0, "col": 0,
            "runs": [{"text": DEMO_TEXT, "b": False, "i": False, "u": False, "s": False}],
            "color": NOTE_COLORS[0],
            "font_family": "Segoe UI",
            "font_size": 11,
            "is_task": False,
        })
    return {
        "theme": "light",
        "toolbar_collapsed": False,
        "window": {"x": 120, "y": 100, "width": 900, "height": 640},
        "grid": {"col_widths": {}, "row_heights": {}},
        "notes": notes,
        "active_tab": "notes",
        "whiteboard": {"zoom": 1.0, "items": [], "connections": [], "strokes": []},
        "events": EventStore().to_dict(),
        "calendar": {"view": "month"},
    }


# ----------------------------------------------------------------------
# Post-it individual (nota normal o tarea)
# ----------------------------------------------------------------------
class PostIt(tk.Frame):
    def __init__(self, master, app, note_id, row, col, color,
                 font_family, font_size, is_task=False, items=None, runs=None):
        super().__init__(master, highlightthickness=1,
                          highlightbackground=app.palette()["border"])
        self.app = app
        self.note_id = note_id
        self.row = row
        self.col = col
        self.color = color
        self.font_family = font_family
        self.font_size = font_size
        self.is_task = is_task
        self.selected = False
        self.item_rows = []

        self.header = tk.Frame(self, height=HEADER_H, cursor="fleur")
        self.header.pack(side="top", fill="x")
        self.header.pack_propagate(False)

        self.delete_btn = tk.Button(
            self.header, text="", bd=0, relief="flat", highlightthickness=0,
            font=("Segoe UI", 9), cursor="hand2", command=self._on_delete,
        )
        self.delete_btn.pack(side="right", padx=2)

        if self.is_task:
            self.font_obj = None
            self.text_widget = None
            self.items_container = tk.Frame(self)
            self.items_container.pack(side="top", fill="both", expand=True)
            initial_items = items if items else [{"text": "", "done": False}]
            for it in initial_items:
                rd = self._build_item_row(it.get("text", ""), it.get("done", False))
                self.item_rows.append(rd)
            self._relayout_items()
            self.items_container.bind("<Button-3>", self._on_note_right_click)
        else:
            self.items_container = None
            self.text_widget = tk.Text(
                self, wrap="word", bd=0, padx=8, pady=6, undo=True,
                relief="flat", highlightthickness=0,
            )
            self._ensure_style_tags()
            self.font_obj = self._style_fonts[_style_tag_name(0, 0, 0, 0)]
            self.text_widget.configure(font=self.font_obj)
            self.text_widget.pack(side="top", fill="both", expand=True)
            self._load_runs(runs or [])
            self.text_widget.bind("<FocusIn>", lambda e: self.app.set_active_note(self))
            self.text_widget.bind("<KeyRelease>", lambda e: self.app.schedule_save())
            self.text_widget.bind("<FocusOut>", lambda e: self.app.schedule_save())
            self.text_widget.bind("<Button-3>", self._on_note_right_click)

        self.grip = tk.Label(self, text="", cursor=RESIZE_CURSOR, font=("Segoe UI", 8), bd=0)
        self.grip.place(relx=1.0, rely=1.0, anchor="se", width=GRIP_SIZE, height=GRIP_SIZE)
        self.grip.lift()

        self._refresh_visual()
        self._bind_events()

    def _bind_events(self):
        self.header.bind("<ButtonPress-1>", self._on_drag_start)
        self.header.bind("<B1-Motion>", self._on_drag_motion)
        self.header.bind("<ButtonRelease-1>", self._on_drag_end)
        self.header.bind("<Button-3>", self._on_note_right_click)
        self.grip.bind("<ButtonPress-1>", self._on_resize_start)
        self.grip.bind("<B1-Motion>", self._on_resize_motion)
        self.grip.bind("<ButtonRelease-1>", self._on_resize_end)

    def _on_note_right_click(self, event):
        self.app.set_active_note(self)
        n = len(self.app.grid_map.get((self.row, self.col), [self]))
        menu = tk.Menu(self.app, tearoff=0)
        menu.add_command(label="Eliminar nota", command=self._on_delete)
        menu.add_separator()
        if n < 2:
            menu.add_command(label="Dividir en 2", command=lambda: self.app.split_cell(self.row, self.col, 2))
        if n < 3:
            menu.add_command(label="Dividir en 3", command=lambda: self.app.split_cell(self.row, self.col, 3))
        menu.tk_popup(event.x_root, event.y_root)

    # ---- checklist: filas de tarea ----
    def _build_item_row(self, text, done):
        row_frame = tk.Frame(self.items_container)
        var = tk.BooleanVar(value=done)
        item_font = tkfont.Font(family=self.font_family, size=self.font_size,
                                 overstrike=1 if done else 0)
        chk = tk.Checkbutton(row_frame, variable=var, bd=0,
                              command=lambda: self._on_item_toggle(row_frame))
        chk.pack(side="left")
        entry = tk.Entry(row_frame, bd=0, relief="flat", font=item_font,
                          highlightthickness=0)
        entry.insert(0, text)
        entry.pack(side="left", fill="x", expand=True, padx=(2, 4))

        row_data = {"frame": row_frame, "var": var, "entry": entry,
                    "font": item_font, "chk": chk}

        entry.bind("<Return>", lambda e, rf=row_frame: self._on_item_return(rf))
        entry.bind("<BackSpace>", lambda e, rf=row_frame: self._on_item_backspace(e, rf))
        entry.bind("<KeyRelease>", lambda e: self.app.schedule_save())
        entry.bind("<FocusOut>", lambda e: self.app.schedule_save())
        entry.bind("<FocusIn>", lambda e: self.app.set_active_note(self))

        return row_data

    def _relayout_items(self):
        for rd in self.item_rows:
            rd["frame"].pack_forget()
        for rd in self.item_rows:
            rd["frame"].pack(side="top", fill="x", pady=1, padx=4)

    def _find_row_index(self, row_frame):
        for i, rd in enumerate(self.item_rows):
            if rd["frame"] is row_frame:
                return i
        return -1

    def _on_item_return(self, row_frame):
        idx = self._find_row_index(row_frame)
        if idx == -1:
            return "break"
        rd = self._build_item_row("", False)
        self.item_rows.insert(idx + 1, rd)
        self._relayout_items()
        self._apply_item_visual(rd)
        rd["entry"].focus_set()
        self.app.schedule_save()
        return "break"

    def _on_item_backspace(self, event, row_frame):
        idx = self._find_row_index(row_frame)
        if idx == -1:
            return
        entry = self.item_rows[idx]["entry"]
        if entry.get() == "" and len(self.item_rows) > 1:
            self._remove_item_at(idx)
            return "break"

    def _remove_item_at(self, idx):
        rd = self.item_rows.pop(idx)
        rd["frame"].destroy()
        self._relayout_items()
        focus_idx = max(0, idx - 1)
        if self.item_rows:
            entry = self.item_rows[focus_idx]["entry"]
            entry.focus_set()
            entry.icursor("end")
        self.app.schedule_save()

    def _on_item_toggle(self, row_frame):
        idx = self._find_row_index(row_frame)
        if idx == -1:
            return
        self._apply_item_visual(self.item_rows[idx])
        self.app.schedule_save()

    def _apply_item_visual(self, row_data):
        done = row_data["var"].get()
        row_data["font"].configure(overstrike=1 if done else 0)
        base_text_color = contrast_text_color(self.color)
        if done:
            text_color = blend_colors(base_text_color, self.color, TASK_DONE_MUTE)
        else:
            text_color = base_text_color
        row_data["entry"].configure(fg=text_color, bg=self.color, insertbackground=text_color)
        row_data["frame"].configure(bg=self.color)
        row_data["chk"].configure(bg=self.color, activebackground=self.color)

    # ---- estilo / color ----
    def _ensure_style_tags(self):
        self._style_fonts = {}
        for b in (0, 1):
            for i in (0, 1):
                for u in (0, 1):
                    for s in (0, 1):
                        name = _style_tag_name(b, i, u, s)
                        f = tkfont.Font(
                            family=self.font_family, size=self.font_size,
                            weight="bold" if b else "normal",
                            slant="italic" if i else "roman",
                            underline=1 if u else 0,
                            overstrike=1 if s else 0,
                        )
                        self._style_fonts[name] = f
                        self.text_widget.tag_configure(name, font=f)

    def _char_style(self, idx):
        for t in self.text_widget.tag_names(idx):
            if t.startswith("style_") and len(t) == 10:
                bits = t[6:]
                return {"b": bits[0] == "1", "i": bits[1] == "1",
                        "u": bits[2] == "1", "s": bits[3] == "1"}
        return {"b": False, "i": False, "u": False, "s": False}

    def _set_char_style(self, start, end, state):
        for name in self._style_fonts.keys():
            self.text_widget.tag_remove(name, start, end)
        name = _style_tag_name(state["b"], state["i"], state["u"], state["s"])
        self.text_widget.tag_add(name, start, end)

    def toggle_style(self, attr):
        """attr es 'b','i','u' o 's'. Alterna ese atributo en el texto seleccionado."""
        text = self.text_widget
        try:
            start = text.index("sel.first")
            end = text.index("sel.last")
        except tk.TclError:
            return False

        all_have = True
        idx = start
        while text.compare(idx, "<", end):
            if not self._char_style(idx)[attr]:
                all_have = False
                break
            idx = text.index(f"{idx}+1c")

        new_value = not all_have
        idx = start
        while text.compare(idx, "<", end):
            next_idx = text.index(f"{idx}+1c")
            state = self._char_style(idx)
            state[attr] = new_value
            self._set_char_style(idx, next_idx, state)
            idx = next_idx
        return True

    def _extract_runs(self):
        text = self.text_widget
        end = text.index("end-1c")
        if text.compare("1.0", "==", end):
            return []
        runs = []
        run_start = "1.0"
        run_state = self._char_style("1.0")
        idx = "1.0"
        while text.compare(idx, "<", end):
            state = self._char_style(idx)
            if state != run_state:
                runs.append({"text": text.get(run_start, idx), **run_state})
                run_start = idx
                run_state = state
            idx = text.index(f"{idx}+1c")
        runs.append({"text": text.get(run_start, end), **run_state})
        return runs

    def _load_runs(self, runs):
        text = self.text_widget
        text.delete("1.0", "end")
        for run in runs:
            start_idx = text.index("end-1c")
            text.insert("end", run.get("text", ""))
            end_idx = text.index("end-1c")
            state = {"b": run.get("b", False), "i": run.get("i", False),
                     "u": run.get("u", False), "s": run.get("s", False)}
            if any(state.values()):
                name = _style_tag_name(state["b"], state["i"], state["u"], state["s"])
                text.tag_add(name, start_idx, end_idx)

    def apply_font(self):
        if self.is_task:
            for rd in self.item_rows:
                rd["font"].configure(family=self.font_family, size=self.font_size)
        else:
            for f in self._style_fonts.values():
                f.configure(family=self.font_family, size=self.font_size)

    def _refresh_visual(self):
        header_color = darken(self.color, 0.82)
        header_text_color = contrast_text_color(self.color)
        self.configure(bg=self.color)
        self.header.configure(bg=header_color)
        close_img = get_icon(self, "close", header_text_color, 12, 2.2)
        grip_img = get_icon(self, "grip", header_text_color, 12, 2.0)
        self.delete_btn.configure(bg=header_color, fg=header_text_color,
                                  activebackground=darken(header_color, 0.9),
                                  image=close_img or "", text="" if close_img else "x")
        self.grip.configure(bg=header_color, fg=header_text_color,
                            image=grip_img or "", text="" if grip_img else "+")
        if self.is_task:
            self.items_container.configure(bg=self.color)
            for rd in self.item_rows:
                self._apply_item_visual(rd)
        else:
            text_color = contrast_text_color(self.color)
            self.text_widget.configure(bg=self.color, fg=text_color, insertbackground=text_color)

    def set_color(self, hex_color):
        self.color = hex_color
        self._refresh_visual()

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
        base = {
            "id": self.note_id,
            "row": self.row,
            "col": self.col,
            "color": self.color,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "is_task": self.is_task,
        }
        if self.is_task:
            base["items"] = [
                {"text": rd["entry"].get(), "done": rd["var"].get()}
                for rd in self.item_rows
            ]
        else:
            base["runs"] = self._extract_runs()
        return base

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
        self.app.confirm_delete_note(self)


# ----------------------------------------------------------------------
# Aplicacion principal
# ----------------------------------------------------------------------
class StickyBoardApp(tk.Tk):
    MASTER_LABEL = "Principal"
    ADD_PROJECT_LABEL = "Añadir proyecto..."
    TABS = (("notes", "Notas y tareas", "notes"), ("pizarra", "Pizarra", "whiteboard"),
            ("calendario", "Calendario", "calendar"), ("eventos", "Eventos", "events"))

    def __init__(self):
        super().__init__()
        updater.cleanup_previous()
        self.settings = load_settings(SCRIPT_DIR)
        self.latest_release = None
        self.master_config_path = CONFIG_PATH
        self._load_projects_registry()
        self.active_config_path = self._resolve_startup_project_path()
        initial_data = self._load_board(self.active_config_path)

        self.theme = initial_data.get("theme", "light")
        self.toolbar_collapsed = initial_data.get("toolbar_collapsed", False)
        self.active_tab = "notes"

        grid_cfg = initial_data.get("grid", {})
        self.col_widths = {int(k): v for k, v in grid_cfg.get("col_widths", {}).items()}
        self.row_heights = {int(k): v for k, v in grid_cfg.get("row_heights", {}).items()}

        self.grid_map = {}       # (row, col) -> PostIt
        self.active_note = None
        self._save_job = None
        self._applying_taskbar_fix = False
        self._minimized = False
        self._maximized = False
        self._restore_geometry = None

        self.default_font_family = self._pick_default_font()

        self.title(APP_NAME)
        self._set_app_icon()
        self.overrideredirect(True)
        self._configure_ttk_style()

        win = initial_data.get("window", {})
        w = win.get("width", 900)
        h = win.get("height", 640)
        x = win.get("x", 120)
        y = win.get("y", 100)
        x, y = self._clamp_to_screen(x, y, w, h)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self._restore_geometry = (x, y, w, h)
        self.minsize(MIN_WIN_W, MIN_WIN_H)
        self.configure(bg=self.palette()["app_bg"])

        self.event_store = EventStore()
        self.event_store.subscribe(self.schedule_save)
        self._build_titlebar()
        self._build_tabs()
        self.notes_page = tk.Frame(self, bg=self.palette()["app_bg"])
        self._build_toolbar()
        self._build_board_area()
        self.whiteboard = Whiteboard(self, self)
        self.calendar_view = CalendarView(self, self, self.event_store)
        self.events_view = EventsView(self, self, self.event_store)
        self._build_window_grip()

        self._rebuild_board_from(initial_data)
        self.show_tab(initial_data.get("active_tab", "notes"), save=False)

        self.bind("<Control-s>", lambda e: (self.save_now(), "break")[1])
        self.bind("<Control-n>", self._shortcut_new_event)
        self.bind("<Control-f>", self._shortcut_find)
        if self.settings.get("check_on_start", True):
            self.after(4000, self._startup_update_check)
        self.bind("<Map>", self._on_map)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(150, self._force_taskbar_icon)
        if win.get("maximized", False):
            self.after(200, self.toggle_maximize)

    # ---------------- utilidades ----------------
    def _set_app_icon(self):
        """Show tablonk.ico in Explorer, taskbar, and our custom titlebar."""
        base = getattr(sys, "_MEIPASS", SCRIPT_DIR)
        ico = os.path.join(base, "tablonk.ico")
        self._icon_path = ico if os.path.isfile(ico) else None
        self._titlebar_icon_image = None
        if sys.platform == "win32":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
            except (AttributeError, OSError):
                pass
        if not os.path.isfile(ico):
            return
        try:
            if sys.platform == "win32":
                self.iconbitmap(default=ico)
        except tk.TclError:
            pass
        try:
            from PIL import Image, ImageTk
            with Image.open(ico) as icon:
                picture = icon.convert("RGBA").resize((24, 24), Image.Resampling.LANCZOS)
                preview = picture.resize((16, 16), Image.Resampling.LANCZOS)
            self._titlebar_icon_image = ImageTk.PhotoImage(preview, master=self)
            self._taskbar_icon_image = ImageTk.PhotoImage(picture, master=self)
            self.iconphoto(True, self._taskbar_icon_image)
        except (ImportError, OSError, tk.TclError):
            pass

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
        style.configure("TProgressbar", background=p["accent"], troughcolor=p["app_bg"])

    # ---------------- construccion de la interfaz ----------------
    def _build_titlebar(self):
        p = self.palette()
        bar = tk.Frame(self, height=TITLEBAR_H, bg=p["titlebar_bg"])
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        self.titlebar_frame = bar

        self.title_icon_label = None
        if self._titlebar_icon_image is not None:
            self.title_icon_label = tk.Label(bar, image=self._titlebar_icon_image,
                                              bg=p["titlebar_bg"], padx=0)
            self.title_icon_label.pack(side="left", padx=(9, 4))
        self.title_lbl = tk.Label(bar, text=APP_NAME, bg=p["titlebar_bg"],
                                   fg=p["text"], font=("Segoe UI", 10, "bold"), padx=4)
        self.title_lbl.pack(side="left")

        for w in (bar, self.title_lbl, self.title_icon_label):
            if w is None:
                continue
            w.bind("<ButtonPress-1>", self._start_move_window)
            w.bind("<B1-Motion>", self._do_move_window)
            w.bind("<ButtonRelease-1>", lambda e: self.schedule_save())
            w.bind("<Double-Button-1>", lambda e: self.toggle_maximize())

        # Orden de Windows (de derecha a izquierda): cerrar, maximizar, minimizar.
        self.titlebar_buttons = []
        self.close_btn = self._titlebar_button(bar, "close", self.on_close, danger=True,
                                               tooltip="Cerrar")
        self.max_btn = self._titlebar_button(bar, "maximize", self.toggle_maximize,
                                             tooltip="Maximizar")
        self.min_btn = self._titlebar_button(bar, "minimize", self.minimize,
                                             tooltip="Minimizar")
        self.toggle_toolbar_btn = self._titlebar_button(
            bar, "chevron_down" if self.toolbar_collapsed else "chevron_up",
            self.toggle_toolbar, tooltip="Mostrar u ocultar la barra de herramientas")

    def _titlebar_button(self, bar, icon, command, danger=False, tooltip=None):
        btn = tk.Button(bar, bd=0, relief="flat", width=46, cursor="arrow",
                        highlightthickness=0, command=command)
        btn.pack(side="right", fill="y")
        btn._icon = icon
        btn._danger = danger
        btn._hover = False

        def enter(_e, b=btn):
            b._hover = True
            self._paint_titlebar_button(b)

        def leave(_e, b=btn):
            b._hover = False
            self._paint_titlebar_button(b)
        btn.bind("<Enter>", enter)
        btn.bind("<Leave>", leave)
        if tooltip:
            ui.HoverTip(btn, tooltip)
        self.titlebar_buttons.append(btn)
        self._paint_titlebar_button(btn)
        return btn

    def _paint_titlebar_button(self, btn, icon=None):
        p = self.palette()
        if icon is not None:
            btn._icon = icon
        if btn._hover:
            bg = p["close_hover"] if btn._danger else p["button_hover"]
            fg = "#FFFFFF" if btn._danger else p["text"]
        else:
            bg, fg = p["titlebar_bg"], p["text"]
        img = get_icon(self, btn._icon, fg, 16, 1.5)
        fallback = {"close": "X", "maximize": "[ ]", "restore": "[]", "minimize": "_",
                    "chevron_up": "^", "chevron_down": "v"}.get(btn._icon, "")
        btn.configure(bg=bg, activebackground=bg, fg=fg, activeforeground=fg,
                      image=img or "", text="" if img else fallback)

    def _build_tabs(self):
        """Pestañas de trabajo y selector UNICO de proyecto, siempre visible."""
        p = self.palette()
        strip = tk.Frame(self, height=42, bg=p["toolbar_bg"])
        strip.pack(side="top", fill="x")
        strip.pack_propagate(False)
        self.tabs_frame = strip
        self.tab_buttons = {}
        for i, (key, label, icon) in enumerate(self.TABS):
            btn = tk.Button(strip, text=" " + label, relief="flat", bd=0, padx=11, pady=2,
                            font=("Segoe UI", 10, "bold"), cursor="hand2", compound="left",
                            highlightthickness=0, command=lambda k=key: self.show_tab(k))
            btn.pack(side="left", padx=((10 if i == 0 else 2), 2), pady=6)
            btn._icon = icon
            self.tab_buttons[key] = btn
        self.notes_tab_btn = self.tab_buttons["notes"]
        self.whiteboard_tab_btn = self.tab_buttons["pizarra"]

        self.settings_btn = ui.FlatButton(strip, self, icon="settings", kind="ghost",
                                          padx=5, pady=3, tooltip="Configuración y actualizaciones",
                                          command=self.open_settings)
        self.settings_btn.pack(side="right", padx=(2, 8), pady=6)
        self.theme_btn = ui.FlatButton(strip, self, icon=("moon" if self.theme == "light" else "sun"),
                                       kind="ghost", padx=5, pady=3,
                                       tooltip="Cambiar entre tema claro y oscuro",
                                       command=self.toggle_theme)
        self.theme_btn.pack(side="right", padx=2, pady=6)
        self.update_badge = ui.FlatButton(strip, self, text="", icon="download", kind="accent",
                                          padx=8, pady=2, font=("Segoe UI", 8, "bold"),
                                          command=lambda: self.open_settings(auto_check=True))
        self.delete_project_btn = ui.FlatButton(
            strip, self, icon="trash", kind="ghost", padx=5, pady=3,
            tooltip="Quitar el proyecto de la lista", command=self._delete_current_project)
        self.delete_project_btn.pack(side="right", padx=(1, 6), pady=6)
        self.project_var = tk.StringVar(value="")
        self.project_cb = ttk.Combobox(strip, textvariable=self.project_var,
                                        width=17, state="readonly")
        self.project_cb.pack(side="right", padx=(0, 5), pady=6)
        self.project_cb.bind("<<ComboboxSelected>>", self._on_project_selected)
        self.project_lbl = tk.Label(strip, text="Proyecto", bg=p["toolbar_bg"],
                                     fg=p["muted_text"], font=("Segoe UI", 9))
        self.project_lbl.pack(side="right", padx=(5, 5))
        self._refresh_project_dropdown()
        self._style_tabs()

    def _style_tabs(self):
        p = self.palette()
        for tab, btn in self.tab_buttons.items():
            active = self.active_tab == tab
            fg = "#FFFFFF" if active else p["text"]
            img = get_icon(self, btn._icon, fg, 16)
            btn.configure(bg=p["accent"] if active else p["button_bg"], fg=fg,
                          activebackground=p["accent"] if active else p["button_hover"],
                          activeforeground=fg, image=img or "")

    def show_tab(self, tab, save=True):
        keys = [k for k, _, _ in self.TABS]
        if tab not in keys:
            tab = "notes"
        if tab != self.active_tab and hasattr(self, "whiteboard"):
            self.whiteboard._finish_edit()
        pages = {"notes": self.notes_page, "pizarra": self.whiteboard,
                 "calendario": self.calendar_view, "eventos": self.events_view}
        for page in pages.values():
            page.pack_forget()
        self.active_tab = tab
        pages[tab].pack(side="top", fill="both", expand=True)
        if tab == "calendario":
            self.after_idle(self.calendar_view.on_show)
        elif tab == "eventos":
            self.after_idle(self.events_view.on_show)
        self._style_tabs()
        if hasattr(self, "window_grip"):
            self.window_grip.lift()
        if save:
            self.schedule_save()

    # ---------------- calendario y eventos ----------------
    def _shortcut_new_event(self, event=None):
        if self.active_tab == "calendario":
            self.calendar_view.new_event()
            return "break"
        if self.active_tab == "eventos":
            self.events_view.new_event()
            return "break"
        return None

    def _shortcut_find(self, event=None):
        if self.active_tab == "eventos":
            self.events_view.search_entry.focus_set()
            self.events_view.search_entry.select_range(0, "end")
            return "break"
        return None

    def show_event_in_calendar(self, event_id):
        self.show_tab("calendario")
        self.after(30, lambda: self.calendar_view.show_event(event_id))

    def show_event_in_table(self, event_id):
        self.show_tab("eventos")
        self.after(60, lambda: self.events_view.reveal(event_id))

    # ---------------- configuracion y actualizaciones ----------------
    def open_settings(self, auto_check=False):
        SettingsDialog(self, auto_check=auto_check).show(width=520)

    def update_settings(self, data):
        self.settings.update(data)
        save_settings(SCRIPT_DIR, self.settings)

    def _startup_update_check(self):
        try:
            check_in_background(self, dict(self.settings), self.on_release_info)
        except Exception:
            pass

    def on_release_info(self, release):
        self.latest_release = release
        if release and release.get("newer"):
            self.update_badge.configure(text=" " + release["tag"])
            self.update_badge.set_tooltip(f"Nueva versión disponible: {release['name']}. "
                                          "Pulsa para instalarla.")
            if not self.update_badge.winfo_ismapped():
                self.update_badge.pack(side="right", padx=(2, 4), pady=8,
                                       before=self.theme_btn)
        elif self.update_badge.winfo_ismapped():
            self.update_badge.pack_forget()

    def _build_toolbar(self):
        p = self.palette()
        bar = tk.Frame(self.notes_page, height=TOOLBAR_H, bg=p["toolbar_bg"])
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        self.toolbar_frame = bar
        self.toolbar_theme_widgets = []
        self.toolbar_separators = []

        self.add_btn = tk.Button(bar, text=" Nota", bd=0, relief="flat", compound="left",
                                  bg=p["button_bg"], fg=p["text"], padx=8,
                                  font=("Segoe UI", 9, "bold"), cursor="hand2",
                                  command=lambda: self.add_note())
        self.add_btn.pack(side="left", padx=(8, 4), pady=8)

        self.add_task_btn = tk.Button(bar, text=" Tarea", bd=0, relief="flat", compound="left",
                                       bg=p["button_bg"], fg=p["text"], padx=8,
                                       font=("Segoe UI", 9, "bold"), cursor="hand2",
                                       command=lambda: self.add_note(is_task=True))
        self.add_task_btn.pack(side="left", padx=(0, 10), pady=8)

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

        self.more_color_btn = tk.Button(bar, text="", bd=0, relief="flat",
                                         bg=p["button_bg"], fg=p["text"], padx=4,
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

        self.chk_bold = tk.Button(bar, text="B", font=b_font, command=self.toggle_bold,
                                   bd=0, relief="flat", width=2, bg=p["toolbar_bg"], fg=p["text"],
                                   activebackground=p["toolbar_bg"], state="disabled", cursor="hand2")
        self.chk_italic = tk.Button(bar, text="I", font=i_font, command=self.toggle_italic,
                                     bd=0, relief="flat", width=2, bg=p["toolbar_bg"], fg=p["text"],
                                     activebackground=p["toolbar_bg"], state="disabled", cursor="hand2")
        self.chk_underline = tk.Button(bar, text="U", font=u_font, command=self.toggle_underline,
                                        bd=0, relief="flat", width=2, bg=p["toolbar_bg"], fg=p["text"],
                                        activebackground=p["toolbar_bg"], state="disabled", cursor="hand2")
        self.chk_strike = tk.Button(bar, text="S", font=s_font, command=self.toggle_strike,
                                     bd=0, relief="flat", width=2, bg=p["toolbar_bg"], fg=p["text"],
                                     activebackground=p["toolbar_bg"], state="disabled", cursor="hand2")
        for chk in (self.chk_bold, self.chk_italic, self.chk_underline, self.chk_strike):
            chk.pack(side="left", padx=1, pady=8)

        self.bullet_btn = tk.Button(bar, text="", font=("Segoe UI", 12), bd=0, relief="flat",
                                     bg=p["toolbar_bg"], fg=p["text"], padx=4,
                                     cursor="hand2", state="disabled", command=self.toggle_bullets)
        self.bullet_btn.pack(side="left", padx=(6, 2), pady=8)

    def _build_board_area(self):
        p = self.palette()
        container = tk.Frame(self.notes_page, bg=p["app_bg"])
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
        self.canvas.bind("<Button-1>", self._on_board_click)
        self.board_frame.bind("<Button-1>", self._on_board_click)

    def _build_window_grip(self):
        p = self.palette()
        grip = tk.Label(self, text="", bg=p["toolbar_bg"], fg=p["text"], bd=0,
                         cursor=RESIZE_CURSOR, font=("Segoe UI", 9),
                         image=get_icon(self, "grip", p["muted_text"], 14, 2.0) or "")
        grip.place(relx=1.0, rely=1.0, anchor="se", width=16, height=16)
        grip.lift()
        grip.bind("<ButtonPress-1>", self._start_resize_window)
        grip.bind("<B1-Motion>", self._do_resize_window)
        grip.bind("<ButtonRelease-1>", lambda e: self.schedule_save())
        self.window_grip = grip

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_board_click(self, event):
        # Pinchar fuera de cualquier nota quita el foco de edicion (el
        # cursor deja de parpadear) y deselecciona la nota activa.
        self.focus_set()
        self.set_active_note(None)

    def _on_board_right_click(self, event):
        bx = event.x_root - self.board_frame.winfo_rootx()
        by = event.y_root - self.board_frame.winfo_rooty()
        row, col = self.nearest_cell(bx, by)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Nueva nota aqui", command=lambda: self.add_note(row, col))
        menu.add_command(label="Nueva tarea aqui",
                          command=lambda: self.add_note(row, col, is_task=True))
        menu.tk_popup(event.x_root, event.y_root)

    # ---------------- ventana: mover / redimensionar / maximizar ---------
    def _screen_work_area(self):
        """Working rectangle of the monitor hosting the window (excludes taskbar)."""
        if sys.platform == "win32":
            try:
                class RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
                class MONITORINFO(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                                ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                user32 = ctypes.windll.user32
                user32.GetParent.argtypes = (ctypes.c_void_p,)
                user32.GetParent.restype = ctypes.c_void_p
                user32.MonitorFromWindow.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
                user32.MonitorFromWindow.restype = ctypes.c_void_p
                user32.GetMonitorInfoW.argtypes = (ctypes.c_void_p, ctypes.POINTER(MONITORINFO))
                hwnd = user32.GetParent(self.winfo_id()) or self.winfo_id()
                monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
                if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    r = info.rcWork
                    if r.right > r.left and r.bottom > r.top:
                        return r.left, r.top, r.right-r.left, r.bottom-r.top
            except (AttributeError, OSError, ValueError):
                pass
        return 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()

    def toggle_maximize(self):
        """Custom maximization for overrideredirect windows; works with Minimize."""
        if self._maximized:
            x, y, width, height = self._restore_geometry
            self.geometry(f"{width}x{height}+{x}+{y}")
            self._maximized = False
            self._paint_titlebar_button(self.max_btn, "maximize")
            self.window_grip.place(relx=1.0, rely=1.0, anchor="se", width=16, height=16)
            self.window_grip.lift()
        else:
            self._restore_geometry = (self.winfo_x(), self.winfo_y(),
                                      self.winfo_width(), self.winfo_height())
            x, y, width, height = self._screen_work_area()
            self.geometry(f"{width}x{height}+{x}+{y}")
            self._maximized = True
            self._paint_titlebar_button(self.max_btn, "restore")
            self.window_grip.place_forget()
        self.schedule_save()

    def _start_move_window(self, event):
        if self._maximized:
            self._move_root = None
            return
        self._move_root = (event.x_root, event.y_root)
        self._move_origin = (self.winfo_x(), self.winfo_y())

    def _do_move_window(self, event):
        if self._maximized or self._move_root is None:
            return
        dx = event.x_root - self._move_root[0]
        dy = event.y_root - self._move_root[1]
        self.geometry(f"+{self._move_origin[0] + dx}+{self._move_origin[1] + dy}")

    def _start_resize_window(self, event):
        if self._maximized:
            return
        self._rw_root = (event.x_root, event.y_root)
        self._rw_start = (self.winfo_width(), self.winfo_height())

    def _do_resize_window(self, event):
        if self._maximized:
            return
        dx = event.x_root - self._rw_root[0]
        dy = event.y_root - self._rw_root[1]
        new_w = max(520, self._rw_start[0] + dx)
        new_h = max(380, self._rw_start[1] + dy)
        self.geometry(f"{new_w}x{new_h}")

    def minimize(self):
        self._minimized = True
        self.overrideredirect(False)
        self.state("iconic")

    def _on_map(self, event):
        # Solo actuamos cuando ES REALMENTE una vuelta desde minimizar
        # (nosotros mismos marcamos _minimized al minimizar). Reaccionar a
        # cualquier evento <Map> sin este control provoca parpadeo continuo,
        # porque forzar overrideredirect puede disparar otro <Map> a su vez.
        if self._applying_taskbar_fix or not self._minimized:
            return
        if self.state() == "normal":
            self._minimized = False
            self.overrideredirect(True)
            self.after(60, self._force_taskbar_icon)

    def _force_taskbar_icon(self):
        # En Windows, una ventana overrideredirect no recibe icono en la
        # barra de tareas salvo que se fuerce por API (WS_EX_APPWINDOW).
        self._applying_taskbar_fix = True
        try:
            gwl_exstyle = -20
            ws_ex_appwindow = 0x00040000
            ws_ex_toolwindow = 0x00000080
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, gwl_exstyle)
            style = (style & ~ws_ex_toolwindow) | ws_ex_appwindow
            ctypes.windll.user32.SetWindowLongW(hwnd, gwl_exstyle, style)
            self.withdraw()
            self.after(10, self._finish_taskbar_fix)
        except Exception:
            self._applying_taskbar_fix = False

    def _finish_taskbar_fix(self):
        self.deiconify()
        self.after(10, self._clear_taskbar_fix_flag)

    def _clear_taskbar_fix_flag(self):
        self._applying_taskbar_fix = False

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
        for (row, col), notes_list in self.grid_map.items():
            w = self.col_widths.get(col, DEFAULT_COL_W)
            h = self.row_heights.get(row, DEFAULT_ROW_H)
            n = len(notes_list)
            sub_h = h / n if n else h
            for i, note in enumerate(notes_list):
                note.place(x=col_x[col], y=row_y[row] + i * sub_h, width=w, height=sub_h)
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
        old_list = self.grid_map.get(old_key, [])
        new_list = self.grid_map.get(new_key, [])
        if len(old_list) > 1 or len(new_list) > 1:
            # una de las dos celdas esta dividida: no se arrastra de forma
            # individual (usa el menu de clic derecho para reorganizar)
            self.relayout()
            return
        occupant = new_list[0] if new_list else None
        if old_key in self.grid_map:
            del self.grid_map[old_key]
        if occupant is not None:
            occupant.row, occupant.col = old_key
            self.grid_map[old_key] = [occupant]
        note.row, note.col = new_key
        self.grid_map[new_key] = [note]
        self.relayout()

    def split_cell(self, row, col, target_count):
        key = (row, col)
        notes_list = self.grid_map.setdefault(key, [])
        while len(notes_list) < target_count:
            color = NOTE_COLORS[len(self.grid_map) % len(NOTE_COLORS)]
            note = PostIt(self.board_frame, self, uuid.uuid4().hex[:8],
                          row, col, color, self.default_font_family, 11,
                          False, None, [])
            notes_list.append(note)
        self.relayout()
        self.schedule_save()

    # ---------------- notas: crear / borrar / seleccionar ----------------
    def add_note(self, target_row=None, target_col=None, is_task=False):
        if target_row is None or target_col is None or (target_row, target_col) in self.grid_map:
            target_row, target_col = self.next_free_cell()
        color = NOTE_COLORS[len(self.grid_map) % len(NOTE_COLORS)]
        items = [{"text": "", "done": False}] if is_task else None
        runs = None if is_task else []
        note = PostIt(self.board_frame, self, uuid.uuid4().hex[:8],
                      target_row, target_col, color,
                      self.default_font_family, 11, is_task, items, runs)
        self.grid_map[(target_row, target_col)] = [note]
        self.relayout()
        self.set_active_note(note)
        if is_task:
            note.item_rows[0]["entry"].focus_set()
        else:
            note.text_widget.focus_set()
        self.schedule_save()

    def confirm_delete_note(self, note):
        """Confirmacion centrada en la pantalla. Teclas: S/Y/Enter si, N/Esc no."""
        if ui.confirm(self, "Eliminar nota", "¿Eliminar esta nota?",
                      "Pulsa S o Enter para eliminarla, N o Esc para cancelar.",
                      ok_text="Eliminar", cancel_text="Cancelar", kind="danger"):
            self.delete_note(note)

    def delete_note(self, note):
        key = (note.row, note.col)
        notes_list = self.grid_map.get(key)
        if notes_list and note in notes_list:
            notes_list.remove(note)
            if not notes_list:
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
        text_style_enabled = enabled and not note.is_task
        cb_state = "readonly" if enabled else "disabled"
        sp_state = "normal" if enabled else "disabled"
        btn_state = "normal" if enabled else "disabled"
        text_style_state = "normal" if text_style_enabled else "disabled"
        self.font_family_cb.configure(state=cb_state)
        self.font_size_sp.configure(state=sp_state)
        for chk in (self.chk_bold, self.chk_italic, self.chk_underline,
                    self.chk_strike, self.bullet_btn):
            chk.configure(state=text_style_state)
        for b in self.color_swatch_buttons:
            b.configure(state=btn_state)
        p = self.palette()
        ink = p["text"] if enabled else p["muted_text"]
        self.more_color_btn.configure(state=btn_state,
                                      image=get_icon(self, "palette", ink, 16) or "",
                                      text="" if get_icon(self, "palette", ink, 16) else "Color")
        list_ink = p["text"] if text_style_enabled else p["muted_text"]
        self.bullet_btn.configure(image=get_icon(self, "list", list_ink, 16) or "",
                                  text="" if get_icon(self, "list", list_ink, 16) else "-")
        if enabled:
            self.font_family_var.set(note.font_family)
            self.font_size_var.set(str(note.font_size))
        else:
            self.font_family_var.set("")
            self.font_size_var.set("")

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
        if not self.active_note or self.active_note.is_task:
            return
        if self.active_note.toggle_style("b"):
            self.active_note.text_widget.focus_set()
            self.schedule_save()

    def toggle_italic(self):
        if not self.active_note or self.active_note.is_task:
            return
        if self.active_note.toggle_style("i"):
            self.active_note.text_widget.focus_set()
            self.schedule_save()

    def toggle_underline(self):
        if not self.active_note or self.active_note.is_task:
            return
        if self.active_note.toggle_style("u"):
            self.active_note.text_widget.focus_set()
            self.schedule_save()

    def toggle_strike(self):
        if not self.active_note or self.active_note.is_task:
            return
        if self.active_note.toggle_style("s"):
            self.active_note.text_widget.focus_set()
            self.schedule_save()

    def toggle_bullets(self):
        if not self.active_note or self.active_note.is_task:
            return
        text = self.active_note.text_widget
        try:
            first_line = int(text.index("sel.first").split(".")[0])
            last_line = int(text.index("sel.last").split(".")[0])
        except tk.TclError:
            first_line = last_line = int(text.index("insert").split(".")[0])

        all_have_bullet = True
        for ln in range(first_line, last_line + 1):
            content = text.get(f"{ln}.0", f"{ln}.end")
            if not content.lstrip().startswith("• "):
                all_have_bullet = False
                break

        for ln in range(first_line, last_line + 1):
            content = text.get(f"{ln}.0", f"{ln}.end")
            stripped = content.lstrip()
            if all_have_bullet:
                if stripped.startswith("• "):
                    lead = len(content) - len(stripped)
                    text.delete(f"{ln}.{lead}", f"{ln}.{lead + 2}")
            else:
                if not stripped.startswith("• "):
                    text.insert(f"{ln}.0", "• ")

        text.focus_set()
        self.schedule_save()

    def set_active_color(self, hex_color):
        if not self.active_note:
            return
        self.active_note.set_color(hex_color)
        self.schedule_save()

    def pick_custom_color(self):
        if not self.active_note:
            return
        color = ui.ask_color(self, self.active_note.color, "Elige un color de post-it")
        if color:
            self.set_active_color(color)

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.theme_btn.set_icon("moon" if self.theme == "light" else "sun")
        self.apply_theme_to_all()
        self.schedule_save()

    def _set_toolbar_collapsed(self, collapsed):
        self.toolbar_collapsed = bool(collapsed)
        if collapsed:
            self.toolbar_frame.pack_forget()
            self._paint_titlebar_button(self.toggle_toolbar_btn, "chevron_down")
        else:
            self.toolbar_frame.pack(side="top", fill="x", before=self.board_container)
            self._paint_titlebar_button(self.toggle_toolbar_btn, "chevron_up")
        self.whiteboard.set_toolbar_collapsed(collapsed)

    def toggle_toolbar(self):
        self._set_toolbar_collapsed(not self.toolbar_collapsed)
        self.schedule_save()

    def apply_theme_to_all(self):
        p = self.palette()
        self.configure(bg=p["app_bg"])
        self.titlebar_frame.configure(bg=p["titlebar_bg"])
        self.title_lbl.configure(bg=p["titlebar_bg"], fg=p["text"])
        if self.title_icon_label is not None:
            self.title_icon_label.configure(bg=p["titlebar_bg"])
        for btn in self.titlebar_buttons:
            self._paint_titlebar_button(btn)
        self.tabs_frame.configure(bg=p["toolbar_bg"])
        self.project_lbl.configure(bg=p["toolbar_bg"], fg=p["muted_text"])
        for btn in (self.settings_btn, self.theme_btn, self.update_badge,
                    self.delete_project_btn):
            btn.restyle()
        self._style_tabs()
        self.notes_page.configure(bg=p["app_bg"])

        self.toolbar_frame.configure(bg=p["toolbar_bg"])
        for w in self.toolbar_theme_widgets:
            w.configure(bg=p["toolbar_bg"], fg=p["text"])
        for s in self.toolbar_separators:
            s.configure(bg=p["border"])
        self.add_btn.configure(bg=p["button_bg"], fg=p["text"],
                               image=get_icon(self, "plus", p["text"], 14) or "")
        self.add_task_btn.configure(bg=p["button_bg"], fg=p["text"],
                                    image=get_icon(self, "task", p["text"], 14) or "")
        for chk in (self.chk_bold, self.chk_italic, self.chk_underline, self.chk_strike):
            chk.configure(bg=p["toolbar_bg"], fg=p["text"], activebackground=p["toolbar_bg"])
        self.more_color_btn.configure(bg=p["button_bg"], activebackground=p["button_hover"])
        self.bullet_btn.configure(bg=p["toolbar_bg"], activebackground=p["toolbar_bg"])
        self._sync_toolbar_from_active()

        self.board_container.configure(bg=p["app_bg"])
        self.canvas.configure(bg=p["board_bg"])
        self.board_frame.configure(bg=p["board_bg"])
        self.window_grip.configure(bg=p["toolbar_bg"], fg=p["text"],
                                   image=get_icon(self, "grip", p["muted_text"], 14, 2.0) or "")

        self._configure_ttk_style()

        for notes_list in self.grid_map.values():
            for note in notes_list:
                note.refresh_theme()
        self.whiteboard.update_theme()
        self.calendar_view.update_theme()
        self.events_view.update_theme()

    # ---------------- proyectos (multiples config.json) ----------------
    def _load_projects_registry(self):
        self.known_projects = []
        self.last_project_path = None
        if os.path.exists(PROJECTS_REGISTRY_PATH):
            try:
                with open(PROJECTS_REGISTRY_PATH, "r", encoding="utf-8") as f:
                    reg = json.load(f)
                if isinstance(reg, dict):
                    self.known_projects = [
                        proj for proj in reg.get("known_projects", [])
                        if isinstance(proj, dict) and proj.get("name") and proj.get("path")
                    ]
                    self.last_project_path = reg.get("last_project_path")
            except (json.JSONDecodeError, OSError):
                pass

    def _save_projects_registry(self):
        try:
            with open(PROJECTS_REGISTRY_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "known_projects": self.known_projects,
                    "last_project_path": self.last_project_path,
                }, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _resolve_startup_project_path(self):
        if self.last_project_path and os.path.exists(self.last_project_path):
            return self.last_project_path
        return self.master_config_path

    def _load_board(self, path):
        if not os.path.exists(path):
            return _default_config(with_demo=(path == self.master_config_path))
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("formato inesperado")
            return data
        except (json.JSONDecodeError, ValueError, OSError):
            try:
                os.replace(path, path + ".bak")
            except OSError:
                pass
            return _default_config(with_demo=False)

    def _rebuild_board_from(self, data):
        for notes_list in list(self.grid_map.values()):
            for note in notes_list:
                note.destroy()
        self.grid_map = {}
        self.set_active_note(None)

        grid_cfg = data.get("grid", {})
        self.col_widths = {int(k): v for k, v in grid_cfg.get("col_widths", {}).items()}
        self.row_heights = {int(k): v for k, v in grid_cfg.get("row_heights", {}).items()}

        self.theme = data.get("theme", "light")
        self.theme_btn.set_icon("moon" if self.theme == "light" else "sun")

        for nd in data.get("notes", []):
            row = nd.get("row", 0)
            col = nd.get("col", 0)
            is_task = nd.get("is_task", False)
            items = nd.get("items")
            if is_task and items is None:
                # compatibilidad con el formato de tarea anterior (una sola casilla)
                items = [{"text": nd.get("text", ""), "done": nd.get("done", False)}]
            runs = nd.get("runs")
            if not is_task and runs is None:
                # compatibilidad con el formato anterior (nota entera con un solo estilo)
                runs = [{
                    "text": nd.get("text", ""),
                    "b": nd.get("bold", False), "i": nd.get("italic", False),
                    "u": nd.get("underline", False), "s": nd.get("strike", False),
                }]
            note = PostIt(
                self.board_frame, self,
                nd.get("id", uuid.uuid4().hex[:8]), row, col,
                nd.get("color", NOTE_COLORS[0]),
                nd.get("font_family", self.default_font_family),
                nd.get("font_size", 11), is_task, items, runs,
            )
            self.grid_map.setdefault((row, col), []).append(note)

        # Compatibilidad: si no existe whiteboard, el proyecto es anterior
        # a esta version y la nueva pizarra empieza vacia.
        self.whiteboard.load(data.get("whiteboard", {}))
        # Compatibilidad: los proyectos anteriores a Advance no tienen eventos;
        # empiezan con los tipos por defecto y la tabla vacia.
        self.event_store.load(data.get("events", {}))
        self.calendar_view.load_state(data.get("calendar", {}))
        self.events_view.load_state(data.get("events_view", {}))
        self.apply_theme_to_all()
        self.relayout()
        self._set_toolbar_collapsed(data.get("toolbar_collapsed", False))

    def _project_display_name(self, path):
        if path == self.master_config_path:
            return self.MASTER_LABEL
        for proj in self.known_projects:
            if proj["path"] == path:
                return proj["name"]
        return os.path.basename(os.path.dirname(path)) or path

    def _refresh_project_dropdown(self):
        names = [self.MASTER_LABEL] + [proj["name"] for proj in self.known_projects] + [self.ADD_PROJECT_LABEL]
        self.project_cb.configure(values=names)
        self.project_var.set(self._project_display_name(self.active_config_path))
        self._update_delete_project_btn_state()

    def _update_delete_project_btn_state(self):
        choice = self.project_var.get()
        known_names = [proj["name"] for proj in self.known_projects]
        self.delete_project_btn.set_enabled(choice in known_names)

    def _delete_current_project(self):
        choice = self.project_var.get()
        target = None
        for proj in self.known_projects:
            if proj["name"] == choice:
                target = proj
                break
        if target is None:
            return
        if not ui.confirm(
            self, "Quitar proyecto",
            "¿Quitar «{}» de la lista de proyectos?".format(target["name"]),
            "No se borra su carpeta ni su config.json: solo deja de aparecer "
            "en el desplegable.", ok_text="Quitar de la lista", kind="danger",
        ):
            return
        self.known_projects = [p for p in self.known_projects if p["path"] != target["path"]]
        if self.active_config_path == target["path"]:
            self._switch_to_project(self.master_config_path)
        else:
            self._save_projects_registry()
            self._refresh_project_dropdown()

    def _on_project_selected(self, event=None):
        choice = self.project_var.get()
        if choice == self.ADD_PROJECT_LABEL:
            self._add_project_flow()
            return
        if choice == self.MASTER_LABEL:
            target = self.master_config_path
        else:
            target = None
            for proj in self.known_projects:
                if proj["name"] == choice:
                    target = proj["path"]
                    break
        if target and target != self.active_config_path:
            self._switch_to_project(target)
        else:
            self._refresh_project_dropdown()

    @staticmethod
    def _is_tablonk_config(path):
        """Evita machacar un config.json que pertenezca a otra aplicacion."""
        if not os.path.isfile(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
            return isinstance(data, dict) and "notes" in data and "grid" in data
        except (OSError, ValueError):
            return False

    def _add_project_flow(self):
        folder = ui.ask_directory(self, title="Elige o crea la carpeta del proyecto")
        if not folder:
            self._refresh_project_dropdown()
            return
        # Los proyectos nuevos guardan juntos config y assets en tablonk/.
        # Los proyectos antiguos mantienen la ruta original sin migracion
        # destructiva ni duplicacion de configuraciones.
        if os.path.basename(os.path.normpath(folder)).lower() == "tablonk":
            new_path = os.path.join(folder, "config.json")
        elif os.path.isfile(os.path.join(folder, "tablonk", "config.json")):
            new_path = os.path.join(folder, "tablonk", "config.json")
        elif self._is_tablonk_config(os.path.join(folder, "config.json")):
            new_path = os.path.join(folder, "config.json")
        else:
            new_path = os.path.join(folder, "tablonk", "config.json")
        if new_path == self.active_config_path:
            self._refresh_project_dropdown()
            return
        base_name = os.path.basename(folder.rstrip("/\\")) or folder
        existing_names = {proj["name"] for proj in self.known_projects} | {self.MASTER_LABEL}
        name = base_name
        i = 2
        while name in existing_names:
            name = f"{base_name} ({i})"
            i += 1
        if not any(proj["path"] == new_path for proj in self.known_projects):
            self.known_projects.append({"name": name, "path": new_path})
        self._switch_to_project(new_path)

    def _switch_to_project(self, new_path):
        self.save_now()
        self.active_config_path = new_path
        data = self._load_board(new_path)
        self._rebuild_board_from(data)
        self.show_tab(data.get("active_tab", "notes"), save=False)
        self.last_project_path = None if new_path == self.master_config_path else new_path
        self._save_projects_registry()
        self._refresh_project_dropdown()
        self.save_now()

    # ---------------- guardado ----------------
    def schedule_save(self):
        if self._save_job is not None:
            try:
                self.after_cancel(self._save_job)
            except Exception:
                pass
        self._save_job = self.after(600, self.save_now)

    def gather_config(self):
        return {
            "theme": self.theme,
            "toolbar_collapsed": self.toolbar_collapsed,
            "window": {
                "x": self._restore_geometry[0] if self._maximized else self.winfo_x(),
                "y": self._restore_geometry[1] if self._maximized else self.winfo_y(),
                "width": self._restore_geometry[2] if self._maximized else self.winfo_width(),
                "height": self._restore_geometry[3] if self._maximized else self.winfo_height(),
                "maximized": self._maximized,
            },
            "grid": {"col_widths": self.col_widths, "row_heights": self.row_heights},
            "notes": [note.to_dict()
                      for notes_list in self.grid_map.values()
                      for note in notes_list],
            "active_tab": self.active_tab,
            "whiteboard": self.whiteboard.to_dict(),
            "events": self.event_store.to_dict(),
            "calendar": self.calendar_view.state(),
            "events_view": self.events_view.state(),
            "app_version": APP_VERSION,
        }

    def save_now(self):
        if self._save_job is not None:
            try:
                self.after_cancel(self._save_job)
            except Exception:
                pass
            self._save_job = None
        # Reemplazo atomico para evitar un JSON a medio escribir tras un
        # cierre brusco o un corte de alimentacion.
        temp_path = None
        try:
            target_dir = os.path.dirname(self.active_config_path)
            os.makedirs(target_dir, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(prefix=".tablonk_", suffix=".tmp", dir=target_dir)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.gather_config(), f, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.active_config_path)
        except OSError as exc:
            self._last_save_error = str(exc)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


if __name__ == "__main__":
    app = StickyBoardApp()
    app.mainloop()
