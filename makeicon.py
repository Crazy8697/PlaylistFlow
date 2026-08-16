"""Generate the app icon: a wave rolling over, with notes riding the crest.

Drawn with QPainter at several sizes and packed into a single .ico, so Windows
picks the right one for the taskbar, the title bar and Explorer.
"""

import math
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush, QPixmap, QPainterPath,
                           QLinearGradient, QFont)
from PySide6.QtCore import Qt, QRectF, QPointF

# Wheel colours from the app, so the icon belongs to the same family.
DEEP = QColor("#101216")
WAVE_HI = QColor("#3FA8D9")
WAVE_LO = QColor("#4A7FD9")
CREST = QColor("#9B54D9")
NOTE = QColor("#E9E7E1")


def draw(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = size / 64.0   # design at 64px, scale from there

    # rounded dark tile
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(DEEP))
    p.drawRoundedRect(QRectF(0, 0, size, size), 12 * s, 12 * s)

    # the wave body: a curl that rises left to right and breaks over
    grad = QLinearGradient(0, size, size, 0)
    grad.setColorAt(0.0, WAVE_LO)
    grad.setColorAt(0.7, WAVE_HI)
    grad.setColorAt(1.0, CREST)

    path = QPainterPath()
    path.moveTo(2 * s, 46 * s)
    path.cubicTo(16 * s, 46 * s, 18 * s, 22 * s, 34 * s, 22 * s)
    path.cubicTo(46 * s, 22 * s, 48 * s, 32 * s, 44 * s, 38 * s)
    path.cubicTo(41 * s, 42 * s, 35 * s, 42 * s, 33 * s, 38 * s)
    path.cubicTo(38 * s, 40 * s, 41 * s, 34 * s, 38 * s, 31 * s)
    path.cubicTo(33 * s, 27 * s, 27 * s, 34 * s, 24 * s, 41 * s)
    path.cubicTo(21 * s, 47 * s, 14 * s, 52 * s, 2 * s, 52 * s)
    path.closeSubpath()
    p.setBrush(QBrush(grad))
    p.drawPath(path)

    # foam line along the trough
    pen = QPen(QColor(255, 255, 255, 70), max(1.0, 1.6 * s))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    foam = QPainterPath()
    foam.moveTo(3 * s, 53 * s)
    foam.cubicTo(16 * s, 55 * s, 26 * s, 49 * s, 32 * s, 41 * s)
    p.drawPath(foam)

    # two notes riding the crest
    def note(cx, cy, stem_h, r):
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(NOTE))
        p.drawEllipse(QPointF(cx, cy), r * 1.15, r)
        pen2 = QPen(NOTE, max(1.0, r * 0.52))
        pen2.setCapStyle(Qt.RoundCap)
        p.setPen(pen2)
        p.drawLine(QPointF(cx + r * 1.05, cy),
                   QPointF(cx + r * 1.05, cy - stem_h))
        return QPointF(cx + r * 1.05, cy - stem_h)

    # Sit them low and close, tracking the rise of the crest, so they read as
    # riding the wave rather than hovering over it.
    a = note(34 * s, 17 * s, 9 * s, 2.9 * s)
    b = note(46 * s, 13 * s, 9 * s, 2.9 * s)
    pen3 = QPen(NOTE, max(1.0, 2.0 * s))
    pen3.setCapStyle(Qt.RoundCap)
    p.setPen(pen3)
    p.drawLine(a, b)

    p.end()
    return pm


def main():
    app = QApplication(sys.argv)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    pixmaps = [draw(s) for s in sizes]

    # Biggest as a PNG for anything that wants one
    pixmaps[-1].save(str(out / "icon.png"))

    # Pack every size into one .ico
    from PySide6.QtGui import QImage
    images = [pm.toImage() for pm in pixmaps]
    ico = out / "icon.ico"
    writer_ok = pixmaps[-1].save(str(ico))
    print("png:", out / "icon.png")
    print("ico:", ico, "ok" if writer_ok else "FAILED")
    for pm, s in zip(pixmaps, sizes):
        pm.save(str(out / f"icon_{s}.png"))
    print("sizes:", sizes)


if __name__ == "__main__":
    main()
