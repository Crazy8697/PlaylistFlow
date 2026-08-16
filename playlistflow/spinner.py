"""A small busy indicator. Hand-painted arc, no animation assets."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget

TRACK = QColor("#2C313A")
ARC = QColor("#3FA8D9")


class Spinner(QWidget):
    def __init__(self, size: int = 16, parent=None):
        super().__init__(parent)
        self._size = size
        self._angle = 0
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def _tick(self):
        self._angle = (self._angle + 30) % 360
        self.update()

    def start(self):
        if not self._timer.isActive():
            self._timer.start()
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = 2.0
        box = QRectF(w, w, self._size - 2 * w, self._size - 2 * w)

        p.setPen(QPen(TRACK, w))
        p.drawEllipse(box)

        pen = QPen(ARC, w)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        # Qt angles are in sixteenths of a degree, counter-clockwise.
        p.drawArc(box, -self._angle * 16, -100 * 16)
        p.end()
