"""Teacher mode: InkCast's ink layer on the PC screen, plus screen streaming and PC control.

Based on InkCast by ssfshad (https://github.com/ssfshad/inkcast), Apache License 2.0.
The ink overlay, item model and drawing code are InkCast's; see NOTICE.
"""
import asyncio
import base64
import io
import json
import math
import os
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from aiohttp import web, WSMsgType
from PySide6.QtCore import Qt, QObject, Signal, QPointF, QRectF, QTimer, QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPolygonF, QRegion
from PySide6.QtWidgets import QApplication, QWidget

import control

REF = 1920.0                      # sizes are defined relative to a 1920px-wide screen
STROKES = {"pen", "marker", "hl", "neon", "laser", "farrow"}
SHAPES = {"line", "arrow", "rect", "ellipse"}
LASER_HOLD, LASER_FADE = 0.6, 0.6  # seconds a laser line stays, then fades
PREVIEW_WIDTH = 1280               # default width of the screen preview sent to the phone
PREVIEW_MAX = 2560                 # zoomed in on the phone -> sharper frames, up to this
PREVIEW_QUALITY = 62
MAX_IMAGE = 1600                   # pasted/inserted images are scaled down to this
BGS = ["white", "grid", "black", "green"]
BGC = {"white": "#ffffff", "grid": "#ffffff", "black": "#141517", "green": "#1f3a2c"}
GEOM_KEYS = ("pts", "w", "a", "b", "x", "y", "fs", "tw", "th", "h")

# Text fonts: the PC serves the same font files to the tablet, so text looks
# (and measures) identical on both. First file found in C:\Windows\Fonts wins.
FONT_OPTIONS = {
    "sans":  [("segoeuib.ttf", "Segoe UI", True)],
    "hand":  [("inkfree.ttf", "Ink Free", False), ("comicbd.ttf", "Comic Sans MS", True)],
    "serif": [("georgiab.ttf", "Georgia", True)],
}

# Global shortcuts: Ctrl + Alt + <key>
HOTKEYS = [
    ("Z", "undo", "Undo"),
    ("Y", "redo", "Redo"),
    ("C", "clear", "Clear ink"),
    ("H", "hide", "Hide / show ink"),
    ("L", "laser", "Laser pointer on / off"),
    ("W", "board", "Whiteboard on / off"),
    ("B", "bg", "Change whiteboard background"),
    ("V", "paste", "Paste image from clipboard"),
]


def resolve_fonts():
    fontdir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    out = {}
    for name, options in FONT_OPTIONS.items():
        chosen = None
        for fname, family, bold in options:
            path = os.path.join(fontdir, fname)
            if os.path.isfile(path):
                chosen = (path, family, bold)
                break
        if chosen is None:
            _f, family, bold = options[-1]
            chosen = (None, family, bold)
        out[name] = chosen
    return out


FONTS = resolve_fonts()


def geom_of(it):
    g = {}
    for k in GEOM_KEYS:
        if k in it:
            v = it[k]
            if k == "pts":
                v = [list(p) for p in v]
            elif isinstance(v, list):
                v = list(v)
            g[k] = v
    return g


def xf_geom(g, f, tx, ty):
    """x' = f*x + tx, y' = f*y + ty; sizes scale by f (uniform in screen pixels)."""
    out = {}
    if "pts" in g:
        out["pts"] = [[x * f + tx, y * f + ty] for x, y in g["pts"]]
    for k in ("a", "b"):
        if k in g:
            out[k] = [g[k][0] * f + tx, g[k][1] * f + ty]
    if "x" in g:
        out["x"] = g["x"] * f + tx
        out["y"] = g["y"] * f + ty
    for k in ("w", "h", "fs", "tw", "th"):
        if k in g:
            out[k] = g[k] * f
    return out


def encode_image_bytes(data):
    """Any image bytes -> (data URL, width, height), scaled down to MAX_IMAGE."""
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(data))
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    im.thumbnail((MAX_IMAGE, MAX_IMAGE))
    has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    buf = io.BytesIO()
    if has_alpha:
        im.convert("RGBA").save(buf, "PNG")
        mime = "image/png"
    else:
        im.convert("RGB").save(buf, "JPEG", quality=90)
        mime = "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode(), im.width, im.height


