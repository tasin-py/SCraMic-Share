"""SCraMic Share - Windows app entry point.

Opens the app window (a Chromium view, so text renders smoothly at any scaling)
and starts the local server the phone connects to.
"""
import ctypes
import os
import sys

if "--rename-mic" in sys.argv:       # the installed exe, restarted with admin rights just for this
    import vdevices
    vdevices.rename_mic_command()
    sys.exit(0)

CHECKING = "--check" in sys.argv     # the release build's test of the finished exe
if CHECKING:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Chromium flags must be set before Qt WebEngine loads.
#  - show real LAN addresses in WebRTC (instead of .local names) so the phone can reach the PC
#  - let incoming phone audio/video play without a click
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--disable-features=WebRtcHideLocalIpsWithMdns "
    "--autoplay-policy=no-user-gesture-required"
    + (" --no-sandbox --disable-gpu" if CHECKING else "")
)

from PySide6.QtCore import QObject, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from rotateview import RotatedView
from server import ROOT, Server, token_ok
from teacher import Teacher

APP_NAME = "SCraMic Share"
BG = "#191919"


def dark_title_bar(hwnd):
    """Windows 11: dark title bar in the app's background color (ignored on Windows 10)."""
    try:
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))      # dark mode
        color = ctypes.c_int(0x00191919)                                              # COLORREF 0x00BBGGRR
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))  # caption color
    except Exception:
        pass


class WinBridge(QObject):
    act = Signal(str)   # "min" / "restore", sent from the server thread
    view = Signal(object)   # the turned phone screen: (hwnd, degrees) or None


class AppView(QWebEngineView):
    """The app's page. window.open() from it makes the pop-out video window."""
    def createWindow(self, kind):
        pop = QWebEngineView()
        pop.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        pop.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        pop.setWindowTitle("ScramicShare Video")
        pop.setWindowIcon(QIcon(str(ROOT / "web" / "assets" / "logo.svg")))
        pop.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        pop.page().setBackgroundColor(QColor("#000000"))
        pop.page().settings().setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        pop.page().windowCloseRequested.connect(pop.close)
        pop.page().geometryChangeRequested.connect(lambda r: pop.resize(r.size()))   # the size the page asked for
        pop.resize(960, 540)
        pop.show()
        dark_title_bar(int(pop.winId()))
        return pop


class Window(QMainWindow):
    def __init__(self, url):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(ROOT / "web" / "assets" / "logo.svg")))
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(f"background:{BG};")

        view = AppView(self)
        page = view.page()
        page.setBackgroundColor(QColor(BG))
        s = page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        # The app's own page (localhost only) may list audio devices, so it can send the
        # phone's sound into "ScramicShare Mic Feed". Nothing else gets permissions.
        def local(url):
            return url.host() in ("127.0.0.1", "localhost")
        if hasattr(page, "permissionRequested"):                      # Qt 6.8+
            page.permissionRequested.connect(lambda perm: perm.grant() if local(perm.origin()) else perm.deny())
        if hasattr(page, "featurePermissionRequested"):               # older Qt
            def on_feature(origin, feature):
                ok = local(origin)
                page.setFeaturePermission(origin, feature,
                                          page.PermissionPolicy.PermissionGrantedByUser if ok
                                          else page.PermissionPolicy.PermissionDeniedByUser)
            try:
                page.featurePermissionRequested.connect(on_feature)
            except Exception:
                pass
        view.load(QUrl(url))
        self.setCentralWidget(view)
        self.view = view
        dark_title_bar(int(self.winId()))

    def window_action(self, a):
        """Teacher / PC Control minimize the app so the phone sees the desktop. An update closes it."""
        if a == "quit":
            QApplication.quit()
        elif a == "min":
            self.showMinimized()
        elif a == "restore" and self.isMinimized():
            self.showNormal()
            self.raise_()
            self.activateWindow()


def self_check(report):
    """--check FILE: does everything load inside the exe? Writes "OK" to FILE, or what went wrong."""
    import importlib
    import traceback

    from PySide6.QtCore import QTimer
    from PySide6.QtMultimedia import QWindowCapture

    def finish(text, code):
        with open(report, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        os._exit(code)

    try:
        for name in ("control", "receivers", "rotateview", "teacher", "tools", "unitycam", "updates", "vdevices", "wired",
                     "cryptography", "mss", "numpy", "PIL.Image", "qrcode.image.svg"):
            importlib.import_module(name)
        for path in ("web/pc/index.html", "web/pc/pc.js", "web/phone/index.html", "web/phone/teacher.html",
                     "web/phone/control.html", "web/assets/logo.svg", "web/assets/stream.ico", "web/assets/bangla-qr.png"):
            if not (ROOT / path).exists():
                raise FileNotFoundError(path)
        QWindowCapture().setMaximumFrameRate(60)      # rotated phone screen
        from unitycam import UnityCam
        UnityCam().close()                            # ScramicShare Cam
        app = QApplication(sys.argv)
        view = QWebEngineView()                       # the app's whole window is one of these
        view.loadFinished.connect(lambda ok: finish("OK" if ok else "the web view failed to load a page", 0 if ok else 1))
        view.setHtml("<title>check</title>ok")
        QTimer.singleShot(60000, lambda: finish("the web view timed out", 1))
        return app.exec()
    except Exception:
        finish(traceback.format_exc(), 1)


def main():
    if CHECKING:
        return self_check(sys.argv[sys.argv.index("--check") + 1])
    try:   # own taskbar icon/group instead of python.exe's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Tasin.SCraMicShare")
    except Exception:
        pass

    # exact (not rounded) display scaling, so ink lands exactly where it was drawn
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    teacher = Teacher(token_ok)            # ink layer over the screen (hidden until Teacher mode)
    server = Server(live=teacher.live)
    try:
        server.start()
    except OSError as e:
        QMessageBox.critical(None, APP_NAME,
                             f"SCraMic Share couldn't start its connection server.\n\n{e}\n\n"
                             "Is SCraMic Share already open?")
        return 1

    win = Window(server.pc_url)
    wb = WinBridge()
    wb.act.connect(win.window_action)
    server.hub.on_win = wb.act.emit
    rotated = RotatedView(lambda: server.hub.rx and server.hub.rx.handle({"a": "rotate-reset"}))
    wb.view.connect(rotated.apply)
    server.hub.on_view = wb.view.emit
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
