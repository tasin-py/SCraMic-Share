"""ScramicShare Cam / ScramicShare Mic: the phone as a real camera and microphone in other apps.

Camera: UnityCapture's DirectShow filter, registered under the name "ScramicShare Cam".
        Zoom, Meet/Teams in Chrome or Edge, Discord, OBS ... list it on Windows 10 and 11.
        Frames are pushed to it by unitycam.py.
Mic:    VB-CABLE. Its two devices are renamed: "ScramicShare Mic" is what other apps pick as
        their microphone; "ScramicShare Mic Feed" is where SCraMic Share plays the phone's sound.

Installing either needs administrator rights once (Windows asks with a UAC prompt).
"""
import ctypes
import io
import sys
import threading
import time
import uuid
import winreg
from ctypes import wintypes

CAM_NAME = "ScramicShare Cam"
MIC_NAME = "ScramicShare Mic"
FEED_NAME = "ScramicShare Mic Feed"
FEED16_NAME = "ScramicShare Feed 16ch"
IFACE_NAME = "SCraMic Share"       # Windows shows devices as "name (this)"; it was "VB-Audio Virtual Cable"
CABLE_DRIVER = "VBAudioVACWDM"

VIDEO_INPUT_CATEGORY = r"CLSID\{860BB310-5D01-11d0-BD3B-00A0C911CE86}\Instance"
MMDEV = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
PK_DEVICEDESC = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
PK_IFACE = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"
PK_DRIVER = "{a8b865dd-2e3d-4094-ad97-e593a70c75d6},8"


# ---------------------------------------------------------------- elevation
def run_elevated(exe, params, cwd=None):
    """Start exe with administrator rights; Windows shows the UAC prompt. True if it started."""
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(exe), params, cwd, 0)
    return r > 32


# ---------------------------------------------------------------- detection (no admin needed)
def cam_installed():
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, VIDEO_INPUT_CATEGORY) as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    return False
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as s:
                        if winreg.QueryValueEx(s, "FriendlyName")[0] == CAM_NAME:
                            return True
                except OSError:
                    pass
    except OSError:
        return False


def _cable_endpoints(flow):
    """(name, name in brackets) of each active virtual-cable endpoint, from the registry (readable by anyone)."""
    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{MMDEV}\\{flow}") as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as d:
                        if winreg.QueryValueEx(d, "DeviceState")[0] != 1:      # 1 = active
                            continue
                    with winreg.OpenKey(k, sub + "\\Properties") as p:
                        if winreg.QueryValueEx(p, PK_DRIVER)[0] == CABLE_DRIVER:
                            out.append((winreg.QueryValueEx(p, PK_DEVICEDESC)[0], winreg.QueryValueEx(p, PK_IFACE)[0]))
                except OSError:
                    pass
    except OSError:
        pass
    return out


def mic_state():
    caps = _cable_endpoints("Capture")
    if not caps:
        return "missing"
    return "ready" if all(c == (MIC_NAME, IFACE_NAME) for c in caps) else "needs-rename"


# ---------------------------------------------------------------- install
def install_cam(dll_path):
    return run_elevated("regsvr32.exe", f'/s "{dll_path}" "/i:UnityCaptureName={CAM_NAME}"')


def uninstall_cam(dll_path):
    return run_elevated("regsvr32.exe", f'/s /u "{dll_path}"')


def install_mic(setup_exe):
    # VB-CABLE's own setup, silently (-i install, -h hidden); then we rename its devices.
    return run_elevated(setup_exe, "-i -h", cwd=str(setup_exe.parent))


