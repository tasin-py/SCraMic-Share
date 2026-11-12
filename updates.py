"""Updates: asks GitHub for this app's releases, each time the app starts and from Settings.

Checking only tells the user. An update is downloaded and installed only when they click its button in Settings.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "1.2.4"
REPO = "tasin-py/SCraMic-Share"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"   # also lists pre-releases
FOLDER = Path(os.environ.get("APPDATA", str(Path.home()))) / "SCraMicShare" / "update"

_installing = threading.Lock()


def _number(version):
    """'v1.2.0' -> (1, 2), so that 1.2 and 1.2.0 count as the same version."""
    parts = [int(p) for p in re.findall(r"\d+", version)]
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _tags_from_api():
    req = urllib.request.Request(RELEASES_API, headers={"User-Agent": "SCraMicShare",
                                                        "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        releases = json.load(r)
    return [x.get("tag_name", "") for x in releases if not x.get("draft")]


def _tags_from_latest_page():
    """The page for the latest release sends you on to its tag. It isn't part of the API, so its limit doesn't apply,
    but it skips pre-releases. Don't use releases.atom here: it also lists the tags of unpublished drafts."""
    req = urllib.request.Request(RELEASES_PAGE + "/latest", headers={"User-Agent": "SCraMicShare"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return re.findall(r"/releases/tag/([^/?#]+)$", r.geturl())   # nothing published: no tag in the address


def check():
    """{"state": "current" | "update" | "none" | "error", "current": VERSION, "version": newest, if newer}"""
    out = {"current": VERSION}
    try:
        try:
            tags = _tags_from_api()
        except urllib.error.HTTPError as e:
            if e.code not in (403, 429):   # GitHub allows 60 API requests an hour per internet address, often shared
                raise
            tags = _tags_from_latest_page()
    except urllib.error.HTTPError as e:
        return {**out, "state": "none" if e.code == 404 else "error"}   # 404: nothing published yet
    except (OSError, ValueError, AttributeError, TypeError):
        return {**out, "state": "error"}
    tags = [t for t in tags if isinstance(t, str) and re.fullmatch(r"v?\d+(\.\d+)*", t)]
    if not tags:
        return {**out, "state": "none"}
    newest = max(tags, key=_number)
    if _number(newest) > _number(VERSION):
        return {**out, "state": "update", "version": newest.lstrip("v"), "can_install": can_install()}
    return {**out, "state": "current"}


def can_install():
    """Only the installed app can update itself: running from source, there's nothing to replace."""
    return bool(getattr(sys, "frozen", False))


def clean():
    """Removes a downloaded installer once it isn't needed. One that's still running just stays until next time."""
    shutil.rmtree(FOLDER, ignore_errors=True)


def download(version, progress):
    """Downloads the installer, checks it against the SHA-256 published with the release, and returns its path.
    Raises OSError or ValueError if anything is wrong: a release without the SHA-256 file can't be installed from here."""
    name = f"SCraMicShare-Setup-{version}.exe"
    base = f"https://github.com/{REPO}/releases/download/v{version}/{name}"
    headers = {"User-Agent": "SCraMicShare"}
    with urllib.request.urlopen(urllib.request.Request(base + ".sha256", headers=headers), timeout=30) as r:
        expected = r.read(200).decode("ascii", "replace").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("the release's SHA-256 file isn't valid")
    clean()
    FOLDER.mkdir(parents=True, exist_ok=True)
    part = FOLDER / (name + ".part")
    digest = hashlib.sha256()
    with urllib.request.urlopen(urllib.request.Request(base, headers=headers), timeout=30) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = shown = 0
        while chunk := r.read(1024 * 1024):
            f.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            percent = done * 100 // total if total else 0
            if percent != shown:
                shown = percent
                progress(percent)
    if digest.hexdigest() != expected:
        clean()
        raise ValueError("the download doesn't match the release's SHA-256")
    return part.replace(FOLDER / name)


def _start_on_its_own(args, cwd):
    """Starts a program that outlives this app, without the settings this app's own copy of Python runs with."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI") and k != "QTWEBENGINE_CHROMIUM_FLAGS"}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"   # an app reopened by it must set itself up from scratch
    subprocess.Popen([str(a) for a in args], cwd=str(cwd), env=env, close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def run_installer(path):
    """Starts the installer on its own. /update=1 makes it reopen the app when it's done."""
    _start_on_its_own([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/update=1"], path.parent)


def uninstaller():
    """The installed app's uninstaller (unins000.exe beside it), or None when running from source."""
    if not getattr(sys, "frozen", False):
        return None
    found = sorted(Path(sys.executable).parent.glob("unins[0-9][0-9][0-9].exe"))
    return found[-1] if found else None


def run_uninstaller():
    """The Uninstall button: Windows' own uninstaller takes over, asking first. True if it started."""
    path = uninstaller()
    if not path:
        return False
    try:
        _start_on_its_own([path], path.parent)
    except OSError:
        return False
    return True


def install_update(notify, close_app):
    """The Update button. Asks GitHub again rather than being told a version, so it can only ever go to a newer release."""
    if not _installing.acquire(blocking=False):
        return
    latest = {}
    try:
        latest = check()
        if latest["state"] != "update" or not latest["can_install"]:
            raise ValueError("no update to install")
        notify({"t": "update-state", "phase": "download", "percent": 0})
        path = download(latest["version"], lambda p: notify({"t": "update-state", "phase": "download", "percent": p}))
        notify({"t": "update-state", "phase": "install"})
        run_installer(path)
        close_app()
    except (OSError, ValueError) as e:
        print("update failed:", e, flush=True)
        notify({"t": "update-state", "phase": "failed", "version": latest.get("version")})
    finally:
        _installing.release()
