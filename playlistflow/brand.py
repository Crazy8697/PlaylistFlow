"""The Spotify mark, drawn rather than shipped.

Bundling the official asset would mean redistributing their artwork, so it is
painted at the size needed: green disc, three arcs cut through the upper half.
Used only to label the buttons that talk to Spotify.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QIcon, QPainter, QPixmap, QColor, QPen

SPOTIFY_GREEN = QColor("#1DB954")


def spotify_pixmap(size: int = 16, arc_colour: QColor | None = None) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)

    s = size / 16.0
    p.setPen(Qt.NoPen)
    p.setBrush(SPOTIFY_GREEN)
    p.drawEllipse(QRectF(0, 0, size, size))

    # Three arcs bowing upward, each shorter and thinner going down.
    arc = arc_colour or QColor("#101216")
    specs = (
        # (x, y, w, h, pen width, span in degrees)
        (2.3 * s, 3.5 * s, 11.4 * s, 7.4 * s, 1.75 * s, 152),
        (3.5 * s, 6.1 * s, 9.0 * s, 6.0 * s, 1.50 * s, 146),
        (4.7 * s, 8.4 * s, 6.6 * s, 4.6 * s, 1.25 * s, 140),
    )
    for x, y, w, h, pw, span in specs:
        pen = QPen(arc, pw)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        # Qt angles are sixteenths of a degree, counter-clockwise from 3 o'clock.
        # Centring the span on 90° puts the arc across the top of the ellipse.
        start = (180 - span) / 2
        p.drawArc(QRectF(x, y, w, h), int(start * 16), int(span * 16))
    p.end()
    return pm


_cache: dict[int, QIcon] = {}


def spotify_icon(size: int = 16) -> QIcon:
    if size not in _cache:
        ic = QIcon()
        for s in (size, size * 2):
            ic.addPixmap(spotify_pixmap(s))
        _cache[size] = ic
    return _cache[size]


def icon_size(size: int = 16) -> QSize:
    return QSize(size, size)
