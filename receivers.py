"""Screen share: this PC becomes a receiver for the phone's own screen sharing.

    iPhone          -> AirPlay (UxPlay for Windows). The iPhone picks "SCraMicShare" in Screen Mirroring.
    Android, USB    -> scrcpy over the same adb link wired mode already uses.
    Android, WiFi   -> scrcpy over adb on the network, paired with Wireless debugging's code (Android 11+).
                       Windows' Wireless Display (Miracast) is the fallback for older phones.

Each receiver shows the phone's screen in its own window, follows rotation and
can play the phone's sound.
"""
import ctypes
import os
import queue
import re
import socket
import subprocess
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

from vdevices import run_elevated
from wired import is_usb_serial

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
AIRPLAY_NAME = "SCraMicShare"     # no spaces: this receiver splits its settings at spaces and ignores quotes
AIRPLAY_START_SECONDS = 20
FW_RULE = "SCraMic Share AirPlay"
APPDATA = Path(os.environ.get("APPDATA", str(Path.home())))
UXPLAY_CFG = APPDATA / "leapbtw" / "uxplay-windows"
STATUS_LOG = APPDATA / "SCraMicShare" / "airplay-status.log"
OUTPUT_LOG = APPDATA / "SCraMicShare" / "airplay-output.log"
SCRCPY_LOG = APPDATA / "SCraMicShare" / "scrcpy-output.log"
ADB_WIFI_PORT = 5555


def _airplay_log(text):
    """Keeps a short record, so a receiver that won't start can be diagnosed afterwards."""
    try:
        STATUS_LOG.parent.mkdir(parents=True, exist_ok=True)
        old = STATUS_LOG.read_text(encoding="utf-8").splitlines()[-200:] if STATUS_LOG.exists() else []
        STATUS_LOG.write_text("\n".join(old + [time.strftime("%Y-%m-%d %H:%M:%S ") + text]) + "\n", encoding="utf-8")
    except OSError:
        pass


def _last_output(path=None):
    """The last lines a receiver printed before it closed."""
    try:
        lines = (path or OUTPUT_LOG).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return " | ".join(x.strip() for x in lines if x.strip())[-400:]


def _listening_ports(pid):
    """TCP ports this program is listening on. AirPlay picks its own, so we look them up."""
    r = _quiet("netstat", "-ano", "-p", "TCP")
    if not r:
        return []
    ports = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and parts[4] == str(pid):
            ports.append(parts[1].rsplit(":", 1)[-1])
    return ports


