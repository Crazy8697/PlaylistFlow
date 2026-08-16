"""Generate the app icon: a breaking wave against a sunset.

Drawn at 64x64 and scaled, so it has to stay legible at 16px — which rules out
fine detail. The shapes are deliberately few and bold: warm sky, deep water,
one big curl, a white crest, three spray dots.
"""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush, QPixmap, QPainterPath,
                           QLinearGradient)
from PySide6.QtCore import Qt, QRectF, QPointF

SKY_HI = QColor("#F0A03A")     # low sun
SKY_LO = QColor("#D8562F")     # burnt orange near the horizon
DEEP = QColor("#12325E")       # trough
MID = QColor("#1E63A8")        # wave body
LIGHT = QColor("#3FA8D9")      # lit face
FOAM = QColor("#EAF4FB")


def draw(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = size / 64.0

    def P(x, y):
        return QPointF(x * s, y * s)

    # Rounded tile, clipped so every shape below stops at the corners.
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(0, 0, size, size), 12 * s, 12 * s)
    p.setClipPath(tile)

    # Sky
    sky = QLinearGradient(0, 0, 0, size)
    sky.setColorAt(0.0, SKY_HI)
    sky.setColorAt(1.0, SKY_LO)
    p.fillRect(QRectF(0, 0, size, size), QBrush(sky))

    # Sun, low and to the right, mostly hidden behind the wave.
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 226, 160, 210))
    p.drawEllipse(P(46, 26), 9 * s, 9 * s)

    # Deep water across the bottom.
    water = QPainterPath()
    water.moveTo(P(0, 44))
    water.cubicTo(P(12, 42), P(20, 50), P(32, 50))
    water.cubicTo(P(44, 50), P(54, 44), P(64, 46))
    water.lineTo(P(64, 64))
    water.lineTo(P(0, 64))
    water.closeSubpath()
    p.setBrush(QBrush(DEEP))
    p.drawPath(water)

    # The curl is a very thick stroked spiral rather than an outlined shape.
    # Filled outlines kept coming out thin enough to read as a hook; a heavy
    # round-capped stroke gives the water actual mass, and survives being
    # scaled down to 16px.
    spiral = QPainterPath()
    spiral.moveTo(P(4, 50))
    spiral.cubicTo(P(12, 44), P(16, 30), P(26, 20))     # flank rising
    spiral.cubicTo(P(36, 10), P(50, 12), P(51, 24))     # over the top
    spiral.cubicTo(P(52, 33), P(43, 37), P(38, 31))     # curling back down
    spiral.cubicTo(P(35, 27), P(38, 22), P(42, 24))     # into the tube

    grad = QLinearGradient(0, size, size * 0.85, 0)
    grad.setColorAt(0.0, DEEP)
    grad.setColorAt(0.5, MID)
    grad.setColorAt(1.0, LIGHT)
    pen = QPen(QBrush(grad), 13 * s)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(spiral)

    # Foam riding the outer edge of the same curl, drawn thinner and offset up.
    foam = QPainterPath()
    foam.moveTo(P(6, 44))
    foam.cubicTo(P(14, 38), P(18, 25), P(27, 15))
    foam.cubicTo(P(37, 5), P(56, 9), P(57, 24))
    foam.cubicTo(P(58, 34), P(50, 41), P(42, 39))
    pen = QPen(FOAM, 4.2 * s)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawPath(foam)

    # Spray thrown off the lip.
    p.setPen(Qt.NoPen)
    p.setBrush(FOAM)
    for x, y, r in ((36, 41, 2.6), (30, 45, 1.7), (57, 33, 1.9), (24, 47, 1.2)):
        p.drawEllipse(P(x, y), r * s, r * s)

    p.end()
    return pm


def main():
    app = QApplication(sys.argv)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    out.mkdir(parents=True, exist_ok=True)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    for s in sizes:
        draw(s).save(str(out / f"icon_{s}.png"))
    draw(256).save(str(out / "icon.png"))
    draw(256).save(str(out / "icon.ico"))
    print("sizes:", sizes)
    print("wrote:", out / "icon.ico")


if __name__ == "__main__":
    main()
