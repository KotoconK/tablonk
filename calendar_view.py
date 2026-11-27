"""Seccion Calendario: vistas de dia, semana, mes y año.

Todo se dibuja en Canvas para controlar el color de cada evento, que es el
color de su tipo. Clic en un evento: editarlo. Doble clic en un hueco: crear
un evento en ese dia (y a esa hora en las vistas de dia y semana).
"""

import calendar as _cal
import datetime as _dt
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from event_dialogs import create_event, edit_event
from events_store import CLOSED_STATUSES, PRIORITY_RANK, minutes
from ui_common import (MONTHS, MONTHS_SHORT, UI_FONT, WEEKDAYS, WEEKDAYS_MIN,
                       WEEKDAYS_SHORT, FlatButton, blend, ink_on)

VIEWS = (("day", "Día"), ("week", "Semana"), ("month", "Mes"), ("year", "Año"))
GUTTER = 72
HOUR_H = 46
LANE_H = 20
NOW_COLOR = "#E35165"


def round_rect(canvas, x0, y0, x1, y1, r=5, **kw):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return canvas.create_polygon(pts, smooth=True, **kw)


def week_start(day):
    return day - _dt.timedelta(days=day.weekday())


def add_months(day, delta):
    m = day.month - 1 + delta
    y = day.year + m // 12
    m = m % 12 + 1
    return _dt.date(y, m, min(day.day, _cal.monthrange(y, m)[1]))


class CanvasTip:
    """Ayuda emergente para zonas de un Canvas."""

    def __init__(self, canvas):
        self.canvas = canvas
        self.win = None

    def show(self, x_root, y_root, text):
        self.hide()
        tip = tk.Toplevel(self.canvas)
        tip.overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except tk.TclError:
            pass
        tk.Label(tip, text=text, bg="#273443", fg="white", justify="left", padx=8, pady=5,
                 font=(UI_FONT, 9)).pack()
        tip.geometry(f"+{x_root + 14}+{y_root + 12}")
        self.win = tip

    def hide(self):
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None