def _quiet(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None


def _bonjour_running():
    r = _quiet("sc", "query", "Bonjour Service")
    return bool(r) and "RUNNING" in r.stdout


def _firewall_rule_exists():
    r = _quiet("netsh", "advfirewall", "firewall", "show", "rule", f"name={FW_RULE}")
    return bool(r) and r.returncode == 0


def _route_ip():
    """This PC's main network address (no traffic is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return ""


def _lan_ips():
    try:
        ips = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return []
    return [ip for ip in ips if not ip.startswith(("127.", "169.254."))]


# ---- the receiver's video window
STREAM_TITLE = "ScramicShare Stream"
STREAM_ICON = Path(__file__).resolve().parent / "web" / "assets" / "stream.ico"
RESOLUTION = re.compile(rb"(?:resolution changed |Texture[^:\n]*: )(\d+)x(\d+)")   # AirPlay's, scrcpy's
WM_SETTEXT, WM_SETICON = 0x000C, 0x0080
ICON_SMALL, ICON_BIG = 0, 1
SM_CXICON, SM_CYICON, SM_CXSMICON, SM_CYSMICON = 11, 12, 49, 50
SMTO_ABORTIFHUNG = 0x2
GWL_STYLE = -16
WS_POPUP, WS_CAPTION, WS_THICKFRAME = 0x80000000, 0x00C00000, 0x00040000
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x4, 0x10, 0x20
SWP_ASYNC = 0x4000     # never wait on the receiver's window thread
SM_XVIRTUALSCREEN = 76


class _Monitor(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


user32 = ctypes.WinDLL("user32", use_last_error=True) if os.name == "nt" else None
if user32:
    _ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (_ENUM, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsZoomed.argtypes = (wintypes.HWND,)
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
    user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(_Monitor))
    user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.SendMessageTimeoutW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                           wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    user32.LoadImageW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT)
    user32.LoadImageW.restype = wintypes.HANDLE


def _send(hwnd, message, wparam, lparam):
    """Never waits long on the receiver's window thread."""
    done = ctypes.c_size_t()
    user32.SendMessageTimeoutW(hwnd, message, wparam, lparam, SMTO_ABORTIFHUNG, 500, ctypes.byref(done))


def _title_window(hwnd):
    """Our name in its title bar. Checked every time, because the receiver sets its own name too."""
    now = ctypes.create_unicode_buffer(128)
    user32.GetWindowTextW(hwnd, now, 128)
    if now.value != STREAM_TITLE:
        text = ctypes.create_unicode_buffer(STREAM_TITLE)
        _send(hwnd, WM_SETTEXT, 0, ctypes.addressof(text))


_icons = {}


def _icon_window(hwnd):
    """Our icon in its title bar and on the taskbar."""
    IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
    for kind, cx, cy in ((ICON_SMALL, SM_CXSMICON, SM_CYSMICON), (ICON_BIG, SM_CXICON, SM_CYICON)):
        if kind not in _icons:     # kept for the life of the app: the other window goes on using them
            _icons[kind] = user32.LoadImageW(None, str(STREAM_ICON), IMAGE_ICON, user32.GetSystemMetrics(cx),
                                             user32.GetSystemMetrics(cy), LR_LOADFROMFILE)
        if _icons[kind]:
            _send(hwnd, WM_SETICON, kind, _icons[kind])


def _rect(hwnd, client=False):
    r = wintypes.RECT()
    (user32.GetClientRect if client else user32.GetWindowRect)(hwnd, ctypes.byref(r))
    return r


def _find_window(pid):
    """The biggest visible window of that program: its video window, if one is open."""
    best, best_area = None, 0

    def check(hwnd, _):
        nonlocal best, best_area
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            r = _rect(hwnd)
            area = (r.right - r.left) * (r.bottom - r.top)
            if area > best_area:
                best, best_area = hwnd, area
        return True
    user32.EnumWindows(_ENUM(check), 0)
    return best


def _fit_size(cur_w, cur_h, video_w, video_h, max_w, max_h):
    """Takes the picture's shape, keeps the size the user gave the window, stays on the screen."""
    long_side = max(cur_w, cur_h)
    scale = min(long_side / max(video_w, video_h), max_w / video_w, max_h / video_h)
    return round(video_w * scale), round(video_h * scale)


def _work_area(hwnd):
    info = _Monitor(size=ctypes.sizeof(_Monitor))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info))   # 2 = nearest
    return info.work, info.monitor


