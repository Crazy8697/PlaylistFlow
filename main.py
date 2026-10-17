"""Playlist Flow, harmonic and tempo sequencing for playlists.

Native Qt. No browser, no local server.
"""

from __future__ import annotations

import sys

from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QIcon

from playlistflow.mainwindow import MainWindow
from playlistflow.config import app_dir
from playlistflow import theme


def app_icon() -> QIcon:
    """PyInstaller 6 unpacks --add-data under _internal/ (sys._MEIPASS), not
    next to the exe, so check there first."""
    bases = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        bases.append(Path(meipass))
    bases += [app_dir(), app_dir() / "_internal", Path(__file__).resolve().parent]
    for base in bases:
        for name in ("assets/icon.ico", "icon.ico", "assets/icon.png"):
            p = base / name
            if p.exists():
                return QIcon(str(p))
    return QIcon()

# The stylesheet lives in playlistflow/theme.py; this name stays for older harnesses.
QSS = theme.QSS


def setup_app(app: QApplication) -> None:
    """Names, the DarkRelay theme and the window icon. Shared with the test harnesses."""
    app.setApplicationName("Playlist Flow")
    app.setOrganizationName("darkrelay")
    theme.apply(app)
    app.setWindowIcon(app_icon())


def main() -> int:
    app = QApplication(sys.argv)
    setup_app(app)

    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
