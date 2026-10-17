"""Spotify's own logo files, white, for attributing Spotify content.

The official assets from developer.spotify.com/documentation/design ship in
assets/spotify (see SOURCE.txt there), unmodified; this only scales them down.
The UI is dark but not pure black, so the guidelines call for the white
monochrome version, never green. Minimum sizes come from the same guidelines:
the full logo never under 70 px wide, the icon never under 21 px. They mark
where Spotify content is shown (the playlist list, the playlist header, the
player, About), never an action button. Partner integrations use the full logo
(icon and wordmark); the icon alone is only for an app icon, so every mark here
is the full logo.

Spotify metadata and artwork must also link back to Spotify, to the Spotify app
when it is installed: spotify_link() is that link, worded the way the
guidelines ask ("OPEN SPOTIFY", or "GET SPOTIFY FREE" when the app isn't there).

Guidelines read 2026-10-17 at https://developer.spotify.com/documentation/design
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy

FULL_LOGO = "Spotify_Full_Logo_RGB_White.png"
ICON = "Spotify_Primary_Logo_RGB_White.png"
FULL_MIN_W = 70
ICON_MIN = 21
SPOTIFY_URL = "https://open.spotify.com"
GET_SPOTIFY_URL = "https://www.spotify.com/download/"


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
        m = exclusion_zone(pm)
        lab.setContentsMargins(m, m, m, m)
    # never squeezed into the clear space by a crowded row: the label is exactly the
    # logo plus its clear space, and layouts (and so the window's minimum size) have
    # to make room for that
    lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    if not pm.isNull():
        import math
        m = lab.contentsMargins()
        lab.setFixedSize(math.ceil(pm.width() / pm.devicePixelRatio()) + m.left() + m.right(),
                         math.ceil(pm.height() / pm.devicePixelRatio()) + m.top() + m.bottom())
    return lab


def exclusion_zone(pm: QPixmap) -> int:
    """The guidelines' clear space: half the height of the icon. In the full logo
    the icon is the full height of the lockup, so half the logo's height."""
    import math
    return max(1, math.ceil(pm.height() / pm.devicePixelRatio() / 2))


# ---------------- linking back to Spotify ----------------

def spotify_installed() -> bool:
    """Is the Spotify app registered for spotify: links on this PC (per user or for
    everyone)? Read only, from the Windows registry's URL handlers."""
    if sys.platform != "win32":
        return False
    import winreg
    for root, path in ((winreg.HKEY_CURRENT_USER, r"Software\Classes\spotify"),
                       (winreg.HKEY_LOCAL_MACHINE, r"Software\Classes\spotify")):
        try:
            with winreg.OpenKey(root, path) as k:
                winreg.QueryValueEx(k, "URL Protocol")
                return True
        except OSError:
            continue
    return False


def link_text(installed: bool | None = None) -> str:
    """The guidelines' wording: OPEN SPOTIFY when the app is installed, else GET SPOTIFY FREE."""
    installed = spotify_installed() if installed is None else installed
    return "OPEN SPOTIFY" if installed else "GET SPOTIFY FREE"


def spotify_target(kind: str, sid: str, installed: bool | None = None) -> str:
    """Where a link back goes: the item in the Spotify app (spotify:kind:id) when it is
    installed, else the page that offers the app for free."""
    installed = spotify_installed() if installed is None else installed
    if installed and kind and sid:
        return f"spotify:{kind}:{sid}"
    return GET_SPOTIFY_URL


def open_in_spotify(kind: str, sid: str, opener=None) -> str:
    """Open a playlist or track in Spotify; returns the address used."""
    url = spotify_target(kind, sid)
    (opener or (lambda u: QDesktopServices.openUrl(QUrl(u))))(url)
    return url


def spotify_link(tip: str = "") -> QLabel:
    """A small text link back to Spotify. Its target is set with set_link_target();
    it stays hidden until there is something to link to."""
    lab = QLabel()
    lab.setObjectName("spotify_link")
    lab.setTextFormat(Qt.RichText)
    lab.setTextInteractionFlags(Qt.TextBrowserInteraction)
    lab.setOpenExternalLinks(False)
    lab.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
    lab.setToolTip(tip)
    lab.setVisible(False)
    return lab


def set_link_target(lab: QLabel, kind: str, sid: str, installed: bool | None = None) -> None:
    if not sid:
        lab.setVisible(False)
        lab.setProperty("target", "")
        return
    installed = spotify_installed() if installed is None else installed
    target = spotify_target(kind, sid, installed)
    lab.setProperty("target", target)
    text = link_text(installed)
    lab.setText(f"<a href='{target}' style='color:#ffffff;text-decoration:none;"
                f"font-weight:700;font-size:11px;letter-spacing:1px'>{text}</a>")
    # A rich-text label reports a minimum of a letter or so, which let a narrow window
    # crush the link (and crowd the logo's clear space): its real width is the minimum.
    from PySide6.QtGui import QFont, QFontMetrics
    f = QFont(lab.font())
    f.setPixelSize(11)
    f.setBold(True)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 1)
    lab.setMinimumWidth(QFontMetrics(f).horizontalAdvance(text) + 8)
    lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
    lab.setVisible(True)