def _fit_window(hwnd, video_w, video_h):
    """Reshapes the window to the phone's picture, around its own center. Full screen stays full screen."""
    win, client = _rect(hwnd), _rect(hwnd, client=True)
    work, screen = _work_area(hwnd)
    if user32.IsZoomed(hwnd) or (win.right - win.left >= screen.right - screen.left
                                 and win.bottom - win.top >= screen.bottom - screen.top):
        return
    extra_w = (win.right - win.left) - client.right
    extra_h = (win.bottom - win.top) - client.bottom
    w, h = _fit_size(client.right, client.bottom, video_w, video_h,
                     work.right - work.left - extra_w, work.bottom - work.top - extra_h)
    w, h = w + extra_w, h + extra_h
    if win.right <= screen.left:     # waiting off the screen behind the turned view: stays there
        x, y = win.left, win.top
    else:
        x = max(work.left, min((win.left + win.right - w) // 2, work.right - w))
        y = max(work.top, min((win.top + win.bottom - h) // 2, work.bottom - h))
    user32.SetWindowPos(hwnd, None, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNC)


def _wrong_shape(hwnd, video_w, video_h):
    client = _rect(hwnd, client=True)
    return client.bottom > 0 and abs(client.right / client.bottom - video_w / video_h) > 0.01


def _hide_window(hwnd):
    """Moves the window off the screen without its frame, so the turned view shows only the picture.
    It can't simply be minimized, because a minimized window stops drawing."""
    r = _rect(hwnd)
    style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_STYLE, (style & ~(WS_CAPTION | WS_THICKFRAME)) | WS_POPUP)
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN) - (r.right - r.left) - 200
    user32.SetWindowPos(hwnd, None, x, r.top, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_ASYNC)
    return r.left, r.top, style


def _unhide_window(hwnd, x, y, style):
    user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
    user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_ASYNC)


def _run_adb(exe, *args, timeout=8):
    """adb's output, or "" if it fails. Output goes to a file, not a pipe: adb may start its
    background server, which would hold a pipe open forever."""
    try:
        with tempfile.TemporaryFile() as out:
            p = subprocess.Popen([exe, *args], stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 creationflags=NO_WINDOW)
            try:
                p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                p.kill()
                return ""
            out.seek(0)
            return out.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _adb_devices(exe):
    """{serial: state} of every phone adb can see."""
    found = {}
    for line in _run_adb(exe, "devices").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            found[parts[0]] = parts[1]
    return found


def _kill_tree(p):
    if p and p.poll() is None:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)


