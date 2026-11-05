"""The phone's screen turned by hand: a live copy of the AirPlay receiver's window, rotated.

The receiver can't turn its own picture while it is running, and restarting it would
make the iPhone connect again. At 0 degrees this view closes and the plain window returns.
"""
from PySide6.QtCore import QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QWindow
from PySide6.QtMultimedia import QCapturableWindow, QMediaCaptureSession, QWindowCapture
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView

from receivers import STREAM_ICON, STREAM_TITLE


class RotatedView(QGraphicsView):
    def __init__(self, on_closed):
        super().__init__()
        self.on_closed = on_closed      # the user closed it: back to no turn
        self.hwnd = None
        self.deg = 0
        self.setWindowTitle(STREAM_TITLE)
        self.setWindowIcon(QIcon(str(STREAM_ICON)))
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)   # the app's life follows its main window only
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QColor("#000000"))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsVideoItem()
        self.scene().addItem(self.item)
        self.item.nativeSizeChanged.connect(self._picture_changed)
        self.capture = QWindowCapture(self)
        self.capture.setMaximumFrameRate(60)   # without this, Qt misreads the monitor and drops to 7.5 fps
        self.session = QMediaCaptureSession(self)
        self.session.setWindowCapture(self.capture)
        self.session.setVideoOutput(self.item)

    def apply(self, value):
        """value: (hwnd, degrees) to show that window turned, or None to close."""
        if not value:
            self.hwnd = None
            self.capture.stop()
            self.hide()
            return
        hwnd, self.deg = value
        if hwnd != self.hwnd:
            self.hwnd = hwnd
            self.capture.stop()
            self.capture.setWindow(QCapturableWindow(QWindow.fromWinId(hwnd)))
            self.capture.start()
        self._picture_changed()
        self.show()
        self.raise_()
        self.activateWindow()

    def _picture_changed(self):
        size = self.item.nativeSize()
        if size.isEmpty():
            size = QSizeF(9, 16)
        self.item.setSize(size)
        self.item.setTransformOriginPoint(size.width() / 2, size.height() / 2)
        self.item.setRotation(self.deg)
        sideways = self.deg % 180 != 0
        w, h = (size.height(), size.width()) if sideways else (size.width(), size.height())
        self.scene().setSceneRect(QRectF(size.width() / 2 - w / 2, size.height() / 2 - h / 2, w, h))
        if not self.isFullScreen() and not self.isMaximized():
            area = (self.screen() or self.window().screen()).availableGeometry()
            scale = min(area.width() * 0.8 / w, area.height() * 0.8 / h)
            new_w, new_h = round(w * scale), round(h * scale)
            center = self.geometry().center() if self.isVisible() else area.center()
            self.setGeometry(center.x() - new_w // 2, center.y() - new_h // 2, new_w, new_h)
        self._fit()

    def _fit(self):
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def closeEvent(self, event):
        super().closeEvent(event)
        self.on_closed()
