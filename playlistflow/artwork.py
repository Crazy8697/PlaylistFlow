"""The app artwork.

Was drawn in code; it is now two supplied illustrations:

    assets/icon_source.png   the icon — flat ground, one heavy curl, notes
    assets/about_source.png  the fuller scene, used behind the About dialog

Both are loaded once and cached. Scaling happens per requested size, because
Windows asks for everything from 16px to 256px and a smooth downscale of the
1024px original beats re-decoding the file each time.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPixmap

ICON_SRC = "icon_source.png"
ABOUT_SRC = "about_source.png"

_cache: dict[str, QImage] = {}
_scaled: dict[tuple, QPixmap] = {}


def asset_path(name: str) -> Path | None:
    """Find an asset from source or from a frozen build.

    PyInstaller 6 unpacks --add-data under _internal/ (sys._MEIPASS) rather
    than beside the exe, so that is checked first — same order main.py uses to
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


def icon_pixmap(size: int, rounded: bool = False) -> QPixmap:
    """The icon at `size`, square.

    Left square by default: the illustration is full-bleed and composed to the
    frame, so rounding it crops the ground colour rather than softening a
    silhouette.
    """
    key = ("icon", size, rounded)
    if key in _scaled:
        return _scaled[key]
    img = _image(ICON_SRC)
    if img.isNull():
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
    else:
        pm = QPixmap.fromImage(
            img.scaled(size, size, Qt.KeepAspectRatioByExpanding,
                       Qt.SmoothTransformation))
        if pm.width() != size or pm.height() != size:
            # Centre-crop anything the aspect expansion overshot.
            x = max(0, (pm.width() - size) // 2)
            y = max(0, (pm.height() - size) // 2)
            pm = pm.copy(x, y, size, size)
        if rounded:
            pm = _rounded(pm, 0.1875)
    _scaled[key] = pm
    return pm


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

    `sky` no longer means anything — the illustration carries its own — but the
    signature stays so makeicon.py and anything else keeps working.
    """
    return icon_pixmap(size, rounded=False)