class CalendarView(tk.Frame):
    def __init__(self, master, app, store):
        super().__init__(master, bd=0)
        self.app = app
        self.store = store
        self.view = "month"
        self.cursor = _dt.date.today()
        self.hidden_types = set()
        self.highlight_id = None
        self._dirty = True
        self._draw_job = None
        self._buttons = []
        self._scrolled_to_morning = False
        self.f_small = tkfont.Font(family=UI_FONT, size=8)
        self.f_norm = tkfont.Font(family=UI_FONT, size=9)
        self.f_bold = tkfont.Font(family=UI_FONT, size=9, weight="bold")
        self.f_day = tkfont.Font(family=UI_FONT, size=10)
        self.f_day_b = tkfont.Font(family=UI_FONT, size=10, weight="bold")
        self.f_big = tkfont.Font(family=UI_FONT, size=16, weight="bold")
        self._build()
        store.subscribe(self._on_store_changed)
        self._tick()

    # ------------------------------------------------------------ estado
    def load_state(self, state):
        state = state if isinstance(state, dict) else {}
        self.view = state.get("view") if state.get("view") in dict(VIEWS) else "month"
        try:
            self.cursor = _dt.date.fromisoformat(state.get("date", ""))
        except (TypeError, ValueError):
            self.cursor = _dt.date.today()
        self.hidden_types = set(state.get("hidden_types", []))
        if state.get("hide_untyped"):
            self.hidden_types.add(None)
        self._scrolled_to_morning = False
        self._dirty = True
        self._update_view_buttons()
        self.redraw()

    def state(self):
        return {"view": self.view, "date": self.cursor.isoformat(),
                "hidden_types": [t for t in self.hidden_types if t is not None],
                "hide_untyped": None in self.hidden_types}

    # ---------------------------------------------------------------- UI
    def _btn(self, parent, **kw):
        b = FlatButton(parent, self.app, **kw)
        self._buttons.append(b)
        return b

    def _build(self):
        bar = tk.Frame(self, height=50)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        self.toolbar = bar
        self._btn(bar, icon="chevron_left", padx=5, pady=4, tooltip="Anterior",
                  command=lambda: self.shift(-1)).pack(side="left", padx=(10, 2), pady=9)
        self.today_btn = self._btn(bar, text="Hoy", icon="today", padx=9, pady=4,
                                   tooltip="Ir a hoy", command=self.go_today)
        self.today_btn.pack(side="left", padx=2, pady=9)
        self._btn(bar, icon="chevron_right", padx=5, pady=4, tooltip="Siguiente",
                  command=lambda: self.shift(1)).pack(side="left", padx=(2, 12), pady=9)
        self.title_lbl = tk.Label(bar, font=(UI_FONT, 14, "bold"), anchor="w")
        self.title_lbl.pack(side="left")
        self.subtitle_lbl = tk.Label(bar, font=(UI_FONT, 9), anchor="w")
        self.subtitle_lbl.pack(side="left", padx=(10, 0), pady=(5, 0))

        self.new_btn = self._btn(bar, text="Evento", icon="plus", kind="accent",
                                 font=(UI_FONT, 9, "bold"), padx=10, pady=4,
                                 tooltip="Crear un evento en el día mostrado",
                                 command=self.new_event)
        self.new_btn.pack(side="right", padx=(8, 10), pady=9)
        self.filter_btn = self._btn(bar, icon="filter", padx=6, pady=4,
                                    tooltip="Filtrar por tipo", command=self._filter_menu)
        self.filter_btn.pack(side="right", padx=2, pady=9)
        seg = tk.Frame(bar)
        seg.pack(side="right", padx=(0, 8), pady=9)
        self.seg = seg
        self.view_buttons = {}
        for key, label in VIEWS:
            b = self._btn(seg, text=label, padx=11, pady=4, font=(UI_FONT, 9, "bold"),
                          command=lambda k=key: self.set_view(k))
            b.pack(side="left", padx=1)
            self.view_buttons[key] = b

        self.stage = tk.Frame(self)
        self.stage.pack(side="top", fill="both", expand=True)

        # Mes y año: un unico canvas cada uno
        self.month_canvas = tk.Canvas(self.stage, highlightthickness=0, bd=0)
        self.year_canvas = tk.Canvas(self.stage, highlightthickness=0, bd=0)
        # Dia y semana: cabecera, franja "todo el dia" y rejilla horaria
        self.time_frame = tk.Frame(self.stage)
        self.head_canvas = tk.Canvas(self.time_frame, height=46, highlightthickness=0, bd=0)
        self.allday_canvas = tk.Canvas(self.time_frame, height=28, highlightthickness=0, bd=0)
        self.grid_canvas = tk.Canvas(self.time_frame, highlightthickness=0, bd=0)
        self.grid_bar = ttk.Scrollbar(self.time_frame, orient="vertical",
                                      command=self.grid_canvas.yview)
        self.grid_canvas.configure(yscrollcommand=self.grid_bar.set)
        self.head_canvas.grid(row=0, column=0, sticky="ew")
        self.allday_canvas.grid(row=1, column=0, sticky="ew")
        self.grid_canvas.grid(row=2, column=0, sticky="nsew")
        self.grid_bar.grid(row=2, column=1, sticky="ns")
        self.time_frame.grid_rowconfigure(2, weight=1)
        self.time_frame.grid_columnconfigure(0, weight=1)

        self.tip = CanvasTip(self)
        for c in (self.month_canvas, self.year_canvas, self.head_canvas,
                  self.allday_canvas, self.grid_canvas):
            c.bind("<Configure>", lambda e: self._schedule_draw())
            c.tag_bind("ev", "<Button-1>", self._on_event_click)
            c.tag_bind("ev", "<Enter>", lambda e, cv=c: cv.configure(cursor="hand2"))
            c.tag_bind("ev", "<Leave>", lambda e, cv=c: (cv.configure(cursor=""), self.tip.hide()))
            c.tag_bind("link", "<Enter>", lambda e, cv=c: cv.configure(cursor="hand2"))
            c.tag_bind("link", "<Leave>", lambda e, cv=c: (cv.configure(cursor=""), self.tip.hide()))
            c.tag_bind("ev", "<Motion>", lambda e, cv=c: self._event_tip(e, cv))
            c.bind("<Button-3>", lambda e, cv=c: self._context_menu(e, cv))
        self.month_canvas.bind("<Double-Button-1>", self._month_double)
        self.year_canvas.tag_bind("yday", "<Motion>", self._year_tip)
        self.grid_canvas.bind("<Double-Button-1>", self._grid_double)
        self.allday_canvas.bind("<Double-Button-1>", self._allday_double)
        for seq in ("<MouseWheel>",):
            self.grid_canvas.bind(seq, lambda e: self.grid_canvas.yview_scroll(
                int(-e.delta / 120) * 2, "units"))
            self.month_canvas.bind(seq, lambda e: self.shift(1 if e.delta < 0 else -1))
        self.grid_canvas.bind("<Button-4>", lambda e: self.grid_canvas.yview_scroll(-2, "units"))
        self.grid_canvas.bind("<Button-5>", lambda e: self.grid_canvas.yview_scroll(2, "units"))
        self.grid_canvas.configure(yscrollincrement=HOUR_H // 2)
        self._update_view_buttons()
        self.update_theme()

    # -------------------------------------------------------------- tema
    def update_theme(self):
        p = self.app.palette()
        self.configure(bg=p["app_bg"])
        self.toolbar.configure(bg=p["toolbar_bg"])
        self.seg.configure(bg=p["toolbar_bg"])
        self.title_lbl.configure(bg=p["toolbar_bg"], fg=p["text"])
        self.subtitle_lbl.configure(bg=p["toolbar_bg"], fg=p["muted_text"])
        self.stage.configure(bg=p["board_bg"])
        self.time_frame.configure(bg=p["board_bg"])
        for c in (self.month_canvas, self.year_canvas, self.head_canvas,
                  self.allday_canvas, self.grid_canvas):
            c.configure(bg=p["board_bg"])
        for b in self._buttons:
            b.restyle()
        self._update_view_buttons()
        self._dirty = True
        self.redraw()

    def _colors(self):
        p = self.app.palette()
        dark = self.app.theme == "dark"
        return {
            "bg": p["board_bg"],
            "cell": blend(p["board_bg"], "#FFFFFF", 0.72) if not dark else blend(p["board_bg"], "#FFFFFF", 0.05),
            "weekend": p["board_bg"],
            "out": blend(p["board_bg"], p["border"], 0.22) if not dark else blend(p["board_bg"], "#000000", 0.22),
            "line": p["border"],
            "soft": blend(p["border"], p["board_bg"], 0.55),
            "text": p["text"],
            "muted": p["muted_text"],
            "accent": p["accent"],
            "today_bg": blend(p["accent"], blend(p["board_bg"], "#FFFFFF", 0.5 if not dark else 0), 0.9),
        }

    # -------------------------------------------------------- navegacion
    def _update_view_buttons(self):
        for key, b in getattr(self, "view_buttons", {}).items():
            b.set_selected(key == self.view)

    def set_view(self, view, day=None):
        if day is not None:
            self.cursor = day
        if view != self.view and view in ("day", "week"):
            self._scrolled_to_morning = False
        self.view = view
        self._update_view_buttons()
        self.redraw()
        self.app.schedule_save()

    def shift(self, delta):
        if self.view == "day":
            self.cursor += _dt.timedelta(days=delta)
        elif self.view == "week":
            self.cursor += _dt.timedelta(days=7 * delta)
        elif self.view == "month":
            self.cursor = add_months(self.cursor, delta)
        else:
            try:
                self.cursor = self.cursor.replace(year=self.cursor.year + delta)
            except ValueError:
                self.cursor = self.cursor.replace(year=self.cursor.year + delta, day=28)
        self.redraw()
        self.app.schedule_save()

    def go_today(self):
        self.cursor = _dt.date.today()
        self._scrolled_to_morning = False
        self.redraw()
        self.app.schedule_save()

    def show_event(self, event_id):
        event = self.store.get(event_id)
        if not event:
            return
        self.cursor = self.store.start_date(event)
        if self.store.is_timed(event):
            self.view = "week" if self.view != "day" else "day"
            start, _ = self.store.time_range(event)
            self._pending_scroll = max(0, start / 60 - 1)
        elif self.view in ("year",):
            self.view = "month"
        self.hidden_types.discard(event["type_id"])
        self.highlight_id = event_id
        self._update_view_buttons()
        self.redraw()
        self.after(2600, self._clear_highlight)

    def _clear_highlight(self):
        self.highlight_id = None
        self.redraw()

    def _type_filter(self):
        if not self.hidden_types:
            return None
        return ({t["id"] for t in self.store.types} | {None}) - self.hidden_types

    def _filter_menu(self):
        menu = tk.Menu(self, tearoff=0)
        entries = [(t["id"], t["name"]) for t in self.store.types] + [(None, "Sin tipo")]
        for tid, name in entries:
            var = tk.BooleanVar(value=tid not in self.hidden_types)
            menu.add_checkbutton(label=name, variable=var,
                                 command=lambda t=tid: self._toggle_type(t))
            menu._vars = getattr(menu, "_vars", []) + [var]
        menu.add_separator()
        menu.add_command(label="Mostrar todos", command=self._show_all_types)
        x = self.filter_btn.winfo_rootx()
        y = self.filter_btn.winfo_rooty() + self.filter_btn.winfo_height()
        menu.tk_popup(x, y)

    def _toggle_type(self, tid):
        self.hidden_types ^= {tid}
        self._after_filter()

    def _show_all_types(self):
        self.hidden_types.clear()
        self._after_filter()

    def _after_filter(self):
        self.filter_btn.set_selected(bool(self.hidden_types))
        self.redraw()
        self.app.schedule_save()

    # ---------------------------------------------------------- dibujo
    def _on_store_changed(self):
        self._dirty = True
        if self.winfo_ismapped():
            self._schedule_draw()

    def on_show(self):
        self.redraw()

    def _schedule_draw(self):
        if self._draw_job is not None:
            self.after_cancel(self._draw_job)
        self._draw_job = self.after(25, self.redraw)

    def _tick(self):
        # Mantiene la linea de "ahora" y el dia de hoy al dia.
        if self.winfo_exists():
            if self.winfo_ismapped() and self.view in ("day", "week"):
                self.redraw()
            self.after(60_000, self._tick)

    def redraw(self):
        self._draw_job = None
        self._dirty = False
        self.tip.hide()
        self.filter_btn.set_selected(bool(self.hidden_types))
        for w in (self.month_canvas, self.year_canvas, self.time_frame):
            w.pack_forget()
        self._update_title()
        if self.view == "month":
            self.month_canvas.pack(fill="both", expand=True)
            self._draw_month()
        elif self.view == "year":
            self.year_canvas.pack(fill="both", expand=True)
            self._draw_year()
        else:
            self.time_frame.pack(fill="both", expand=True)
            self._draw_time_view()

    def _update_title(self):
        c = self.cursor
        if self.view == "month":
            title, sub = f"{MONTHS[c.month - 1].capitalize()} {c.year}", ""
        elif self.view == "year":
            title, sub = str(c.year), ""
        elif self.view == "week":
            a = week_start(c)
            b = a + _dt.timedelta(days=6)
            if a.month == b.month:
                title = f"{a.day} – {b.day} {MONTHS_SHORT[a.month - 1]} {b.year}"
            elif a.year == b.year:
                title = f"{a.day} {MONTHS_SHORT[a.month - 1]} – {b.day} {MONTHS_SHORT[b.month - 1]} {b.year}"
            else:
                title = (f"{a.day} {MONTHS_SHORT[a.month - 1]} {a.year} – "
                         f"{b.day} {MONTHS_SHORT[b.month - 1]} {b.year}")
            sub = f"Semana {a.isocalendar()[1]}"
        else:
            title = f"{WEEKDAYS[c.weekday()].capitalize()}, {c.day} de {MONTHS[c.month - 1]}"
            sub = str(c.year)
        self.title_lbl.configure(text=title)
        self.subtitle_lbl.configure(text=sub)

    def _events(self, first, last):
        return self.store.events_between(first, last, self._type_filter())

    def _event_colors(self, event):
        color = self.store.type_color(event["type_id"])
        if event["status"] in CLOSED_STATUSES:
            bg = blend(color, self.app.palette()["board_bg"], 0.5)
            return bg, blend(ink_on(color), bg, 0.45)
        return color, ink_on(color)

    @staticmethod
    def _fit(text, font, width):
        if width <= 8:
            return ""
        if font.measure(text) <= width:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.measure(text[:mid] + "…") <= width:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + "…" if lo else ""

    def _draw_bar(self, canvas, event, x0, y0, x1, y1, label, font=None):
        bg, fg = self._event_colors(event)
        tags = ("ev", f"ev:{event['id']}")
        outline = ""
        width = 1
        if event["id"] == self.highlight_id:
            outline, width = self.app.palette()["accent"], 2
        round_rect(canvas, x0, y0, x1, y1, 4, fill=bg, outline=outline, width=width, tags=tags)
        font = font or self.f_norm
        canvas.create_text(x0 + 6, (y0 + y1) / 2, text=self._fit(label, font, x1 - x0 - 10),
                           anchor="w", fill=fg, font=font, tags=tags)

    def _lanes(self, segments):
        """Asigna carriles a segmentos (c0, c1, event). Devuelve [(lane, seg)]."""
        segments.sort(key=lambda s: (s[0], -(s[1] - s[0]),
                                     0 if s[2]["all_day"] else 1,
                                     s[2]["start_time"] or "",
                                     PRIORITY_RANK.get(s[2]["priority"], 9)))
        occupied = []
        result = []
        for seg in segments:
            c0, c1, _ = seg
            lane = 0
            while True:
                if lane >= len(occupied):
                    occupied.append(set())
                if not any(c in occupied[lane] for c in range(c0, c1 + 1)):
                    occupied[lane].update(range(c0, c1 + 1))
                    break
                lane += 1
            result.append((lane, seg))
        return result

    # ------------------------------------------------------------- mes
    def _draw_month(self):
        cv = self.month_canvas
        cv.delete("all")
        col = self._colors()
        W, H = max(cv.winfo_width(), 300), max(cv.winfo_height(), 240)
        head_h = 28
        weeks = _cal.Calendar(0).monthdatescalendar(self.cursor.year, self.cursor.month)
        n = len(weeks)
        cw = W / 7
        ch = (H - head_h) / n
        today = _dt.date.today()
        for i, name in enumerate(WEEKDAYS_SHORT):
            cv.create_text(i * cw + 10, head_h / 2, text=name.capitalize(), anchor="w",
                           fill=col["muted"], font=self.f_bold)
        cv.create_line(0, head_h, W, head_h, fill=col["line"])
        events = self._events(weeks[0][0], weeks[-1][-1])
        self._month_cells = []
        for r, week in enumerate(weeks):
            y0 = head_h + r * ch
            for c, day in enumerate(week):
                x0 = c * cw
                fill = col["cell"] if day.month == self.cursor.month else col["out"]
                if c >= 5 and day.month == self.cursor.month:
                    fill = blend(col["cell"], col["weekend"], 0.6)
                if day == today:
                    fill = col["today_bg"]
                cv.create_rectangle(x0, y0, x0 + cw, y0 + ch, fill=fill, outline=col["line"])
                self._month_cells.append((x0, y0, x0 + cw, y0 + ch, day))
                num_tags = ("link", f"day:{day.isoformat()}")
                if day == today:
                    cv.create_oval(x0 + 4, y0 + 4, x0 + 26, y0 + 26, fill=col["accent"],
                                   outline="", tags=num_tags)
                    cv.create_text(x0 + 15, y0 + 15, text=str(day.day), fill="#FFFFFF",
                                   font=self.f_day_b, tags=num_tags)
                else:
                    fg = col["text"] if day.month == self.cursor.month else col["muted"]
                    label = str(day.day)
                    if day.day == 1:
                        label = f"{day.day} {MONTHS_SHORT[day.month - 1]}"
                    cv.create_text(x0 + 9, y0 + 15, text=label, anchor="w", fill=fg,
                                   font=self.f_day, tags=num_tags)
            # eventos de la semana en carriles
            first, last = week[0], week[-1]
            segs = []
            for ev in events:
                s, e = self.store.start_date(ev), self.store.end_date(ev)
                if s > last or e < first:
                    continue
                c0 = (max(s, first) - first).days
                c1 = (min(e, last) - first).days
                segs.append([c0, c1, ev])
            placed = self._lanes(segs)
            cap = max(0, int((ch - 30) // LANE_H))
            per_day = [0] * 7
            for lane, (c0, c1, _) in placed:
                for c in range(c0, c1 + 1):
                    per_day[c] = max(per_day[c], lane + 1)
            visible = [cap if per_day[c] <= cap else max(0, cap - 1) for c in range(7)]
            hidden = [0] * 7
            for lane, (c0, c1, ev) in placed:
                if lane >= min(visible[c0:c1 + 1]):
                    for c in range(c0, c1 + 1):
                        hidden[c] += 1
                    continue
                y = y0 + 28 + lane * LANE_H
                label = ev["name"]
                if self.store.is_timed(ev):
                    label = f"{ev['start_time']}  {label}"
                self._draw_bar(cv, ev, c0 * cw + 3, y, (c1 + 1) * cw - 3, y + LANE_H - 3, label)
            for c in range(7):
                if hidden[c]:
                    x = c * cw + 8
                    y = y0 + 28 + visible[c] * LANE_H + 7
                    tags = ("link", f"day:{week[c].isoformat()}")
                    cv.create_text(x, y, text=f"{hidden[c]} más", anchor="w",
                                   fill=col["accent"], font=self.f_bold, tags=tags)
        cv.tag_bind("link", "<Button-1>", self._on_day_link)

    def _day_at(self, x, y):
        for x0, y0, x1, y1, day in getattr(self, "_month_cells", []):
            if x0 <= x < x1 and y0 <= y < y1:
                return day
        return None

    def _month_double(self, event):
        if self._current_event_id(self.month_canvas):
            return
        day = self._day_at(event.x, event.y)
        if day:
            self.new_event(day)

    # ------------------------------------------------------------- año
    def _draw_year(self):
        cv = self.year_canvas
        cv.delete("all")
        col = self._colors()
        W, H = max(cv.winfo_width(), 320), max(cv.winfo_height(), 260)
        cols = 4 if W >= 960 else 3 if W >= 600 else 2
        rows = 12 // cols
        pad = 14
        bw = (W - pad * (cols + 1)) / cols
        bh = (H - pad * (rows + 1)) / rows
        year = self.cursor.year
        today = _dt.date.today()
        events = self._events(_dt.date(year, 1, 1), _dt.date(year, 12, 31))
        by_day = {}
        for ev in events:
            s = max(self.store.start_date(ev), _dt.date(year, 1, 1))
            e = min(self.store.end_date(ev), _dt.date(year, 12, 31))
            d = s
            while d <= e:
                by_day.setdefault(d, []).append(ev)
                d += _dt.timedelta(days=1)
        self._year_days = by_day
        for m in range(12):
            r, c = divmod(m, cols)
            x0 = pad + c * (bw + pad)
            y0 = pad + r * (bh + pad)
            round_rect(cv, x0, y0, x0 + bw, y0 + bh, 8, fill=col["cell"], outline=col["line"])
            tags = ("link", f"month:{year}-{m + 1:02d}")
            cv.create_text(x0 + 12, y0 + 16, text=MONTHS[m].capitalize(), anchor="w",
                           fill=col["accent"] if (today.year == year and today.month == m + 1)
                           else col["text"], font=self.f_bold, tags=tags)
            count = sum(1 for ev in events
                        if self.store.start_date(ev).month == m + 1
                        and self.store.start_date(ev).year == year)
            if count:
                cv.create_text(x0 + bw - 10, y0 + 16, text=str(count), anchor="e",
                               fill=col["muted"], font=self.f_small)
            gx0, gy0 = x0 + 8, y0 + 32
            gw, gh = bw - 16, bh - 40
            cwid, rh = gw / 7, gh / 7
            for i, name in enumerate(WEEKDAYS_MIN):
                cv.create_text(gx0 + (i + .5) * cwid, gy0 + rh / 2, text=name,
                               fill=col["muted"], font=self.f_small)
            weeks = _cal.Calendar(0).monthdatescalendar(year, m + 1)
            rad = max(5, min(cwid, rh) / 2 - 1.5)
            for wi, week in enumerate(weeks):
                for di, day in enumerate(week):
                    if day.month != m + 1:
                        continue
                    cx = gx0 + (di + .5) * cwid
                    cy = gy0 + (wi + 1.5) * rh
                    tags = ("link", "yday", f"day:{day.isoformat()}")
                    evs = by_day.get(day)
                    fg = col["text"] if di < 5 else col["muted"]
                    if evs:
                        best = min(evs, key=lambda e: PRIORITY_RANK.get(e["priority"], 9))
                        fill = self.store.type_color(best["type_id"])
                        cv.create_oval(cx - rad, cy - rad, cx + rad, cy + rad, fill=fill,
                                       outline="", tags=tags)
                        fg = ink_on(fill)
                    if day == today:
                        cv.create_oval(cx - rad, cy - rad, cx + rad, cy + rad,
                                       outline=col["accent"], width=2, tags=tags)
                        if not evs:
                            fg = col["accent"]
                    cv.create_text(cx, cy, text=str(day.day), fill=fg, tags=tags,
                                   font=self.f_small if rad < 9 else self.f_norm)
        cv.tag_bind("link", "<Button-1>", self._on_day_link)

    def _year_tip(self, event):
        day = self._tag_date(self.year_canvas)
        evs = self._year_days.get(day) if day else None
        if not evs:
            self.tip.hide()
            return
        lines = [f"{day.day} de {MONTHS[day.month - 1]}"]
        for ev in evs[:6]:
            hour = f"{ev['start_time']}  " if self.store.is_timed(ev) else ""
            lines.append(f"{hour}{ev['name']}  ({self.store.type_name(ev['type_id'])})")
        if len(evs) > 6:
            lines.append(f"y {len(evs) - 6} más")
        self.tip.show(event.x_root, event.y_root, "\n".join(lines))

    # ---------------------------------------------------- dia y semana
    def _time_days(self):
        if self.view == "day":
            return [self.cursor]
        start = week_start(self.cursor)
        return [start + _dt.timedelta(days=i) for i in range(7)]

    def _draw_time_view(self):
        col = self._colors()
        days = self._time_days()
        self.update_idletasks()
        W = max(self.grid_canvas.winfo_width(), 300)
        n = len(days)
        cw = (W - GUTTER) / n
        today = _dt.date.today()
        events = self._events(days[0], days[-1])
        timed = [e for e in events if self.store.is_timed(e)]
        allday = [e for e in events if not self.store.is_timed(e)]

        # Cabecera
        hc = self.head_canvas
        hc.delete("all")
        hc.configure(height=48)
        for i, day in enumerate(days):
            x0 = GUTTER + i * cw
            tags = ("link", f"day:{day.isoformat()}")
            is_today = day == today
            hc.create_text(x0 + cw / 2, 13, text=WEEKDAYS_SHORT[day.weekday()].capitalize(),
                           fill=col["accent"] if is_today else col["muted"], font=self.f_small,
                           tags=tags)
            if is_today:
                hc.create_oval(x0 + cw / 2 - 15, 20, x0 + cw / 2 + 15, 46, fill=col["accent"],
                               outline="", tags=tags)
            hc.create_text(x0 + cw / 2, 33, text=str(day.day), font=self.f_day_b,
                           fill="#FFFFFF" if is_today else col["text"], tags=tags)
        hc.create_line(0, 47, W, 47, fill=col["line"])
        hc.tag_bind("link", "<Button-1>", self._on_day_link)

        # Franja "todo el dia"
        ac = self.allday_canvas
        ac.delete("all")
        segs = []
        for ev in allday:
            s, e = self.store.start_date(ev), self.store.end_date(ev)
            c0 = max(0, (s - days[0]).days)
            c1 = min(n - 1, (e - days[0]).days)
            segs.append([c0, c1, ev])
        placed = self._lanes(segs)
        lanes = max([lane + 1 for lane, _ in placed] or [0])
        ah = max(26, lanes * LANE_H + 8)
        ac.configure(height=ah)
        ac.create_text(GUTTER - 8, 13, text="Todo el día", anchor="e", fill=col["muted"],
                       font=self.f_small)
        for i, day in enumerate(days):
            x0 = GUTTER + i * cw
            ac.create_line(x0, 0, x0, ah, fill=col["soft"])
        for lane, (c0, c1, ev) in placed:
            y = 4 + lane * LANE_H
            self._draw_bar(ac, ev, GUTTER + c0 * cw + 3, y, GUTTER + (c1 + 1) * cw - 3,
                           y + LANE_H - 3, ev["name"])
        ac.create_line(0, ah - 1, W, ah - 1, fill=col["line"])

        # Rejilla horaria
        gc = self.grid_canvas
        gc.delete("all")
        total = 24 * HOUR_H
        gc.configure(scrollregion=(0, 0, W, total))
        for i, day in enumerate(days):
            x0 = GUTTER + i * cw
            fill = col["today_bg"] if day == today else (
                blend(col["cell"], col["weekend"], 0.6) if day.weekday() >= 5 else col["cell"])
            gc.create_rectangle(x0, 0, x0 + cw, total, fill=fill, outline="")
        for h in range(24):
            y = h * HOUR_H
            gc.create_line(GUTTER - 6, y, W, y, fill=col["line"])
            gc.create_line(GUTTER, y + HOUR_H / 2, W, y + HOUR_H / 2, fill=col["soft"], dash=(2, 4))
            if h:
                gc.create_text(GUTTER - 10, y, text=f"{h:02d}:00", anchor="e",
                               fill=col["muted"], font=self.f_small)
        for i in range(n + 1):
            x = GUTTER + i * cw
            gc.create_line(x, 0, x, total, fill=col["line"])

        for i, day in enumerate(days):
            x0 = GUTTER + i * cw
            day_events = [e for e in timed if e["start"] == day.isoformat()]
            for ev, idx, cols in self._columns_for(day_events):
                start, end = self.store.time_range(ev)
                y0 = start / 60 * HOUR_H + 1
                y1 = max(y0 + 18, end / 60 * HOUR_H - 1)
                w = (cw - 6) / cols
                bx0 = x0 + 3 + idx * w
                bx1 = bx0 + w - 2
                bg, fg = self._event_colors(ev)
                tags = ("ev", f"ev:{ev['id']}")
                outline = self.app.palette()["accent"] if ev["id"] == self.highlight_id else \
                    blend(bg, "#000000", 0.18)
                round_rect(gc, bx0, y0, bx1, y1, 5, fill=bg, outline=outline,
                           width=2 if ev["id"] == self.highlight_id else 1, tags=tags)
                gc.create_rectangle(bx0 + 1, y0 + 3, bx0 + 4, y1 - 3,
                                    fill=blend(bg, "#000000", 0.28), outline="", tags=tags)
                inner = bx1 - bx0 - 12
                time_txt = f"{ev['start_time']} – {ev['end_time'] or '':s}".rstrip(" –")
                if y1 - y0 < 34:
                    gc.create_text(bx0 + 8, (y0 + y1) / 2,
                                   text=self._fit(f"{ev['start_time']}  {ev['name']}", self.f_norm, inner),
                                   anchor="w", fill=fg, font=self.f_norm, tags=tags)
                else:
                    gc.create_text(bx0 + 8, y0 + 5, text=self._fit(ev["name"], self.f_bold, inner),
                                   anchor="nw", fill=fg, font=self.f_bold, tags=tags)
                    gc.create_text(bx0 + 8, y0 + 21, text=self._fit(time_txt, self.f_small, inner),
                                   anchor="nw", fill=blend(fg, bg, 0.25), font=self.f_small, tags=tags)
                    if y1 - y0 > 56 and ev["notes"]:
                        note = " ".join(ev["notes"].split())
                        gc.create_text(bx0 + 8, y0 + 37, text=note, width=max(20, inner),
                                       anchor="nw", fill=blend(fg, bg, 0.3), font=self.f_small,
                                       tags=tags + ("note",))
            if day == today:
                now = _dt.datetime.now()
                y = (now.hour * 60 + now.minute) / 60 * HOUR_H
                gc.create_line(x0, y, x0 + cw, y, fill=NOW_COLOR, width=2)
                gc.create_oval(x0 - 4, y - 4, x0 + 4, y + 4, fill=NOW_COLOR, outline="")
        # las notas largas no deben salirse del bloque: se recortan visualmente
        gc.tag_raise("ev")
        self._clip_notes(gc, timed, days, cw)

        target = getattr(self, "_pending_scroll", None)
        if target is not None:
            gc.yview_moveto(target * HOUR_H / total)
            self._pending_scroll = None
            self._scrolled_to_morning = True
        elif not self._scrolled_to_morning:
            first = min([self.store.time_range(e)[0] for e in timed] or [8 * 60])
            hour = min(8, max(0, first // 60 - 1))
            gc.yview_moveto(hour * HOUR_H / total)
            self._scrolled_to_morning = True

    def _clip_notes(self, gc, timed, days, cw):
        """Recorta el texto de notas que excede la altura de su bloque."""
        for item in gc.find_withtag("note"):
            tags = gc.gettags(item)
            ev_id = next((t[3:] for t in tags if t.startswith("ev:")), None)
            ev = self.store.get(ev_id) if ev_id else None
            if not ev:
                continue
            _, end = self.store.time_range(ev)
            limit = end / 60 * HOUR_H - 4
            text = gc.itemcget(item, "text")
            while text:
                box = gc.bbox(item)
                if not box or box[3] <= limit:
                    break
                words = text.split(" ")
                if len(words) <= 1:
                    gc.delete(item)
                    break
                text = " ".join(words[:-1]).rstrip(".,;") + "…"
                gc.itemconfigure(item, text=text)
                if text == "…":
                    gc.delete(item)
                    break

    @staticmethod
    def _columns_for(events):
        """Reparte eventos solapados en columnas: [(evento, indice, total)]."""
        items = []
        for ev in events:
            s = minutes(ev["start_time"]) or 0
            e = minutes(ev["end_time"])
            if e is None or e <= s:
                e = min(1440, s + 60)
            e = max(e, s + 25)
            items.append((s, e, ev))
        items.sort(key=lambda t: (t[0], -t[1]))
        result = []
        cluster = []
        cluster_end = -1

        def flush():
            if not cluster:
                return
            cols_end = []
            assigned = []
            for s, e, ev in cluster:
                for idx, end in enumerate(cols_end):
                    if end <= s:
                        cols_end[idx] = e
                        break
                else:
                    idx = len(cols_end)
                    cols_end.append(e)
                assigned.append((ev, idx))
            for ev, idx in assigned:
                result.append((ev, idx, len(cols_end)))

        for s, e, ev in items:
            if cluster and s >= cluster_end:
                flush()
                cluster = []
                cluster_end = -1
            cluster.append((s, e, ev))
            cluster_end = max(cluster_end, e)
        flush()
        return result

    def _grid_pos(self, event):
        days = self._time_days()
        W = self.grid_canvas.winfo_width()
        cw = (W - GUTTER) / len(days)
        x = self.grid_canvas.canvasx(event.x)
        y = self.grid_canvas.canvasy(event.y)
        if x < GUTTER:
            return None, None
        idx = min(len(days) - 1, int((x - GUTTER) // cw))
        mins = int(y / HOUR_H * 60) // 30 * 30
        return days[idx], max(0, min(23 * 60 + 30, mins))

    def _grid_double(self, event):
        if self._current_event_id(self.grid_canvas):
            return
        day, mins = self._grid_pos(event)
        if day is None:
            return
        end = min(mins + 60, 23 * 60 + 59)
        self.new_event(day, f"{mins // 60:02d}:{mins % 60:02d}", f"{end // 60:02d}:{end % 60:02d}")

    def _allday_double(self, event):
        if self._current_event_id(self.allday_canvas):
            return
        days = self._time_days()
        cw = (self.allday_canvas.winfo_width() - GUTTER) / len(days)
        if event.x < GUTTER:
            return
        self.new_event(days[min(len(days) - 1, int((event.x - GUTTER) // cw))])

    # ---------------------------------------------------- interaccion
    @staticmethod
    def _current_event_id(canvas):
        for tag in canvas.gettags("current"):
            if tag.startswith("ev:"):
                return tag[3:]
        return None

    @staticmethod
    def _tag_date(canvas):
        for tag in canvas.gettags("current"):
            if tag.startswith("day:"):
                try:
                    return _dt.date.fromisoformat(tag[4:])
                except ValueError:
                    return None
        return None

    def _on_event_click(self, event):
        canvas = event.widget
        ev_id = self._current_event_id(canvas)
        if ev_id:
            self.tip.hide()
            self.app.show_event_in_table(ev_id)
        return "break"

    def _on_day_link(self, event):
        canvas = event.widget
        for tag in canvas.gettags("current"):
            if tag.startswith("day:"):
                day = _dt.date.fromisoformat(tag[4:])
                self.set_view("day", day)
                return "break"
            if tag.startswith("month:"):
                y, m = tag[6:].split("-")
                self.set_view("month", _dt.date(int(y), int(m), 1))
                return "break"
        return None

    def _event_tip(self, event, canvas):
        ev = self.store.get(self._current_event_id(canvas) or "")
        if not ev:
            self.tip.hide()
            return
        s, e = self.store.start_date(ev), self.store.end_date(ev)
        when = s.strftime("%d/%m/%Y")
        if e != s:
            when += " – " + e.strftime("%d/%m/%Y")
        if not ev["all_day"] and ev["start_time"]:
            when += f"  {ev['start_time']}" + (f"–{ev['end_time']}" if ev["end_time"] else "")
        text = (f"{ev['name']}\n{self.store.type_name(ev['type_id'])}   {when}\n"
                f"Prioridad: {ev['priority']}   Estado: {ev['status']}\n"
                "Clic: ver en Eventos")
        self.tip.show(event.x_root, event.y_root, text)

    def _context_menu(self, event, canvas):
        self.tip.hide()
        ev_id = self._current_event_id(canvas)
        menu = tk.Menu(self, tearoff=0)
        if ev_id:
            ev = self.store.get(ev_id)
            menu.add_command(label="Editar", command=lambda: edit_event(self.app, self.store, ev_id))
            menu.add_command(label="Desfijar" if ev["pinned"] else "Fijar",
                             command=lambda: self.store.toggle_pin(ev_id))
            menu.add_command(label="Ver en la tabla de eventos",
                             command=lambda: self.app.show_event_in_table(ev_id))
            menu.add_separator()
            menu.add_command(label="Eliminar", command=lambda: self._delete(ev_id))
        else:
            day, start = None, ""
            if canvas is self.month_canvas:
                day = self._day_at(event.x, event.y)
            elif canvas is self.grid_canvas:
                day, mins = self._grid_pos(event)
                if day is not None:
                    start = f"{mins // 60:02d}:{mins % 60:02d}"
            elif canvas is self.year_canvas:
                day = self._tag_date(canvas)
            day = day or self.cursor
            end = ""
            if start:
                m = min(minutes(start) + 60, 23 * 60 + 59)
                end = f"{m // 60:02d}:{m % 60:02d}"
            label = f"Nuevo evento el {day.day} de {MONTHS[day.month - 1]}"
            if start:
                label += f" a las {start}"
            menu.add_command(label=label, command=lambda: self.new_event(day, start, end))
            menu.add_command(label="Ver este día", command=lambda: self.set_view("day", day))
        menu.tk_popup(event.x_root, event.y_root)

    def _delete(self, ev_id):
        from ui_common import confirm
        ev = self.store.get(ev_id)
        if ev and confirm(self.app, "Eliminar evento", "¿Eliminar este evento?",
                          f"«{ev['name']}» desaparecerá del calendario y de la tabla.",
                          ok_text="Eliminar", kind="danger"):
            self.store.delete_event(ev_id)

    def new_event(self, day=None, start_time="", end_time=""):
        if day is None:
            today = _dt.date.today()
            if self.view == "day":
                day = self.cursor
            elif self.view == "week":
                days = self._time_days()
                day = today if today in days else days[0]
            elif self.view == "month":
                day = today if (today.year, today.month) == (self.cursor.year, self.cursor.month) \
                    else self.cursor.replace(day=1)
            else:
                day = today if today.year == self.cursor.year else _dt.date(self.cursor.year, 1, 1)
        create_event(self.app, self.store, day, start_time, end_time)


