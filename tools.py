"""Outside tools SCraMic Share downloads on first use, each checked against a pinned SHA-256.

    uxplay  - AirPlay receiver (iPhone screen mirroring). UxPlay for Windows, GPLv3, run as its own program.
    scrcpy  - Android screen mirroring over USB. Apache-2.0.
    ucam    - UnityCapture DirectShow camera filter (becomes "ScramicShare Cam"). MIT.
    vbcable - VB-CABLE virtual audio cable (becomes "ScramicShare Mic"). Donationware by VB-Audio.
"""
import hashlib
import shutil
import threading
import urllib.request
import zipfile
from pathlib import Path

TOOLS = {
    "uxplay": {
        "url": "https://github.com/leapbtw/uxplay-windows/releases/download/2.0.0.1736/uxplay-windows.zip",
        "sha256": "9d3a51c15fc9db857351195e7eb7bbb21700d9ae25d936a54bcf8536b62cca18",
        "zip": True, "label": "AirPlay receiver (UxPlay)", "size": "113 MB",
    },
    "scrcpy": {
        "url": "https://github.com/Genymobile/scrcpy/releases/download/v5.0.1/scrcpy-win64-v5.0.1.zip",
        "sha256": "b12a2c4ee8be317422451fc7dcf8ee20a71b5ea7ef9ad73ddd825a25316227a5",
        "zip": True, "label": "Android USB mirroring (scrcpy)", "size": "11 MB",
    },
    "ucam": {
        "url": "https://raw.githubusercontent.com/schellingb/UnityCapture/3ed54c325e0ad71afcf4f246c07e5e17b3d7f2d2/Install/UnityCaptureFilter64.dll",
        "sha256": "72812f5363d8ecb45632253f8c8c888844b1b62e27616f3c8cc21064ccde25e5", "zip": False, "file": "UnityCaptureFilter64.dll",
        "label": "Virtual camera driver (UnityCapture)", "size": "0.2 MB",
    },
    "vbcable": {
        "url": "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip",
        "sha256": "b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb", "zip": True, "label": "Virtual mic driver (VB-CABLE)", "size": "1.3 MB",
    },
}


class Tools:
    def __init__(self, data_dir, on_change=None):
        self.root = Path(data_dir) / "tools"
        self.on_change = on_change or (lambda: None)
        self.progress = {}          # name -> {"done", "total"} | {"error"}
        self.lock = threading.Lock()

    def dir(self, name):
        return self.root / name

    def ready(self, name):
        d = self.dir(name)
        return d.exists() and (d / ".ok").exists()

    def find(self, name, filename):
        """Path of a file somewhere inside a downloaded tool, or None."""
        d = self.dir(name)
        if not d.exists():
            return None
        hits = sorted(d.rglob(filename), key=lambda p: len(p.parts))
        return hits[0] if hits else None

    def state(self):
        out = {}
        for n, t in TOOLS.items():
            p = self.progress.get(n)
            out[n] = {"ready": self.ready(n), "label": t["label"], "size": t["size"], **({"progress": p} if p else {})}
        return out

    def fetch(self, name, wait=False):
        with self.lock:
            if self.ready(name) or (name in self.progress and "error" not in self.progress[name]):
                return
            self.progress[name] = {"done": 0, "total": 0}
        th = threading.Thread(target=self._fetch, args=(name,), daemon=True, name=f"fetch-{name}")
        th.start()
        if wait:
            th.join()

    def _fetch(self, name):
        t = TOOLS[name]
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f"{name}.download"
        try:
            h = hashlib.sha256()
            req = urllib.request.Request(t["url"], headers={"User-Agent": "SCraMicShare"})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = r.read(512 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    self.progress[name] = {"done": done, "total": total}
                    self.on_change()
            digest = h.hexdigest()
            if t["sha256"] and digest != t["sha256"]:
                raise ValueError("the download didn't match its checksum, so it wasn't used")
            d = self.dir(name)
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True)
            if t["zip"]:
                with zipfile.ZipFile(tmp) as z:
                    for m in z.infolist():
                        target = (d / m.filename).resolve()
                        if not str(target).startswith(str(d.resolve())):   # never write outside our folder
                            continue
                        if m.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with z.open(m) as src, open(target, "wb") as dst:
                                shutil.copyfileobj(src, dst)
            else:
                shutil.copy(tmp, d / t["file"])
            (d / ".ok").write_text(digest)
            self.progress.pop(name, None)
        except Exception as e:
            self.progress[name] = {"error": str(e)}
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
        self.on_change()