def setup(tools, notify):
    """Background helpers for the PC page's Install buttons."""
    def state():
        notify({"t": "devices", "cam": "ready" if cam_installed() else "missing", "mic": mic_state()})

    def wait_for(check, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if check():
                return True
            time.sleep(1)
        return False

    def do_cam():
        tools.fetch("ucam", wait=True)
        dll = tools.find("ucam", "UnityCaptureFilter64.dll")
        if dll and install_cam(dll):
            wait_for(cam_installed, 60)
        state()

    def do_mic():
        if mic_state() == "missing":
            tools.fetch("vbcable", wait=True)
            setup_exe = tools.find("vbcable", "VBCABLE_Setup_x64.exe")
            if setup_exe and install_mic(setup_exe):
                wait_for(lambda: mic_state() != "missing", 120)
        if mic_state() == "needs-rename":
            try:
                rename_mic()
            except Exception:
                pass
            if mic_state() != "ready" and rename_mic_elevated():
                wait_for(lambda: mic_state() == "ready", 60)
        state()

    def handle(msg):
        a = msg.get("a")
        job = {"state": state, "install-cam": do_cam, "install-mic": do_mic}.get(a)
        if job:
            threading.Thread(target=job, daemon=True, name=f"dev-{a}").start()

    return handle


def rename_mic_elevated():
    """Rename the VB-CABLE devices (needs admin): runs this file elevated with --rename-mic."""
    if getattr(sys, "frozen", False):        # the installed exe: it handles --rename-mic itself
        return run_elevated(sys.executable, "--rename-mic")
    script = str(__import__("pathlib").Path(__file__).resolve())
    exe = sys.executable.replace("pythonw.exe", "python.exe")
    return run_elevated(exe, f'"{script}" --rename-mic')


# ---------------------------------------------------------------- renaming via Windows' audio API
class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, s):
        u = uuid.UUID(s)
        g = cls()
        ctypes.memmove(ctypes.byref(g), u.bytes_le, 16)
        return g


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("p", ctypes.c_void_p), ("pad", ctypes.c_void_p)]


VT_LPWSTR = 31
CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
eRender, eCapture = 0, 1
DEVICE_STATE_ACTIVE = 1
STGM_READ, STGM_READWRITE = 0, 2


def _vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])


