"""Notas con texto enriquecido para los eventos.

Formato guardado (lista de "runs", en el evento como "notes_rich"):
    {"text": "...", "b": bool, "i": bool, "u": bool, "s": bool,
     "h": 0|1|2, "link": "https://..."}          -> texto
    {"image": "assets/eventos/xxx.png", "w": 320} -> imagen incrustada

Las listas son texto normal que empieza por "• " o "1. ", asi siguen siendo
legibles en la tabla y en la busqueda. El texto plano se guarda ademas en
"notes" para la columna Notas y el buscador.
"""

import io
import os
import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import project_files as pf
from ui_common import UI_FONT, Dialog, FlatButton, alert, ask_open_filename, styled_entry

try:
    from PIL import Image, ImageGrab, ImageOps, ImageTk
except ImportError:
    Image = ImageGrab = ImageOps = ImageTk = None

BULLET = "• "
LIST_RE = re.compile(r"^(• |(\d+)\. )")
SIZES = {"Pequeña": 180, "Mediana": 320, "Grande": 520}
STYLE_KEYS = ("h", "b", "i", "u", "s")


def plain_from_runs(runs):
    return "".join(r.get("text", "") for r in runs if isinstance(r, dict)).strip()


def clean_runs(runs):
    """Valida lo leido del config.json."""
    result = []
    for r in runs if isinstance(runs, list) else []:
        if not isinstance(r, dict):
            continue
        if isinstance(r.get("image"), str):
            try:
                w = int(r.get("w") or 320)
            except (TypeError, ValueError):
                w = 320
            result.append({"image": r["image"], "w": max(40, min(1200, w))})
        elif isinstance(r.get("text"), str) and r["text"]:
            h = r.get("h") if r.get("h") in (0, 1, 2) else 0
            run = {"text": r["text"], "h": h}
            for k in ("b", "i", "u", "s"):
                run[k] = bool(r.get(k, False))
            if isinstance(r.get("link"), str) and r["link"].strip():
                run["link"] = r["link"].strip()
            result.append(run)
    return result