def qimage_to_dataurl(img):
    if img.width() > MAX_IMAGE or img.height() > MAX_IMAGE:
        img = img.scaled(MAX_IMAGE, MAX_IMAGE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    if img.hasAlphaChannel():
        img.save(buf, "PNG")
        mime = "image/png"
    else:
        img.save(buf, "JPG", 90)
        mime = "image/jpeg"
    buf.close()
    return f"data:{mime};base64," + base64.b64encode(bytes(ba)).decode(), img.width(), img.height()


# --------------------------------------------------------------------------- overlay (PC side)

class Bridge(QObject):
    ops = Signal(str)       # raw JSON text from the tablet, parsed on the GUI thread
    hotkey = Signal(str)    # name of a pressed global shortcut
    tablet = Signal()       # a tablet connected
    inkOn = Signal(bool)    # show / hide the ink layer (shown while Teacher mode is open)


def smooth_path(pts):
    path = QPainterPath(pts[0])
    if len(pts) < 3:
        for q in pts[1:]:
            path.lineTo(q)
        return path
    for i in range(1, len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        path.quadTo(a, QPointF((a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0))
    path.lineTo(pts[-1])
    return path


class Overlay(QWidget):
    def __init__(self):
        flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                 Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(QGuiApplication.primaryScreen().geometry())
        self.pages = {"screen": {}, "board": {}}   # id -> item, in z-order, per page
        self.page = "screen"
        self.bg = "white"
        self.live = set()     # ids being drawn / moved (painted live, not cached)
        self.snap = {}        # id -> geometry when a move/resize started
        self.lasers = {}      # id -> laser stroke (temporary)
        self.cache = None
        self.dirty = True     # cache needs a full rebuild
        self.pending = []     # finished items to paint on top of the cache
        self.region = QRegion()
        self.full = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    @property
    def items(self):
        return self.pages[self.page]

    # ---- dirty-region tracking (repainting only what changed keeps it fast)
    def _mark(self, r):
        if r is not None:
            self.region = self.region.united(r.toAlignedRect())

    def _rect_of(self, it, pts=None):
        W, H = self.width(), self.height()
        s = W / REF
        k = it.get("k")
        m = 4.0
        if k in STROKES:
            P = pts if pts is not None else it.get("pts", [])
            if not P:
                return None
            xs = [p[0] for p in P]
            ys = [p[1] for p in P]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            w = float(it.get("w", 6)) * s
            m += w * (1.7 if k in ("neon", "laser") else 0.7)
            if k == "farrow":
                m += max(14 * s, w * 3.2) + w
        elif k in SHAPES:
            x0, x1 = sorted((it["a"][0], it["b"][0]))
            y0, y1 = sorted((it["a"][1], it["b"][1]))
            w = float(it.get("w", 6)) * s
            m += w + (max(14 * s, w * 3.2) if k == "arrow" else 0)
        elif k == "text":
            x0, y0 = it["x"], it["y"]
            x1, y1 = x0 + it.get("tw", 0.1), y0 + it.get("th", 0.05)
            m += float(it.get("fs", 30)) * s * 0.5
        elif k == "img":
            x0, y0 = it["x"], it["y"]
            x1, y1 = x0 + it["w"], y0 + it["h"]
        else:
            return None
        return QRectF(x0 * W - m, y0 * H - m, (x1 - x0) * W + 2 * m, (y1 - y0) * H + 2 * m)

    # ---- incoming ops
    def on_ops(self, text):
        try:
            d = json.loads(text)
        except ValueError:
            return
        for op in (d.get("ops", []) if d.get("t") == "b" else [d]):
            try:
                self._apply(op)
            except Exception as e:  # never let one bad op kill the overlay
                print("op error:", e)
        self._flush_region()

    def _flush_region(self):
        if self.full:
            self.update()
        elif not self.region.isEmpty():
            self.update(self.region)
        self.region = QRegion()
        self.full = False

    def _prep(self, it):
        it["_c"] = QColor(it.get("c", "#ff3b30"))
        if it.get("k") == "img":
            q = QImage()
            src = it.get("src", "")
            try:
                q.loadFromData(base64.b64decode(src.split(",", 1)[1]))
            except Exception:
                pass
            it["_img"] = q
        if it.get("k") == "laser":
            it["_t0"] = time.monotonic()
            it["_end"] = None
        return it

    def _finish(self, it):
        """Item stopped being live: paint it onto the cache cheaply if it's on top."""
        ids = list(self.items.keys())
        if not self.dirty and self.cache is not None and ids and ids[-1] == it["id"]:
            self.pending.append(it)
        else:
            self.dirty = True

    def _ids(self, d):
        if "ids" in d:
            return list(d["ids"])
        return [d["id"]] if "id" in d else []

    def _apply(self, d):
        t = d.get("t")
        items = self.items
        if t == "add":
            it = self._prep(dict(d["item"]))
            if it["k"] == "laser":
                self.lasers[it["id"]] = it
            else:
                items[it["id"]] = it
                if d.get("done"):
                    self._finish(it)
                else:
                    self.live.add(it["id"])
            self._mark(self._rect_of(it))
        elif t == "pts":
            it = items.get(d["id"]) or self.lasers.get(d["id"])
            if it and d.get("pts"):
                seg = ([it["pts"][-1]] if it["pts"] else []) + d["pts"]
                it["pts"].extend(d["pts"])
                if it["k"] == "farrow":       # the arrow head moves with the end of the line
                    seg = it["pts"][-12:] if len(it["pts"]) > 12 else it["pts"]
                self._mark(self._rect_of(it, seg))
        elif t == "upd":
            it = items.get(d["id"])
            if it:
                self._mark(self._rect_of(it))
                for k, v in d.items():
                    if k not in ("t", "id"):
                        it[k] = v
                if "c" in d:
                    it["_c"] = QColor(d["c"])
                self._mark(self._rect_of(it))
                if d["id"] not in self.live:
                    self.dirty = True
        elif t == "grab":
            for i in self._ids(d):
                it = items.get(i)
                if it:
                    self.live.add(i)
                    self.snap[i] = geom_of(it)
                    self.dirty = True
                    self._mark(self._rect_of(it))
        elif t == "xf":
            f, tx, ty = float(d.get("f", 1)), float(d.get("tx", 0)), float(d.get("ty", 0))
            for i in self._ids(d):
                it = items.get(i)
                if not it:
                    continue
                g = self.snap.get(i) or geom_of(it)
                self.snap.setdefault(i, g)
                self._mark(self._rect_of(it))
                it.update(xf_geom(g, f, tx, ty))
                self._mark(self._rect_of(it))
        elif t == "end":
            for i in self._ids(d):
                self.snap.pop(i, None)
                if i in self.lasers:
                    self.lasers[i]["_end"] = time.monotonic()
                if i in self.live:
                    self.live.discard(i)
                    it = items.get(i)
                    if it:
                        if len(self._ids(d)) == 1 and "id" in d:
                            self._finish(it)
                        else:
                            self.dirty = True
                        self._mark(self._rect_of(it))
        elif t == "del":
            it = items.pop(d["id"], None)
            if it is not None:
                self.live.discard(d["id"])
                self.dirty = True
                self._mark(self._rect_of(it))
        elif t == "clear":
            items.clear(); self.live.clear(); self.lasers.clear(); self.snap.clear()
            self.dirty = True
            self.full = True
        elif t == "page":
            if d.get("p") in self.pages:
                self.page = d["p"]
            if d.get("bg") in BGC:
                self.bg = d["bg"]
            self.live.clear(); self.snap.clear()
            self.dirty = True
            self.full = True
        elif t == "sync":
            self.live.clear(); self.snap.clear()
            pages = d.get("pages", {})
            for name in self.pages:
                self.pages[name] = {}
                for it in pages.get(name, []):
                    it = self._prep(dict(it))
                    self.pages[name][it["id"]] = it
            if d.get("page") in self.pages:
                self.page = d["page"]
            if d.get("bg") in BGC:
                self.bg = d["bg"]
            self.dirty = True
            self.full = True

    def add_local(self, item):
        self._apply({"t": "add", "item": item, "done": True})
        self._flush_region()

    # ---- painting
    def _tick(self):
        if not self.lasers:
            return
        now = time.monotonic()
        for i, it in list(self.lasers.items()):
            self._mark(self._rect_of(it))
            end = it["_end"]
            if (end is not None and now - end > LASER_HOLD + LASER_FADE) or now - it["_t0"] > 60:
                del self.lasers[i]
        self._flush_region()

    def _new_cache(self):
        dpr = self.devicePixelRatioF()
        img = QImage(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)),
                     QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)
        return img

    def _painter(self, dev):
        p = QPainter(dev)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        return p

    def _update_cache(self):
        if self.dirty or self.cache is None:
            self.cache = self._new_cache()
            p = self._painter(self.cache)
            for i, it in self.items.items():
                if i not in self.live:
                    self._draw(p, it)
            p.end()
            self.dirty = False
            self.pending.clear()
        elif self.pending:
            p = self._painter(self.cache)
            for it in self.pending:
                if it["id"] in self.items and it["id"] not in self.live:
                    self._draw(p, it)
            p.end()
            self.pending.clear()

    def _paint_board(self, p):
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), QColor(BGC.get(self.bg, "#ffffff")))
        if self.bg == "grid":
            s = W / REF
            step = 48 * s
            p.setPen(QPen(QColor("#dfe3e8"), max(1.0, s)))
            x = step
            while x < W:
                p.drawLine(QPointF(x, 0), QPointF(x, H)); x += step
            y = step
            while y < H:
                p.drawLine(QPointF(0, y), QPointF(W, y)); y += step

    def paintEvent(self, _e):
        self._update_cache()
        p = self._painter(self)
        if self.page == "board":
            self._paint_board(p)
        p.drawImage(QPointF(0, 0), self.cache)
        for i, it in self.items.items():
            if i in self.live:
                self._draw(p, it)
        now = time.monotonic()
        for it in self.lasers.values():
            fade = 1.0
            if it["_end"] is not None:
                age = now - it["_end"] - LASER_HOLD
                if age > 0:
                    fade = max(0.0, 1.0 - age / LASER_FADE)
            if fade > 0:
                self._draw(p, it, fade)
        p.end()

    def _pen(self, p, color, width, cap=Qt.RoundCap, alpha=1.0):
        c = QColor(color)
        c.setAlphaF(max(0.0, min(1.0, c.alphaF() * alpha)))
        p.setPen(QPen(c, max(0.5, width), Qt.SolidLine, cap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)

    def _head(self, p, tip, ux, uy, c, w, s, fade=1.0):
        hl = max(14 * s, w * 3.2)
        hw = hl * 0.55
        bx, by = tip.x() - ux * hl, tip.y() - uy * hl
        col = QColor(c)
        col.setAlphaF(col.alphaF() * fade)
        p.setPen(QPen(col, max(0.5, w * 0.5), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(col)
        p.drawPolygon(QPolygonF([tip, QPointF(bx - uy * hw, by + ux * hw), QPointF(bx + uy * hw, by - ux * hw)]))

    def _draw(self, p, it, fade=1.0):
        W, H = self.width(), self.height()
        s = W / REF
        k = it["k"]
        c = it["_c"]
        if k in STROKES:
            w = float(it.get("w", 6)) * s
            pts = [QPointF(x * W, y * H) for x, y in it["pts"]]
            if not pts:
                return
            path = smooth_path(pts)

            def stroke(color, width, cap=Qt.RoundCap, alpha=1.0):
                self._pen(p, color, width, cap, alpha * fade)
                if len(pts) == 1:
                    p.drawPoint(pts[0])
                else:
                    p.drawPath(path)

            if k in ("neon", "laser"):
                stroke(c, w * 3.0, alpha=0.12)
                stroke(c, w * 1.8, alpha=0.25)
                stroke(c, w)
                stroke(QColor(255, 255, 255), w * 0.4, alpha=0.85)
            elif k == "hl":
                stroke(c, w, Qt.SquareCap, 0.35)
            else:
                stroke(c, w)
            if k == "farrow" and len(pts) >= 2:
                last = pts[-1]
                hl = max(14 * s, w * 3.2)
                j = len(pts) - 2
                while j > 0 and math.hypot(pts[j].x() - last.x(), pts[j].y() - last.y()) < hl * 0.8:
                    j -= 1
                dx, dy = last.x() - pts[j].x(), last.y() - pts[j].y()
                d = math.hypot(dx, dy)
                if d >= 0.5:
                    ux, uy = dx / d, dy / d
                    tip = QPointF(last.x() + ux * w * 0.5, last.y() + uy * w * 0.5)
                    self._head(p, tip, ux, uy, c, w, s, fade)
        elif k in SHAPES:
            w = float(it.get("w", 6)) * s
            a = QPointF(it["a"][0] * W, it["a"][1] * H)
            b = QPointF(it["b"][0] * W, it["b"][1] * H)
            self._pen(p, c, w)
            if k == "line":
                p.drawLine(a, b)
            elif k == "arrow":
                dx, dy = b.x() - a.x(), b.y() - a.y()
                L = math.hypot(dx, dy)
                if L < 1:
                    return
                ux, uy = dx / L, dy / L
                hl = min(max(14 * s, w * 3.2), L)
                p.drawLine(a, QPointF(b.x() - ux * hl * 0.8, b.y() - uy * hl * 0.8))
                hw = hl * 0.55
                bx, by = b.x() - ux * hl, b.y() - uy * hl
                p.setPen(QPen(c, max(0.5, w * 0.5), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.setBrush(c)
                p.drawPolygon(QPolygonF([b, QPointF(bx - uy * hw, by + ux * hw), QPointF(bx + uy * hw, by - ux * hw)]))
            else:
                r = QRectF(a, b).normalized()
                if k == "rect":
                    p.drawRect(r)
                else:
                    p.drawEllipse(r)
        elif k == "text":
            fs = max(1.0, float(it.get("fs", 30)) * s)
            _path, family, bold = FONTS.get(it.get("f", "sans"), FONTS["sans"])
            f = QFont(family)
            f.setPixelSize(max(1, int(round(fs))))
            f.setBold(bold)
            p.setFont(f)
            p.setPen(QPen(c))
            x, y = it["x"] * W, it["y"] * H
            for i, line in enumerate(str(it.get("txt", "")).split("\n")):
                p.drawText(QPointF(x, y + fs * 0.92 + i * fs * 1.2), line)
        elif k == "img":
            q = it.get("_img")
            if q is not None and not q.isNull():
                p.drawImage(QRectF(it["x"] * W, it["y"] * H, it["w"] * W, it["h"] * H), q)



# --------------------------------------------------------------------------- phone connection (/live)

class Live:
    """Ink state, screen frames and PC control for the phone's Teacher / PC Control pages.

    Runs on the server's asyncio loop. Ink ops are mirrored here (so a reloaded
    phone page gets them back) and forwarded to the Overlay on the GUI thread.
    """

    def __init__(self, bridge, aspect, token_ok):
        self.bridge = bridge
        self.aspect = aspect
        self.token_ok = token_ok
        self.pages = {"screen": {}, "board": {}}
        self.page = "screen"
        self.bg = "white"
        self.snap = {}
        self.clients = {}            # ws -> mode ("teacher" | "control")
        self.exec = ThreadPoolExecutor(max_workers=2)
        self.tl = threading.local()
        self.loop = None
        self.grab_failed = False
        self.ctl = control.Controller()

    def routes(self, app):
        app.router.add_get("/live", self.ws_handler)
        app.router.add_get("/font/{name}", self.font)

    # ---- state mirror (same rules as the overlay)
    def apply(self, d):
        t = d.get("t")
        items = self.pages[self.page]
        ids = list(d["ids"]) if "ids" in d else ([d["id"]] if "id" in d else [])
        if t == "b":
            for op in d.get("ops", []):
                self.apply(op)
        elif t == "add":
            it = d.get("item", {})
            if it.get("k") != "laser":
                items[it["id"]] = it
        elif t == "pts":
            it = items.get(d.get("id"))
            if it and "pts" in it:
                it["pts"].extend(d.get("pts", []))
        elif t == "upd":
            it = items.get(d.get("id"))
            if it:
                for k, v in d.items():
                    if k not in ("t", "id"):
                        it[k] = v
        elif t == "grab":
            for i in ids:
                if i in items:
                    self.snap[i] = geom_of(items[i])
        elif t == "xf":
            f, tx, ty = float(d.get("f", 1)), float(d.get("tx", 0)), float(d.get("ty", 0))
            for i in ids:
                it = items.get(i)
                if it:
                    g = self.snap.setdefault(i, geom_of(it))
                    it.update(xf_geom(g, f, tx, ty))
        elif t == "end":
            for i in ids:
                self.snap.pop(i, None)
        elif t == "del":
            items.pop(d.get("id"), None)
        elif t == "clear":
            items.clear()
        elif t == "page":
            if d.get("p") in self.pages:
                self.page = d["p"]
            if d.get("bg") in BGC:
                self.bg = d["bg"]
        elif t == "sync":
            pages = d.get("pages", {})
            self.pages = {n: {it["id"]: it for it in pages.get(n, [])} for n in ("screen", "board")}
            if d.get("page") in self.pages:
                self.page = d["page"]
            if d.get("bg") in BGC:
                self.bg = d["bg"]

    # ---- screen frames
    def grab(self, width, quality):
        from PIL import Image
        if not hasattr(self.tl, "sct"):
            import mss
            try:
                import mss.windows as mw
                mw.CAPTUREBLT = 0   # keeps our own ink layer out of the frames (no double ink on the phone)
            except Exception:
                pass
            self.tl.sct = (getattr(mss, "MSS", None) or mss.mss)()
            mons = self.tl.sct.monitors[1:]
            self.tl.mon = next((m for m in mons if m["left"] == 0 and m["top"] == 0), mons[0])
        shot = self.tl.sct.grab(self.tl.mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        if img.width > width:
            img = img.resize((width, round(img.height * width / img.width)), Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        return buf.getvalue()

    async def send_frame(self, ws, width, quality):
        try:
            data = await self.loop.run_in_executor(self.exec, self.grab, width, quality)
            if not ws.closed:
                await ws.send_bytes(data)
                cur = control.cursor_pos()
                if cur:
                    await ws.send_str(json.dumps({"t": "cur", "x": round(cur[0], 5), "y": round(cur[1], 5)}))
        except Exception as e:
            if not self.grab_failed:
                print("Screen preview unavailable:", e)
                self.grab_failed = True

    # ---- images from the web / clipboard
    async def download_image(self, url):
        if url.startswith("data:image/"):
            data = base64.b64decode(url.split(",", 1)[1])
        else:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as s:
                async with s.get(url) as r:
                    if r.status != 200:
                        raise ValueError(f"HTTP {r.status}")
                    data = await r.content.read(25 * 1024 * 1024 + 1)
                    if len(data) > 25 * 1024 * 1024:
                        raise ValueError("image is too large")
        return await self.loop.run_in_executor(self.exec, encode_image_bytes, data)

    async def fetch_for_phone(self, ws, url):
        try:
            src, _w, _h = await self.download_image(url)
            await ws.send_str(json.dumps({"t": "cmd", "c": "img", "src": src}))
        except Exception as e:
            print("Couldn't load image:", e)
            await ws.send_str(json.dumps({"t": "toast", "msg": "Couldn't load that image. Try saving it to Photos and use Image."}))

    def add_image(self, src, iw, ih):
        """From the GUI thread: an image from the PC clipboard (Ctrl+Alt+V)."""
        if self.loop:
            self.loop.call_soon_threadsafe(self._add_image, src, iw, ih)

    def fetch_for_pc(self, url):
        async def run():
            try:
                src, iw, ih = await self.download_image(url)
                self._add_image(src, iw, ih)
            except Exception as e:
                print("Couldn't load image from clipboard link:", e)
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(run()))

    def teachers(self):
        return [w for w, m in self.clients.items() if m == "teacher"]

    def _add_image(self, src, iw, ih):
        if self.teachers():
            # the phone adds it (so it's selected, resizable and undoable)
            asyncio.ensure_future(self.broadcast({"t": "cmd", "c": "img", "src": src}))
            return
        w = 0.3
        h = w * self.aspect * ih / max(1, iw)
        if h > 0.6:
            w *= 0.6 / h
            h = 0.6
        item = {"id": uuid.uuid4().hex[:8], "k": "img", "src": src, "c": "#000",
                "x": (1 - w) / 2, "y": (1 - h) / 2, "w": w, "h": h}
        op = {"t": "add", "item": item, "done": True}
        self.apply(op)
        self.bridge.ops.emit(json.dumps(op))

    # ---- http / websocket
    async def font(self, request):
        f = FONTS.get(request.match_info["name"])
        if not f or not f[0]:
            raise web.HTTPNotFound()
        return web.FileResponse(f[0], headers={"Content-Type": "font/ttf", "Cache-Control": "max-age=86400"})

    async def ws_handler(self, request):
        if not self.token_ok(request):
            raise web.HTTPForbidden(text="Scan the QR code in SCraMic Share again.")
        self.loop = asyncio.get_running_loop()
        mode = "control" if request.query.get("m") == "control" else "teacher"
        ws = web.WebSocketResponse(max_msg_size=0, heartbeat=15, compress=False)
        await ws.prepare(request)
        sock = request.transport.get_extra_info("socket") if request.transport else None
        if sock is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
        was_teaching = bool(self.teachers())
        may_control = True                  # PC Control's view-only switch turns this off
        self.clients[ws] = mode
        if mode == "teacher" and not was_teaching:
            self.bridge.inkOn.emit(True)
        await ws.send_str(json.dumps({
            "t": "hello", "aspect": self.aspect, "page": self.page, "bg": self.bg,
            "pages": {n: list(v.values()) for n, v in self.pages.items()}}))
        try:
            async for m in ws:
                if m.type != WSMsgType.TEXT:
                    continue
                try:
                    d = json.loads(m.data)
                except ValueError:
                    continue
                t = d.get("t")
                if t == "f":
                    w = max(480, min(PREVIEW_MAX, int(d.get("w") or PREVIEW_WIDTH)))
                    q = max(30, min(90, int(d.get("q") or PREVIEW_QUALITY)))
                    asyncio.ensure_future(self.send_frame(ws, w, q))
                elif t == "ctl":
                    may_control = bool(d.get("on"))
                    if not may_control:
                        self.ctl.release_all()
                elif t in ("m", "wheel", "key", "char", "text"):
                    if may_control:
                        self.ctl.handle(d)
                elif t == "fetch":
                    url = str(d.get("url", ""))
                    if url.startswith(("http://", "https://", "data:image/")):
                        asyncio.ensure_future(self.fetch_for_phone(ws, url))
                elif mode == "teacher":
                    self.apply(d)
                    self.bridge.ops.emit(m.data)
        finally:
            self.clients.pop(ws, None)
            self.ctl.release_all()          # never leave a key or button stuck down
            if mode == "teacher" and not self.teachers():
                self.bridge.inkOn.emit(False)
        return ws

    async def broadcast(self, obj):
        text = json.dumps(obj)
        for ws in self.teachers():
            try:
                await ws.send_str(text)
            except Exception:
                pass

    # ---- PC shortcuts
    def command(self, name):
        if self.loop:
            self.loop.call_soon_threadsafe(self._command, name)

    def _command(self, name):
        if self.teachers():
            # the phone does the work, so it stays undoable and in sync
            asyncio.ensure_future(self.broadcast({"t": "cmd", "c": name}))


def start_hotkeys(emit):
    """Ctrl+Alt+<key> shortcuts (Windows). Returns the keys another app already took."""
    import ctypes
    from ctypes import wintypes
    failed = []
    ready = threading.Event()

    def run():
        user32 = ctypes.windll.user32
        MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, WM_HOTKEY = 0x0001, 0x0002, 0x4000, 0x0312
        for i, (key, _name, _label) in enumerate(HOTKEYS, start=1):
            if not user32.RegisterHotKey(None, i, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, ord(key)):
                failed.append(key)
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and 1 <= msg.wParam <= len(HOTKEYS):
                emit(HOTKEYS[msg.wParam - 1][1])

    threading.Thread(target=run, daemon=True, name="hotkeys").start()
    ready.wait(2)
    return failed


class Teacher:
    """Owns the ink overlay window and the PC shortcuts. Create on the GUI thread."""

    def __init__(self, token_ok):
        self.bridge = Bridge()
        self.overlay = Overlay()
        self.overlay.setWindowTitle("SCraMic Share ink layer")
        self.bridge.ops.connect(self.overlay.on_ops)
        self.bridge.inkOn.connect(self._ink_on)
        g = self.overlay.geometry()
        self.live = Live(self.bridge, g.width() / max(1, g.height()), token_ok)
        self.hidden = False
        self.bridge.hotkey.connect(self._hotkey)
        self.failed_hotkeys = start_hotkeys(self.bridge.hotkey.emit)

    def _ink_on(self, on):
        self.overlay.setVisible(on and not self.hidden)

    def _hotkey(self, name):
        if not self.live.teachers():
            return                      # shortcuts only act while Teacher mode is open
        if name == "hide":
            self.hidden = not self.hidden
            self.overlay.setVisible(not self.hidden)
        elif name == "paste":
            self._paste_from_pc()
        else:
            self.live.command(name)

    def _paste_from_pc(self):
        cb = QApplication.clipboard()
        img = cb.image()
        md = cb.mimeData()
        if img.isNull() and md is not None and md.hasUrls():
            for u in md.urls():
                if u.isLocalFile():
                    q = QImage(u.toLocalFile())
                    if not q.isNull():
                        img = q
                        break
        if not img.isNull():
            src, iw, ih = qimage_to_dataurl(img)
            self.live.add_image(src, iw, ih)
            return
        txt = (cb.text() or "").strip()
        if txt.startswith(("http://", "https://")):
            self.live.fetch_for_pc(txt)
