"""The wave, drawn in code.

Lives in the package rather than in the icon script because the app draws it
too — faintly, behind the About dialog. One definition, so the icon and the
artwork can never drift apart.

It has to stay legible at 16px, which rules out fine detail: warm sky, deep
water, one heavy curl, foam, spray.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush, QPixmap,
                           QPainterPath, QLinearGradient)

SKY_HI = QColor("#F0A03A")     # low sun
SKY_LO = QColor("#D8562F")     # burnt orange near the horizon
DEEP = QColor("#12325E")       # trough
MID = QColor("#1E63A8")        # wave body
LIGHT = QColor("#3FA8D9")      # lit face
FOAM = QColor("#EAF4FB")


def paint_wave(p: QPainter, size: float, rounded: bool = True,
               sky: bool = True) -> None:
    """Draw the wave into `p`, filling a `size` square at the origin."""
    p.setRenderHint(QPainter.Antialiasing, True)
    s = size / 64.0

    def P(x, y):
        return QPointF(x * s, y * s)

    if rounded:
        tile = QPainterPath()
        tile.addRoundedRect(QRectF(0, 0, size, size), 12 * s, 12 * s)
        p.setClipPath(tile)

    if sky:
        grad = QLinearGradient(0, 0, 0, size)
        grad.setColorAt(0.0, SKY_HI)
        grad.setColorAt(1.0, SKY_LO)
        p.fillRect(QRectF(0, 0, size, size), QBrush(grad))

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
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(DEEP))
    p.drawPath(water)

    # The curl is a very thick stroked spiral rather than an outlined shape.
    # Filled outlines came out thin enough to read as a hook; a heavy
    # round-capped stroke gives the water mass, and survives 16px.
    spiral = QPainterPath()
    spiral.moveTo(P(4, 50))
    spiral.cubicTo(P(12, 44), P(16, 30), P(26, 20))     # flank rising
    spiral.cubicTo(P(36, 10), P(50, 12), P(51, 24))     # over the top
    spiral.cubicTo(P(52, 33), P(43, 37), P(38, 31))     # curling back down
    spiral.cubicTo(P(35, 27), P(38, 22), P(42, 24))     # into the tube

    body = QLinearGradient(0, size, size * 0.85, 0)
    body.setColorAt(0.0, DEEP)
    body.setColorAt(0.5, MID)
    body.setColorAt(1.0, LIGHT)
    pen = QPen(QBrush(body), 13 * s)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(spiral)

    # Foam riding the outer edge of the same curl.
    foam = QPainterPath()
    foam.moveTo(P(6, 44))
    foam.cubicTo(P(14, 38), P(18, 25), P(27, 15))
    foam.cubicTo(P(37, 5), P(56, 9), P(57, 24))
    foam.cubicTo(P(58, 34), P(50, 41), P(42, 39))
    pen = QPen(FOAM, 4.2 * s)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawPath(foam)

    # Spray off the lip.
    p.setPen(Qt.NoPen)
    p.setBrush(FOAM)
    for x, y, r in ((36, 41, 2.6), (30, 45, 1.7), (57, 33, 1.9), (24, 47, 1.2)):
        p.drawEllipse(P(x, y), r * s, r * s)


def wave_pixmap(size: int, rounded: bool = True, sky: bool = True) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    paint_wave(p, size, rounded=rounded, sky=sky)
    p.end()
    return pm