class RichText(tk.Frame):
    def __init__(self, parent, app, editable=True, height=8, width=50, on_change=None):
        p = app.palette()
        super().__init__(parent, bg=p["border"])
        self.app = app
        self.editable = editable
        self.on_change = on_change
        self.images = {}            # nombre Tk -> {"asset", "w", "photo"}
        self.links = {}             # etiqueta -> destino
        self._fonts = {}
        self._link_seq = 0
        inner = tk.Frame(self, bg=p["button_bg"])
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.text = tk.Text(inner, wrap="word", relief="flat", bd=0, undo=editable,
                            height=height, width=width, padx=10, pady=8,
                            font=(UI_FONT, 10), highlightthickness=0, spacing1=1, spacing3=2)
        self.bar = ttk.Scrollbar(inner, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.inner = inner
        self.text.tag_configure("li", lmargin1=6, lmargin2=24)
        self.text.tag_configure("link", underline=True)
        self.text.tag_bind("link", "<Enter>", lambda e: self.text.configure(cursor="hand2"))
        self.text.tag_bind("link", "<Leave>", lambda e: self.text.configure(
            cursor="xterm" if self.editable else "arrow"))
        if editable:
            self.text.tag_bind("link", "<Control-Button-1>", self._click_link)
            self.text.bind("<Return>", self._on_return)
            self.text.bind("<Control-v>", self._on_paste)
            self.text.bind("<Control-V>", self._on_paste)
            self.text.bind("<Control-b>", lambda e: (self.toggle("b"), "break")[1])
            self.text.bind("<Control-i>", lambda e: (self.toggle("i"), "break")[1])
            self.text.bind("<Control-u>", lambda e: (self.toggle("u"), "break")[1])
            self.text.bind("<Control-k>", lambda e: (self.insert_link(), "break")[1])
            self.text.bind("<<Modified>>", self._modified)
            self.text.bind("<Button-3>", self._context_menu)
        else:
            self.text.tag_bind("link", "<Button-1>", self._click_link)
            self.text.configure(cursor="arrow", insertwidth=0)
            self.text.bind("<Button-3>", self._context_menu)
            for seq in ("<Key>",):
                self.text.bind(seq, self._readonly_key)
        self.restyle()

    # ------------------------------------------------------------ tema
    def restyle(self, bg=None):
        p = self.app.palette()
        bg = bg or p["button_bg"]
        self.configure(bg=p["border"])
        self.inner.configure(bg=bg)
        self.text.configure(bg=bg, fg=p["text"], insertbackground=p["text"],
                            selectbackground=p["accent"], selectforeground="#FFFFFF")
        self.text.tag_configure("link", foreground=p["accent"])

    def _readonly_key(self, event):
        if event.state & 0x4 and event.keysym.lower() in ("c", "a"):
            return None
        if event.keysym in ("Up", "Down", "Left", "Right", "Prior", "Next", "Home", "End"):
            return None
        return "break"

    def _modified(self, _e=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            if self.on_change:
                self.on_change()

    # ---------------------------------------------------------- fuentes
    def _style_tag(self, h=0, b=False, i=False, u=False, s=False):
        name = f"st{h}{int(b)}{int(i)}{int(u)}{int(s)}"
        if name not in self._fonts:
            size = {0: 10, 1: 15, 2: 12}[h]
            weight = "bold" if (b or h) else "normal"
            f = tkfont.Font(family=UI_FONT, size=size, weight=weight,
                            slant="italic" if i else "roman",
                            underline=1 if u else 0, overstrike=1 if s else 0)
            self._fonts[name] = f
            spacing = {0: 1, 1: 8, 2: 6}[h]
            self.text.tag_configure(name, font=f, spacing1=spacing)
            self.text.tag_lower(name)
        return name

    def _style_at(self, index):
        for tag in self.text.tag_names(index):
            if len(tag) == 7 and tag.startswith("st"):
                bits = tag[2:]
                return {"h": int(bits[0]), "b": bits[1] == "1", "i": bits[2] == "1",
                        "u": bits[3] == "1", "s": bits[4] == "1"}
        return {"h": 0, "b": False, "i": False, "u": False, "s": False}

    def _set_style(self, start, end, st):
        for name in list(self._fonts):
            self.text.tag_remove(name, start, end)
        if any(st[k] for k in ("b", "i", "u", "s")) or st["h"]:
            self.text.tag_add(self._style_tag(**st), start, end)

    # ------------------------------------------------------ cargar/guardar
    def clear(self):
        state = self.text.cget("state")
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.images.clear()
        for tag in list(self.links):
            self.text.tag_delete(tag)
        self.links.clear()
        self.text.configure(state=state)

    def load(self, runs, plain=""):
        self.text.configure(state="normal")
        self.clear()
        runs = clean_runs(runs)
        if not runs and plain:
            runs = [{"text": plain, "h": 0}]
        for run in runs:
            if "image" in run:
                self._insert_image("end", run["image"], run["w"])
                continue
            tags = []
            st = {k: run.get(k, 0 if k == "h" else False) for k in STYLE_KEYS}
            if st["h"] or any(st[k] for k in ("b", "i", "u", "s")):
                tags.append(self._style_tag(**st))
            if run.get("link"):
                tags += ["link", self._new_link_tag(run["link"])]
            self.text.insert("end", run["text"], tuple(tags))
        self.refresh_lists()
        self.text.edit_reset()
        self.text.edit_modified(False)
        if not self.editable:
            self.text.configure(state="disabled")

    def dump(self):
        runs = []
        active = set()
        for key, value, index in self.text.dump("1.0", "end-1c", text=True, tag=True, image=True):
            if key == "tagon":
                active.add(value)
            elif key == "tagoff":
                active.discard(value)
            elif key == "image":
                info = self.images.get(value)
                if info:
                    runs.append({"image": info["asset"], "w": info["w"]})
            elif key == "text" and value:
                st = {"h": 0, "b": False, "i": False, "u": False, "s": False}
                link = ""
                for tag in active:
                    if len(tag) == 7 and tag.startswith("st"):
                        bits = tag[2:]
                        st = {"h": int(bits[0]), "b": bits[1] == "1", "i": bits[2] == "1",
                              "u": bits[3] == "1", "s": bits[4] == "1"}
                    elif tag in self.links:
                        link = self.links[tag]
                run = {"text": value, **st}
                if link:
                    run["link"] = link
                prev = runs[-1] if runs else None
                if prev and "text" in prev and {k: prev.get(k) for k in (*STYLE_KEYS, "link")} == \
                        {k: run.get(k) for k in (*STYLE_KEYS, "link")}:
                    prev["text"] += value
                else:
                    runs.append(run)
        # quitar saltos de linea finales sobrantes
        while runs and "text" in runs[-1] and not runs[-1]["text"].strip("\n "):
            runs.pop()
        if runs and "text" in runs[-1]:
            runs[-1]["text"] = runs[-1]["text"].rstrip()
            if not runs[-1]["text"]:
                runs.pop()
        return runs

    def plain_text(self):
        return self.text.get("1.0", "end-1c").strip()

    def is_empty(self):
        return not self.plain_text() and not self.images

    # ------------------------------------------------------------ estilo
    def _selection(self):
        try:
            return self.text.index("sel.first"), self.text.index("sel.last")
        except tk.TclError:
            return None

    def _each_char(self, start, end):
        idx = start
        while self.text.compare(idx, "<", end):
            nxt = self.text.index(f"{idx}+1c")
            yield idx, nxt
            idx = nxt

    def toggle(self, attr):
        sel = self._selection()
        if not sel:
            return
        start, end = sel
        all_on = all(self._style_at(i)[attr] for i, _ in self._each_char(start, end)
                     if self.text.get(i) not in ("\n", ""))
        for i, nxt in self._each_char(start, end):
            st = self._style_at(i)
            st[attr] = not all_on
            self._set_style(i, nxt, st)
        self.text.tag_add("sel", start, end)
        self._changed()

    def _line_range(self):
        sel = self._selection()
        if sel:
            first = int(sel[0].split(".")[0])
            last_idx = sel[1]
            last = int(last_idx.split(".")[0])
            if last_idx.endswith(".0") and last > first:
                last -= 1
        else:
            first = last = int(self.text.index("insert").split(".")[0])
        return first, last

    def toggle_heading(self, level=1):
        first, last = self._line_range()
        start, end = f"{first}.0", f"{last}.end"
        chars = [(i, n) for i, n in self._each_char(start, end) if self.text.get(i)]
        all_on = chars and all(self._style_at(i)["h"] == level for i, _ in chars)
        for i, nxt in chars:
            st = self._style_at(i)
            st["h"] = 0 if all_on else level
            self._set_style(i, nxt, st)
        self._changed()

    def clear_format(self):
        sel = self._selection()
        if not sel:
            first, last = self._line_range()
            sel = (f"{first}.0", f"{last}.end")
        for name in list(self._fonts):
            self.text.tag_remove(name, *sel)
        for tag in list(self.links):
            self.text.tag_remove(tag, *sel)
        self.text.tag_remove("link", *sel)
        self._changed()

    # ------------------------------------------------------------ listas
    def toggle_list(self, kind="bullet"):
        first, last = self._line_range()
        lines = range(first, last + 1)
        def has(ln):
            m = LIST_RE.match(self.text.get(f"{ln}.0", f"{ln}.end"))
            return m and ((kind == "bullet") == (m.group(1) == BULLET))
        remove = all(has(ln) for ln in lines)
        n = 1
        for ln in lines:
            content = self.text.get(f"{ln}.0", f"{ln}.end")
            m = LIST_RE.match(content)
            if m:
                self.text.delete(f"{ln}.0", f"{ln}.{len(m.group(1))}")
            if not remove:
                self.text.insert(f"{ln}.0", BULLET if kind == "bullet" else f"{n}. ")
                n += 1
        self.refresh_lists()
        self._changed()

    def refresh_lists(self):
        state = self.text.cget("state")
        self.text.tag_remove("li", "1.0", "end")
        last = int(self.text.index("end-1c").split(".")[0])
        for ln in range(1, last + 1):
            if LIST_RE.match(self.text.get(f"{ln}.0", f"{ln}.end")):
                self.text.tag_add("li", f"{ln}.0", f"{ln}.end+1c")
        self.text.configure(state=state)

    def _on_return(self, _event):
        line = self.text.get("insert linestart", "insert lineend")
        m = LIST_RE.match(line)
        if not m:
            self.after_idle(self.refresh_lists)
            return None
        if line.strip() == m.group(1).strip():          # elemento vacio: termina la lista
            self.text.delete("insert linestart", "insert lineend")
            self.refresh_lists()
            return "break"
        prefix = BULLET if m.group(1) == BULLET else f"{int(m.group(2)) + 1}. "
        self.text.insert("insert", "\n" + prefix)
        self.text.see("insert")
        self.refresh_lists()
        return "break"

    # ------------------------------------------------------------ enlaces
    def _new_link_tag(self, target):
        self._link_seq += 1
        tag = f"lk{self._link_seq}"
        self.links[tag] = target
        self.text.tag_configure(tag)
        self.text.tag_raise(tag)
        return tag

    def _link_at(self, index):
        for tag in self.text.tag_names(index):
            if tag in self.links:
                return tag
        return None

    def _click_link(self, event):
        tag = self._link_at(f"@{event.x},{event.y}")
        if tag:
            try:
                pf.open_link(self.links[tag])
            except OSError as exc:
                alert(self.app, "Abrir enlace", "No se pudo abrir el enlace.", str(exc),
                      "warning", parent=self.winfo_toplevel())
        return "break"

    def insert_link(self, index=None):
        sel = self._selection()
        current_tag = self._link_at(index or (sel[0] if sel else "insert"))
        text = self.text.get(*sel) if sel else ""
        target = self.links.get(current_tag, "")
        result = LinkDialog(self.app, text, target, with_text=not sel,
                            parent=self.winfo_toplevel()).show(width=440)
        if not result:
            return
        label, target = result
        target = pf.normalize_link(target)
        if sel:
            start, end = sel
            for tag in list(self.links):
                self.text.tag_remove(tag, start, end)
            if target:
                self.text.tag_add("link", start, end)
                self.text.tag_add(self._new_link_tag(target), start, end)
            else:
                self.text.tag_remove("link", start, end)
        elif target:
            label = label or target
            st = self._style_at("insert-1c") if self.text.compare("insert", ">", "1.0") else None
            tags = ["link", self._new_link_tag(target)]
            if st and (st["h"] or any(st[k] for k in ("b", "i", "u", "s"))):
                tags.append(self._style_tag(**st))
            self.text.insert("insert", label, tuple(tags))
            self.text.insert("insert", " ")
        self._changed()

    def _remove_link(self, tag):
        ranges = self.text.tag_ranges(tag)
        for i in range(0, len(ranges), 2):
            self.text.tag_remove("link", ranges[i], ranges[i + 1])
        self.text.tag_delete(tag)
        self.links.pop(tag, None)
        self._changed()

    # ------------------------------------------------------------ imagenes
    def _photo(self, asset, width):
        path = pf.resolve(self.app, asset)
        if Image is None or not path or not os.path.isfile(path):
            return None
        try:
            with Image.open(path) as original:
                img = ImageOps.exif_transpose(original).convert("RGBA")
                if img.width > width:
                    img = img.resize((width, max(1, round(img.height * width / img.width))),
                                     Image.Resampling.LANCZOS)
                return ImageTk.PhotoImage(img, master=self)
        except OSError:
            return None

    def _missing_photo(self):
        from icons import get_icon
        return get_icon(self, "image", self.app.palette()["muted_text"], 40)

    def _insert_image(self, index, asset, width=320):
        photo = self._photo(asset, width) or self._missing_photo()
        if photo is None:
            return None
        name = self.text.image_create(index, image=photo, padx=2, pady=4)
        self.images[name] = {"asset": asset, "w": width, "photo": photo}
        return name

    def insert_image_file(self, path=None):
        if path is None:
            path = ask_open_filename(self.app, parent=self.winfo_toplevel(),
                                     title="Insertar imagen en las notas",
                                     filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                                                ("Todos los archivos", "*.*")])
        if not path:
            return
        try:
            if Image is None:
                raise OSError("Pillow no está instalado.")
            with Image.open(path) as test:
                test.verify()
            asset, _size = pf.store_file(self.app, path)
        except (OSError, ValueError) as exc:
            alert(self.app, "Insertar imagen", "No se pudo insertar la imagen.", str(exc),
                  "error", parent=self.winfo_toplevel())
            return
        self._insert_image("insert", asset)
        self._changed()

    def _on_paste(self, _event):
        if Image is None or ImageGrab is None:
            return None
        try:
            data = ImageGrab.grabclipboard()
        except (OSError, RuntimeError, NotImplementedError):
            data = None
        if isinstance(data, Image.Image):
            buffer = io.BytesIO()
            data.convert("RGBA" if "A" in data.getbands() else "RGB").save(buffer, "PNG")
            asset = pf.store_bytes(self.app, buffer.getvalue(), "captura.png")
            self._insert_image("insert", asset)
            self._changed()
            return "break"
        if isinstance(data, list):
            images = [f for f in data if os.path.isfile(f) and pf.is_image(f)]
            for f in images:
                self.insert_image_file(f)
            if images:
                return "break"
        return None

    def _image_at(self, index):
        try:
            name = self.text.image_cget(index, "name")
        except tk.TclError:
            return None
        return name if name in self.images else None

    def _resize_image(self, name, width):
        info = self.images.get(name)
        if not info:
            return
        index = self.text.index(name)
        self.text.delete(index)
        self.images.pop(name, None)
        self._insert_image(index, info["asset"], width)
        self._changed()

    # ------------------------------------------------------------ menu
    def _context_menu(self, event):
        index = self.text.index(f"@{event.x},{event.y}")
        menu = tk.Menu(self, tearoff=0)
        image = self._image_at(index)
        link = self._link_at(index)
        if image:
            path = pf.resolve(self.app, self.images[image]["asset"])
            menu.add_command(label="Abrir imagen", command=lambda: pf.open_path(path))
            if self.editable:
                sub = tk.Menu(menu, tearoff=0)
                for label, w in SIZES.items():
                    sub.add_command(label=label, command=lambda w=w: self._resize_image(image, w))
                menu.add_cascade(label="Tamaño", menu=sub)
                menu.add_command(label="Quitar imagen",
                                 command=lambda: (self.text.delete(self.text.index(image)),
                                                  self.images.pop(image, None), self._changed()))
        elif link:
            target = self.links[link]
            menu.add_command(label="Abrir enlace", command=lambda: pf.open_link(target))
            menu.add_command(label="Copiar dirección",
                             command=lambda: (self.clipboard_clear(), self.clipboard_append(target)))
            if self.editable:
                menu.add_command(label="Editar enlace", command=lambda: self._edit_link(link))
                menu.add_command(label="Quitar enlace", command=lambda: self._remove_link(link))
        else:
            if self._selection():
                menu.add_command(label="Copiar", command=lambda: self.text.event_generate("<<Copy>>"))
            if self.editable:
                if self._selection():
                    menu.add_command(label="Cortar", command=lambda: self.text.event_generate("<<Cut>>"))
                menu.add_command(label="Pegar", command=lambda: (
                    self._on_paste(None) or self.text.event_generate("<<Paste>>")))
                menu.add_separator()
                menu.add_command(label="Insertar enlace...", command=self.insert_link)
                menu.add_command(label="Insertar imagen...", command=self.insert_image_file)
            if menu.index("end") is None:
                return "break"
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _edit_link(self, tag):
        ranges = self.text.tag_ranges(tag)
        if not ranges:
            return
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", ranges[0], ranges[-1])
        self.insert_link(index=ranges[0])

    def _changed(self):
        if self.on_change:
            self.on_change()


class LinkDialog(Dialog):
    def __init__(self, app, text, target, with_text=True, parent=None):
        super().__init__(app, "Enlace", parent)
        p = app.palette()
        body = tk.Frame(self, bg=self.bg)
        body.pack(fill="both", padx=20, pady=(18, 6))
        body.grid_columnconfigure(1, weight=1)
        self.text_var = tk.StringVar(value=text)
        self.target_var = tk.StringVar(value=target)
        row = 0
        if with_text:
            tk.Label(body, text="Texto", bg=self.bg, fg=p["muted_text"],
                     font=(UI_FONT, 9)).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
            styled_entry(body, app, width=40, textvariable=self.text_var).grid(
                row=row, column=1, sticky="ew", ipady=3)
            row += 1
        tk.Label(body, text="Dirección", bg=self.bg, fg=p["muted_text"],
                 font=(UI_FONT, 9)).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        self.target_entry = styled_entry(body, app, width=40, textvariable=self.target_var)
        self.target_entry.grid(row=row, column=1, sticky="ew", ipady=3)
        tk.Label(body, text="Una web (ejemplo.com), un correo o la ruta de un archivo o carpeta.",
                 bg=self.bg, fg=p["muted_text"], font=(UI_FONT, 8)).grid(
            row=row + 1, column=1, sticky="w", pady=(2, 0))
        bar = tk.Frame(self, bg=self.bg)
        bar.pack(fill="x", padx=16, pady=14)
        FlatButton(bar, app, text="Aceptar", kind="accent", padx=16, pady=5,
                   font=(UI_FONT, 9, "bold"), command=self._ok).pack(side="right", padx=(6, 0))
        FlatButton(bar, app, text="Cancelar", padx=16, pady=5, font=(UI_FONT, 9, "bold"),
                   command=self.cancel).pack(side="right")
        self.bind("<Return>", lambda e: self._ok())
        self.after(50, self.target_entry.focus_set)

    def _ok(self):
        self.result = (self.text_var.get().strip(), self.target_var.get().strip())
        self.close()


class RichToolbar(tk.Frame):
    """Barra de formato para un RichText editable."""

    def __init__(self, parent, app, rich):
        super().__init__(parent, bg=app.palette()["button_bg"])
        self.app = app
        self.rich = rich
        self.buttons = []
        letters = (("B", "b", "Negrita (Ctrl+B)", "bold"), ("I", "i", "Cursiva (Ctrl+I)", "italic"),
                   ("U", "u", "Subrayado (Ctrl+U)", "underline"), ("S", "s", "Tachado", "overstrike"))
        for text, attr, tip, style in letters:
            font = tkfont.Font(family=UI_FONT, size=10, **(
                {"weight": "bold"} if style == "bold" else {"slant": "italic"} if style == "italic"
                else {"underline": 1} if style == "underline" else {"overstrike": 1}))
            self._add(text=text, font=font, tooltip=tip, width=2,
                      command=lambda a=attr: self.rich.toggle(a))
        self._sep()
        self._add(icon="heading", tooltip="Título", command=lambda: self.rich.toggle_heading(1))
        self._add(text="T", font=tkfont.Font(family=UI_FONT, size=8, weight="bold"),
                  tooltip="Subtítulo", width=2, command=lambda: self.rich.toggle_heading(2))
        self._add(icon="list", tooltip="Lista con viñetas",
                  command=lambda: self.rich.toggle_list("bullet"))
        self._add(icon="list_numbered", tooltip="Lista numerada",
                  command=lambda: self.rich.toggle_list("number"))
        self._sep()
        self._add(icon="chain", tooltip="Enlace a web, correo o archivo (Ctrl+K)",
                  command=self.rich.insert_link)
        self._add(icon="image", tooltip="Insertar imagen (también Ctrl+V con una captura)",
                  command=self.rich.insert_image_file)
        self._sep()
        self._add(icon="clear_format", tooltip="Quitar formato", command=self.rich.clear_format)

    def _add(self, **kw):
        b = FlatButton(self, self.app, kind="ghost", bg_key="button_bg", padx=5, pady=2, **kw)
        b.pack(side="left", padx=1)
        self.buttons.append(b)
        return b

    def _sep(self):
        tk.Frame(self, width=1, bg=self.app.palette()["border"]).pack(side="left", fill="y",
                                                                     padx=5, pady=4)