class Receivers:
    def __init__(self, tools, wired, notify):
        self.tools = tools
        self.wired = wired
        self.notify = notify            # notify(dict) -> PC page
        self.kind = None                # "airplay" | "miracast" | "scrcpy"
        self.audio = True
        self.serial = None              # which Android phone, when one was chosen
        self.control = True             # Android with scrcpy: the PC's mouse and keyboard reach the phone
        self.cable_wait = 0             # changes whenever an older wait for the cable should end
        self.wifi_target = None         # where adb reaches the phone over WiFi, while connected
        self.wifi_port = None           # the port the user read off the phone, if discovery can't find it
        self.pair_note = ""             # "", "paired" or "failed"
        self.proc = None
        self.error = ""
        self._miracast_id = None
        self.airplay_failed = ""        # why the receiver isn't running, in words
        self.airplay_up = False
        self.auto_rotate = True         # the window takes the shape of the phone's picture
        self.turn = 0                   # manual quarter turns, 0-3
        self.video = None               # the phone's picture size (w, h)
        self.on_view = None             # on_view((hwnd, degrees) or None) -> the turned view
        self.lock = threading.Lock()
        # one at a time and in order: a Stop must never land after the Start that followed it
        self.jobs = queue.Queue()
        threading.Thread(target=self._run_jobs, daemon=True, name="rx").start()

    # ---- Windows Wireless Display (Miracast)
    def miracast_app_id(self):
        """Start-menu id of Windows' "Wireless Display" app, or None if it isn't installed."""
        if self._miracast_id:
            return self._miracast_id
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-StartApps | Where-Object { $_.AppID -like '*PPIProjection*' -or $_.Name -eq 'Wireless Display' } | "
                 "Select-Object -First 1 -ExpandProperty AppID"],
                capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
            app = r.stdout.strip()
            if app:
                self._miracast_id = app
            return app or None
        except (OSError, subprocess.SubprocessError):
            return None

    # ---- state for the PC page
    def state(self):
        running = self.proc is not None and self.proc.poll() is None
        out = {
            "t": "rx-state", "kind": self.kind, "running": running, "audio": self.audio, "error": self.error,
            "pcName": socket.gethostname(), "airplayName": AIRPLAY_NAME,
            "tools": self.tools.state(),
            "rotate": {"auto": self.auto_rotate, "deg": self.turn * 90}, "control": self.control,
            "pairNote": self.pair_note,
        }
        if self.kind == "airplay":
            out["airplay"] = self._airplay_state()
        return out

    def _airplay_state(self):
        """What the iPhone needs from this PC, so the page can say what is actually wrong."""
        ips = _lan_ips()
        return {
            "listening": self.airplay_up,
            "failed": self.airplay_failed,
            "bonjour": _bonjour_running(),
            "firewallOk": _firewall_rule_exists(),
            "ip": _route_ip(),
            "hotspot":any(ip.startswith("172.20.10.") for ip in ips),
        }

    def _report(self):
        self.notify(self.state())

    def tool_changed(self):
        """A download moved on. If the share was only waiting for that tool, carry on by itself."""
        waiting = self.error.split(":", 1)[1] if self.error.startswith("needs-tool:") else None
        if waiting and self.kind and self.tools.ready(waiting):
            self.jobs.put((self.start, (self.kind, self.audio, self.serial)))
        else:
            self._report()

    def _run_jobs(self):
        while True:
            job, args = self.jobs.get()
            try:
                job(*args)
            except Exception as e:
                self.error = str(e)

    # ---- start / stop
    def start(self, kind, audio=True, serial=None):
        with self.lock:
            # the phone's page may be away when this is retried, so its address is kept
            if kind == "scrcpy-wifi" and not serial and self.kind == kind:
                serial = self.serial
            self._stop()
            self.kind, self.audio, self.serial, self.error = kind, bool(audio), serial, ""
            self.cable_wait += 1
            try:
                if kind == "airplay":
                    self._start_airplay()
                elif kind == "scrcpy":
                    self._start_scrcpy(serial)
                elif kind == "scrcpy-wifi":
                    self._start_scrcpy_wifi(serial)
                elif kind == "miracast":
                    self._start_miracast()
            except Exception as e:
                self.error = str(e)
        self._report()

    def stop(self):
        with self.lock:
            self._stop()
            self.kind = None
            self.wifi_port = None
            self.pair_note = ""
        self._report()

    def _stop(self):
        proc, self.proc = self.proc, None      # cleared first, so its watcher knows this stop is ours
        _kill_tree(proc)
        if self.wifi_target and ":" in self.wifi_target and self._adb_exe():
            _run_adb(self._adb_exe(), "disconnect", self.wifi_target)
        self.wifi_target = None
        self.cable_wait += 1
        self.airplay_up = False
        self.turn = 0
        self.video = None
        self._show_view(None)

    def _start_airplay(self):
        exe = self.tools.find("uxplay", "uxplay-windows.exe")
        if not exe:
            self.error = "needs-tool:uxplay"
            return
        # It only allows one copy, and a leftover one would ignore the new settings.
        subprocess.run(["taskkill", "/IM", exe.name, "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
        UXPLAY_CFG.mkdir(parents=True, exist_ok=True)
        # -vsync no: show each frame as it arrives instead of holding it for its timestamp
        args = f"-n {AIRPLAY_NAME} -nh -vsync no" + ("" if self.audio else " -a")   # -a = no sound
        (UXPLAY_CFG / "arguments.txt").write_text(args + "\n", encoding="ascii")
        self.airplay_failed = ""
        _airplay_log(f"starting {exe} with: {args}")
        try:
            # its messages go to a file, so a failure can say why. GST_DEBUG adds the video player's
            # warnings, and h264parse:4 reports each new picture size, which auto rotation follows.
            STATUS_LOG.parent.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ, GST_DEBUG="2,h264parse:4", GST_DEBUG_NO_COLOR="1")
            with open(OUTPUT_LOG, "wb") as out:
                self.proc = subprocess.Popen([str(exe)], cwd=str(exe.parent), env=env, stdin=subprocess.DEVNULL,
                                             stdout=out, stderr=subprocess.STDOUT)
        except OSError as e:
            self.airplay_failed = f"Windows wouldn't start it: {e}"
            _airplay_log(self.airplay_failed)
            return
        threading.Thread(target=self._watch_airplay, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._follow_video, args=(self.proc,), daemon=True).start()

    def _show_view(self, value):
        if self.on_view:
            self.on_view(value)

    def _follow_video(self, proc, log=None, airplay=True):
        """Keeps the receiver's window matching the phone: its shape (auto) and its turn (manual).
        Android's window always follows, and keeps scrcpy's own name and icon."""
        pos, hwnd, fitted, hidden_at, shown, settle = 0, None, None, None, None, 0
        while self.proc is proc and proc.poll() is None:
            time.sleep(0.4)
            try:
                with open(log or OUTPUT_LOG, "rb") as f:
                    f.seek(pos)
                    data = f.read()
            except OSError:
                data = b""
            data = data[:data.rfind(b"\n") + 1]    # whole lines only, the rest is read next time
            pos += len(data)
            sizes = RESOLUTION.findall(data)
            if sizes:
                size = (int(sizes[-1][0]), int(sizes[-1][1]))
                if size != self.video:
                    self.video = size
                    _airplay_log(f"phone picture is {size[0]}x{size[1]}")
                    self._report()

            found = _find_window(proc.pid)
            if found != hwnd:                       # opened, or closed by the phone or the user
                hwnd, fitted, hidden_at = found, None, None
                if hwnd and airplay:
                    _icon_window(hwnd)
            if not hwnd:
                if shown:
                    shown = None
                    self._show_view(None)
                continue
            if airplay:
                _title_window(hwnd)
            if (self.auto_rotate or not airplay) and self.video:
                if self.video != fitted:
                    _fit_window(hwnd, *self.video)
                    fitted = self.video
                    settle = time.monotonic() + 3     # the receiver may still be resizing its window itself
                elif time.monotonic() < settle and _wrong_shape(hwnd, *self.video):
                    _fit_window(hwnd, *self.video)

            want = (hwnd, self.turn * 90) if self.turn else None
            if want != shown:
                shown = want
                if want and hidden_at is None:
                    hidden_at = _hide_window(hwnd)
                self._show_view(want)
                if not want and hidden_at is not None:
                    _unhide_window(hwnd, *hidden_at)
                    hidden_at = None
        self._show_view(None)

    def _watch_airplay(self, proc):
        """Tells the page when the receiver is really listening, or exactly how it failed."""
        end = time.monotonic() + AIRPLAY_START_SECONDS
        while self.proc is proc:
            code = proc.poll()
            if code is not None:
                self.airplay_up = False
                self.airplay_failed = f"It closed by itself (code {code & 0xFFFFFFFF:#x})."
                said = _last_output()
                if said:
                    self.airplay_failed += f" It said: {said}"
                _airplay_log(self.airplay_failed)
                self._report()
                return
            if not self.airplay_up:
                ports = _listening_ports(proc.pid)
                if ports:
                    self.airplay_up = True
                    _airplay_log(f"listening on {', '.join(ports)}")
                    self._report()
                elif time.monotonic() > end:
                    self.airplay_failed = f"It is running, but still isn't accepting connections after {AIRPLAY_START_SECONDS} seconds."
                    _airplay_log(self.airplay_failed)
                    self._report()
                    return
            time.sleep(1)

    def allow_firewall(self):
        """Let only the AirPlay receiver through Windows Firewall. Windows asks for approval."""
        exe = self.tools.find("uxplay", "uxplay-windows.exe")
        if exe:
            run_elevated("netsh", f'advfirewall firewall add rule name="{FW_RULE}" dir=in action=allow '
                                  f'program="{exe}" enable=yes profile=any')
            end = time.monotonic() + 30
            while time.monotonic() < end and not _firewall_rule_exists():
                time.sleep(1)
        self._report()

    def _start_scrcpy(self, serial):
        exe = self.tools.find("scrcpy", "scrcpy.exe")
        if not exe:
            self.error = "needs-tool:scrcpy"
            return
        if not serial:
            ready = [s for s, d in self.wired.devices.items() if d.get("state") == "device"]
            serial = ready[0] if ready else None
        if not serial:
            self.error = "No Android phone on the cable. Plug it in and allow USB debugging."
            return
        self._run_scrcpy(exe, serial)

    def _adb_exe(self):
        """Wired mode's adb if it is there (two versions fight each other), else the one scrcpy brings."""
        found = self.wired.adb_path() or self.tools.find("scrcpy", "adb.exe")
        return str(found) if found else None

    def _start_scrcpy_wifi(self, ip):
        exe = self.tools.find("scrcpy", "scrcpy.exe")
        if not exe:
            self.error = "needs-tool:scrcpy"
            return
        adb = self._adb_exe()
        if not ip or not adb:
            self.error = "Couldn't find your phone on the network. Open SCraMic Share on the phone again."
            return
        self._report()                       # the page says "connecting" while this runs
        target, state = self._wifi_find(adb, ip)
        if state not in ("device", "unauthorized"):
            usb = [s for s, st in _adb_devices(adb).items() if is_usb_serial(s) and st == "device"]
            if not usb:
                self.error = "needs-pairing"
                # a cable also works, if one happens to get plugged in
                threading.Thread(target=self._wait_for_cable, args=(adb, self.cable_wait), daemon=True).start()
                return
            if len(usb) > 1:                 # only switch on the phone that is on this address
                usb = [s for s in usb if ip in _run_adb(adb, "-s", s, "shell", "ip", "route")] or usb[:1]
            _run_adb(adb, "-s", usb[0], "tcpip", str(ADB_WIFI_PORT))
            target = f"{ip}:{ADB_WIFI_PORT}"
            for _ in range(5):               # the phone takes a moment to start listening
                time.sleep(1)
                state = self._wifi_connect(adb, target)
                if state == "device":
                    break
        self.wifi_target = target            # so Stop also clears a half-finished connection
        if state == "unauthorized":
            self.error = "Tap Allow on your phone, then try again."
        elif state != "device":
            self.error = "Couldn't reach your phone over WiFi. Check that it's on the same WiFi as this PC, then try again."
        else:
            self.pair_note = ""
            self._run_scrcpy(exe, target)

    def _wifi_find(self, adb, ip):
        """Tries every way this phone may be listening. Returns (where, state), or (None, None)."""
        where = [f"{ip}:{self.wifi_port}"] if self.wifi_port else []
        names = {}                           # Wireless debugging announces itself, on a port that changes
        for line in _run_adb(adb, "mdns", "services", timeout=5).splitlines():
            parts = line.split()
            if len(parts) >= 3 and "_adb-tls-connect" in parts[1] and parts[2].startswith(f"{ip}:"):
                where.append(parts[2])
                names[parts[2]] = f"{parts[0]}.{parts[1].rstrip('.')}"
        where.append(f"{ip}:{ADB_WIFI_PORT}")
        for target in where:
            state = self._wifi_connect(adb, target)
            if state is None and target in names:      # adb may list it by its announced name instead
                target = names[target]
                state = _adb_devices(adb).get(target)
            if state in ("device", "unauthorized"):
                return target, state
        return None, None

    def _pair(self, port, code):
        """Android 11+: Wireless debugging's pairing code, so no cable is ever needed."""
        adb = self._adb_exe()
        if not (port.isdigit() and code.isdigit() and self.serial and adb):
            self.pair_note = "failed"
            self._report()
            return
        out = _run_adb(adb, "pair", f"{self.serial}:{port}", code, timeout=15)
        if "Successfully paired" not in out:
            self.pair_note = "failed"
            _airplay_log(f"pairing failed: {out.strip()[:200]}")
            self._report()
            return
        self.pair_note = "paired"
        time.sleep(1.5)                      # the phone takes a moment to announce itself
        self.start(self.kind, self.audio, self.serial)

    def _wifi_connect(self, adb, target):
        """Connects adb to the phone over the network. Returns its state, or None if it isn't listening."""
        _run_adb(adb, "connect", target, timeout=6)
        state = _adb_devices(adb).get(target)
        if state == "offline":               # left over from an earlier connection
            _run_adb(adb, "disconnect", target)
            _run_adb(adb, "connect", target, timeout=6)
            state = _adb_devices(adb).get(target)
        return state

    def _wait_for_cable(self, adb, wait):
        """The first time over WiFi: carries on by itself as soon as the phone is plugged in and allowed."""
        while wait == self.cable_wait:
            time.sleep(2)
            if wait == self.cable_wait and any(is_usb_serial(s) and st == "device" for s, st in _adb_devices(adb).items()):
                self.jobs.put((self.start, (self.kind, self.audio, self.serial)))
                return

    def _run_scrcpy(self, exe, serial):
        env = dict(os.environ)
        adb = self._adb_exe()
        if adb:
            env["ADB"] = adb
        cmd = [str(exe), "-s", serial, "--window-title", "SCraMic Share - phone screen",
               "--video-bit-rate", "12M", "--max-fps", "60"]
        # share only: nothing done on the PC reaches the phone. scrcpy refuses to keep the phone awake then.
        cmd.append("--stay-awake" if self.control else "--no-control")
        if not self.audio:
            cmd.append("--no-audio")
        STATUS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SCRCPY_LOG, "wb") as out:      # its messages go to a file, so a failure can say why
            self.proc = subprocess.Popen(cmd, cwd=str(exe.parent), env=env, creationflags=NO_WINDOW,
                                         stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
        threading.Thread(target=self._watch_scrcpy, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._follow_video, args=(self.proc, SCRCPY_LOG, False), daemon=True).start()

    def _watch_scrcpy(self, proc):
        """Tells the page when the mirror ends by itself, and why."""
        code = proc.wait()
        if self.proc is not proc:                # we stopped it ourselves
            return
        if code == 0:
            self.error = "The phone screen window was closed."
        else:
            said = _last_output(SCRCPY_LOG)
            self.error = f"The phone screen couldn't open (code {code & 0xFFFFFFFF:#x})." + (f" It said: {said}" if said else "")
        self._report()

    def _start_miracast(self):
        app = self.miracast_app_id()
        if not app:
            self.error = "needs-wireless-display"
            return
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app}"])

    # ---- messages from the PC page
    def handle(self, msg):
        a = msg.get("a")
        if a == "start":
            self.jobs.put((self.start, (msg.get("kind"), msg.get("audio", True), msg.get("serial"))))
        elif a == "stop":
            self.jobs.put((self.stop, ()))
        elif a == "state":
            self.jobs.put((self._report, ()))
        elif a == "rotate":
            self.turn = (self.turn + (1 if msg.get("by", 1) > 0 else -1)) % 4
            self.jobs.put((self._report, ()))
        elif a == "rotate-reset":
            self.turn = 0
            self.jobs.put((self._report, ()))
        elif a == "auto-rotate":
            self.auto_rotate = bool(msg.get("on"))
            self.jobs.put((self._report, ()))
        elif a == "pair":
            self.jobs.put((self._pair, (str(msg.get("port", "")), str(msg.get("code", "")))))
        elif a == "wifi-port":
            port = str(msg.get("port", ""))
            if port.isdigit() and self.kind == "scrcpy-wifi":
                self.wifi_port = port
                self.jobs.put((self.start, (self.kind, self.audio, self.serial)))
        elif a == "control":
            changed =self.control != bool(msg.get("on"))
            self.control = bool(msg.get("on"))
            if changed and self.kind in ("scrcpy", "scrcpy-wifi"):      # scrcpy only reads this when it starts
                self.jobs.put((self.start, (self.kind, self.audio, self.serial)))
            else:
                self.jobs.put((self._report, ()))
        elif a == "allow-firewall":
            threading.Thread(target=self.allow_firewall, daemon=True).start()
        elif a == "fetch":
            if msg.get("name") in ("uxplay", "scrcpy"):
                self.tools.fetch(msg["name"])
                self.tool_changed()      # already downloaded: fetch has nothing to do and says nothing
        elif a == "install-wireless-display":
            os.startfile("ms-settings:optionalfeatures")
        elif a == "project-settings":
            os.startfile("ms-settings:project")
