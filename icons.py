"""Iconos minimalistas de TablonK Advance.

Todos los iconos se dibujan con Pillow sobre una rejilla de 24x24 unidades,
con supermuestreo x4 para que el trazo quede suave a cualquier tamano. No se
usan caracteres Unicode ni archivos externos: el ejecutable no necesita
recursos adicionales.

Uso:
    from icons import get_icon
    img = get_icon(widget, "calendar", "#20242a", 18)
    tk.Button(..., image=img)
"""

import math

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:  # sin Pillow la app usa texto como respaldo
    Image = ImageDraw = ImageTk = None

_SS = 4                 # factor de supermuestreo
_CACHE = {}             # (name, color, size, fill) -> PhotoImage


def available():
    return Image is not None


class _Pen:
    """Pequeno lienzo vectorial: coordenadas en unidades de 24x24."""

    def __init__(self, size, color, stroke):
        self.px = size * _SS
        self.f = self.px / 24.0
        self.color = color
        self.stroke = stroke
        self.img = Image.new("RGBA", (self.px, self.px), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def _p(self, pt):
        return (pt[0] * self.f, pt[1] * self.f)

    def _cap(self, pt, w):
        x, y = self._p(pt)
        r = w * self.f / 2
        self.d.ellipse((x - r, y - r, x + r, y + r), fill=self.color)

    def line(self, pts, w=None, closed=False, color=None):
        w = self.stroke if w is None else w
        color = color or self.color
        pts = list(pts)
        if closed:
            pts = pts + [pts[0]]
        self.d.line([self._p(p) for p in pts], fill=color,
                    width=max(1, round(w * self.f)), joint="curve")
        if color == self.color:
            for p in (pts if not closed else pts[:-1]):
                self._cap(p, w)

    def poly(self, pts, fill=None):
        self.d.polygon([self._p(p) for p in pts], fill=fill or self.color)

    def rect(self, box, r=2.0, w=None, fill=None):
        w = self.stroke if w is None else w
        b = tuple(v * self.f for v in box)
        self.d.rounded_rectangle(b, radius=r * self.f, outline=self.color,
                                 width=max(1, round(w * self.f)), fill=fill)

    def frect(self, box, r=2.0, color=None):
        b = tuple(v * self.f for v in box)
        self.d.rounded_rectangle(b, radius=r * self.f, fill=color or self.color)

    def circle(self, cx, cy, r, w=None):
        w = self.stroke if w is None else w
        b = ((cx - r) * self.f, (cy - r) * self.f, (cx + r) * self.f, (cy + r) * self.f)
        self.d.ellipse(b, outline=self.color, width=max(1, round(w * self.f)))

    def dot(self, cx, cy, r, color=None):
        b = ((cx - r) * self.f, (cy - r) * self.f, (cx + r) * self.f, (cy + r) * self.f)
        self.d.ellipse(b, fill=color or self.color)

    def arc(self, cx, cy, r, start, end, w=None, steps=28):
        """Arco como polilinea (grados, 0 = derecha, sentido horario)."""
        pts = []
        for i in range(steps + 1):
            a = math.radians(start + (end - start) * i / steps)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        self.line(pts, w)
        return pts


# ----------------------------------------------------------------------
# Definiciones (cada funcion recibe un _Pen)
# ----------------------------------------------------------------------
def _close(p):
    p.line([(6.5, 6.5), (17.5, 17.5)])
    p.line([(17.5, 6.5), (6.5, 17.5)])


def _minimize(p):
    p.line([(6, 12.5), (18, 12.5)])


def _maximize(p):
    p.rect((6, 6, 18, 18), 1.6)


def _restore(p):
    p.rect((5, 9, 15, 19), 1.4)
    p.line([(9, 9), (9, 5.5), (19, 5.5), (19, 15), (15, 15)])


def _chev(points):
    def draw(p):
        p.line(points)
    return draw


def _moon(p):
    mask = Image.new("L", (p.px, p.px), 0)
    md = ImageDraw.Draw(mask)
    f = p.f
    md.ellipse((4.5 * f, 4.5 * f, 19.5 * f, 19.5 * f), fill=255)
    md.ellipse((9.5 * f, 1.5 * f, 24.5 * f, 16.5 * f), fill=0)
    solid = Image.new("RGBA", (p.px, p.px), p.color)
    p.img.paste(solid, (0, 0), mask)


def _sun(p):
    p.circle(12, 12, 3.8)
    for i in range(8):
        a = math.radians(i * 45)
        p.line([(12 + 6.8 * math.cos(a), 12 + 6.8 * math.sin(a)),
                (12 + 9.0 * math.cos(a), 12 + 9.0 * math.sin(a))])


def _trash(p):
    p.line([(4.5, 7), (19.5, 7)])
    p.line([(9.5, 7), (9.5, 4.5), (14.5, 4.5), (14.5, 7)])
    p.line([(6.5, 7), (7.6, 19.8), (16.4, 19.8), (17.5, 7)])
    p.line([(10.3, 10.5), (10.5, 16.5)], 1.5)
    p.line([(13.7, 10.5), (13.5, 16.5)], 1.5)


def _palette(p):
    p.arc(12, 12, 8.3, 40, 330)
    p.line([(12 + 8.3 * math.cos(math.radians(330)), 12 + 8.3 * math.sin(math.radians(330))),
            (16.5, 13.5), (15.5, 17.5), (12 + 8.3 * math.cos(math.radians(40)),
                                       12 + 8.3 * math.sin(math.radians(40)))])
    for x, y in ((8, 10), (11.5, 7.5), (15.5, 8.5), (8.5, 14.5)):
        p.dot(x, y, 1.35)


def _grip(p):
    for a, b in (((19, 9), (9, 19)), ((19, 13.5), (13.5, 19)), ((19, 18), (18, 19))):
        p.line([a, b], 1.6)


def _check(p):
    p.line([(5, 12.5), (10, 17.5), (19, 7)])


def _plus(p):
    p.line([(12, 5.5), (12, 18.5)])
    p.line([(5.5, 12), (18.5, 12)])


def _minus(p):
    p.line([(5.5, 12), (18.5, 12)])


def _undo(p):
    p.line([(9, 5), (5, 9), (9, 13)])
    p.line([(5, 9), (14, 9)])
    p.arc(14, 14, 5, -90, 90)
    p.line([(14, 19), (8.5, 19)])


def _redo(p):
    p.line([(15, 5), (19, 9), (15, 13)])
    p.line([(19, 9), (10, 9)])
    p.arc(10, 14, 5, 270, 90)
    p.line([(10, 19), (15.5, 19)])


def _list(p):
    for y in (7, 12, 17):
        p.dot(6, y, 1.5)
        p.line([(10, y), (19, y)])


def _align(kind):
    rows = ((7, 14), (11, 9), (15, 14), (19, 7))

    def draw(p):
        for y, length in rows:
            if kind == "left":
                x0, x1 = 5, 5 + length
            elif kind == "right":
                x0, x1 = 19 - length, 19
            else:
                x0, x1 = 12 - length / 2, 12 + length / 2
            p.line([(x0, y), (x1, y)])
    return draw


def _notes(p):
    p.line([(4.5, 4.5), (19.5, 4.5), (19.5, 14), (14, 19.5), (4.5, 19.5)], closed=True)
    p.line([(14, 19.5), (14, 14), (19.5, 14)])
    p.line([(8, 9), (16, 9)], 1.6)
    p.line([(8, 12.5), (12.5, 12.5)], 1.6)


def _task(p):
    p.rect((4.5, 4.5, 19.5, 19.5), 3)
    p.line([(8.2, 12.3), (11, 15.2), (16, 9)])


def _whiteboard(p):
    p.rect((3.5, 4, 20.5, 16), 1.8)
    p.line([(8.5, 16), (6.5, 21)])
    p.line([(15.5, 16), (17.5, 21)])
    p.line([(7, 12.5), (10, 9), (13, 11.5), (17, 7.5)], 1.6)


def _calendar(p):
    p.rect((4, 5.5, 20, 20), 2.4)
    p.line([(4, 10), (20, 10)])
    p.line([(8.5, 3.5), (8.5, 7)])
    p.line([(15.5, 3.5), (15.5, 7)])
    for x in (8.5, 12, 15.5):
        p.dot(x, 13.6, 1.1)
    for x in (8.5, 12):
        p.dot(x, 16.8, 1.1)


def _today(p):
    p.rect((4, 5.5, 20, 20), 2.4)
    p.line([(4, 10), (20, 10)])
    p.line([(8.5, 3.5), (8.5, 7)])
    p.line([(15.5, 3.5), (15.5, 7)])
    p.frect((10, 12.5, 14.5, 17), 1)


def _events(p):
    p.rect((3.5, 5, 20.5, 19), 2.2)
    p.line([(3.5, 9.6), (20.5, 9.6)])
    p.line([(3.5, 14.3), (20.5, 14.3)], 1.4)
    p.line([(9, 9.6), (9, 19)], 1.4)


def _settings(p):
    pts = []
    teeth = 8
    for t in range(teeth):
        base = t * 360 / teeth
        for off, r in ((-15, 7.0), (-9, 9.3), (9, 9.3), (15, 7.0)):
            a = math.radians(base + off)
            pts.append((12 + r * math.cos(a), 12 + r * math.sin(a)))
    p.line(pts, 1.6, closed=True)
    p.circle(12, 12, 3.0, 1.7)


def _search(p):
    p.circle(10.5, 10.5, 5.8)
    p.line([(14.8, 14.8), (19.5, 19.5)], 2.2)


def _pin(filled):
    def draw(p):
        body = [(9, 4.5), (15, 4.5), (14.2, 10), (17.5, 14.2), (6.5, 14.2), (9.8, 10)]
        if filled:
            p.poly(body)
        p.line(body, 1.7, closed=True)
        p.line([(12, 14.2), (12, 20.5)], 1.8)
    return draw


def _edit(p):
    p.line([(15, 5), (19, 9), (9.2, 18.8), (5, 19), (5.2, 14.8)], closed=True)
    p.line([(12.8, 7.2), (16.8, 11.2)], 1.6)


def _tag(p):
    p.line([(4.5, 4.5), (11.5, 4.5), (19.5, 12.5), (12.5, 19.5), (4.5, 11.5)], closed=True)
    p.dot(8.6, 8.6, 1.5)


def _columns(p):
    p.rect((3.5, 5, 20.5, 19), 2.2)
    p.line([(9.2, 5), (9.2, 19)], 1.5)
    p.line([(14.8, 5), (14.8, 19)], 1.5)


def _filter(p):
    p.line([(4, 5.5), (20, 5.5), (14, 12.5), (14, 19), (10, 17), (10, 12.5)], closed=True)


def _download(p):
    p.line([(12, 4), (12, 15)])
    p.line([(7.5, 10.5), (12, 15), (16.5, 10.5)])
    p.line([(5, 15.5), (5, 19.5), (19, 19.5), (19, 15.5)])


def _refresh(p):
    p.arc(12, 12, 7, 20, 300)
    a = math.radians(300)
    ex, ey = 12 + 7 * math.cos(a), 12 + 7 * math.sin(a)
    tx, ty = -math.sin(a), math.cos(a)          # tangente (sentido del giro)
    nx, ny = math.cos(a), math.sin(a)           # normal hacia fuera
    tip = (ex + tx * 2.2, ey + ty * 2.2)
    p.line([(tip[0] - tx * 4 + nx * 3, tip[1] - ty * 4 + ny * 3), tip,
            (tip[0] - tx * 4 - nx * 3, tip[1] - ty * 4 - ny * 3)])


def _clock(p):
    p.circle(12, 12, 8)
    p.line([(12, 7.5), (12, 12), (15.5, 14)])


def _duplicate(p):
    p.rect((8.5, 8.5, 19.5, 19.5), 2)
    p.line([(15.5, 8.5), (15.5, 4.5), (4.5, 4.5), (4.5, 15.5), (8.5, 15.5)])


def _export(p):
    p.line([(12, 15), (12, 4)])
    p.line([(7.5, 8.5), (12, 4), (16.5, 8.5)])
    p.line([(5, 13), (5, 19.5), (19, 19.5), (19, 13)])


def _paste(p):
    p.rect((5.5, 5, 18.5, 20.5), 2.2)
    p.frect((9, 3.2, 15, 6.8), 1.2)
    p.line([(8.5, 11), (15.5, 11)], 1.5)
    p.line([(8.5, 14.5), (13.5, 14.5)], 1.5)


def _image(p):
    p.rect((3, 4.5, 21, 19.5), 2.2)
    p.dot(15.8, 9, 1.8)
    p.line([(5, 17.5), (10, 12), (13.5, 15.5), (16, 13), (19.5, 17)], 1.7)


def _info(p):
    p.circle(12, 12, 8.5)
    p.dot(12, 8, 1.3)
    p.line([(12, 11), (12, 16.5)], 2.1)


def _warning(p):
    p.line([(12, 4), (20.5, 19), (3.5, 19)], closed=True)
    p.line([(12, 9.5), (12, 13.5)], 2.1)
    p.dot(12, 16.3, 1.25)


def _error(p):
    p.circle(12, 12, 8.5)
    p.line([(9, 9), (15, 15)])
    p.line([(15, 9), (9, 15)])


def _question(p):
    p.circle(12, 12, 8.5)
    p.arc(12, 9.6, 2.6, 180, 405, 2.0, 18)
    a = math.radians(405)
    p.line([(12 + 2.6 * math.cos(a), 9.6 + 2.6 * math.sin(a)), (12, 13.6)], 2.0)
    p.dot(12, 16.6, 1.25)


def _view_day(p):
    p.rect((4, 5.5, 20, 20), 2.4)
    p.line([(4, 10), (20, 10)])
    p.frect((8, 12.5, 16, 17.5), 1)


def _sidebar(p):
    p.rect((3.5, 5, 20.5, 19), 2.2)
    p.line([(9, 5), (9, 19)], 1.5)


def _link(p):
    p.line([(10, 6), (6, 6), (6, 18), (18, 18), (18, 14)])
    p.line([(13, 5.5), (18.5, 5.5), (18.5, 11)])
    p.line([(18.5, 5.5), (11, 13)])


def _list_numbered(p):
    for i, y in enumerate((7, 12, 17)):
        # numeros dibujados como trazos minimos: 1, 2, 3
        if i == 0:
            p.line([(4.8, 5.4), (6, 4.6), (6, 9)], 1.3)
        elif i == 1:
            p.line([(4.4, 10.6), (5.4, 9.9), (6.6, 10.4), (6.5, 11.6), (4.4, 14), (7, 14)], 1.4)
        else:
            p.line([(4.4, 15.4), (6.8, 15.4), (5.4, 17.1), (6.8, 17.8), (6.4, 19.2), (4.4, 19.2)], 1.4)
        p.line([(10, y), (19.5, y)])


def _capsule(p, cx, cy, length, radius, angle, w=2.0):
    """Eslabon: rectangulo con extremos redondos, girado 'angle' grados."""
    pts = []
    half = length / 2 - radius
    for side, base in ((1, -90), (-1, 90)):
        ox = side * half
        for i in range(15):
            t = math.radians(base + 180 * i / 14)
            pts.append((ox + radius * math.cos(t), radius * math.sin(t)))
    ang = math.radians(angle)
    rot = [(cx + x * math.cos(ang) - y * math.sin(ang),
            cy + x * math.sin(ang) + y * math.cos(ang)) for x, y in pts]
    p.line(rot, w, closed=True)


def _chain(p):
    _capsule(p, 8.6, 15.4, 10.5, 3.4, -45)
    _capsule(p, 15.4, 8.6, 10.5, 3.4, -45)


def _paperclip(p):
    p.line([(16.5, 9), (9.5, 16)], 1.8)
    p.arc(8, 14.5, 2.1, 45, 225, 1.8, 12)
    a = math.radians(225)
    p.line([(8 + 2.1 * math.cos(a), 14.5 + 2.1 * math.sin(a)), (15.6, 4.9)], 1.8)
    p.arc(17.3, 6.6, 2.4, 225, 405, 1.8, 12)
    b = math.radians(405)
    p.line([(17.3 + 2.4 * math.cos(b), 6.6 + 2.4 * math.sin(b)), (10, 19)], 1.8)
    p.arc(7.4, 16.4, 3.6, 45, 225, 1.8, 14)
    p.line([(7.4 + 3.6 * math.cos(a), 16.4 + 3.6 * math.sin(a)), (12, 7.8)], 1.8)


def _heading(p):
    p.line([(5, 5.5), (19, 5.5)], 2.3)
    p.line([(12, 5.5), (12, 19)], 2.3)


def _file(p):
    p.line([(6, 3.5), (14, 3.5), (19, 8.5), (19, 20.5), (6, 20.5)], closed=True)
    p.line([(14, 3.5), (14, 8.5), (19, 8.5)])
    p.line([(9, 13), (16, 13)], 1.5)
    p.line([(9, 16.5), (14, 16.5)], 1.5)


def _folder(p):
    p.line([(3.5, 6), (9.5, 6), (11.5, 8.5), (20.5, 8.5), (20.5, 19), (3.5, 19)], closed=True)
    p.line([(3.5, 11), (20.5, 11)], 1.5)


def _clear_format(p):
    p.line([(6, 5.5), (18, 5.5)], 2.1)
    p.line([(12, 5.5), (9.5, 19)], 2.1)
    p.line([(14.5, 14), (19.5, 19)], 1.8)
    p.line([(19.5, 14), (14.5, 19)], 1.8)


_DEFS = {
    "close": _close, "minimize": _minimize, "maximize": _maximize,
    "restore": _restore,
    "chevron_up": _chev([(7, 14.5), (12, 9.5), (17, 14.5)]),
    "chevron_down": _chev([(7, 9.5), (12, 14.5), (17, 9.5)]),
    "chevron_left": _chev([(14.5, 7), (9.5, 12), (14.5, 17)]),
    "chevron_right": _chev([(9.5, 7), (14.5, 12), (9.5, 17)]),
    "moon": _moon, "sun": _sun, "trash": _trash, "palette": _palette,
    "grip": _grip, "check": _check, "plus": _plus, "minus": _minus,
    "undo": _undo, "redo": _redo, "list": _list,
    "align_left": _align("left"), "align_center": _align("center"),
    "align_right": _align("right"),
    "notes": _notes, "task": _task, "whiteboard": _whiteboard,
    "calendar": _calendar, "today": _today, "events": _events,
    "settings": _settings, "search": _search,
    "pin": _pin(False), "pin_filled": _pin(True),
    "edit": _edit, "tag": _tag, "columns": _columns, "filter": _filter,
    "download": _download, "refresh": _refresh, "clock": _clock,
    "duplicate": _duplicate, "export": _export, "paste": _paste,
    "image": _image, "info": _info, "warning": _warning, "error": _error,
    "question": _question, "view_day": _view_day, "sidebar": _sidebar,
    "link": _link, "list_numbered": _list_numbered, "chain": _chain,
    "paperclip": _paperclip, "heading": _heading, "file": _file,
    "folder": _folder, "clear_format": _clear_format,
}


def names():
    return sorted(_DEFS)


def render(name, color, size=18, stroke=1.9):
    """Devuelve una imagen PIL RGBA del icono (o None sin Pillow)."""
    if Image is None or name not in _DEFS:
        return None
    pen = _Pen(size, color, stroke)
    _DEFS[name](pen)
    return pen.img.resize((size, size), Image.Resampling.LANCZOS)


def get_icon(master, name, color, size=18, stroke=1.9):
    """PhotoImage cacheado. Devuelve None si no hay Pillow."""
    key = (name, color, size, stroke)
    if key in _CACHE:
        return _CACHE[key]
    picture = render(name, color, size, stroke)
    if picture is None:
        return None
    photo = ImageTk.PhotoImage(picture, master=master)
    _CACHE[key] = photo
    return photo


def swatch(master, color, size=16, checked=False, check_color="#1a1a1a",
           border="#00000033", radius=4):
    """Muestra de color redondeada, opcionalmente con una marca de seleccion."""
    key = ("__swatch", color, size, checked, check_color, border, radius)
    if key in _CACHE:
        return _CACHE[key]
    if Image is None:
        return None
    k = _SS
    img = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((k, k, size * k - k, size * k - k), radius=radius * k,
                        fill=color, outline=_rgba(border), width=k)
    if checked:
        f = size * k / 24.0
        pts = [(6.5 * f, 12.5 * f), (10.5 * f, 16.5 * f), (17.5 * f, 8 * f)]
        d.line(pts, fill=check_color, width=round(2.6 * f), joint="curve")
    photo = ImageTk.PhotoImage(img.resize((size, size), Image.Resampling.LANCZOS),
                               master=master)
    _CACHE[key] = photo
    return photo


def _rgba(value):
    value = value.lstrip("#")
    if len(value) == 8:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4, 6))
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def clear_cache():
    _CACHE.clear()
