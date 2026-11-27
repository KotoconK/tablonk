"""Configuracion de TablonK Advance: apariencia y actualizaciones."""

import json
import os
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

import updater
from icons import get_icon
from ui_common import UI_FONT, Dialog, FlatButton, alert, confirm, styled_entry
from version import APP_NAME, APP_VERSION, GITHUB_REPO

SETTINGS_FILE = "tablonk_ajustes.json"
DEFAULTS = {"update_repo": GITHUB_REPO, "check_on_start": True,
            "include_prerelease": False, "skipped_version": ""}


def load_settings(folder):
    data = dict(DEFAULTS)
    try:
        with open(os.path.join(folder, SETTINGS_FILE), "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            data.update({k: raw[k] for k in DEFAULTS if k in raw})
    except (OSError, ValueError):
        pass
    return data


def save_settings(folder, data):
    try:
        with open(os.path.join(folder, SETTINGS_FILE), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


class BackgroundTask:
    """Ejecuta 'work' en un hilo y entrega mensajes al hilo de Tk."""

    def __init__(self, widget, work, on_message):
        self.widget = widget
        self.queue = queue.Queue()
        self.on_message = on_message
        self.cancelled = False
        self.thread = threading.Thread(target=self._run, args=(work,), daemon=True)
        self.thread.start()
        self._poll()

    def _run(self, work):
        try:
            work(self.queue.put, lambda: self.cancelled)
        except updater.UpdateError as exc:
            self.queue.put(("error", str(exc)))
        except Exception as exc:  # error inesperado: se informa sin cerrar la app
            self.queue.put(("error", f"Error inesperado: {exc}"))

    def _poll(self):
        try:
            while True:
                self.on_message(self.queue.get_nowait())
        except queue.Empty:
            pass
        except tk.TclError:
            return
        if self.thread.is_alive() or not self.queue.empty():
            try:
                self.widget.after(100, self._poll)
            except tk.TclError:
                pass


def check_in_background(app, settings, on_result):
    """Comprobacion silenciosa al iniciar: on_result(release|None)."""
    def work(put, _cancelled):
        release = updater.check_latest(settings["update_repo"], settings["include_prerelease"])
        put(("release", release))

    def handle(msg):
        if msg[0] == "release":
            on_result(msg[1])
    BackgroundTask(app, work, handle)


class SettingsDialog(Dialog):
    def __init__(self, app, auto_check=False):
        super().__init__(app, f"Configuración de {APP_NAME}")
        self.settings = dict(app.settings)
        self.release = None
        self.task = None
        p = app.palette()
        self._section_bg = p["button_bg"]

        head = tk.Frame(self, bg=self.bg)
        head.pack(fill="x", padx=22, pady=(18, 8))
        logo = getattr(app, "_titlebar_icon_image", None)
        if logo is not None:
            tk.Label(head, image=logo, bg=self.bg).pack(side="left", padx=(0, 10))
        tk.Label(head, text=APP_NAME, bg=self.bg, fg=p["text"],
                 font=(UI_FONT, 15, "bold")).pack(side="left")
        tk.Label(head, text=f"versión {APP_VERSION}", bg=self.bg, fg=p["muted_text"],
                 font=(UI_FONT, 9)).pack(side="left", padx=10, pady=(6, 0))

        # Apariencia
        box = self._section("Apariencia", "sun")
        row = tk.Frame(box, bg=self._section_bg)
        row.pack(fill="x", pady=(2, 0))
        tk.Label(row, text="Tema", bg=self._section_bg, fg=p["text"],
                 font=(UI_FONT, 9), width=12, anchor="w").pack(side="left")
        self.theme_btns = {}
        for key, label, icon in (("light", "Claro", "sun"), ("dark", "Oscuro", "moon")):
            b = FlatButton(row, app, text=label, icon=icon, padx=10, pady=3,
                           command=lambda k=key: self._set_theme(k))
            b.configure(bg=p["app_bg"])
            b.pack(side="left", padx=(0, 4))
            self.theme_btns[key] = b
        self._sync_theme_buttons()

        # Actualizaciones
        box = self._section("Actualizaciones", "download")
        r1 = tk.Frame(box, bg=self._section_bg)
        r1.pack(fill="x", pady=2)
        tk.Label(r1, text="Repositorio", bg=self._section_bg, fg=p["text"],
                 font=(UI_FONT, 9), width=12, anchor="w").pack(side="left")
        self.repo_var = tk.StringVar(value=self.settings["update_repo"])
        styled_entry(r1, app, width=30, textvariable=self.repo_var).pack(side="left", ipady=3)
        FlatButton(r1, app, icon="link", padx=4, tooltip="Abrir las releases en el navegador",
                   command=self._open_repo).pack(side="left", padx=4)
        self.check_start = tk.BooleanVar(value=self.settings["check_on_start"])
        self.prerelease = tk.BooleanVar(value=self.settings["include_prerelease"])
        for text, var in (("Buscar actualizaciones al iniciar", self.check_start),
                          ("Incluir versiones preliminares (pre-release)", self.prerelease)):
            tk.Checkbutton(box, text=text, variable=var, bg=self._section_bg, fg=p["text"],
                           activebackground=self._section_bg, activeforeground=p["text"],
                           selectcolor=p["app_bg"], font=(UI_FONT, 9), bd=0,
                           highlightthickness=0, command=self._store).pack(anchor="w", pady=1)
        r2 = tk.Frame(box, bg=self._section_bg)
        r2.pack(fill="x", pady=(8, 2))
        self.check_btn = FlatButton(r2, app, text="Buscar actualizaciones", icon="refresh",
                                    padx=10, pady=4, command=self.check)
        self.check_btn.configure(bg=p["app_bg"])
        self.check_btn.pack(side="left")
        self.install_btn = FlatButton(r2, app, text="Descargar e instalar", icon="download",
                                      kind="accent", padx=10, pady=4,
                                      font=(UI_FONT, 9, "bold"), command=self.install)
        self.status_icon = tk.Label(box, bg=self._section_bg)
        self.status = tk.Label(box, text="", bg=self._section_bg, fg=p["muted_text"],
                               font=(UI_FONT, 9), justify="left", anchor="w", wraplength=430)
        self.status.pack(fill="x", pady=(8, 0))
        self.progress = ttk.Progressbar(box, mode="determinate", maximum=100)
        self.notes = tk.Text(box, height=7, width=56, wrap="word", relief="flat", bd=0,
                             bg=p["app_bg"], fg=p["text"], font=(UI_FONT, 9), padx=8, pady=6,
                             highlightthickness=0)
        mode = "ejecutable de Windows" if updater.is_frozen() else "código Python"
        tk.Label(box, text=f"Instalación actual: {mode} en {updater.app_dir()}",
                 bg=self._section_bg, fg=p["muted_text"], font=(UI_FONT, 8), anchor="w",
                 justify="left", wraplength=430).pack(fill="x", pady=(6, 0))

        footer = tk.Frame(self, bg=self.bg)
        footer.pack(fill="x", padx=18, pady=16)
        FlatButton(footer, app, text="Cerrar", padx=16, pady=5, font=(UI_FONT, 9, "bold"),
                   command=self.cancel).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        if auto_check:
            self.after(200, self.check)

    def _section(self, title, icon):
        p = self.app.palette()
        outer = tk.Frame(self, bg=self._section_bg, highlightthickness=1,
                         highlightbackground=p["border"])
        outer.pack(fill="x", padx=18, pady=6)
        head = tk.Frame(outer, bg=self._section_bg)
        head.pack(fill="x", padx=14, pady=(12, 6))
        img = get_icon(self, icon, p["accent"], 16)
        if img:
            tk.Label(head, image=img, bg=self._section_bg).pack(side="left", padx=(0, 7))
        tk.Label(head, text=title, bg=self._section_bg, fg=p["text"],
                 font=(UI_FONT, 10, "bold")).pack(side="left")
        body = tk.Frame(outer, bg=self._section_bg)
        body.pack(fill="x", padx=14, pady=(0, 14))
        return body

    # ----------------------------------------------------------- tema
    def _set_theme(self, theme):
        if theme != self.app.theme:
            self.app.toggle_theme()
        self._sync_theme_buttons()

    def _sync_theme_buttons(self):
        for key, b in self.theme_btns.items():
            b.set_selected(key == self.app.theme)

    # -------------------------------------------------- actualizaciones
    def _store(self):
        self.settings.update({"update_repo": self.repo_var.get().strip() or GITHUB_REPO,
                              "check_on_start": self.check_start.get(),
                              "include_prerelease": self.prerelease.get()})
        self.app.update_settings(self.settings)

    def _open_repo(self):
        repo = (self.repo_var.get().strip() or GITHUB_REPO).removeprefix("https://github.com/")
        webbrowser.open(f"https://github.com/{repo.strip('/')}/releases")

    def _set_status(self, text, kind="muted"):
        p = self.app.palette()
        color = {"muted": p["muted_text"], "ok": "#2F9461", "error": p.get("danger", "#c0392b"),
                 "accent": p["accent"]}[kind]
        self.status.configure(text=text, fg=color)

    def check(self):
        if self.task is not None and self.task.thread.is_alive():
            return
        self._store()
        self.install_btn.pack_forget()
        self.notes.pack_forget()
        self.progress.pack_forget()
        self.check_btn.set_enabled(False)
        self._set_status("Consultando GitHub...")
        repo, pre = self.settings["update_repo"], self.settings["include_prerelease"]

        def work(put, _cancelled):
            put(("release", updater.check_latest(repo, pre)))
        self.task = BackgroundTask(self, work, self._on_check)

    def _on_check(self, msg):
        if not self.winfo_exists():
            return
        self.check_btn.set_enabled(True)
        if msg[0] == "error":
            self._set_status(msg[1], "error")
            return
        rel = msg[1]
        self.release = rel
        self.app.on_release_info(rel)
        if not rel["newer"]:
            self._set_status(f"Tienes la última versión ({APP_VERSION}). "
                             f"Última publicada: {rel['tag']} ({rel['published']}).", "ok")
            return
        try:
            asset = updater.pick_asset(rel)
        except updater.UpdateError as exc:
            self._set_status(f"Hay una versión nueva ({rel['tag']}), pero no se puede "
                             f"instalar automáticamente: {exc}", "error")
            return
        size = f" ({asset['size'] / 1_048_576:.1f} MB)" if asset.get("size") else ""
        self._set_status(f"Nueva versión disponible: {rel['name']} — publicada el "
                         f"{rel['published']}{size}.", "accent")
        self.install_btn.configure(text=f"Descargar e instalar {rel['tag']}")
        self.install_btn.pack(side="left", padx=(8, 0))
        if rel["notes"]:
            self.notes.configure(state="normal")
            self.notes.delete("1.0", "end")
            self.notes.insert("1.0", rel["notes"])
            self.notes.configure(state="disabled")
            self.notes.pack(fill="x", pady=(8, 0))

    def install(self):
        rel = self.release
        if not rel:
            return
        try:
            asset = updater.pick_asset(rel)
        except updater.UpdateError as exc:
            self._set_status(str(exc), "error")
            return
        if not confirm(self.app, "Actualizar", f"¿Instalar {APP_NAME} {rel['tag']}?",
                       "Se descargará desde GitHub. Tus notas, pizarras, eventos y proyectos "
                       "no se modifican. Al terminar podrás reiniciar la aplicación.",
                       ok_text="Descargar e instalar", parent=self):
            return
        self.app.save_now()
        self.install_btn.set_enabled(False)
        self.check_btn.set_enabled(False)
        self.progress.configure(value=0)
        self.progress.pack(fill="x", pady=(8, 0))
        self._set_status("Descargando...")

        def work(put, cancelled):
            def progress(done, total):
                put(("progress", done, total))
            path = updater.download(asset, progress, cancelled)
            put(("status", "Instalando..."))
            command = updater.install(path, asset)
            put(("installed", command))
        self.task = BackgroundTask(self, work, self._on_install)

    def _on_install(self, msg):
        if not self.winfo_exists():
            return
        kind = msg[0]
        if kind == "progress":
            done, total = msg[1], msg[2]
            if total:
                self.progress.configure(mode="determinate", value=done * 100 / total)
                self._set_status(f"Descargando... {done / 1_048_576:.1f} de "
                                 f"{total / 1_048_576:.1f} MB")
            else:
                self.progress.configure(mode="indeterminate")
                self.progress.step(2)
        elif kind == "status":
            self._set_status(msg[1])
        elif kind == "error":
            self.progress.pack_forget()
            self.install_btn.set_enabled(True)
            self.check_btn.set_enabled(True)
            self._set_status(msg[1], "error")
        elif kind == "installed":
            self.progress.configure(value=100)
            self._set_status("Actualización instalada.", "ok")
            command = msg[1]
            if confirm(self.app, "Actualización instalada",
                       f"{APP_NAME} {self.release['tag']} está listo.",
                       "Reinicia ahora para empezar a usarlo. Si prefieres seguir, la nueva "
                       "versión se abrirá la próxima vez.", ok_text="Reiniciar ahora",
                       cancel_text="Más tarde", parent=self):
                try:
                    self.app.save_now()
                    updater.restart(command)
                except OSError as exc:
                    alert(self.app, "Reiniciar", "No se pudo abrir la nueva versión.",
                          f"Ábrela manualmente. ({exc})", "warning", parent=self)
                    return
                self.close()
                self.app.on_close()
