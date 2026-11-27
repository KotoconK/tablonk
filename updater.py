"""Actualizaciones desde las releases de GitHub.

Flujo:
  1. check_latest() consulta la API publica de GitHub
     (https://api.github.com/repos/<repo>/releases/latest).
  2. Si la version publicada es mayor que APP_VERSION, download() descarga el
     archivo adecuado de la release y verifica su SHA-256 cuando GitHub lo
     publica.
  3. install():
     - Ejecutable (.exe): Windows permite RENOMBRAR un exe en uso. Se renombra
       el actual a <nombre>.old, se coloca el nuevo con el nombre original y
       se arranca. El .old se borra en el siguiente inicio.
     - Modo Python: se extrae el zip de codigo sobre la carpeta del programa,
       guardando antes una copia de los .py en _copia_vX.Y.Z/. Los datos del
       usuario (config.json, assets, tablonk_proyectos.json) no se tocan.

Todas las funciones de red son bloqueantes: llamarlas desde un hilo.
"""

import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

from version import APP_NAME, APP_VERSION, EXE_ASSET, GITHUB_REPO, SRC_ASSET

API = "https://api.github.com/repos/{repo}/releases"
TIMEOUT = 20
PROTECTED = {"config.json", "tablonk_proyectos.json", "tablonk_ajustes.json"}


class UpdateError(Exception):
    pass


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def app_dir():
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def parse_version(text):
    """'v4.10.2-beta' -> (4, 10, 2). Ignora sufijos."""
    nums = re.findall(r"\d+", str(text or "").split("-")[0])
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def is_newer(remote, local=APP_VERSION):
    return parse_version(remote) > parse_version(local)


def _context():
    return ssl.create_default_context()


