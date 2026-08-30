"""OTA updater — check and apply updates from GitHub Releases."""
from __future__ import annotations

import fcntl
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_log = logging.getLogger(__name__)
_RELEASES_REPO = "enzopellegrino/camera-viewer-releases"
_API = f"https://api.github.com/repos/{_RELEASES_REPO}/releases/latest"
_APP_DIR = Path.home() / "camera-viewer"
_BACKUP_DIR = Path.home() / "camera-viewer.bak"
_LOCK_FILE = Path.home() / ".camera-viewer-update.lock"


def _version_file() -> Path:
    return _APP_DIR / "VERSION"


def current_version() -> str:
    try:
        return _version_file().read_text().strip()
    except OSError:
        return "0.0.0"


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())


def check_update() -> dict:
    """Return latest release info from the public releases repo (no auth)."""
    headers = {"Accept": "application/vnd.github+json"}
    req = Request(_API, headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except (URLError, OSError, json.JSONDecodeError) as exc:
        return {"available": False, "error": str(exc)}

    latest = data.get("tag_name", "").lstrip("v")
    current = current_version()

    # Find the .tar.gz asset attached to the release
    asset_url = ""
    for asset in data.get("assets", []):
        if asset.get("name", "").endswith(".tar.gz"):
            asset_url = asset.get("browser_download_url", "")
            break

    return {
        "available": _version_tuple(latest) > _version_tuple(current),
        "current_version": current,
        "latest_version": latest,
        "release_name": data.get("name", ""),
        "release_notes": data.get("body", ""),
        "published_at": data.get("published_at", ""),
        "tarball_url": asset_url,
    }


def apply_update() -> tuple[bool, str]:
    """Download latest release tarball, backup current app, extract, restart."""
    lock_fd = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_fd.close()
        return False, "Aggiornamento già in corso"

    try:
        return _do_update()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _do_update() -> tuple[bool, str]:
    info = check_update()
    if not info.get("available"):
        return False, "Nessun aggiornamento disponibile"

    tarball_url = info.get("tarball_url", "")
    if not tarball_url:
        return False, "URL tarball non trovato nella release"

    parsed = urlparse(tarball_url)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith("github.com"):
        return False, "URL tarball non valido"

    stat = shutil.disk_usage(_APP_DIR.parent)
    if stat.free < 200 * 1024 * 1024:
        return False, "Spazio su disco insufficiente (servono almeno 200 MB)"

    tmp_tar = None
    try:
        req = Request(tarball_url)
        with urlopen(req, timeout=120) as resp:
            tmp_tar = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
            shutil.copyfileobj(resp, tmp_tar)
            tmp_tar.close()

        # Backup current installation
        if _BACKUP_DIR.exists():
            shutil.rmtree(_BACKUP_DIR)
        shutil.copytree(_APP_DIR, _BACKUP_DIR, symlinks=True)

        # Extract tarball — GitHub wraps contents in a top-level dir
        with tarfile.open(tmp_tar.name, "r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                if member.name.startswith("/") or ".." in member.name.split("/"):
                    _rollback()
                    return False, "Tarball contiene percorsi non sicuri"

            prefix = members[0].name.split("/")[0] + "/" if members else ""

            extract_kwargs = {"filter": "data"} if sys.version_info >= (3, 11, 4) else {}
            for member in members:
                if not member.name.startswith(prefix):
                    continue
                member.name = member.name[len(prefix):]
                if not member.name:
                    continue
                tar.extract(member, _APP_DIR, **extract_kwargs)

        _restart_services()
        return True, f"Aggiornato a v{info['latest_version']}"

    except Exception as exc:
        _log.exception("Update failed")
        _rollback()
        return False, "Errore durante l'aggiornamento, rollback eseguito"
    finally:
        if tmp_tar and os.path.exists(tmp_tar.name):
            os.unlink(tmp_tar.name)


def _rollback():
    """Restore from backup if update failed."""
    try:
        if _BACKUP_DIR.exists():
            if _APP_DIR.exists():
                shutil.rmtree(_APP_DIR)
            shutil.move(str(_BACKUP_DIR), str(_APP_DIR))
    except OSError:
        _log.critical("Rollback failed", exc_info=True)


def _restart_services():
    """Restart viewer and schedule portal restart."""
    subprocess.run(["pkill", "-f", "python3 main.py"], check=False)
    # Kill ourselves after a short delay so the HTTP response is sent first.
    # systemd Restart=always will relaunch the portal with the new code.
    subprocess.Popen(
        ["bash", "-c", f"sleep 2 && kill {os.getpid()}"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
