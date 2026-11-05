"""Wired mode: find phones on the USB cable.

Android: Google's adb tool (USB debugging). Once the phone is authorized we
forward the phone's localhost:<port> to this PC ("adb reverse"), so the phone's
browser reaches SCraMic Share at http://localhost:<port> over the cable, and we
open that page on the phone automatically.

iPhone: with Personal Hotspot on and the cable plugged in, Windows gets a
network link to the iPhone (172.20.10.x). The phone reaches the PC over it.
"""
import ipaddress
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

ADB_ZIP_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
IPHONE_NET = ipaddress.ip_network("172.20.10.0/28")      # iPhone Personal Hotspot
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_usb_serial(serial):
    """adb also lists phones it reaches over WiFi: 192.168.1.5:5555 or adb-xxxx._adb-tls-connect._tcp"""
    return ":" not in serial and "._adb" not in serial


class Wired:
    def __init__(self, data_dir, local_port, token, notify, ips_fn):
        self.dir = Path(data_dir)
        self.port = local_port
        self.token = token
        self.notify = notify            # notify(dict) -> sends to the PC page
        self.ips_fn = ips_fn            # () -> list of this PC's IPv4 addresses
        self.watching = False
        self.download = None            # None | {"done": bytes, "total": bytes} | {"error": str}
        self.devices = {}               # serial -> {"state", "model", "ready"}
        self.opened = set()             # serials we already opened the page on
        self.last = None
        self.iphone_usb = False         # an iPhone is plugged in (hotspot or not)
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True, name="wired").start()

    # ---- adb
    def adb_path(self):
        p = self.dir / "platform-tools" / "adb.exe"
        if p.exists():
            return str(p)
        return shutil.which("adb")

    def _adb(self, *args, serial=None, timeout=8):
        exe = self.adb_path()
        if not exe:
            return None
        cmd = [exe] + (["-s", serial] if serial else []) + list(args)
        # Output goes to a temp file, not a pipe: adb may start its background
        # server, which keeps a pipe open forever and would hang us.
        try:
            with tempfile.TemporaryFile() as out:
                p = subprocess.Popen(cmd, stdout=out, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                     creationflags=NO_WINDOW)
                try:
                    p.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    p.kill()
                    return None
                out.seek(0)
                return out.read().decode("utf-8", "replace")
        except OSError:
            return None

    def start_download(self):
        with self.lock:
            if self.download and "error" not in self.download:
                return
            self.download = {"done": 0, "total": 0}
        threading.Thread(target=self._download, daemon=True, name="adb-download").start()

    def _download(self):
        tmp = self.dir / "platform-tools.zip"
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(ADB_ZIP_URL, headers={"User-Agent": "SCraMicShare"})
            with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    self.download = {"done": done, "total": total}
                    self._report()
            with zipfile.ZipFile(tmp) as z:
                for name in z.namelist():   # only the files we need, never outside our folder
                    if name.startswith("platform-tools/") and ".." not in name and not name.endswith("/"):
                        target = self.dir / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(name) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
            self.download = None
        except Exception as e:
            self.download = {"error": str(e)}
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
        self.last = None
        self._report()

    def phone_url(self):
        return f"http://localhost:{self.port}/?k={self.token}&wired=1"

    def open_on_phone(self, serial):
        """Open SCraMic Share in the phone's browser, through the cable."""
        self._adb("reverse", f"tcp:{self.port}", f"tcp:{self.port}", serial=serial)
        self._adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", f"'{self.phone_url()}'",
                  serial=serial)

    def _scan_android(self):
        out = self._adb("devices", "-l")
        if out is None:
            return
        seen = {}
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            if not is_usb_serial(serial):
                continue
            model = next((p.split(":", 1)[1].replace("_", " ") for p in parts[2:] if p.startswith("model:")), "")
            seen[serial] = {"state": state, "model": model}
        for serial, d in seen.items():
            prev = self.devices.get(serial, {})
            d["ready"] = prev.get("ready", False)
            if d["state"] == "device" and not d["ready"]:
                out = self._adb("reverse", f"tcp:{self.port}", f"tcp:{self.port}", serial=serial)
                d["ready"] = out is not None
                if d["ready"] and serial not in self.opened:
                    self.opened.add(serial)
                    self.open_on_phone(serial)
        self.opened &= set(seen)        # unplugged phones get the page opened again next time
        self.devices = seen

    # ---- iPhone
    def iphone_ips(self):
        out = []
        for ip in self.ips_fn():
            try:
                if ipaddress.ip_address(ip) in IPHONE_NET:
                    out.append(ip)
            except ValueError:
                pass
        return out

    def _scan_iphone_usb(self):
        """Is an Apple device on the USB cable? (Apple's USB vendor id is 05AC.)"""
        try:
            r = subprocess.run(["pnputil", "/enum-devices", "/connected"], capture_output=True, text=True,
                               timeout=10, creationflags=NO_WINDOW)
            self.iphone_usb = "VID_05AC" in r.stdout.upper()
        except (OSError, subprocess.SubprocessError):
            self.iphone_usb = False

    # ---- status loop
    def _status(self):
        if self.download is not None:
            adb = "error" if "error" in self.download else "downloading"
        else:
            adb = "ready" if self.adb_path() else "missing"
        return {
            "t": "wired",
            "adb": adb,
            "download": self.download,
            "android": [{"serial": s, **d} for s, d in self.devices.items()],
            "iphone": self.iphone_ips(),
            "iphoneUsb": self.iphone_usb,
        }

    def _report(self, force=False):
        st = self._status()
        if force or st != self.last:
            self.last = st
            self.notify(st)

    def _loop(self):
        started = False
        n = 0
        while True:
            try:                         # one bad scan must never stop the watcher
                if self.watching:
                    if n % 2 == 0:
                        self._scan_iphone_usb()
                    n += 1
                    if self.adb_path() and self.download is None:
                        if not started:
                            self._adb("start-server", timeout=20)
                            started = True
                        self._scan_android()
                    self._report()
            except Exception as e:
                print("wired watcher:", e)
            time.sleep(1.5)

    # ---- messages from the PC page
    def handle(self, msg):
        t = msg.get("t")
        if t == "wired-watch":
            self.watching = bool(msg.get("on"))
            if self.watching:
                self.last = None
                self._report(force=True)
        elif t == "wired-download":
            self.start_download()
            self._report()
        elif t == "wired-open":
            s = msg.get("serial")
            if s in self.devices:
                threading.Thread(target=self.open_on_phone, args=(s,), daemon=True).start()