def _request(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"{APP_NAME.replace(' ', '')}/{APP_VERSION}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    })
    return urllib.request.urlopen(req, timeout=TIMEOUT, context=_context())


def _clean_repo(repo):
    repo = (repo or GITHUB_REPO).strip()
    repo = re.sub(r"^https?://github\.com/", "", repo).strip("/")
    repo = re.sub(r"\.git$", "", repo)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise UpdateError("El repositorio debe tener el formato propietario/repositorio.")
    return repo


def check_latest(repo=GITHUB_REPO, include_prerelease=False):
    """Devuelve un dict con la ultima release o lanza UpdateError."""
    repo = _clean_repo(repo)
    base = API.format(repo=repo)
    try:
        if include_prerelease:
            with _request(base + "?per_page=10") as resp:
                releases = json.loads(resp.read().decode("utf-8"))
            releases = [r for r in releases if not r.get("draft")]
            if not releases:
                raise UpdateError("El repositorio todavía no tiene releases publicadas.")
            data = max(releases, key=lambda r: parse_version(r.get("tag_name")))
        else:
            with _request(base + "/latest") as resp:
                data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("No hay releases publicadas en "
                              f"github.com/{repo} (o el repositorio no existe).") from exc
        if exc.code == 403:
            raise UpdateError("GitHub ha limitado las consultas temporalmente. "
                              "Vuelve a intentarlo en unos minutos.") from exc
        raise UpdateError(f"GitHub respondió con el error {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise UpdateError("No se pudo conectar con GitHub. Revisa la conexión "
                          f"a internet ({exc.reason}).") from exc
    except (OSError, ValueError) as exc:
        raise UpdateError(f"Respuesta no válida de GitHub: {exc}") from exc

    tag = data.get("tag_name") or ""
    assets = [{"name": a.get("name", ""), "url": a.get("browser_download_url", ""),
               "size": a.get("size", 0), "digest": a.get("digest") or ""}
              for a in data.get("assets", [])]
    return {
        "tag": tag,
        "version": ".".join(str(n) for n in parse_version(tag)),
        "name": data.get("name") or tag,
        "notes": (data.get("body") or "").strip(),
        "url": data.get("html_url") or f"https://github.com/{repo}/releases",
        "published": (data.get("published_at") or "")[:10],
        "prerelease": bool(data.get("prerelease")),
        "assets": assets,
        "zipball": data.get("zipball_url") or "",
        "newer": is_newer(tag),
    }


def pick_asset(release):
    """Elige el archivo de la release que corresponde a esta instalacion."""
    assets = release.get("assets", [])
    if is_frozen():
        exact = [a for a in assets if a["name"].lower() == EXE_ASSET.lower()]
        any_exe = [a for a in assets if a["name"].lower().endswith(".exe")]
        chosen = (exact or any_exe or [None])[0]
        if chosen is None:
            raise UpdateError(f"La release {release['tag']} no incluye {EXE_ASSET}.")
        return {**chosen, "kind": "exe"}
    exact = [a for a in assets if a["name"].lower() == SRC_ASSET.lower()]
    any_zip = [a for a in assets if a["name"].lower().endswith(".zip")]
    chosen = (exact or any_zip or [None])[0]
    if chosen is not None:
        return {**chosen, "kind": "zip"}
    if release.get("zipball"):
        return {"name": "codigo.zip", "url": release["zipball"], "size": 0,
                "digest": "", "kind": "zip"}
    raise UpdateError("La release no incluye el código fuente.")


def download(asset, progress=None, cancel=None):
    """Descarga el asset a un archivo temporal junto al programa."""
    target_dir = app_dir()
    suffix = ".exe.part" if asset["kind"] == "exe" else ".zip.part"
    fd, tmp = tempfile.mkstemp(prefix=".tablonk_update_", suffix=suffix, dir=target_dir)
    sha = hashlib.sha256()
    done = 0
    try:
        with os.fdopen(fd, "wb") as out, _request(asset["url"], "application/octet-stream") as resp:
            total = int(resp.headers.get("Content-Length") or asset.get("size") or 0)
            while True:
                if cancel is not None and cancel():
                    raise UpdateError("Descarga cancelada.")
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        digest = asset.get("digest") or ""
        if digest.startswith("sha256:") and digest[7:].lower() != sha.hexdigest():
            raise UpdateError("La descarga no coincide con la huella SHA-256 publicada. "
                              "No se ha instalado nada.")
        if asset["kind"] == "exe":
            with open(tmp, "rb") as f:
                if f.read(2) != b"MZ":
                    raise UpdateError("El archivo descargado no es un ejecutable de Windows.")
        elif not zipfile.is_zipfile(tmp):
            raise UpdateError("El archivo descargado no es un zip válido.")
        return tmp
    except urllib.error.URLError as exc:
        _remove(tmp)
        raise UpdateError(f"Error de red durante la descarga: {exc.reason}") from exc
    except Exception:
        _remove(tmp)
        raise


def _remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def install(downloaded, asset):
    """Instala lo descargado. Devuelve el comando para reiniciar la app."""
    if asset["kind"] == "exe":
        return _install_exe(downloaded)
    return _install_zip(downloaded)


def _install_exe(downloaded):
    current = os.path.abspath(sys.executable)
    old = current + ".old"
    _remove(old)
    try:
        os.replace(current, old)
    except OSError as exc:
        _remove(downloaded)
        raise UpdateError("No se pudo sustituir el ejecutable. Comprueba que la carpeta "
                          f"no es de solo lectura. ({exc})") from exc
    try:
        os.replace(downloaded, current)
    except OSError as exc:
        try:
            os.replace(old, current)
        finally:
            _remove(downloaded)
        raise UpdateError(f"No se pudo colocar la nueva versión: {exc}") from exc
    return [current]


def _install_zip(downloaded):
    target = app_dir()
    backup = os.path.join(target, f"_copia_v{APP_VERSION}")
    try:
        with zipfile.ZipFile(downloaded) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            if not members:
                raise UpdateError("El zip de la actualización está vacío.")
            # Los zip de GitHub incluyen una carpeta raiz "repo-sha/": se elimina.
            roots = {m.filename.split("/", 1)[0] for m in members}
            strip = len(roots) == 1 and all("/" in m.filename for m in members)
            files = []
            for m in members:
                rel = m.filename.split("/", 1)[1] if strip else m.filename
                rel = rel.replace("\\", "/")
                if not rel or rel.startswith("/") or ".." in rel.split("/"):
                    continue
                if rel.split("/")[0] in (".github", "build", "dist", "assets"):
                    continue
                if os.path.basename(rel) in PROTECTED or rel.lower().endswith(".exe"):
                    continue
                files.append((m, rel))
            if not any(rel == "tablonk.py" for _, rel in files):
                raise UpdateError("El zip no contiene tablonk.py: no parece una versión de "
                                  "TablonK Advance.")
            os.makedirs(backup, exist_ok=True)
            for name in os.listdir(target):
                if name.endswith(".py"):
                    shutil.copy2(os.path.join(target, name), os.path.join(backup, name))
            for m, rel in files:
                dest = os.path.join(target, *rel.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(m) as src, open(dest + ".new", "wb") as out:
                    shutil.copyfileobj(src, out)
                os.replace(dest + ".new", dest)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"No se pudo instalar la actualización: {exc}") from exc
    finally:
        _remove(downloaded)
    script = os.path.join(target, "tablonk.py")
    python = sys.executable
    if sys.platform == "win32" and python.lower().endswith("python.exe"):
        pyw = python[:-10] + "pythonw.exe"
        if os.path.exists(pyw):
            python = pyw
    return [python, script]


def restart(command):
    """Lanza la nueva version como proceso independiente."""
    kwargs = {"cwd": app_dir(), "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    env = dict(os.environ)
    # PyInstaller: que el nuevo exe no herede la carpeta temporal del actual.
    for key in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE",
                "_PYI_PARENT_PROCESS_LEVEL"):
        env.pop(key, None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen(command, env=env, **kwargs)


def cleanup_previous():
    """Borra restos de una actualizacion anterior (exe .old, descargas a medias)."""
    if is_frozen():
        _remove(os.path.abspath(sys.executable) + ".old")
    try:
        for name in os.listdir(app_dir()):
            if name.startswith(".tablonk_update_") and name.endswith(".part"):
                _remove(os.path.join(app_dir(), name))
    except OSError:
        pass