def _endpoints(flow, mode):
    """Yield (property store, DeviceDesc) for each active endpoint of a flow."""
    ole = ctypes.windll.ole32
    ole.CoInitialize(None)
    enum = ctypes.c_void_p()
    hr = ole.CoCreateInstance(ctypes.byref(GUID.of(CLSID_MMDeviceEnumerator)), None, 1,
                              ctypes.byref(GUID.of(IID_IMMDeviceEnumerator)), ctypes.byref(enum))
    if hr != 0:
        raise OSError(f"MMDeviceEnumerator failed: {hr & 0xFFFFFFFF:#x}")
    coll = ctypes.c_void_p()
    _vcall(enum, 3, ctypes.HRESULT, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))(
        enum, flow, DEVICE_STATE_ACTIVE, ctypes.byref(coll))
    n = wintypes.UINT()
    _vcall(coll, 3, ctypes.HRESULT, ctypes.POINTER(wintypes.UINT))(coll, ctypes.byref(n))
    key = PROPERTYKEY(GUID.of("{a45c254e-df1c-4efd-8020-67d146a850e0}"), 2)
    for i in range(n.value):
        dev = ctypes.c_void_p()
        _vcall(coll, 4, ctypes.HRESULT, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(coll, i, ctypes.byref(dev))
        store = ctypes.c_void_p()
        hr = _vcall(dev, 4, ctypes.c_long, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))(dev, mode, ctypes.byref(store))
        if hr != 0:
            raise PermissionError(f"OpenPropertyStore failed: {hr & 0xFFFFFFFF:#x}")
        pv = PROPVARIANT()
        _vcall(store, 5, ctypes.HRESULT, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(
            store, ctypes.byref(key), ctypes.byref(pv))
        name = ctypes.wstring_at(pv.p) if pv.vt == VT_LPWSTR and pv.p else ""
        yield store, key, name


def list_endpoint_names(flow):
    return [name for _s, _k, name in _endpoints(flow, STGM_READ)]


def _pkey(text):
    fmtid, pid = text.split(",")
    return PROPERTYKEY(GUID.of(fmtid), int(pid))


def _get_text(store, key):
    pv = PROPVARIANT()
    _vcall(store, 5, ctypes.HRESULT, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(
        store, ctypes.byref(key), ctypes.byref(pv))
    return ctypes.wstring_at(pv.p) if pv.vt == VT_LPWSTR and pv.p else ""


def _set_text(store, key, text):
    buf = ctypes.create_unicode_buffer(text)
    pv = PROPVARIANT(vt=VT_LPWSTR, p=ctypes.cast(buf, ctypes.c_void_p))
    _vcall(store, 6, ctypes.HRESULT, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(
        store, ctypes.byref(key), ctypes.byref(pv))


def rename_mic():
    """Admin only. Removes every "CABLE" and "VB-Audio" name from the virtual cable's devices."""
    done = []
    driver, iface = _pkey(PK_DRIVER), _pkey(PK_IFACE)
    for flow in (eCapture, eRender):
        for store, key, name in _endpoints(flow, STGM_READWRITE):
            if _get_text(store, driver) != CABLE_DRIVER:
                continue
            new = MIC_NAME if flow == eCapture else (FEED16_NAME if "16" in name else FEED_NAME)
            _set_text(store, key, new)
            _set_text(store, iface, IFACE_NAME)
            _vcall(store, 7, ctypes.HRESULT)(store)
            done.append(new)
    return done


# ---------------------------------------------------------------- frames -> ScramicShare Cam
class VirtualCam:
    """Takes JPEG frames from the PC page and shows them in ScramicShare Cam."""
    W, H, FPS = 1280, 720, 30

    def __init__(self):
        self.cam = None
        self.want = (self.W, self.H, self.FPS)
        self.frame = None
        self.last_new = 0.0
        self.lock = threading.Lock()
        self.error = ""
        self.idle = None
        threading.Thread(target=self._loop, daemon=True, name="vcam").start()

    def _idle_frame(self):
        if self.idle is None:
            import numpy as np
            from PIL import Image, ImageDraw, ImageFont
            im = Image.new("RGB", (1280, 720), (25, 25, 25))
            d = ImageDraw.Draw(im)
            try:
                big = ImageFont.truetype("segoeuib.ttf", 54)
                small = ImageFont.truetype("segoeui.ttf", 30)
            except OSError:
                big = small = ImageFont.load_default()
            d.rounded_rectangle((640 - 60, 200, 640 + 60, 320), 28, fill=(255, 122, 26))
            d.text((640, 380), "SCraMic Share", font=big, fill=(242, 242, 242), anchor="mm")
            d.text((640, 440), "Start Camera share on your phone", font=small, fill=(150, 150, 150), anchor="mm")
            self.idle = np.asarray(im.resize((self.W, self.H)))
        return self.idle

    def configure(self, w, h, fps):
        """Output size for ScramicShare Cam: 720p30 normally, up to 1080p60 in Streamer mode."""
        try:
            self.want = (max(320, min(int(w), 1920)), max(240, min(int(h), 1080)), max(15, min(int(fps), 60)))
        except (TypeError, ValueError):
            pass

    def push_jpeg(self, data):
        """Called from the server thread with one JPEG frame."""
        try:
            import numpy as np
            from PIL import Image
            im = Image.open(io.BytesIO(data)).convert("RGB")
            with self.lock:
                self.frame = np.asarray(im)
                self.last_new = time.monotonic()
        except Exception as e:
            self.error = str(e)

    def _loop(self):
        next_frame = time.monotonic()
        while True:
            if not cam_installed():
                time.sleep(3)
                continue
            try:
                from unitycam import UnityCam
                if self.want != (self.W, self.H, self.FPS):
                    self.W, self.H, self.FPS = self.want
                    self.idle = None
                if self.cam is None:
                    self.cam = UnityCam()
                    self.error = ""
                with self.lock:
                    live = self.frame is not None and time.monotonic() - self.last_new < 2.0
                    f = self.frame if live else None
                if f is None or f.shape[:2] != (self.H, self.W):   # none yet, or from before a size change
                    f = self._idle_frame()
                if not self.cam.send(f):                           # no app has the camera open
                    time.sleep(0.5)
                    next_frame = time.monotonic()
                    continue
                next_frame += 1 / self.FPS
                wait = next_frame - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                else:
                    next_frame = time.monotonic()                  # fell behind: don't try to catch up
            except Exception as e:
                self.error = str(e)
                self.cam = None
                time.sleep(2)


def rename_mic_command():
    """--rename-mic: this program restarted with administrator rights, just for the rename."""
    try:
        rename_mic()
    except Exception as e:
        ctypes.windll.user32.MessageBoxW(None, f"Couldn't rename the VB-CABLE devices:\n{e}", "SCraMic Share", 0x10)


if __name__ == "__main__" and "--rename-mic" in sys.argv:
    rename_mic_command()
