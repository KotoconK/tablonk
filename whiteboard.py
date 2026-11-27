"""TablonK whiteboard, stored inside the project's single config.json.

Dependencies: Tkinter and Pillow. Existing projects (including old 'text'
objects) remain readable. All image paths are local to config.json/assets/.
"""

import copy
import hashlib
import io
import math
import os
import re
import shutil
import tkinter as tk
import uuid
from tkinter import ttk, font as tkfont

import ui_common as ui
from icons import get_icon

try:
    from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageOps, ImageTk
except ImportError:
    Image = ImageDraw = ImageFont = ImageGrab = ImageOps = ImageTk = None


BOARD_COLORS = (
    ("Amarillo", "#FFE596"), ("Naranja", "#FFD293"),
    ("Rosa", "#FAA5BE"), ("Verde", "#AEE5C1"),
    ("Azul", "#A8D8FF"), ("Morado", "#D7B5F5"),
    ("Blanco", "#FFFFFF"), ("Gris", "#E2E7ED"),
    ("Negro", "#233044"),
)
INK_COLORS = (
    ("Oscuro", "#263244"), ("Negro", "#101419"),
    ("Blanco", "#FFFFFF"), ("Rojo", "#E35165"),
    ("Azul", "#2C7CD1"), ("Verde", "#2F9461"),
    ("Morado", "#8A56C5"), ("Naranja", "#F18828"),
)
MIN_BOX_W = 110
MIN_BOX_H = 64
STYLE_FIELDS = {"b": "bold", "i": "italic", "u": "underline", "s": "strike"}
STYLE_ORDER = ("b", "i", "u", "s")


def _style_tuple(data):
    return tuple(bool(data.get(k, data.get(STYLE_FIELDS[k], False))) for k in STYLE_ORDER)


def _style_name(bits):
    return "style_" + "".join("1" if v else "0" for v in bits)


def _merge_text_runs(runs):
    """Compact runs while retaining the independent B/I/U/S state of each span."""
    merged = []
    for raw in runs:
        piece = str(raw.get("text", ""))
        if not piece:
            continue
        bits = _style_tuple(raw)
        if merged and _style_tuple(merged[-1]) == bits:
            merged[-1]["text"] += piece
        else:
            merged.append({"text": piece, **dict(zip(STYLE_ORDER, bits))})
    return merged


def _node_text_runs(obj):
    """Old nodes have only 'text' + whole-node style; newer ones have runs.

    Keep the original plain-text field for backwards compatibility with all
    versions of TablonK. Ignore corrupt/stale runs rather than losing text.
    """
    text = str(obj.get("text") or "")
    saved = obj.get("text_runs")
    if isinstance(saved, list) and all(isinstance(run, dict) for run in saved):
        merged = _merge_text_runs(saved)
        if "".join(run["text"] for run in merged) == text:
            return merged
    return _merge_text_runs([{"text": text, **dict(zip(STYLE_ORDER, _style_tuple(obj)))}])


def _layout_rich_text(runs, max_width, max_height, font_for, measure, linespace):
    """Wrap text with mixed styles, returning [(segments, width, height), ...].

    Each segment is (text, style_bits, font, width). Uses the caller's real
    font metrics, so both Tk canvas preview and Pillow PNG export are styled.
    """
    max_width, max_height = max(1, max_width), max(1, max_height)
    raw = [(char, _style_tuple(run)) for run in runs for char in run.get("text", "")]
    if not raw:
        return []
    cache = {}
    def font(bits):
        if bits not in cache:
            cache[bits] = font_for(bits)
        return cache[bits]
    def width(char, bits):
        return measure(font(bits), char)
    result_lines = []
    line = []
    current_width = 0.0
    index = 0
    just_wrapped = False
    while index < len(raw):
        char, bits = raw[index]
        if char == "\n":
            result_lines.append(line)
            line, current_width, just_wrapped = [], 0.0, False
            index += 1
            continue
        if just_wrapped and not line and char == " ":
            index += 1
            continue
        w = width(char, bits)
        if line and current_width + w > max_width:
            space = next((k for k in range(len(line)-1, 0, -1) if line[k][0] == " "), None)
            if space is not None:
                result_lines.append(line[:space])
                line = line[space+1:]
                while line and line[0][0] == " ":
                    line.pop(0)
                current_width = sum(width(c, t) for c, t in line)
            else:
                result_lines.append(line)
                line, current_width = [], 0.0
            just_wrapped = True
            continue
        line.append((char, bits))
        current_width += w
        just_wrapped = False
        index += 1
    result_lines.append(line)
    visible = []
    total_height = 0
    for characters in result_lines:
        height = max([linespace(font(bits)) for _, bits in characters] or
                     [linespace(font((False, False, False, False)))])
        if visible and total_height + height > max_height:
            break
        visible.append(list(characters))
        total_height += height
    if len(visible) < len(result_lines) and visible:
        last = visible[-1]
        ellipsis = ("…", last[-1][1] if last else (False, False, False, False))
        while last and sum(width(c, t) for c, t in last) + width(*ellipsis) > max_width:
            last.pop()
        if width(*ellipsis) <= max_width:
            last.append(ellipsis)
    result = []
    for characters in visible:
        segments = []
        height = max([linespace(font(bits)) for _, bits in characters] or
                     [linespace(font((False, False, False, False)))])
        for ch, bits in characters:
            font_obj = font(bits)
            if segments and segments[-1][1] == bits:
                last_text, _, last_font, last_width = segments[-1]
                segments[-1] = (last_text + ch, bits, last_font, last_width + width(ch, bits))
            else:
                segments.append((ch, bits, font_obj, width(ch, bits)))
        result.append((segments, sum(seg[3] for seg in segments), height))
    return result


def _id():
    return uuid.uuid4().hex[:12]


def _number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def _ink_on(background):
    try:
        color = background.lstrip("#")
        r, g, b = (int(color[i:i+2], 16) for i in (0, 2, 4))
        return "#182434" if (r*299 + g*587 + b*114) / 1000 > 150 else "#FFFFFF"
    except (ValueError, IndexError, AttributeError):
        return "#182434"


def _center(obj):
    return obj["x"] + obj["w"] / 2, obj["y"] + obj["h"] / 2


def _anchor_toward(a, b):
    ax, ay = _center(a)
    bx, by = _center(b)
    dx, dy = bx - ax, by - ay
    if abs(dx) + abs(dy) < 0.001:
        return ax, ay
    scale = min((a["w"] / 2) / max(abs(dx), 0.001),
                (a["h"] / 2) / max(abs(dy), 0.001))
    return ax + dx * scale, ay + dy * scale


