"""Spotify's own logo files, white, for attributing Spotify content.

The official assets from developer.spotify.com/documentation/design ship in
assets/spotify (see SOURCE.txt there), unmodified; this only scales them down.
The UI is dark but not pure black, so the guidelines call for the white
monochrome version, never green. Minimum sizes come from the same guidelines:
the full logo never under 70 px wide, the icon never under 21 px. They mark
where Spotify content is shown (the playlist list, the playlist header, the
player, About), never an action button.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel

FULL_LOGO = "Spotify_Full_Logo_RGB_White.png"
ICON = "Spotify_Primary_Logo_RGB_White.png"
FULL_MIN_W = 70
ICON_MIN = 21
SPOTIFY_URL = "https://open.spotify.com"


def _asset(name: str) -> Path | None:
    bases = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        bases.append(Path(meipass))
    bases.append(Path(__file__).resolve().parent.parent)
    for b in bases:
        p = b / "assets" / "spotify" / name
        if p.exists():
            return p
    return None


_cache: dict[tuple, QPixmap] = {}


def _scaled(name: str, w: int, h: int, dpr: float) -> QPixmap:
    key = (name, w, h, dpr)
    if key not in _cache:
        p = _asset(name)
        src = QPixmap(str(p)) if p else QPixmap()
        if src.isNull():
            _cache[key] = QPixmap()
        else:
            pm = src.scaled(int(w * dpr), int(h * dpr), Qt.KeepAspectRatio,
                            Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            _cache[key] = pm
    return _cache[key]


def full_logo_pixmap(width: int = 84, dpr: float = 2.0) -> QPixmap:
    """The full logo (icon + wordmark), at least 70 px wide."""
    width = max(FULL_MIN_W, width)
    return _scaled(FULL_LOGO, width, width, dpr)


def icon_pixmap(size: int = 22, dpr: float = 2.0) -> QPixmap:
    """The icon alone, at least 21 px."""
    size = max(ICON_MIN, size)
    return _scaled(ICON, size, size, dpr)


def logo_label(full: bool = True, size: int = 84, tip: str = "Content from Spotify",
               zone: bool = True) -> QLabel:
    """A label holding the logo. zone=True pads it with the guidelines' exclusion
    zone, half the icon's height clear on every side."""
    lab = QLabel()
    lab.setObjectName("spotify_logo")
    pm = full_logo_pixmap(size) if full else icon_pixmap(size)
    lab.setPixmap(pm)
    lab.setToolTip(tip)
    if zone and not pm.isNull():
        m = max(1, round(pm.height() / pm.devicePixelRatio() / 2))
        lab.setContentsMargins(m, m, m, m)
    return lab
