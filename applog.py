"""The error log: what the app saw, kept in %APPDATA%\\SCraMicShare\\scramicshare.log so a user can send it.

It notes each start (version, Windows, this PC's addresses, the ports the app got), port trouble, phones that
come and go, phones that reached the PC but couldn't connect, and any error with its details. It keeps about
2 MB at most: one file of 1 MB, and the one before it. The phone link's key never goes in.
"""
import logging
import logging.handlers
import os
import platform
import re
import subprocess
import sys
import threading
from pathlib import Path

DATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "SCraMicShare"
FILE = DATA / "scramicshare.log"
NO_WINDOW = 0x08000000

log = logging.getLogger("scramicshare")
_KEY = re.compile(r"([?&]k=)[^&\s'\"]+")


class _NoKey(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        record.msg, record.args = _KEY.sub(r"\1…", msg), None
        return True


def start(version):
    """Opens the log and catches errors nobody else catches, in every thread."""
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(FILE, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    except OSError:
        h = logging.NullHandler()   # no log is better than no app
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    h.addFilter(_NoKey())
    log.addHandler(h)
    log.propagate = False
    for name in ("aiohttp.server", "aiohttp.web", "asyncio"):   # errors inside the web server
        other = logging.getLogger(name)
        other.addHandler(h)
        other.setLevel(logging.ERROR)

    old_hook = sys.excepthook

    def on_error(kind, value, tb):
        log.critical("Unhandled error", exc_info=(kind, value, tb))
        old_hook(kind, value, tb)
    sys.excepthook = on_error

    def on_thread_error(a):
        if a.exc_type is not SystemExit:
            log.error("Unhandled error in thread %s", a.thread.name if a.thread else "?",
                      exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    threading.excepthook = on_thread_error

    frozen = "installed" if getattr(sys, "frozen", False) else "from source"
    log.info("==== SCraMic Share %s started (%s) on Windows %s, Python %s",
             version, frozen, platform.version(), platform.python_version())


def text():
    """The whole log, older file first, for the Copy button."""
    parts = []
    for f in (FILE.with_name(FILE.name + ".1"), FILE):
        try:
            parts.append(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return "".join(parts)


def copy():
    """Puts the log on the clipboard. Returns how many characters, 0 if there was nothing to copy."""
    t = text()
    if not t:
        return 0
    import ctypes
    from ctypes import wintypes
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.GlobalAlloc.restype = k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.argtypes = k32.GlobalUnlock.argtypes = k32.GlobalFree.argtypes = [ctypes.c_void_p]
    u32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    u32.SetClipboardData.restype = ctypes.c_void_p
    data = t.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-16-le") + b"\0\0"
    for _ in range(10):                      # another app may hold the clipboard for a moment
        if u32.OpenClipboard(None):
            break
        threading.Event().wait(0.1)
    else:
        return 0
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(0x0002, len(data))   # GMEM_MOVEABLE
        p = k32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        if not u32.SetClipboardData(13, h):      # CF_UNICODETEXT; the clipboard owns h from here on
            k32.GlobalFree(h)
            return 0
    finally:
        u32.CloseClipboard()
    return len(t)


def show():
    """Opens the log's folder with the log selected."""
    try:
        if FILE.exists():
            subprocess.Popen(["explorer", "/select,", str(FILE)])
        else:
            os.startfile(DATA)
    except OSError:
        pass
