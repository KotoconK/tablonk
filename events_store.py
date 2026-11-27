"""Datos de eventos de TablonK Advance.

Se guardan dentro del config.json del proyecto, en la clave "events":

    {
      "types":   [{"id", "name", "color"}],
      "columns": [{"key", "label", "visible", "width", "builtin"}],
      "items":   [{"id", "name", "type_id", "start", "end", "all_day",
                   "start_time", "end_time", "priority", "status",
                   "notes", "pinned", "custom": {key: valor}}]
    }

Las fechas se guardan en ISO (AAAA-MM-DD) y las horas como HH:MM.
"""

import copy
import datetime as _dt
import unicodedata
import uuid

from rich_notes import clean_runs

NO_TYPE_COLOR = "#D5DAE0"

DEFAULT_TYPES = (
    {"id": "entrega", "name": "Entrega cliente", "color": "#F6B4A8"},
    {"id": "presentacion", "name": "Presentación propuesta", "color": "#A9CBF5"},
)

PRIORITIES = ("Urgente", "Alta", "Media", "Baja")
PRIORITY_RANK = {name: i for i, name in enumerate(PRIORITIES)}
PRIORITY_COLORS = {"Urgente": "#D64545", "Alta": "#E58A2B",
                   "Media": "#3D7BD9", "Baja": "#8A949E"}

STATUSES = ("Pendiente", "En curso", "Hecho", "Cancelado")
CLOSED_STATUSES = ("Hecho", "Cancelado")

BUILTIN_COLUMNS = (
    {"key": "name", "label": "Nombre", "visible": True, "width": 240},
    {"key": "type", "label": "Tipo", "visible": True, "width": 170},
    {"key": "start", "label": "Inicio", "visible": True, "width": 150},
    {"key": "end", "label": "Fin", "visible": True, "width": 150},
    {"key": "priority", "label": "Prioridad", "visible": True, "width": 95},
    {"key": "status", "label": "Estado", "visible": True, "width": 95},
    {"key": "notes", "label": "Notas", "visible": False, "width": 220},
)
BUILTIN_KEYS = tuple(c["key"] for c in BUILTIN_COLUMNS)


def new_id(prefix=""):
    return prefix + uuid.uuid4().hex[:10]


def parse_iso(value):
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def fold(text):
    """Minusculas y sin tildes, para buscar sin importar acentos."""
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def minutes(hhmm):
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


