"""Archivos de eventos (imagenes de notas y adjuntos) dentro del proyecto.

Se copian a <carpeta del config.json>/assets/eventos/ y se guardan con una
ruta relativa, igual que las imagenes de la pizarra. Asi el proyecto se
puede mover o copiar entero sin romper nada.
"""

import hashlib
import os
import re
import subprocess
import sys
import webbrowser

FOLDER = "assets/eventos"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff")


def project_dir(app):
    return os.path.abspath(os.path.dirname(app.active_config_path))


def resolve(app, relative):
    """Ruta absoluta de un archivo del proyecto, o None si sale de la carpeta."""
    if not relative or not isinstance(relative, str):
        return None
    base = project_dir(app)
    target = os.path.abspath(os.path.join(base, relative))
    try:
        if os.path.commonpath((base, target)) == base:
            return target
    except ValueError:
        pass
    return None


def _safe_name(name):
    stem, ext = os.path.splitext(os.path.basename(name))
    stem = re.sub(r"[^\w\-. ]", "_", stem, flags=re.UNICODE).strip(" .")[:40] or "archivo"
    ext = re.sub(r"[^\w.]", "", ext)[:10]
    return stem.replace(" ", "_") + ext.lower()


def store_bytes(app, payload, original_name):
    folder = os.path.join(project_dir(app), *FOLDER.split("/"))
    os.makedirs(folder, exist_ok=True)
    filename = hashlib.sha256(payload).hexdigest()[:12] + "_" + _safe_name(original_name)
    destination = os.path.join(folder, filename)
    if not os.path.exists(destination):
        temp = destination + ".writing"
        with open(temp, "wb") as stream:
            stream.write(payload)
        os.replace(temp, destination)
    return FOLDER + "/" + filename


def store_file(app, source):
    """Copia un archivo al proyecto. Devuelve (ruta_relativa, tamano)."""
    with open(source, "rb") as stream:
        payload = stream.read()
    return store_bytes(app, payload, os.path.basename(source)), len(payload)


def is_image(path):
    return os.path.splitext(str(path))[1].lower() in IMAGE_EXT


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def open_path(path):
    """Abre un archivo con la aplicacion predeterminada del sistema."""
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - accion pedida por el usuario
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def show_in_folder(path):
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        open_path(os.path.dirname(path))


def normalize_link(target):
    target = (target or "").strip()
    if not target:
        return ""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) and not re.match(r"^[a-zA-Z]:[\\/]", target):
        return target                       # http:, https:, mailto:, file:...
    if re.match(r"^[a-zA-Z]:[\\/]", target) or target.startswith(("\\\\", "/")):
        return target                       # ruta de archivo o carpeta
    if "@" in target and " " not in target and "/" not in target:
        return "mailto:" + target
    return "https://" + target


def open_link(target):
    target = normalize_link(target)
    if not target:
        return
    if re.match(r"^(https?|mailto|ftp):", target, re.I):
        webbrowser.open(target)
    else:
        path = target[7:] if target.lower().startswith("file://") else target
        open_path(path)
