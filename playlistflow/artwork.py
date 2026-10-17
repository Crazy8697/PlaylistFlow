"""The app artwork.

    assets/icon.svg          the icon (Funnel A), the master
    assets/icon-small.svg    the same design for 16 and 24 px: thicker strokes, no
                             staff lines, because the master turns to mush that small
    assets/about_source.png  the fuller scene, used behind the About dialog

The icon is rendered from the SVG at each requested size (Windows asks for
everything from 16 to 256 px), so every size is drawn sharp rather than scaled.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPixmap

ICON_SVG = "icon.svg"
ICON_SMALL_SVG = "icon-small.svg"
SMALL_MAX = 24            # this size and below use icon-small.svg
ABOUT_SRC = "about_source.png"

_cache: dict[str, QImage] = {}
_scaled: dict[tuple, QPixmap] = {}


def asset_path(name: str) -> Path | None:
    """Find an asset from source or from a frozen build.

    PyInstaller 6 unpacks --add-data under _internal/ (sys._MEIPASS) rather
    than beside the exe, so that is checked first, same order main.py uses to
    find the window icon.
    """
    bases = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        bases.append(Path(meipass))
    here = Path(__file__).resolve().parent
    bases += [here.parent, here.parent / "_internal", here]
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).parent
        bases += [exe, exe / "_internal"]
    for base in bases:
        for rel in ("assets/" + name, name):
            p = base / rel
            if p.exists():
                return p
    return None


def _image(name: str) -> QImage:
    if name not in _cache:
        p = asset_path(name)
        _cache[name] = QImage(str(p)) if p else QImage()
    return _cache[name]


def _rounded(pm: QPixmap, radius_frac: float) -> QPixmap:
    """Clip to a rounded square. Only used where the platform expects it."""
    out = QPixmap(pm.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    path = QPainterPath()
    r = pm.width() * radius_frac
    path.addRoundedRect(QRectF(0, 0, pm.width(), pm.height()), r, r)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


def icon_image(size: int) -> QImage:
    """The icon rendered at exactly size x size, transparent outside its rounded tile."""
    from PySide6.QtSvg import QSvgRenderer
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = asset_path(ICON_SMALL_SVG if size <= SMALL_MAX else ICON_SVG) or asset_path(ICON_SVG)
    if p is None:
        return img
    r = QSvgRenderer(str(p))
    if r.isValid():
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        r.render(painter)
        painter.end()
    return img


def icon_pixmap(size: int, rounded: bool = False) -> QPixmap:
    """The icon at `size`, square. The SVG already has its rounded tile; `rounded`
    is kept for older callers and changes nothing."""
    key = ("icon", size)
    if key not in _scaled:
        _scaled[key] = QPixmap.fromImage(icon_image(size))
    return _scaled[key]


def about_pixmap(width: int, height: int) -> QPixmap:
    """The fuller scene, cropped to cover a `width` x `height` panel."""
    key = ("about", width, height)
    if key in _scaled:
        return _scaled[key]
    img = _image(ABOUT_SRC)
    if img.isNull():
        pm = QPixmap(width, height)
        pm.fill(Qt.transparent)
    else:
        scaled = img.scaled(width, height, Qt.KeepAspectRatioByExpanding,
                            Qt.SmoothTransformation)
        x = max(0, (scaled.width() - width) // 2)
        y = max(0, (scaled.height() - height) // 2)
        pm = QPixmap.fromImage(scaled.copy(x, y, width, height))
    _scaled[key] = pm
    return pm


def wave_pixmap(size: int, rounded: bool = True, sky: bool = True) -> QPixmap:
    """Kept for callers written against the drawn version.

    `sky` no longer means anything, the illustration carries its own, but the
    signature stays so makeicon.py and anything else keeps working.
    """
    return icon_pixmap(size, rounded=False)

# --------------------------------------------------------------------------
# Remote covers
# --------------------------------------------------------------------------

_remote: dict = {}


def remote_pixmap(url: str, size: int) -> QPixmap:
    """Fetch a cover from Spotify's CDN, square-cropped to `size`.

    Cached by (url, size): the player asks for the same art on every poll, and
    covers are immutable at a given URL. A failure caches as a null pixmap so a
    dead URL is not retried on a two-second timer.
    """
    key = (url, size)
    if key in _remote:
        return _remote[key]
    pm = QPixmap()
    if url:
        try:
            import requests
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                img = QImage()
                if img.loadFromData(r.content):
                    scaled = img.scaled(size, size, Qt.KeepAspectRatioByExpanding,
                                        Qt.SmoothTransformation)
                    x = max(0, (scaled.width() - size) // 2)
                    y = max(0, (scaled.height() - size) // 2)
                    pm = QPixmap.fromImage(scaled.copy(x, y, size, size))
        except Exception:
            pm = QPixmap()
    _remote[key] = pm
    return pm