class EventStore:
    def __init__(self, data=None):
        self._listeners = []
        self.load(data)

    # ------------------------------------------------------------ carga
    def load(self, data):
        data = data if isinstance(data, dict) else {}
        raw_types = data.get("types")
        if not isinstance(raw_types, list):
            raw_types = copy.deepcopy(list(DEFAULT_TYPES))
        self.types = []
        seen = set()
        for t in raw_types:
            if not isinstance(t, dict) or not t.get("id") or t["id"] in seen:
                continue
            seen.add(t["id"])
            self.types.append({"id": str(t["id"]), "name": str(t.get("name") or "Tipo"),
                               "color": t.get("color") or NO_TYPE_COLOR})
        self.columns = self._clean_columns(data.get("columns"))
        self.items = []
        for raw in data.get("items", []) if isinstance(data.get("items"), list) else []:
            if isinstance(raw, dict):
                self.items.append(self._clean_event(raw))

    def _clean_columns(self, raw):
        result = []
        seen = set()
        defaults = {c["key"]: c for c in BUILTIN_COLUMNS}
        for col in raw if isinstance(raw, list) else []:
            if not isinstance(col, dict) or not col.get("key") or col["key"] in seen:
                continue
            key = str(col["key"])
            builtin = key in defaults
            if not builtin and not key.startswith("c_"):
                continue
            base = defaults.get(key, {"label": "Campo", "visible": True, "width": 150})
            seen.add(key)
            result.append({
                "key": key,
                "label": str(col.get("label") or base["label"]),
                "visible": True if key == "name" else bool(col.get("visible", base["visible"])),
                "width": int(col.get("width") or base["width"]),
                "builtin": builtin,
            })
        for col in BUILTIN_COLUMNS:          # columnas nuevas de futuras versiones
            if col["key"] not in seen:
                result.append({**col, "builtin": True})
        return result

    def _clean_event(self, raw):
        today = _dt.date.today().isoformat()
        start = parse_iso(raw.get("start")) or parse_iso(today)
        end = parse_iso(raw.get("end")) or start
        if end < start:
            end = start
        priority = raw.get("priority") if raw.get("priority") in PRIORITIES else "Media"
        status = raw.get("status") if raw.get("status") in STATUSES else "Pendiente"
        custom = raw.get("custom") if isinstance(raw.get("custom"), dict) else {}
        attachments = []
        for a in raw.get("attachments") or []:
            if isinstance(a, dict) and isinstance(a.get("path"), str) and a["path"]:
                attachments.append({"name": str(a.get("name") or a["path"].rsplit("/", 1)[-1]),
                                    "path": a["path"], "size": int(a.get("size") or 0)})
        all_day = bool(raw.get("all_day", not raw.get("start_time")))
        return {
            "id": str(raw.get("id") or new_id("e")),
            "name": str(raw.get("name") or "Sin título"),
            "type_id": raw.get("type_id") if raw.get("type_id") else None,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "all_day": all_day,
            "start_time": "" if all_day else str(raw.get("start_time") or ""),
            "end_time": "" if all_day else str(raw.get("end_time") or ""),
            "priority": priority,
            "status": status,
            "notes": str(raw.get("notes") or ""),
            "pinned": bool(raw.get("pinned", False)),
            "custom": {str(k): str(v) for k, v in custom.items()},
            "notes_rich": clean_runs(raw.get("notes_rich")),
            "attachments": attachments,
        }

    def to_dict(self):
        return {"types": copy.deepcopy(self.types),
                "columns": [{k: c[k] for k in ("key", "label", "visible", "width")}
                            for c in self.columns],
                "items": copy.deepcopy(self.items)}

    # ------------------------------------------------------- avisos
    def subscribe(self, callback):
        self._listeners.append(callback)

    def changed(self):
        for callback in list(self._listeners):
            callback()

    # ------------------------------------------------------- tipos
    def type_by_id(self, type_id):
        return next((t for t in self.types if t["id"] == type_id), None)

    def type_name(self, type_id):
        t = self.type_by_id(type_id)
        return t["name"] if t else "Sin tipo"

    def type_color(self, type_id):
        t = self.type_by_id(type_id)
        return t["color"] if t else NO_TYPE_COLOR

    def count_by_type(self, type_id):
        return sum(1 for e in self.items if e["type_id"] == type_id)

    def set_types(self, types):
        valid = {t["id"] for t in types}
        self.types = copy.deepcopy(types)
        for event in self.items:
            if event["type_id"] and event["type_id"] not in valid:
                event["type_id"] = None
        self.changed()

    # ------------------------------------------------------ columnas
    def visible_columns(self):
        return [c for c in self.columns if c["visible"]]

    def custom_columns(self):
        return [c for c in self.columns if not c["builtin"]]

    def set_columns(self, columns):
        keys = {c["key"] for c in columns}
        self.columns = self._clean_columns(columns)
        for event in self.items:
            event["custom"] = {k: v for k, v in event["custom"].items() if k in keys}
        self.changed()

    def set_column_width(self, key, width):
        for col in self.columns:
            if col["key"] == key:
                col["width"] = int(width)

    # ------------------------------------------------------ eventos
    def get(self, event_id):
        return next((e for e in self.items if e["id"] == event_id), None)

    def new_event(self, day=None, start_time="", end_time="", type_id=None):
        day = day or _dt.date.today()
        if type_id is None and self.types:
            type_id = self.types[0]["id"]
        return self._clean_event({
            "id": new_id("e"), "name": "", "type_id": type_id,
            "start": day.isoformat(), "end": day.isoformat(),
            "all_day": not start_time, "start_time": start_time,
            "end_time": end_time,
        }) | {"name": ""}

    def save_event(self, event):
        clean = self._clean_event(event)
        for i, existing in enumerate(self.items):
            if existing["id"] == clean["id"]:
                self.items[i] = clean
                break
        else:
            self.items.append(clean)
        self.changed()
        return clean

    def delete_event(self, event_id):
        self.items = [e for e in self.items if e["id"] != event_id]
        self.changed()

    def duplicate_event(self, event_id):
        event = self.get(event_id)
        if not event:
            return None
        copy_ = copy.deepcopy(event)
        copy_["id"] = new_id("e")
        copy_["name"] = event["name"] + " (copia)"
        copy_["pinned"] = False
        self.items.append(copy_)
        self.changed()
        return copy_

    def toggle_pin(self, event_id):
        event = self.get(event_id)
        if event:
            event["pinned"] = not event["pinned"]
            self.changed()

    def pinned(self):
        return sorted((e for e in self.items if e["pinned"]), key=self.sort_key_start)

    # ---------------------------------------------------- consultas
    @staticmethod
    def start_date(event):
        return parse_iso(event["start"])

    @staticmethod
    def end_date(event):
        return parse_iso(event["end"]) or parse_iso(event["start"])

    @staticmethod
    def sort_key_start(event):
        return (event["start"], "" if event["all_day"] else (event["start_time"] or "99:99"),
                event["name"].lower())

    def events_between(self, first, last, type_filter=None):
        """Eventos que se solapan con el intervalo [first, last]."""
        result = []
        for event in self.items:
            if type_filter is not None and event["type_id"] not in type_filter:
                continue
            s, e = self.start_date(event), self.end_date(event)
            if s and e and s <= last and e >= first:
                result.append(event)
        result.sort(key=self.sort_key_start)
        return result

    def is_timed(self, event):
        """Evento con hora dentro de un solo dia (se dibuja en la rejilla horaria)."""
        return (not event["all_day"] and bool(event["start_time"])
                and event["start"] == event["end"])

    def time_range(self, event):
        start = minutes(event["start_time"]) or 0
        end = minutes(event["end_time"])
        if end is None or end <= start:
            end = min(24 * 60, start + 60)
        return start, end

    def search_text(self, event):
        parts = [event["name"], event["notes"], self.type_name(event["type_id"]),
                 event["priority"], event["status"], *event["custom"].values(),
                 *(a["name"] for a in event.get("attachments", [])),
                 *(r.get("link", "") for r in event.get("notes_rich", []))]
        return fold(" ".join(parts))

    def filtered(self, query="", type_filter=None, priorities=None, show_closed=True):
        tokens = fold(query).split()
        result = []
        for event in self.items:
            if type_filter is not None and event["type_id"] not in type_filter:
                continue
            if priorities is not None and event["priority"] not in priorities:
                continue
            if not show_closed and event["status"] in CLOSED_STATUSES:
                continue
            if tokens:
                haystack = self.search_text(event)
                if not all(tok in haystack for tok in tokens):
                    continue
            result.append(event)
        return result

    def cell_text(self, event, key):
        if key == "name":
            return event["name"]
        if key == "type":
            return self.type_name(event["type_id"])
        if key in ("start", "end"):
            day = parse_iso(event[key])
            text = day.strftime("%d/%m/%Y") if day else ""
            hour = event["start_time" if key == "start" else "end_time"]
            if hour and not event["all_day"]:
                text += "  " + hour
            return text
        if key == "notes":
            return " ".join(event["notes"].split())
        if key in ("priority", "status"):
            return event[key]
        return event["custom"].get(key, "")

    def sort_value(self, event, key):
        if key == "start":
            return (event["start"], event["start_time"] or "")
        if key == "end":
            return (event["end"], event["end_time"] or "")
        if key == "priority":
            return PRIORITY_RANK.get(event["priority"], 9)
        if key == "status":
            return STATUSES.index(event["status"]) if event["status"] in STATUSES else 9
        return fold(self.cell_text(event, key))
