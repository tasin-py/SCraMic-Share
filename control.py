"""Mouse and keyboard input on the PC (Windows SendInput), driven by the phone.

Coordinates arrive normalized (0..1) over the primary monitor, the same monitor
that is streamed to the phone. Every key or button pressed through here is
remembered so it can all be released if the phone disconnects mid-press.
"""
import ctypes
import sys
from ctypes import wintypes

IS_WIN = sys.platform == "win32"

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0001, 0x0002, 0x0004

BUTTONS = {
    "l": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "r": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "m": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

# Named keys the phone can send.
VK = {
    "win": 0x5B, "ctrl": 0x11, "alt": 0x12, "shift": 0x10,
    "esc": 0x1B, "tab": 0x09, "enter": 0x0D, "backspace": 0x08, "delete": 0x2E,
    "space": 0x20, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "insert": 0x2D,
    "printscreen": 0x2C, "menu": 0x5D,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
}
EXTENDED = {0x5B, 0x2E, 0x25, 0x26, 0x27, 0x28, 0x24, 0x23, 0x21, 0x22, 0x2D, 0x2C, 0x5D}

if IS_WIN:
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)


def _send(*inputs):
    if not IS_WIN or not inputs:
        return
    arr = (INPUT * len(inputs))(*inputs)
    _user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _mouse(flags, dx=0, dy=0, data=0):
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    return i


def _key(vk=0, up=False, scan=0, unicode=False):
    i = INPUT(type=INPUT_KEYBOARD)
    flags = (KEYEVENTF_KEYUP if up else 0)
    if unicode:
        flags |= KEYEVENTF_UNICODE
    elif vk in EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    i.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


def cursor_pos():
    """Cursor position normalized over the primary monitor, or None."""
    if not IS_WIN:
        return None
    pt = wintypes.POINT()
    if not _user32.GetCursorPos(ctypes.byref(pt)):
        return None
    w, h = _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)
    if not w or not h:
        return None
    return pt.x / w, pt.y / h


class Controller:
    def __init__(self):
        self.buttons = set()   # mouse buttons currently held
        self.keys = set()      # virtual keys currently held

    # ---- mouse
    def _abs(self, x, y):
        x = min(1.0, max(0.0, float(x)))
        y = min(1.0, max(0.0, float(y)))
        return int(round(x * 65535)), int(round(y * 65535))

    def move(self, x, y):
        dx, dy = self._abs(x, y)
        _send(_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, dx, dy))

    def button(self, b, down, x=None, y=None):
        if b not in BUTTONS:
            return
        seq = []
        if x is not None and y is not None:
            dx, dy = self._abs(x, y)
            seq.append(_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, dx, dy))
        seq.append(_mouse(BUTTONS[b][0 if down else 1]))
        _send(*seq)
        (self.buttons.add if down else self.buttons.discard)(b)

    def click(self, b, x, y):
        self.button(b, True, x, y)
        self.button(b, False)

    def wheel(self, dy=0, dx=0):
        seq = []
        if dy:
            seq.append(_mouse(MOUSEEVENTF_WHEEL, data=int(dy)))
        if dx:
            seq.append(_mouse(MOUSEEVENTF_HWHEEL, data=int(dx)))
        _send(*seq)

    # ---- keyboard
    def key(self, name_or_vk, action="tap"):
        vk = VK.get(name_or_vk) if isinstance(name_or_vk, str) else int(name_or_vk)
        if not vk:
            return
        if action in ("down", "tap"):
            _send(_key(vk))
            self.keys.add(vk)
        if action in ("up", "tap"):
            _send(_key(vk, up=True))
            self.keys.discard(vk)

    def char(self, ch):
        """A letter/digit pressed as a real key, so held Ctrl/Alt/Win apply (Ctrl+C, Win+D...)."""
        c = ch.upper()
        if len(c) == 1 and ("A" <= c <= "Z" or "0" <= c <= "9"):
            self.key(ord(c), "tap")
        else:
            self.text(ch)

    def text(self, s):
        seq = []
        for ch in str(s)[:2000]:
            if ch == "\n":
                seq += [_key(VK["enter"]), _key(VK["enter"], up=True)]
                continue
            for unit in _utf16(ch):
                seq += [_key(0, scan=unit, unicode=True), _key(0, up=True, scan=unit, unicode=True)]
        _send(*seq)

    def release_all(self):
        for b in list(self.buttons):
            _send(_mouse(BUTTONS[b][1]))
        for vk in list(self.keys):
            _send(_key(vk, up=True))
        self.buttons.clear()
        self.keys.clear()

    # ---- one message from the phone
    def handle(self, d):
        t = d.get("t")
        if t == "m":
            a, x, y = d.get("a"), d.get("x"), d.get("y")
            b = d.get("b", "l")
            if a == "move" and x is not None:
                self.move(x, y)
            elif a == "down":
                self.button(b, True, x, y)
            elif a == "up":
                self.button(b, False, x, y)
            elif a == "click" and x is not None:
                self.click(b, x, y)
        elif t == "wheel":
            self.wheel(int(d.get("dy", 0)), int(d.get("dx", 0)))
        elif t == "key":
            self.key(d.get("k"), d.get("a", "tap"))
        elif t == "char":
            self.char(str(d.get("s", ""))[:1])
        elif t == "text":
            self.text(d.get("s", ""))


def _utf16(ch):
    b = ch.encode("utf-16-le")
    return [int.from_bytes(b[i:i + 2], "little") for i in range(0, len(b), 2)]