def _distance_to_segment(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    vx, vy = bx-ax, by-ay
    denom = vx*vx + vy*vy
    t = max(0., min(1., ((px-ax)*vx+(py-ay)*vy) / denom)) if denom else 0.
    return math.hypot(px - ax - t*vx, py - ay - t*vy)


def _rect_intersects(rect_a, rect_b):
    a0, b0, a1, b1 = rect_a
    c0, d0, c1, d1 = rect_b
    return a0 <= c1 and c0 <= a1 and b0 <= d1 and d0 <= b1


def _arrow_polygon(a, b, scale=1.0):
    x1, y1 = a
    x2, y2 = b
    angle = math.atan2(y2 - y1, x2 - x1)
    length, half = 13.0*scale, 5.8*scale
    back_x, back_y = x2-length*math.cos(angle), y2-length*math.sin(angle)
    return [(x2, y2),
            (back_x + half*math.sin(angle), back_y - half*math.cos(angle)),
            (back_x - half*math.sin(angle), back_y + half*math.cos(angle))]


class HoverTip:
    """Tooltip for icon-only tools; no third-party UI library required."""

    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.job = None
        self.window = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _enter(self, event):
        self._hide()
        self.job = self.widget.after(550, self._show)

    def _show(self):
        self.job = None
        if self.window is not None or not self.widget.winfo_exists():
            return
        root_x = self.widget.winfo_rootx() + 7
        root_y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        tip = tk.Toplevel(self.widget)
        tip.overrideredirect(True)
        tip.wm_geometry(f"+{root_x}+{root_y}")
        tk.Label(tip, text=self.text, bg="#273443", fg="white", padx=8,
                 pady=5, font=("Segoe UI", 9), relief="flat").pack()
        self.window = tip

    def _hide(self, event=None):
        if self.job is not None:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


class Whiteboard(tk.Frame):
    """A multi-select, antialiased whiteboard with a contextual property panel."""

    DEFAULT_NODE = {
        "fill": "#FFE596", "text_color": "#182434", "font_family": "Segoe UI",
        "font_size": 15, "bold": False, "italic": False,
        "underline": False, "strike": False, "align": "left",
    }
    DEFAULT_PEN = {"color": "#263244", "width": 3.0}
    DEFAULT_EDGE = {"color": "#263244", "width": 2.8}

    def __init__(self, master, app):
        super().__init__(master, borderwidth=0)
        self.app = app
        self.tool = "select"
        self.zoom = 1.0
        self.items = []
        self.connections = []
        self.strokes = []
        self.node_defaults = copy.deepcopy(self.DEFAULT_NODE)
        self.pen_style = copy.deepcopy(self.DEFAULT_PEN)
        self.edge_style = copy.deepcopy(self.DEFAULT_EDGE)
        self.selection = set()  # {("obj"|"stroke"|"edge", unique_id)}
        self.selected = None    # Legacy shortcut for a single selection.
        self.pending_connection = None
        self._drag = None
        self._marquee = None
        self._draft_stroke = None
        self._editor = None
        self._editor_fonts = []  # keep Tk font instances used by Text tags alive
        self._undo = []
        self._redo = []
        self._image_cache = {}
        self._paint_cache = {}
        self._paint_refs = []
        self._font_cache = {}
        self._icon_images = {}
        self._toolbar_collapsed = False
        self._props_open = True
        self._properties_refresh_job = None
        self._internal_clipboard = None
        self.status_text = tk.StringVar(value="Arrastra para seleccionar varios elementos. Doble clic: editar nodo.")
        self._build_ui()
        self.update_theme()
        self._render()

    # -------------------------- interface --------------------------------
    def _make_icon(self, name, ink):
        if Image is None:
            return None
        k = 4
        picture = Image.new("RGBA", (26*k, 26*k), (0, 0, 0, 0))
        d = ImageDraw.Draw(picture)
        def line(points, width=2.2, fill=ink):
            d.line([(round(x*k), round(y*k)) for x, y in points],
                   fill=fill, width=round(width*k), joint="curve")
        def box(bounds, radius=3, fill=None, outline=ink, width=2):
            d.rounded_rectangle(tuple(round(x*k) for x in bounds),
                                radius=radius*k, fill=fill, outline=outline,
                                width=round(width*k))
        def circle(bounds, fill=ink):
            d.ellipse(tuple(round(x*k) for x in bounds), fill=fill)
        if name == "select":
            d.polygon([(4*k, 2*k), (5*k, 21*k), (10*k, 15*k),
                       (14*k, 24*k), (18*k, 22*k), (13*k, 13*k),
                       (20*k, 12*k)], fill=ink)
        elif name == "node":
            box((2.5, 4, 23.5, 22), 4)
            line([(6.5, 9), (19.5, 9)], 1.8)
            line([(6.5, 13), (18, 13)], 1.8)
            line([(6.5, 17), (14.5, 17)], 1.8)
        elif name == "image":
            box((2, 3.5, 24, 22.5), 3)
            circle((16.5, 7, 21, 11.5))
            line([(4, 20), (10, 13), (14, 17), (17, 14), (23, 21)], 2)
        elif name == "pen":
            line([(5, 21), (19, 6)], 5)
            line([(5, 21), (19, 6)], 2.3, "#FFFFFF")
            d.polygon([(3*k, 23*k), (5*k, 17*k), (9*k, 21*k)], fill=ink)
            line([(19, 4.5), (22, 7.5)], 3.2)
        elif name == "connect":
            box((1.5, 3, 9, 11), 2, fill=None, width=2)
            box((17, 15, 24.5, 23), 2, fill=None, width=2)
            line([(9, 9), (18, 18)], 2)
            line([(14, 18), (18, 18), (17, 14)], 2)
        elif name == "paste":
            box((6, 5, 23, 24), 2.5)
            box((2.5, 2, 13, 18), 2, fill="#FFFFFF")
            line([(6, 8), (10, 8)], 1.7)
            line([(6, 12), (10, 12)], 1.7)
        return ImageTk.PhotoImage(picture.resize((26, 26), Image.Resampling.LANCZOS),
                                  master=self)

    def _build_ui(self):
        self.toolbar_frame = tk.Frame(self, height=45)
        self.toolbar_frame.pack(side="top", fill="x")
        self.toolbar_frame.pack_propagate(False)
        self.tool_buttons = {}
        tool_labels = (
            ("select", "Seleccionar (arrastrar un rect\u00e1ngulo para selecci\u00f3n m\u00faltiple)"),
            ("node", "Nodo / cuadro de texto"),
            ("image", "Insertar imagen desde archivo"),
            ("pen", "L\u00e1piz"),
            ("connect", "Conectar nodos"),
        )
        for name, tooltip in tool_labels:
            button = tk.Button(self.toolbar_frame, relief="flat", bd=0,
                               cursor="hand2", width=32, height=32,
                               command=lambda key=name: self.set_tool(key))
            button.pack(side="left", padx=(3, 1), pady=5)
            self.tool_buttons[name] = button
            HoverTip(button, tooltip)

        self.paste_btn = tk.Button(self.toolbar_frame, bd=0, relief="flat", width=32,
                                   height=32, command=self.paste_image, cursor="hand2")
        self.paste_btn.pack(side="left", padx=(5, 1), pady=5)
        HoverTip(self.paste_btn, "Pegar imagen desde el portapapeles (Ctrl+V)")

        self.properties_toggle = tk.Button(self.toolbar_frame, relief="flat", bd=0,
                                           cursor="hand2", padx=6, compound="right",
                                           text="Opciones ",
                                           font=("Segoe UI", 9),
                                           command=self.toggle_properties)
        self.properties_toggle.pack(side="left", padx=(8, 0), pady=6)

        self.undo_btn = tk.Button(self.toolbar_frame, text="", bd=0, padx=7, pady=4,
                                  font=("Segoe UI", 13), relief="flat", command=self.undo)
        self.redo_btn = tk.Button(self.toolbar_frame, text="", bd=0, padx=7, pady=4,
                                  font=("Segoe UI", 13), relief="flat", command=self.redo)
        self.undo_btn.pack(side="left", padx=(9, 0))
        self.redo_btn.pack(side="left")
        HoverTip(self.undo_btn, "Deshacer (Ctrl+Z)")
        HoverTip(self.redo_btn, "Rehacer (Ctrl+Y)")

        self.export_btn = tk.Button(self.toolbar_frame, text=" PNG", bd=0, compound="left",
                                    padx=8, pady=3, relief="flat", command=self.export_png)
        self.export_btn.pack(side="right", padx=(0, 8), pady=6)
        HoverTip(self.export_btn, "Exportar pizarra a PNG")
        self.zoom_plus = tk.Button(self.toolbar_frame, text="", bd=0, padx=6, pady=4,
                                   relief="flat", command=lambda: self.change_zoom(1.25))
        self.zoom_minus = tk.Button(self.toolbar_frame, text="", bd=0, padx=6, pady=4,
                                    relief="flat", command=lambda: self.change_zoom(0.8))
        ui.HoverTip(self.zoom_plus, "Acercar (Ctrl+rueda)")
        ui.HoverTip(self.zoom_minus, "Alejar (Ctrl+rueda)")
        self.zoom_label = tk.Label(self.toolbar_frame, text="100%", font=("Segoe UI", 9))
        self.zoom_plus.pack(side="right")
        self.zoom_label.pack(side="right", padx=3)
        self.zoom_minus.pack(side="right")

        self.properties_frame = tk.Frame(self)
        self.properties_frame.pack(side="top", fill="x")
        self.properties_content = tk.Frame(self.properties_frame)
        self.properties_content.pack(side="top", fill="x", padx=9, pady=(5, 3))
        self.properties_secondary = tk.Frame(self.properties_frame)

        self.body_frame = tk.Frame(self)
        self.body_frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.body_frame, bd=0, highlightthickness=0,
                                bg="#FCFDFE", cursor="arrow")
        self.vbar = tk.Scrollbar(self.body_frame, orient="vertical", command=self.canvas.yview)
        self.hbar = tk.Scrollbar(self.body_frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.body_frame.grid_rowconfigure(0, weight=1)
        self.body_frame.grid_columnconfigure(0, weight=1)
        self.status_lbl = tk.Label(self, anchor="w", font=("Segoe UI", 9),
                                    textvariable=self.status_text, padx=9, pady=4)
        self.status_lbl.pack(side="bottom", fill="x")

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<Button-3>", self._context_menu)
        self.canvas.bind("<ButtonPress-2>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B2-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<MouseWheel>", self._mousewheel)
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))
        self.canvas.bind("<Control-MouseWheel>", self._zoom_wheel)
        self.canvas.bind("<Control-Button-4>", lambda e: self.change_zoom(1.1))
        self.canvas.bind("<Control-Button-5>", lambda e: self.change_zoom(1/1.1))
        self.app.bind("<Control-z>", self._shortcut_undo)
        self.app.bind("<Control-y>", self._shortcut_redo)
        self.app.bind("<Control-c>", self._shortcut_copy)
        self.app.bind("<Control-v>", self._shortcut_paste)
        self.app.bind("<Control-a>", self._shortcut_select_all)
        self.app.bind("<Delete>", self._shortcut_delete)
        self.app.bind("<Escape>", self._shortcut_escape)

    def set_toolbar_collapsed(self, collapsed):
        self._toolbar_collapsed = bool(collapsed)
        if collapsed:
            self.toolbar_frame.pack_forget()
            self.properties_frame.pack_forget()
        else:
            self.toolbar_frame.pack(side="top", fill="x", before=self.body_frame)
            if self._props_open:
                self.properties_frame.pack(side="top", fill="x", before=self.body_frame)

    def toggle_properties(self):
        self._props_open = not self._props_open
        self._paint_options_toggle()
        if self._props_open and not self._toolbar_collapsed:
            self.properties_frame.pack(side="top", fill="x", before=self.body_frame)
            self._refresh_properties()
        else:
            self.properties_frame.pack_forget()

    def update_theme(self):
        if not hasattr(self, "canvas"):
            return
        p = self.app.palette()
        self.configure(bg=p["app_bg"])
        self.body_frame.configure(bg=p["app_bg"])
        self.toolbar_frame.configure(bg=p["toolbar_bg"])
        self.properties_frame.configure(bg=p["toolbar_bg"])
        self.properties_content.configure(bg=p["toolbar_bg"])
        self.properties_secondary.configure(bg=p["toolbar_bg"])
        self.status_lbl.configure(bg=p["toolbar_bg"], fg=p["muted_text"])
        self.canvas.configure(bg="#FCFDFE" if self.app.theme == "light" else "#252B33")
        self._icon_images.clear()
        for name, button in self.tool_buttons.items():
            for selected in (False, True):
                ink = "#FFFFFF" if selected else p["text"]
                self._icon_images[(name, selected)] = self._make_icon(name, ink)
        self._icon_images[("paste", False)] = self._make_icon("paste", p["text"])
        if self._icon_images[("paste", False)]:
            self.paste_btn.configure(image=self._icon_images[("paste", False)], text="")
        else:
            self.paste_btn.configure(text="Pegar")
        for btn in (self.paste_btn, self.properties_toggle, self.undo_btn,
                    self.redo_btn, self.export_btn, self.zoom_minus, self.zoom_plus):
            btn.configure(fg=p["text"], bg=p["button_bg"], activebackground=p["button_hover"])
        for btn, name in ((self.undo_btn, "undo"), (self.redo_btn, "redo"),
                          (self.zoom_minus, "minus"), (self.zoom_plus, "plus"),
                          (self.export_btn, "export")):
            img = get_icon(self, name, p["text"], 16)
            fallback = {"undo": "<", "redo": ">", "minus": "-", "plus": "+", "export": "PNG"}[name]
            if name == "export":
                btn.configure(image=img or "", text=" PNG" if img else "PNG")
            else:
                btn.configure(image=img or "", text="" if img else fallback)
        self._paint_options_toggle()
        self.zoom_label.configure(fg=p["text"], bg=p["toolbar_bg"])
        self._update_tool_buttons()
        self._refresh_properties()
        self._paint_cache.clear()
        self._render()

    def _paint_options_toggle(self):
        p = self.app.palette()
        icon = "chevron_up" if self._props_open else "chevron_down"
        img = get_icon(self, icon, p["text"], 14)
        self.properties_toggle.configure(image=img or "",
                                         text="Opciones " if img else "Opciones")

    def _update_tool_buttons(self):
        p = self.app.palette()
        for name, btn in self.tool_buttons.items():
            active = name == self.tool
            image = self._icon_images.get((name, active))
            btn.configure(image=image if image else "",
                          text="" if image else name[:1].upper(),
                          bg=p["accent"] if active else p["button_bg"],
                          fg="#FFFFFF" if active else p["text"],
                          activebackground=p["accent"] if active else p["button_hover"])
        self.canvas.configure(cursor={"pen": "pencil", "connect": "crosshair",
                                      "node": "crosshair"}.get(self.tool, "arrow"))

    def set_tool(self, tool):
        if tool == "image":
            self.import_image()
            return
        if tool not in ("select", "node", "pen", "connect"):
            return
        self._finish_edit()
        self.tool = tool
        self.pending_connection = None
        descriptions = {
            "select": "Seleccionar: arrastra una zona vac\u00eda para marcar varios; Shift+clic a\u00f1ade o quita.",
            "node": "Haz clic en el lienzo para crear un nodo con texto.",
            "pen": "L\u00e1piz: dibuja sobre nodos y flechas; puedes cambiar color y grosor.",
            "connect": "Conectar: haz clic en un nodo de origen y luego en el de destino.",
        }
        self.status_text.set(descriptions[tool])
        self._update_tool_buttons()
        self._refresh_properties()
        self._render()

    # ------------------------ contextual properties ----------------------
    def _single(self):
        return next(iter(self.selection)) if len(self.selection) == 1 else None

    def _context(self):
        if self.tool in ("node", "pen", "connect"):
            return self.tool
        if len(self.selection) > 1:
            return "multi"
        target = self._single()
        if target:
            if target[0] == "obj":
                obj = self._item_by_id(target[1])
                return "image" if obj and obj.get("type") == "image" else "node"
            if target[0] == "stroke":
                return "pen"
            if target[0] == "edge":
                return "connect"
        return "select"

    def _style_target(self, context):
        defaults = {"node": self.node_defaults, "pen": self.pen_style,
                    "connect": self.edge_style}
        # Choosing a creation/drawing tool edits its FUTURE style, not the
        # previously selected object's properties.
        if self.tool == context and context in defaults:
            return defaults[context]
        target = self._single()
        if target:
            kind, uid = target
            if context == "node" and kind == "obj":
                obj = self._item_by_id(uid)
                if obj and obj.get("type") != "image":
                    return obj
            if context == "pen" and kind == "stroke":
                return next((s for s in self.strokes if s.get("id") == uid), None)
            if context == "connect" and kind == "edge":
                return next((e for e in self.connections if e.get("id") == uid), None)
        return defaults.get(context, {})

    def _panel_label(self, parent, text, weight="normal"):
        p = self.app.palette()
        label = tk.Label(parent, text=text, font=("Segoe UI", 9, weight),
                         bg=p["toolbar_bg"], fg=p["text"])
        label.pack(side="left", padx=(5, 4))
        return label

    def _panel_btn(self, parent, text, callback, selected=False, width=None, tooltip=None,
                   icon=None):
        p = self.app.palette()
        kw = dict(text=text, command=callback, bd=0, relief="flat", cursor="hand2",
                  font=("Segoe UI", 9), padx=7, pady=3,
                  bg=p["accent"] if selected else p["button_bg"],
                  fg="#FFFFFF" if selected else p["text"],
                  activebackground=p["button_hover"])
        if icon:
            img = get_icon(self, icon, "#FFFFFF" if selected else p["text"], 14)
            if img is not None:
                kw.update(image=img, text="", padx=5, pady=4)
        if width:
            kw["width"] = width
        btn = tk.Button(parent, **kw)
        btn.pack(side="left", padx=2)
        if tooltip:
            HoverTip(btn, tooltip)
        return btn

    def _color_dropdown(self, parent, caption, current, kind, context):
        self._panel_label(parent, caption)
        # Keep the exact target that belongs to this menu. If the selection
        # changes before the queued callback runs, never recolor a new object.
        target = self._style_target(context)
        arrow = get_icon(self, "chevron_down", _ink_on(current), 14)
        btn = tk.Menubutton(parent, text="" if arrow else "v", image=arrow or "",
                            width=34 if arrow else 4, relief="flat", bd=1,
                            bg=current, fg=_ink_on(current), cursor="hand2",
                            activebackground=current, font=("Segoe UI", 9))
        btn.pack(side="left", padx=(0, 8), ipady=2)
        menu = tk.Menu(btn, tearoff=0)
        choices = BOARD_COLORS if kind == "fill" else INK_COLORS
        for name, color in choices:
            # Windows' native Tk menus can crash if their own parent button
            # is destroyed from the menu command. Finish the native menu
            # event first, then change the value, and rebuild later.
            menu.add_command(
                label=name, background=color, foreground=_ink_on(color),
                command=lambda c=color, t=target: self.after(
                    10, self._change_color, context, kind, c, t))
        menu.add_separator()
        menu.add_command(
            label="Personalizado...",
            command=lambda t=target: self.after(10, self._choose_color, context, kind, t))
        btn.configure(menu=menu)
        HoverTip(btn, f"{caption}: {current}. Pulsa para elegir color")

    def _change_color(self, context, key, value, target=None):
        if target is None:
            target = self._style_target(context)
        if not target or target.get(key) == value:
            return
        is_default = any(target is default for default in
                         (self.node_defaults, self.pen_style, self.edge_style))
        if not is_default:
            self._checkpoint()
        old = target.get(key)
        target[key] = value
        if context == "node" and key == "fill":
            if target.get("text_color", _ink_on(old)) == _ink_on(old):
                target["text_color"] = _ink_on(value)
        self._changed()

    def _choose_color(self, context, key, target=None):
        if target is None:
            target = self._style_target(context)
        old = target.get(key, "#263244")
        color = ui.ask_color(self.app, old, "Elegir color")
        if color:
            self._change_color(context, key, color, target)

    def _set_property(self, context, key, value):
        target = self._style_target(context)
        if not target or target.get(key) == value:
            return
        is_default = target in (self.node_defaults, self.pen_style, self.edge_style)
        if not is_default:
            self._finish_edit()  # commit rich text before changing node-wide properties
            self._checkpoint()
        target[key] = value
        if context == "node" and key in STYLE_FIELDS.values() and not is_default:
            # Node-wide toolbar formatting remains available when NOT editing.
            # Keep text_runs consistent: otherwise older mixed styles would
            # silently override the new whole-node setting in the preview.
            attr = next(short for short, long in STYLE_FIELDS.items() if long == key)
            runs = _node_text_runs(target)
            for run in runs:
                run[attr] = bool(value)
            target["text_runs"] = _merge_text_runs(runs)
        self._changed()

    def _editor_selection_has_style(self, field):
        if self._editor is None or field not in STYLE_FIELDS.values():
            return None
        editor, _ = self._editor
        if not editor.winfo_exists() or not editor.tag_ranges("sel"):
            return None
        start, end = editor.index("sel.first"), editor.index("sel.last")
        bit = next(short for short, long in STYLE_FIELDS.items() if long == field)
        current = start
        while editor.compare(current, "<", end):
            if not self._editor_char_style(editor, current)[STYLE_ORDER.index(bit)]:
                return False
            current = editor.index(f"{current}+1c")
        return True

    def _toggle_node_style(self, field):
        if self._editor is not None:
            editor, obj_id = self._editor
            if not editor.winfo_exists() or not editor.tag_ranges("sel"):
                self.status_text.set("Selecciona primero las palabras que quieres formatear.")
                return
            short = next(short for short, long in STYLE_FIELDS.items() if long == field)
            start, end = editor.index("sel.first"), editor.index("sel.last")
            desired = not bool(self._editor_selection_has_style(field))
            cursor = start
            while editor.compare(cursor, "<", end):
                next_cursor = editor.index(f"{cursor}+1c")
                bits = list(self._editor_char_style(editor, cursor))
                bits[STYLE_ORDER.index(short)] = desired
                for tag in self._editor_fonts:
                    editor.tag_remove(tag, cursor, next_cursor)
                editor.tag_add(_style_name(bits), cursor, next_cursor)
                cursor = next_cursor
            editor.focus_set()
            editor.tag_add("sel", start, end)
            self._schedule_properties_refresh()
            self.status_text.set("Formato aplicado a la selecci\u00f3n. Ctrl+Enter para guardar.")
            return
        obj = self._style_target("node")
        self._set_property("node", field, not bool(obj.get(field, False)))

    def _schedule_properties_refresh(self):
        """Refresh after Tk has finished the active menu/combobox/button event.

        Destroying the current dropdown inside its own callback can terminate
        Tk on Windows, especially with native menus in a frozen executable.
        """
        if self._properties_refresh_job is not None:
            self.after_cancel(self._properties_refresh_job)
        self._properties_refresh_job = self.after(75, self._deferred_properties_refresh)

    def _deferred_properties_refresh(self):
        self._properties_refresh_job = None
        if self.winfo_exists():
            self._refresh_properties()

    def _refresh_properties(self):
        if not hasattr(self, "properties_content"):
            return
        if self._properties_refresh_job is not None:
            self.after_cancel(self._properties_refresh_job)
            self._properties_refresh_job = None
        for widget in self.properties_content.winfo_children():
            widget.destroy()
        for widget in self.properties_secondary.winfo_children():
            widget.destroy()
        self.properties_secondary.pack_forget()
        context = self._context()
        target = self._style_target(context)
        content = self.properties_content
        p = self.app.palette()
        self._panel_label(content, {"node": "NODO", "pen": "L\u00c1PIZ",
                                    "connect": "CONEXI\u00d3N", "image": "IMAGEN",
                                    "multi": "SELECCI\u00d3N", "select": "SELECCIONAR"}[context], "bold")
        if context == "node":
            self._color_dropdown(content, "Fondo", target.get("fill", "#FFE596"), "fill", context)
            self._color_dropdown(content, "Texto", target.get("text_color", "#182434"), "text_color", context)
            families = ["Segoe UI", "Arial", "Calibri", "Consolas", "Tahoma", "Georgia", "Verdana"]
            self._panel_label(content, "Fuente")
            family = ttk.Combobox(content, width=12, state="readonly", values=families)
            family.set(target.get("font_family", "Segoe UI"))
            family.pack(side="left", padx=(0, 5))
            family.bind("<<ComboboxSelected>>", lambda e: self._set_property("node", "font_family", family.get()))
            self._panel_label(content, "Pt")
            sizes = tuple(str(i) for i in (8, 9, 10, 11, 12, 13, 14, 15, 16, 18, 20, 22, 24, 28, 32, 36, 44, 52, 60, 72))
            size = ttk.Combobox(content, width=3, values=sizes)
            size.set(str(target.get("font_size", 15)))
            size.pack(side="left", padx=(0, 7))
            def submit_size(e=None):
                try:
                    n = int(size.get())
                except ValueError:
                    return
                self._set_property("node", "font_size", max(8, min(72, n)))
            size.bind("<<ComboboxSelected>>", submit_size)
            size.bind("<Return>", submit_size)
            size.bind("<FocusOut>", submit_size)
            self.properties_secondary.pack(side="top", fill="x", padx=11, pady=(0, 5))
            self._panel_label(self.properties_secondary, "Estilo")
            for prop, text, tip in (("bold", "B", "Negrita"),
                                     ("italic", "I", "Cursiva"),
                                     ("underline", "U", "Subrayado"),
                                     ("strike", "S", "Tachado")):
                active = self._editor_selection_has_style(prop)
                if active is None:
                    active = bool(target.get(prop, False))
                self._panel_btn(self.properties_secondary, text,
                                lambda key=prop: self._toggle_node_style(key),
                                active, tooltip=tip + " (selecciona palabras durante la edici\u00f3n)")
            if self._editor is not None:
                self._panel_label(self.properties_secondary, "Selecciona palabras para darles formato")
            self._panel_label(self.properties_secondary, "Alineaci\u00f3n")
            for align, character in (("left", "Izq"), ("center", "Cen"), ("right", "Der")):
                self._panel_btn(self.properties_secondary, character,
                                lambda a=align: self._set_property("node", "align", a),
                                target.get("align", "left") == align,
                                tooltip="Alinear " + {"left": "izquierda", "center": "centro", "right": "derecha"}[align],
                                icon="align_" + align)
        elif context in ("pen", "connect"):
            self._color_dropdown(content, "Color", target.get("color", "#263244"), "color", context)
            self._panel_label(content, "Grosor")
            sizes = tuple(str(i) for i in range(1, 17))
            size = ttk.Combobox(content, values=sizes, width=4)
            size.set(str(round(target.get("width", 3), 1)))
            size.pack(side="left", padx=(0, 10))
            def submit_width(e=None):
                try:
                    n = float(size.get().replace(",", "."))
                except ValueError:
                    return
                self._set_property(context, "width", max(1., min(24., n)))
            size.bind("<<ComboboxSelected>>", submit_width)
            size.bind("<Return>", submit_width)
            size.bind("<FocusOut>", submit_width)
            self._panel_label(content, "Dibuja por encima de los nodos" if context == "pen"
                              else "Flechas adaptadas al mover los nodos")
        elif context == "image":
            self._panel_btn(content, "Abrir archivo", self.import_image)
            self._panel_btn(content, "Pegar (Ctrl+V)", self.paste_image)
            self._panel_label(content, "Arrastra para mover o cambia su tama\u00f1o desde la esquina")
        elif context == "multi":
            self._panel_label(content, f"{len(self.selection)} elementos seleccionados. Arrastra para moverlos juntos.")
            self._panel_btn(content, "Eliminar selecci\u00f3n", self.delete_selected)
        else:
            self._panel_label(content, "Arrastra un rect\u00e1ngulo en el espacio vac\u00edo para seleccionar varios elementos.")
            self._panel_btn(content, "Pegar imagen", self.paste_image)

    # ------------------------------ state ---------------------------------
    def _snapshot(self):
        return copy.deepcopy({"items": self.items, "connections": self.connections,
                              "strokes": self.strokes})

    def _checkpoint(self, before=None):
        self._undo.append(before if before is not None else self._snapshot())
        if len(self._undo) > 80:
            del self._undo[:-80]
        self._redo.clear()

    def _changed(self):
        self._paint_cache.clear() if len(self._paint_cache) > 250 else None
        self._render()
        self._schedule_properties_refresh()
        self.app.schedule_save()

    def undo(self):
        self._finish_edit()
        if not self._undo:
            return
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())

    def redo(self):
        self._finish_edit()
        if not self._redo:
            return
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())

    def _restore(self, state):
        self.items = copy.deepcopy(state["items"])
        self.strokes = copy.deepcopy(state["strokes"])
        self.connections = copy.deepcopy(state["connections"])
        self._set_selection(set(), render=False)
        self.pending_connection = None
        self._changed()

    def to_dict(self):
        # Autosave must never close the live Text editor while someone types
        # or selects words. Serialize an in-progress edit into a temporary
        # snapshot; _finish_edit creates the undo checkpoint on actual exit.
        items = copy.deepcopy(self.items)
        if self._editor is not None:
            editor, obj_id = self._editor
            if editor.winfo_exists():
                for obj in items:
                    if obj.get("id") == obj_id:
                        obj["text"] = editor.get("1.0", "end-1c")
                        obj["text_runs"] = self._extract_editor_runs(editor)
                        break
        return {"zoom": self.zoom, "items": items,
                "connections": copy.deepcopy(self.connections),
                "strokes": copy.deepcopy(self.strokes),
                "defaults": {"node": copy.deepcopy(self.node_defaults),
                             "pen": copy.deepcopy(self.pen_style),
                             "connect": copy.deepcopy(self.edge_style)}}

    def load(self, data):
        self._finish_edit(commit=False)
        data = data if isinstance(data, dict) else {}
        self.items = copy.deepcopy(data.get("items", [])) if isinstance(data.get("items", []), list) else []
        self.connections = copy.deepcopy(data.get("connections", [])) if isinstance(data.get("connections", []), list) else []
        self.strokes = copy.deepcopy(data.get("strokes", [])) if isinstance(data.get("strokes", []), list) else []
        self.zoom = max(.4, min(2.5, _number(data.get("zoom", 1), 1)))
        defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
        self.node_defaults = {**self.DEFAULT_NODE, **(defaults.get("node") or {})}
        self.pen_style = {**self.DEFAULT_PEN, **(defaults.get("pen") or {})}
        self.edge_style = {**self.DEFAULT_EDGE, **(defaults.get("connect") or {})}
        self._set_selection(set(), render=False)
        self._image_cache.clear()
        self._paint_cache.clear()
        self._font_cache.clear()
        self.pending_connection = None
        self._undo.clear()
        self._redo.clear()
        self.zoom_label.configure(text=f"{round(self.zoom * 100)}%")
        self._refresh_properties()
        self._render()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _item_by_id(self, obj_id):
        return next((o for o in self.items if o.get("id") == obj_id), None)

    def _set_selection(self, selection, render=True):
        self.selection = set(selection)
        self.selected = self._single()
        if render:
            self._refresh_properties()
            self._render()

    def _world(self, event):
        return self.canvas.canvasx(event.x) / self.zoom, self.canvas.canvasy(event.y) / self.zoom

    def _hit(self, event):
        x, y = self._world(event)
        p = (x, y)
        tolerance = 6 / self.zoom
        one = self._single()
        if one and one[0] == "obj":
            obj = self._item_by_id(one[1])
            if obj and self._is_resize_grip(event, obj):
                return one
        # Ink is the topmost layer, followed by objects and then connectors.
        for stroke in reversed(self.strokes):
            points = stroke.get("points", [])
            size = max(5, _number(stroke.get("width", 3)) / 2 + tolerance)
            if any(_distance_to_segment(p, a, b) <= size for a, b in zip(points, points[1:])):
                return "stroke", stroke["id"]
        for obj in reversed(self.items):
            ox, oy = obj["x"], obj["y"]
            if ox <= x <= ox+obj["w"] and oy <= y <= oy+obj["h"]:
                return "obj", obj["id"]
        index = {o["id"]: o for o in self.items}
        for edge in reversed(self.connections):
            a, b = index.get(edge.get("from")), index.get(edge.get("to"))
            if a and b and _distance_to_segment(p, _anchor_toward(a, b), _anchor_toward(b, a)) <= tolerance + edge.get("width", 3):
                return "edge", edge["id"]
        return None

    def _is_resize_grip(self, event, item):
        x, y = self._world(event)
        return (abs(x-(item["x"]+item["w"])) < 14 / self.zoom and
                abs(y-(item["y"]+item["h"])) < 14 / self.zoom)

    def _add_box(self, kind, x, y):
        # Historical 'text' objects can still be opened and edited as nodes.
        self._checkpoint()
        obj = {"id": _id(), "type": "node", "x": round(max(0, x), 1),
               "y": round(max(0, y), 1), "w": 235, "h": 139,
               "text": "Nuevo nodo", **copy.deepcopy(self.node_defaults)}
        self.items.append(obj)
        self._set_selection({("obj", obj["id"])}, render=False)
        self.tool = "select"
        self._update_tool_buttons()
        self._changed()
        self.after(80, lambda uid=obj["id"]: self._start_inline_edit(self._item_by_id(uid))
                   if self._item_by_id(uid) else None)
        return obj

    def _on_press(self, event):
        self._finish_edit()
        self.canvas.focus_set()
        x, y = self._world(event)
        hit = self._hit(event)
        self._drag = None
        if self.tool == "node":
            self._add_box("node", x, y)
            return "break"
        if self.tool == "pen":
            self._draft_stroke = {"id": _id(), "color": self.pen_style["color"],
                                  "width": self.pen_style["width"], "points": [[x, y]]}
            self._render()
            return "break"
        if self.tool == "connect":
            if hit and hit[0] == "obj":
                clicked = hit[1]
                if self.pending_connection and self.pending_connection != clicked:
                    if not any(e.get("from") == self.pending_connection and e.get("to") == clicked
                               for e in self.connections):
                        self._checkpoint()
                        self.connections.append({"id": _id(), "from": self.pending_connection,
                                                 "to": clicked, **copy.deepcopy(self.edge_style)})
                        self._changed()
                    self.pending_connection = None
                    self.status_text.set("Conexi\u00f3n creada. Selecciona otros dos nodos para conectar.")
                else:
                    self.pending_connection = clicked
                    self.status_text.set("Elige el nodo de destino (Esc cancela).")
                self._set_selection({("obj", clicked)})
            return "break"

        additive = bool(event.state & 0x0001)  # Shift+click
        if not hit:
            if not additive:
                self._set_selection(set(), render=False)
            self._marquee = {"start": (x, y), "end": (x, y),
                             "base": set(self.selection), "additive": additive, "moved": False}
            self._refresh_properties()
            self._render()
            return "break"
        if additive:
            new_selection = set(self.selection)
            if hit in new_selection:
                new_selection.remove(hit)
            else:
                new_selection.add(hit)
            self._set_selection(new_selection)
            return "break"
        if hit not in self.selection:
            self._set_selection({hit}, render=False)
        obj = self._item_by_id(hit[1]) if hit[0] == "obj" else None
        resize = obj and len(self.selection) == 1 and self._is_resize_grip(event, obj)
        self._drag = {"hit": hit, "mode": "resize" if resize else "move",
                      "last": (x, y), "before": self._snapshot(), "moved": False,
                      "start_positions": {o["id"]: (o["x"], o["y"]) for o in self.items}}
        self._refresh_properties()
        self._render()
        return "break"

    def _on_motion(self, event):
        x, y = self._world(event)
        if self._draft_stroke is not None:
            points = self._draft_stroke["points"]
            if math.hypot(x-points[-1][0], y-points[-1][1]) >= 1.2:
                points.append([round(x, 1), round(y, 1)])
                self._render()
            return "break"
        if self._marquee is not None:
            self._marquee["end"] = (x, y)
            if math.hypot(x-self._marquee["start"][0], y-self._marquee["start"][1]) >= 3/self.zoom:
                self._marquee["moved"] = True
            self._render()
            return "break"
        if self._drag is None:
            return
        drag = self._drag
        dx, dy = x-drag["last"][0], y-drag["last"][1]
        if abs(dx) + abs(dy) < .01:
            return
        kind, uid = drag["hit"]
        if drag["mode"] == "resize" and kind == "obj":
            obj = self._item_by_id(uid)
            if obj:
                obj["w"] = max(MIN_BOX_W, round(obj["w"]+dx, 1))
                obj["h"] = max(MIN_BOX_H, round(obj["h"]+dy, 1))
                if obj.get("type") == "image":
                    self._image_cache.clear()
        elif kind in ("obj", "stroke"):
            for skind, sid in self.selection:
                if skind == "obj":
                    obj = self._item_by_id(sid)
                    if obj:
                        obj["x"] = max(0, round(obj["x"]+dx, 1))
                        obj["y"] = max(0, round(obj["y"]+dy, 1))
                elif skind == "stroke":
                    stroke = next((s for s in self.strokes if s.get("id") == sid), None)
                    if stroke:
                        stroke["points"] = [[round(px+dx, 1), round(py+dy, 1)]
                                            for px, py in stroke["points"]]
        drag["last"] = (x, y)
        drag["moved"] = True
        self._render()
        return "break"

    def _targets_in_rectangle(self, rectangle):
        result = set()
        for obj in self.items:
            if _rect_intersects(rectangle,
                                (obj["x"], obj["y"], obj["x"]+obj["w"], obj["y"]+obj["h"])):
                result.add(("obj", obj["id"]))
        for stroke in self.strokes:
            points = stroke.get("points", [])
            if points and _rect_intersects(rectangle,
                                           (min(x for x, _ in points), min(y for _, y in points),
                                            max(x for x, _ in points), max(y for _, y in points))):
                result.add(("stroke", stroke["id"]))
        index = {o["id"]: o for o in self.items}
        for edge in self.connections:
            a, b = index.get(edge.get("from")), index.get(edge.get("to"))
            if a and b:
                p1, p2 = _anchor_toward(a, b), _anchor_toward(b, a)
                if _rect_intersects(rectangle,
                                    (min(p1[0], p2[0]), min(p1[1], p2[1]),
                                     max(p1[0], p2[0]), max(p1[1], p2[1]))):
                    result.add(("edge", edge["id"]))
        return result

    def _on_release(self, event):
        if self._draft_stroke is not None:
            stroke = self._draft_stroke
            self._draft_stroke = None
            if len(stroke["points"]) == 1:
                x, y = stroke["points"][0]
                stroke["points"].append([x+.2, y+.2])
            self._checkpoint()
            self.strokes.append(stroke)
            self._changed()
        if self._marquee is not None:
            marquee = self._marquee
            self._marquee = None
            if marquee["moved"]:
                a, b = marquee["start"], marquee["end"]
                bounds = (min(a[0], b[0]), min(a[1], b[1]),
                          max(a[0], b[0]), max(a[1], b[1]))
                found = self._targets_in_rectangle(bounds)
                self._set_selection(found | marquee["base"] if marquee["additive"] else found)
            else:
                self._refresh_properties()
                self._render()
        if self._drag is not None:
            if self._drag["moved"] and self._drag["before"] != self._snapshot():
                self._checkpoint(self._drag["before"])
                self.app.schedule_save()
            self._drag = None
            self._render()
        return "break"

    # ------------------------ editing and actions ------------------------
    def _on_double(self, event):
        hit = self._hit(event)
        if hit and hit[0] == "obj":
            obj = self._item_by_id(hit[1])
            if obj and obj.get("type") != "image":
                self._start_inline_edit(obj)
        return "break"

    def _node_style(self, obj):
        return {**self.DEFAULT_NODE, **{k: obj.get(k, v) for k, v in self.DEFAULT_NODE.items()}}

    def _font(self, obj, zoom=None, state=None):
        style = self._node_style(obj)
        if state is not None:
            style.update({name: bool(value) for name, value in zip(STYLE_FIELDS.values(), state)})
        z = self.zoom if zoom is None else zoom
        key = (style["font_family"], max(8, round(style["font_size"]*z)),
               bool(style["bold"]), bool(style["italic"]),
               bool(style["underline"]), bool(style["strike"]))
        if key not in self._font_cache:
            self._font_cache[key] = tkfont.Font(
                root=self.app, family=key[0], size=key[1],
                weight="bold" if key[2] else "normal",
                slant="italic" if key[3] else "roman",
                underline=key[4], overstrike=key[5])
            if len(self._font_cache) > 200:
                self._font_cache = {key: self._font_cache[key]}
        return self._font_cache[key]

    @staticmethod
    def _visible_text(text, font, available_width, available_height):
        """Clip only the canvas preview, never the saved/edited full text."""
        if not text:
            return ""
        line_height = max(1, font.metrics("linespace") + 2)
        max_lines = max(1, int(available_height / line_height))
        lines = []
        for paragraph in text.split("\n"):
            if not paragraph:
                lines.append("")
                continue
            current = ""
            for word in paragraph.split(" "):
                trial = (current + " " + word).strip()
                if current and font.measure(trial) > available_width:
                    lines.append(current)
                    current = word
                else:
                    current = trial
                # Split unusually long single words as a last resort.
                while font.measure(current) > available_width and len(current) > 1:
                    chars = len(current)-1
                    while chars > 1 and font.measure(current[:chars]) > available_width:
                        chars -= 1
                    lines.append(current[:chars])
                    current = current[chars:]
            lines.append(current)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            end = lines[-1].rstrip() + "..."
            while len(end) > 3 and font.measure(end) > available_width:
                end = end[:-4] + "..."
            lines[-1] = end
        return "\n".join(lines)

    @staticmethod
    def _editor_char_style(editor, idx):
        for tag in editor.tag_names(idx):
            if tag.startswith("style_") and len(tag) == 10 and set(tag[6:]) <= {"0", "1"}:
                return tuple(char == "1" for char in tag[6:])
        return tuple(bool(v) for v in getattr(editor, "_default_bits", (False,)*4))

    def _extract_editor_runs(self, editor):
        full_text = editor.get("1.0", "end-1c")
        runs = []
        start = "1.0"
        for ch in full_text:
            bits = self._editor_char_style(editor, start)
            runs.append({"text": ch, **dict(zip(STYLE_ORDER, bits))})
            start = editor.index(f"{start}+1c")
        return _merge_text_runs(runs)

    def _start_inline_edit(self, obj):
        if not obj or obj not in self.items or obj.get("type") == "image":
            return
        self._finish_edit()
        self._set_selection({("obj", obj["id"])}, render=False)
        self._refresh_properties()
        self._render()
        x = obj["x"]*self.zoom - self.canvas.canvasx(0) + 6
        y = obj["y"]*self.zoom - self.canvas.canvasy(0) + 6
        fill = obj.get("fill", "#FFE596")
        color = obj.get("text_color") or _ink_on(fill)
        editor = tk.Text(self.canvas, wrap="word", undo=True, bd=0, relief="flat",
                         font=self._font(obj), bg=fill, fg=color, insertbackground=color,
                         exportselection=False, padx=8, pady=6, spacing1=0, spacing3=1)
        editor._default_bits = _style_tuple(obj)
        editor._font_refs = []  # keep tag fonts alive if cache is pruned
        self._editor_fonts = []
        for mask in range(16):
            bits = tuple(bool(mask & (1 << (3-i))) for i in range(4))
            tag = _style_name(bits)
            font_obj = self._font(obj, state=bits)
            editor._font_refs.append(font_obj)
            editor.tag_configure(tag, font=font_obj)
            self._editor_fonts.append(tag)
        for run in _node_text_runs(obj):
            editor.insert("end-1c", run["text"], (_style_name(_style_tuple(run)),))
        editor.tag_configure("align", justify=obj.get("align", "left"))
        editor.tag_add("align", "1.0", "end")
        editor.place(x=max(0, round(x)), y=max(0, round(y)),
                     width=max(100, round(obj["w"]*self.zoom-12)),
                     height=max(50, round(obj["h"]*self.zoom-12)))
        self._editor = (editor, obj["id"])
        editor.bind("<Control-Return>", lambda e: (self._finish_edit(), "break")[1])
        editor.bind("<Escape>", lambda e: (self._finish_edit(commit=False), "break")[1])
        for sequence, field in (("<Control-b>", "bold"), ("<Control-i>", "italic"),
                                ("<Control-u>", "underline"), ("<Control-Shift-S>", "strike")):
            editor.bind(sequence, lambda e, attr=field: (self._toggle_node_style(attr), "break")[1])
        editor.bind("<ButtonRelease-1>", lambda e: self._schedule_properties_refresh())
        editor.bind("<KeyRelease>", lambda e: self._schedule_properties_refresh())
        # Do not close on FocusOut: clicking B/I/U/S or a dropdown must keep
        # the selected text and its Tk tags alive. Clicking the canvas, a new
        # tool, switching projects/tabs, or saving commits the edit.
        editor.focus_set()
        self._refresh_properties()
        self.status_text.set("Edita y selecciona palabras para B/I/U/S; Ctrl+Enter guarda, Esc cancela.")

    def _finish_edit(self, commit=True):
        if self._editor is None:
            return
        editor, obj_id = self._editor
        self._editor = None
        obj = self._item_by_id(obj_id)
        if editor.winfo_exists():
            text = editor.get("1.0", "end-1c")
            runs = self._extract_editor_runs(editor)
            editor.destroy()
        else:
            text, runs = "", []
        self._editor_fonts = []
        if commit and obj and (text != obj.get("text", "") or runs != _node_text_runs(obj)):
            self._checkpoint()
            obj["text"] = text  # old format readers still see the same plain text
            obj["text_runs"] = runs
            self._changed()
        else:
            self._render()
        self._schedule_properties_refresh()

    def delete_selected(self):
        self._finish_edit()
        targets = set(self.selection)
        if not targets:
            return
        self._checkpoint()
        deleted_obj = {uid for kind, uid in targets if kind == "obj"}
        deleted_strokes = {uid for kind, uid in targets if kind == "stroke"}
        deleted_edges = {uid for kind, uid in targets if kind == "edge"}
        self.items = [o for o in self.items if o["id"] not in deleted_obj]
        self.strokes = [s for s in self.strokes if s["id"] not in deleted_strokes]
        self.connections = [e for e in self.connections
                            if e["id"] not in deleted_edges and e.get("from") not in deleted_obj
                            and e.get("to") not in deleted_obj]
        self.pending_connection = None
        self._set_selection(set(), render=False)
        self._changed()

    def _delete_target(self, hit):
        if hit:
            self._set_selection({hit}, render=False)
            self.delete_selected()

    def _duplicate_selected(self):
        objects = [self._item_by_id(uid) for kind, uid in self.selection if kind == "obj"]
        objects = [o for o in objects if o]
        if not objects:
            return
        self._checkpoint()
        added = set()
        for obj in objects:
            new = copy.deepcopy(obj)
            new["id"] = _id()
            new["x"] += 35
            new["y"] += 35
            self.items.append(new)
            added.add(("obj", new["id"]))
        self._set_selection(added, render=False)
        self._changed()

    def _bring_to_front(self):
        picked = [o for o in self.items if ("obj", o["id"]) in self.selection]
        if not picked:
            return
        self._checkpoint()
        self.items = [o for o in self.items if o not in picked] + picked
        self._changed()

    def _context_menu(self, event):
        hit = self._hit(event)
        if hit and hit not in self.selection:
            self._set_selection({hit})
        elif not hit:
            self._set_selection(set())
        menu = tk.Menu(self, tearoff=False)
        x, y = self._world(event)
        if hit:
            obj = self._item_by_id(hit[1]) if hit[0] == "obj" else None
            if obj and obj.get("type") != "image":
                menu.add_command(label="Editar texto", command=lambda: self._start_inline_edit(obj))
            if obj:
                menu.add_command(label="Duplicar", command=self._duplicate_selected)
                menu.add_command(label="Traer delante", command=self._bring_to_front)
            menu.add_separator()
            menu.add_command(label=f"Eliminar ({len(self.selection)})", command=self.delete_selected)
        else:
            menu.add_command(label="Crear nodo aqu\u00ed", command=lambda: self._add_box("node", x, y))
            menu.add_command(label="Insertar imagen", command=lambda: self.import_image(at=(x, y)))
            menu.add_command(label="Pegar imagen (Ctrl+V)", command=lambda: self.paste_image(at=(x, y)))
            if self.selection:
                menu.add_command(label="Eliminar selecci\u00f3n", command=self.delete_selected)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    # ------------------------- project images -----------------------------
    def _asset_path(self, relative):
        if not relative or not isinstance(relative, str):
            return None
        base = os.path.abspath(os.path.dirname(self.app.active_config_path))
        target = os.path.abspath(os.path.join(base, relative))
        try:
            if os.path.commonpath((base, target)) == base:
                return target
        except ValueError:
            pass
        return None

    def _save_asset_bytes(self, payload, ext=".png", original_name="imagen"):
        base = os.path.dirname(self.app.active_config_path)
        folder = os.path.join(base, "assets")
        os.makedirs(folder, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", original_name)[:28] or "imagen"
        filename = hashlib.sha256(payload).hexdigest()[:20] + "_" + safe + ext
        destination = os.path.join(folder, filename)
        if not os.path.exists(destination):
            temp = destination + ".writing"
            with open(temp, "wb") as stream:
                stream.write(payload)
            os.replace(temp, destination)
        return os.path.join("assets", filename).replace("\\", "/")

    def _copy_image_into_project(self, source):
        if Image is None:
            raise RuntimeError("Pillow es necesario para importar imagenes")
        with Image.open(source) as original:
            original.verify()
        with open(source, "rb") as stream:
            payload = stream.read()
        ext = os.path.splitext(source)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"):
            ext = ".png"
        return self._save_asset_bytes(payload, ext,
                                      os.path.splitext(os.path.basename(source))[0])

    def _insert_stored_image(self, relative, width, height, at=None):
        if at is None:
            at = (self.canvas.canvasx(self.canvas.winfo_width()/2) / self.zoom,
                  self.canvas.canvasy(self.canvas.winfo_height()/2) / self.zoom)
        factor = min(1.0, 330/max(1, width), 260/max(1, height))
        w, h = max(45, round(width*factor)), max(45, round(height*factor))
        self._checkpoint()
        obj = {"id": _id(), "type": "image", "x": round(max(0, at[0]-w/2), 1),
               "y": round(max(0, at[1]-h/2), 1), "w": w, "h": h,
               "asset": relative, "text": ""}
        self.items.append(obj)
        self.tool = "select"
        self._set_selection({("obj", obj["id"])}, render=False)
        self._update_tool_buttons()
        self._changed()
        return obj

    def import_image(self, at=None, filename=None):
        if filename is None:
            filename = ui.ask_open_filename(
                self.app, title="Insertar imagen en la pizarra",
                filetypes=[("Im\u00e1genes", "*.png *.jpg *.jpeg *.gif *.bmp *.webp *.tif *.tiff"),
                           ("Todos los archivos", "*.*")])
        if not filename:
            return None
        try:
            if Image is None:
                raise RuntimeError("Pillow no est\u00e1 instalado")
            with Image.open(filename) as original:
                w, h = original.size
            relative = self._copy_image_into_project(filename)
            return self._insert_stored_image(relative, w, h, at)
        except Exception as exc:
            ui.alert(self.app, "Imagen no incorporada", "No se pudo añadir la imagen.",
                     str(exc), "error")
            return None

    def paste_image(self, at=None, quiet=False):
        """Windows clipboard bitmap, copied file(s), or a path in the clipboard."""
        if Image is None or ImageGrab is None:
            if not quiet:
                self.status_text.set("Instala Pillow para pegar im\u00e1genes.")
            return None
        try:
            pasted = ImageGrab.grabclipboard()
        except (OSError, RuntimeError, NotImplementedError):
            pasted = None
        if isinstance(pasted, Image.Image):
            try:
                # PNG preserves transparency and avoids depending on original format.
                if pasted.width * pasted.height > 60_000_000:
                    raise ValueError("La imagen del portapapeles es demasiado grande")
                converted = pasted.convert("RGBA" if "A" in pasted.getbands() else "RGB")
                buffer = io.BytesIO()
                converted.save(buffer, format="PNG", optimize=True)
                relative = self._save_asset_bytes(buffer.getvalue(), ".png", "portapapeles")
                result = self._insert_stored_image(relative, pasted.width, pasted.height, at)
                self.status_text.set("Imagen pegada y copiada a assets/ del proyecto.")
                return result
            except (OSError, ValueError) as exc:
                ui.alert(self.app, "Pegar imagen", "No se pudo pegar la imagen.",
                         str(exc), "error")
                return None
        if isinstance(pasted, list):
            for path in pasted:
                if os.path.isfile(path):
                    result = self.import_image(at=at, filename=path)
                    if result:
                        return result
        try:
            text = self.app.clipboard_get().strip().strip('"')
            if os.path.isfile(text):
                return self.import_image(at=at, filename=text)
        except (tk.TclError, OSError):
            pass
        if not quiet:
            self.status_text.set("El portapapeles no contiene una imagen. Prueba copiando una captura o archivo.")
        return None

    def _image_for(self, obj):
        path = self._asset_path(obj.get("asset", ""))
        if not path or not os.path.isfile(path):
            return None
        w, h = max(1, round(obj["w"]*self.zoom)), max(1, round(obj["h"]*self.zoom))
        if w > 4000 or h > 4000:
            return None
        key = (path, w, h)
        if key in self._image_cache:
            return self._image_cache[key]
        try:
            if Image is not None:
                with Image.open(path) as original:
                    result = ImageTk.PhotoImage(
                        ImageOps.exif_transpose(original).convert("RGBA").resize(
                            (w, h), Image.Resampling.LANCZOS), master=self.canvas)
            else:
                result = tk.PhotoImage(file=path, master=self.canvas)
            if len(self._image_cache) > 70:
                self._image_cache.clear()
            self._image_cache[key] = result
            return result
        except (OSError, ValueError, tk.TclError):
            return None

    # -------------------------- clipboard -------------------------------
    def copy_selection(self):
        if not self.selection:
            return False
        objects = [copy.deepcopy(o) for o in self.items if ("obj", o["id"]) in self.selection]
        strokes = [copy.deepcopy(s) for s in self.strokes if ("stroke", s["id"]) in self.selection]
        obj_ids = {o["id"] for o in objects}
        edges = [copy.deepcopy(e) for e in self.connections
                 if ("edge", e["id"]) in self.selection or
                 (e.get("from") in obj_ids and e.get("to") in obj_ids)]
        self._internal_clipboard = (objects, strokes, edges, self.app.active_config_path)
        try:
            # A marker prevents an older external clipboard screenshot taking priority.
            self.app.clipboard_clear()
            self.app.clipboard_append("TablonK:seleccion")
        except tk.TclError:
            pass
        self.status_text.set("Selecci\u00f3n copiada. Ctrl+V para duplicar.")
        return True

    def _paste_internal(self):
        if not self._internal_clipboard:
            return None
        objects, strokes, edges, original_config = self._internal_clipboard
        if not (objects or strokes):
            return None
        self._checkpoint()
        mapping = {}
        picked = set()
        for original in objects:
            obj = copy.deepcopy(original)
            new_id = _id()
            mapping[obj["id"]] = new_id
            obj["id"] = new_id
            obj["x"] += 35
            obj["y"] += 35
            if obj.get("type") == "image" and original_config != self.app.active_config_path:
                old_base = os.path.abspath(os.path.dirname(original_config))
                source = os.path.abspath(os.path.join(old_base, original.get("asset", "")))
                try:
                    permitted = os.path.commonpath((old_base, source)) == old_base
                except ValueError:
                    permitted = False
                if permitted and os.path.isfile(source):
                    obj["asset"] = self._copy_image_into_project(source)
                else:
                    continue
            self.items.append(obj)
            picked.add(("obj", new_id))
        for old in strokes:
            stroke = copy.deepcopy(old)
            stroke["id"] = _id()
            stroke["points"] = [[x+35, y+35] for x, y in stroke.get("points", [])]
            self.strokes.append(stroke)
            picked.add(("stroke", stroke["id"]))
        for old in edges:
            if old.get("from") in mapping and old.get("to") in mapping:
                edge = copy.deepcopy(old)
                edge["id"] = _id()
                edge["from"], edge["to"] = mapping[old["from"]], mapping[old["to"]]
                self.connections.append(edge)
        self._set_selection(picked, render=False)
        self._changed()
        return picked

    def _focus_in_field(self, event):
        return isinstance(event.widget, (tk.Text, tk.Entry, tk.Spinbox,
                                         ttk.Entry, ttk.Combobox))

    def _shortcut_copy(self, event):
        if self.app.active_tab != "pizarra" or self._focus_in_field(event) or self._editor:
            return None
        return "break" if self.copy_selection() else None

    def _shortcut_paste(self, event):
        if self.app.active_tab != "pizarra" or self._focus_in_field(event) or self._editor:
            return None
        marker = False
        try:
            marker = self.app.clipboard_get() == "TablonK:seleccion"
        except tk.TclError:
            pass
        if marker and self._internal_clipboard:
            self._paste_internal()
        else:
            self.paste_image(quiet=False)
        return "break"

    def _shortcut_select_all(self, event):
        if self.app.active_tab != "pizarra" or self._focus_in_field(event) or self._editor:
            return None
        all_items = {("obj", o["id"]) for o in self.items}
        all_items.update(("stroke", s["id"]) for s in self.strokes)
        all_items.update(("edge", e["id"]) for e in self.connections)
        self._set_selection(all_items)
        return "break"

    def _shortcut_undo(self, event):
        if self.app.active_tab != "pizarra" or self._focus_in_field(event) or self._editor:
            return None
        self.undo()
        return "break"

    def _shortcut_redo(self, event):
        if self.app.active_tab != "pizarra" or self._focus_in_field(event) or self._editor:
            return None
        self.redo()
        return "break"

    def _shortcut_delete(self, event):
        if self.app.active_tab != "pizarra" or self._focus_in_field(event) or self._editor:
            return None
        self.delete_selected()
        return "break"

    def _shortcut_escape(self, event):
        if self.app.active_tab != "pizarra":
            return None
        if self._editor:
            self._finish_edit(commit=False)
        else:
            self.tool = "select"
            self.pending_connection = None
            self._drag = None
            self._marquee = None
            self._set_selection(set(), render=False)
            self._update_tool_buttons()
            self._refresh_properties()
            self._render()
        return "break"

    # -------------------------- antialiased drawing -----------------------
    def _draw_grid(self, world_w, world_h):
        z = self.zoom
        tone = "#E8EBF0" if self.app.theme == "light" else "#363D48"
        for x in range(0, round(world_w)+1, 100):
            self.canvas.create_line(x*z, 0, x*z, world_h*z, fill=tone, tags=("grid",))
        for y in range(0, round(world_h)+1, 100):
            self.canvas.create_line(0, y*z, world_w*z, y*z, fill=tone, tags=("grid",))

    def _aa_path(self, points, color, width, arrow=False, key=None):
        """Draw each line in a tight 3x Pillow buffer; canvas stays interactive.

        Tk canvas itself does not antialias create_line(), including arrowheads.
        A translucent PNG with supersampling fixes that at arbitrary zooms.
        """
        if Image is None or len(points) < 2:
            return None
        if key in self._paint_cache:
            return self._paint_cache[key]
        pad = max(14., width*2 + 3)
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        left, top = math.floor(min(xs)-pad), math.floor(min(ys)-pad)
        right, bottom = math.ceil(max(xs)+pad), math.ceil(max(ys)+pad)
        pixel_w, pixel_h = max(1, right-left), max(1, bottom-top)
        # Do not allocate a huge buffer for a single diagonal on a very big board.
        aa = 3 if pixel_w*pixel_h < 1_500_000 else 2 if pixel_w*pixel_h < 5_000_000 else 1
        high = Image.new("RGBA", (pixel_w*aa, pixel_h*aa), (0, 0, 0, 0))
        draw = ImageDraw.Draw(high)
        scaled = [((p[0]-left)*aa, (p[1]-top)*aa) for p in points]
        pen_width = max(1, round(width*aa))
        draw.line(scaled, fill=color, width=pen_width, joint="curve")
        circle_r = pen_width/2
        for x, y in (scaled[0], scaled[-1]):
            draw.ellipse((x-circle_r, y-circle_r, x+circle_r, y+circle_r), fill=color)
        if arrow:
            tip = _arrow_polygon(scaled[-2], scaled[-1], scale=aa)
            draw.polygon(tip, fill=color)
        if aa > 1:
            high = high.resize((pixel_w, pixel_h), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(high, master=self.canvas)
        result = (left, top, photo)
        if len(self._paint_cache) > 135:
            self._paint_cache.clear()
        self._paint_cache[key] = result
        return result

    def _rounded_box(self, obj):
        if Image is None:
            return None
        w = max(1, round(obj["w"]*self.zoom))
        h = max(1, round(obj["h"]*self.zoom))
        fill = obj.get("fill", "#FFE596")
        key = ("box", w, h, fill, self.app.theme)
        if key in self._paint_cache:
            return self._paint_cache[key]
        aa, shadow = 3, 7
        im = Image.new("RGBA", ((w+shadow)*aa, (h+shadow)*aa), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        radius = round(min(14*self.zoom, w/5, h/5)*aa)
        d.rounded_rectangle((3*aa, 4*aa, (w+3)*aa, (h+4)*aa),
                            radius=radius, fill=(0, 0, 0, 45 if self.app.theme == "light" else 88))
        d.rounded_rectangle((0, 0, w*aa-1, h*aa-1), radius=radius,
                            fill=fill, outline="#8794A3", width=max(1, aa))
        picture = ImageTk.PhotoImage(im.resize((w+shadow, h+shadow), Image.Resampling.LANCZOS),
                                     master=self.canvas)
        if len(self._paint_cache) > 135:
            self._paint_cache.clear()
        self._paint_cache[key] = picture
        return picture

    def _draw_node_text(self, canvas, obj, x, y, w, h, tags):
        """Render styled word spans on Tk Canvas, not one uniform text item."""
        z = self.zoom
        left, top, available_w = x+13*z, y+12*z, max(12, w-26*z)
        available_h = max(10, h-23*z)
        lines = _layout_rich_text(
            _node_text_runs(obj), available_w, available_h,
            lambda bits: self._font(obj, state=bits),
            lambda font, text: font.measure(text),
            lambda font: font.metrics("linespace")+2*z)
        color = obj.get("text_color") or _ink_on(obj.get("fill", "#FFE596"))
        y_pos = top
        for segments, line_w, line_h in lines:
            align = obj.get("align", "left")
            x_pos = left + ((available_w-line_w)/2 if align == "center" else
                            max(0, available_w-line_w) if align == "right" else 0)
            for text, bits, font, measured in segments:
                canvas.create_text(x_pos, y_pos, text=text, font=font, fill=color,
                                   anchor="nw", tags=tags)
                x_pos += measured
            y_pos += line_h

    def _render(self):
        if not hasattr(self, "canvas"):
            return
        canvas = self.canvas
        canvas.delete("all")
        self._paint_refs = []
        z = self.zoom
        max_x = max([o.get("x", 0)+o.get("w", 0) for o in self.items] +
                    [p[0] for s in self.strokes for p in s.get("points", [])] + [2400])
        max_y = max([o.get("y", 0)+o.get("h", 0) for o in self.items] +
                    [p[1] for s in self.strokes for p in s.get("points", [])] + [1600])
        world_w, world_h = min(12000, max_x+350), min(12000, max_y+280)
        canvas.configure(scrollregion=(0, 0, world_w*z, world_h*z))
        self._draw_grid(world_w, world_h)
        index = {o.get("id"): o for o in self.items}

        # First edges. Their per-object PNG buffers have antialiased shafts and tips.
        for edge in self.connections:
            a, b = index.get(edge.get("from")), index.get(edge.get("to"))
            if not (a and b):
                continue
            p1 = tuple(n*z for n in _anchor_toward(a, b))
            p2 = tuple(n*z for n in _anchor_toward(b, a))
            selected = ("edge", edge.get("id")) in self.selection
            color = "#EF882B" if selected else edge.get("color", self.edge_style["color"])
            width = max(1., _number(edge.get("width", 2.8), 2.8)*z)
            if Image is not None:
                key = ("edge", edge.get("id"), p1, p2, color, width)
                info = self._aa_path([p1, p2], color, width, arrow=True, key=key)
                if info:
                    x, y, photo = info
                    canvas.create_image(x, y, anchor="nw", image=photo,
                                        tags=("edge:"+edge["id"],))
                    self._paint_refs.append(photo)
            else:
                canvas.create_line(*p1, *p2, fill=color, width=width,
                                   arrow="last", tags=("edge:"+edge["id"],))

        # Next node backgrounds, text and image assets.
        for obj in self.items:
            x, y, w, h = (obj[field]*z for field in ("x", "y", "w", "h"))
            tags = ("obj:"+obj["id"],)
            if obj.get("type") == "image":
                photo = self._image_for(obj)
                if photo:
                    canvas.create_image(x, y, image=photo, anchor="nw", tags=tags)
                    self._paint_refs.append(photo)
                else:
                    canvas.create_rectangle(x, y, x+w, y+h, fill="#F0F0F0",
                                            outline="#C54848", dash=(4, 3), tags=tags)
                    canvas.create_text(x+w/2, y+h/2, text="Imagen no disponible",
                                       justify="center", tags=tags)
                canvas.create_rectangle(x, y, x+w, y+h, outline="#9BA6B3", tags=tags)
            else:
                if Image is not None:
                    bg = self._rounded_box(obj)
                    canvas.create_image(x, y, image=bg, anchor="nw", tags=tags)
                    self._paint_refs.append(bg)
                else:
                    canvas.create_rectangle(x, y, x+w, y+h,
                                            fill=obj.get("fill", "#FFE596"),
                                            outline="#8794A3", tags=tags)
                self._draw_node_text(canvas, obj, x, y, w, h, tags)
            if self.pending_connection == obj["id"]:
                canvas.create_rectangle(x-4, y-4, x+w+4, y+h+4,
                                        outline="#27A56F", width=3, tags=tags)

        # Ink is above BOTH nodes and arrows, on screen and in exported PNGs.
        for stroke in self.strokes:
            points = [(pt[0]*z, pt[1]*z) for pt in stroke.get("points", [])]
            if len(points) < 2:
                continue
            selected = ("stroke", stroke["id"]) in self.selection
            color = "#EF882B" if selected else stroke.get("color", self.pen_style["color"])
            width = max(1., _number(stroke.get("width", 3), 3)*z)
            if Image is not None:
                key = ("stroke", stroke["id"], tuple(points), color, width)
                info = self._aa_path(points, color, width, key=key)
                if info:
                    x, y, photo = info
                    canvas.create_image(x, y, image=photo, anchor="nw",
                                        tags=("stroke:"+stroke["id"],))
                    self._paint_refs.append(photo)
            else:
                canvas.create_line(*[v for p in points for v in p], smooth=len(points)>4,
                                   capstyle="round", joinstyle="round", fill=color,
                                   width=width, tags=("stroke:"+stroke["id"],))
        if self._draft_stroke is not None:
            stroke = self._draft_stroke
            coords = [n*z for p in stroke.get("points", []) for n in p]
            if len(coords) >= 4:
                canvas.create_line(*coords, smooth=len(coords)>6, splinesteps=14,
                                   capstyle="round", joinstyle="round",
                                   fill=stroke["color"], width=max(1, stroke["width"]*z))

        # Selection controls remain visible above the ink, but are not exported.
        for kind, uid in self.selection:
            if kind == "obj":
                obj = index.get(uid)
                if not obj:
                    continue
                x, y = obj["x"]*z, obj["y"]*z
                w, h = obj["w"]*z, obj["h"]*z
                canvas.create_rectangle(x-2, y-2, x+w+2, y+h+2,
                                        outline="#247CD9", width=2, dash=(6, 3),
                                        tags=("selection",))
                if len(self.selection) == 1:
                    canvas.create_rectangle(x+w-7, y+h-7, x+w+6, y+h+6,
                                            fill="#247CD9", outline="#FFFFFF",
                                            width=1, tags=("selection",))
        if self._marquee and self._marquee["moved"]:
            a, b = self._marquee["start"], self._marquee["end"]
            x1, y1 = a[0]*z, a[1]*z
            x2, y2 = b[0]*z, b[1]*z
            canvas.create_rectangle(x1, y1, x2, y2, outline="#237FE4",
                                    width=1.5, dash=(6, 3), fill="#70AEEF",
                                    stipple="gray75", tags=("marquee",))

    # ------------------------------ zoom ---------------------------------
    def change_zoom(self, multiplier):
        self._finish_edit()  # avoid leaving an editor at the wrong zoom/location
        old = self.zoom
        z = max(.4, min(2.5, round(old*multiplier, 3)))
        if abs(old-z) < .005:
            return
        middle = (self.canvas.canvasx(self.canvas.winfo_width()/2)/old,
                  self.canvas.canvasy(self.canvas.winfo_height()/2)/old)
        self.zoom = z
        self.zoom_label.configure(text=f"{round(z*100)}%")
        self._image_cache.clear()
        self._paint_cache.clear()
        self._font_cache.clear()
        self._render()
        self.canvas.update_idletasks()
        region = self.canvas.cget("scrollregion").split()
        total_w, total_h = float(region[2]), float(region[3])
        self.canvas.xview_moveto(max(0, (middle[0]*z-self.canvas.winfo_width()/2)/max(1, total_w)))
        self.canvas.yview_moveto(max(0, (middle[1]*z-self.canvas.winfo_height()/2)/max(1, total_h)))
        self.app.schedule_save()

    def _mousewheel(self, event):
        if event.state & 0x4:
            return self._zoom_wheel(event)
        axis = self.canvas.xview_scroll if event.state & 0x1 else self.canvas.yview_scroll
        axis(-3 if event.delta > 0 else 3, "units")
        return "break"

    def _zoom_wheel(self, event):
        self.change_zoom(1.1 if event.delta > 0 else 1/1.1)
        return "break"

    # ------------------------------ export --------------------------------
    @staticmethod
    def _export_font(size, obj, bits=None):
        bold = bool(obj.get("bold", False)) if bits is None else bool(bits[0])
        italic = bool(obj.get("italic", False)) if bits is None else bool(bits[1])
        if bold and italic:
            names = ["seguisbi.ttf", "arialbi.ttf", "DejaVuSans-BoldOblique.ttf"]
        elif bold:
            names = ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
        elif italic:
            names = ["segoeuii.ttf", "ariali.ttf", "DejaVuSans-Oblique.ttf"]
        else:
            names = ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]
        custom = obj.get("font_family", "")
        for name in names:
            for path in ("C:/Windows/Fonts/"+name,
                         "/usr/share/fonts/truetype/dejavu/"+name,
                         "/usr/share/fonts/truetype/liberation2/"+name):
                if os.path.isfile(path):
                    try:
                        return ImageFont.truetype(path, max(8, int(size)))
                    except OSError:
                        pass
        try:
            return ImageFont.truetype(custom or "DejaVuSans.ttf", max(8, int(size)))
        except OSError:
            return ImageFont.load_default()

    @staticmethod
    def _draw_wrapped_text(draw, text, font, x, y, width, height, color,
                           align="left", underline=False, strike=False):
        if not text:
            return
        try:
            spacing = max(10, font.getbbox("Ag")[3]-font.getbbox("Ag")[1]+5)
        except (ValueError, AttributeError):
            spacing = 17
        lines = []
        for paragraph in text.split("\n"):
            if not paragraph.strip():
                lines.append("")
                continue
            current = ""
            for word in paragraph.split():
                candidate = (current+" "+word).strip()
                if current and draw.textbbox((0, 0), candidate, font=font)[2] > width:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            lines.append(current)
        for i, line in enumerate(lines):
            ty = y+i*spacing
            if ty+spacing > y+height:
                break
            box = draw.textbbox((0, 0), line, font=font)
            tw = box[2]-box[0]
            tx = x+max(0, (width-tw)/2) if align == "center" else x+max(0, width-tw) if align == "right" else x
            draw.text((tx, ty), line, font=font, fill=color)
            if underline:
                yy = ty+spacing-3
                draw.line([(tx, yy), (tx+tw, yy)], fill=color, width=1)
            if strike:
                yy = ty+spacing*.54
                draw.line([(tx, yy), (tx+tw, yy)], fill=color, width=1)

    def _draw_node_text_png(self, draw, obj, x, y, w, h, aa):
        """Export the same per-span styles as the interactive node preview."""
        fonts = {}
        size = round(_number(obj.get("font_size", 15))*aa)
        def font_for(bits):
            if bits not in fonts:
                fonts[bits] = self._export_font(size, obj, bits)
            return fonts[bits]
        def line_h(font):
            box = font.getbbox("Mg")
            return max(9*aa, box[3]-box[1]+4*aa)
        lines = _layout_rich_text(
            _node_text_runs(obj), max(12, w-26*aa), max(10, h-22*aa),
            font_for, lambda font, text: draw.textlength(text, font=font), line_h)
        color = obj.get("text_color") or _ink_on(obj.get("fill", "#FFE596"))
        available_w = max(12, w-26*aa)
        top = y+12*aa
        for segments, line_width, height in lines:
            align = obj.get("align", "left")
            cx = x+13*aa + ((available_w-line_width)/2 if align == "center" else
                             max(0, available_w-line_width) if align == "right" else 0)
            for text, bits, font, span_width in segments:
                draw.text((cx, top), text, font=font, fill=color)
                if bits[2]:
                    yy = top+height-3*aa
                    draw.line((cx, yy, cx+span_width, yy), fill=color, width=max(1, aa))
                if bits[3]:
                    yy = top+height*.54
                    draw.line((cx, yy, cx+span_width, yy), fill=color, width=max(1, aa))
                cx += span_width
            top += height

    def export_png(self):
        if Image is None:
            ui.alert(self.app, "Exportar PNG", "Pillow no está instalado.",
                     "Instálalo con: python -m pip install Pillow", "warning")
            return
        self._finish_edit()
        points = []
        for obj in self.items:
            points += [(obj["x"], obj["y"]), (obj["x"]+obj["w"], obj["y"]+obj["h"])]
        for stroke in self.strokes:
            points += [tuple(p) for p in stroke.get("points", [])]
        if not points:
            ui.alert(self.app, "Exportar PNG", "La pizarra está vacía.",
                     "Añade algún nodo, imagen o trazo antes de exportar.", "info")
            return
        pad = 60
        left = math.floor(min(x for x, _ in points)-pad)
        top = math.floor(min(y for _, y in points)-pad)
        right = math.ceil(max(x for x, _ in points)+pad)
        bottom = math.ceil(max(y for _, y in points)+pad)
        w, h = right-left, bottom-top
        if w > 11000 or h > 11000 or w*h > 42_000_000:
            ui.alert(self.app, "Exportar PNG", "La imagen sería demasiado grande.",
                     "Acerca los elementos de la pizarra para reducir el tamaño.", "warning")
            return
        destination = ui.ask_saveas_filename(
            self.app, defaultextension=".png", title="Exportar pizarra a PNG",
            initialfile="pizarra.png", filetypes=[("Imagen PNG", "*.png")])
        if not destination:
            return
        # Supersampling also applies to the exported connectors and rounded boxes.
        aa = 3 if w*h <= 4_500_000 else 2 if w*h <= 11_000_000 else 1
        try:
            picture = Image.new("RGB", (w*aa, h*aa), "white")
            draw = ImageDraw.Draw(picture)
            point = lambda p: ((p[0]-left)*aa, (p[1]-top)*aa)
            index = {o["id"]: o for o in self.items}
            for edge in self.connections:
                a, b = index.get(edge.get("from")), index.get(edge.get("to"))
                if not (a and b):
                    continue
                p1, p2 = point(_anchor_toward(a, b)), point(_anchor_toward(b, a))
                color = edge.get("color", "#263244")
                width = max(1, round(_number(edge.get("width", 2.8))*aa))
                draw.line((p1, p2), fill=color, width=width)
                draw.polygon(_arrow_polygon(p1, p2, aa), fill=color)
            for obj in self.items:
                x, y = point((obj["x"], obj["y"]))
                ow, oh = round(obj["w"]*aa), round(obj["h"]*aa)
                if obj.get("type") == "image":
                    path = self._asset_path(obj.get("asset", ""))
                    if path and os.path.isfile(path):
                        with Image.open(path) as original:
                            img = ImageOps.exif_transpose(original).convert("RGBA")
                            img = img.resize((ow, oh), Image.Resampling.LANCZOS)
                            picture.paste(img, (round(x), round(y)), mask=img.getchannel("A"))
                    continue
                fill = obj.get("fill", "#FFE596")
                radius = max(4, round(13*aa))
                draw.rounded_rectangle((x+2*aa, y+3*aa, x+ow+2*aa, y+oh+3*aa),
                                       radius=radius, fill="#CFD5DC")
                draw.rounded_rectangle((x, y, x+ow, y+oh), radius=radius,
                                       fill=fill, outline="#8794A3", width=max(1, aa))
                self._draw_node_text_png(draw, obj, x, y, ow, oh, aa)
            # Pen on TOP of nodes and connectors (matches the editable canvas).
            for stroke in self.strokes:
                points = [point(p) for p in stroke.get("points", [])]
                if len(points) < 2:
                    continue
                color = stroke.get("color", "#263244")
                width = max(1, round(_number(stroke.get("width", 3))*aa))
                draw.line(points, fill=color, width=width, joint="curve")
                for sx, sy in (points[0], points[-1]):
                    r = width/2
                    draw.ellipse((sx-r, sy-r, sx+r, sy+r), fill=color)
            if aa > 1:
                picture = picture.resize((w, h), Image.Resampling.LANCZOS)
            picture.save(destination, "PNG")
            self.status_text.set("Pizarra exportada: " + os.path.basename(destination))
        except (OSError, ValueError, MemoryError) as exc:
            ui.alert(self.app, "Exportar PNG", "No se pudo exportar la pizarra.",
                     str(exc), "error")
