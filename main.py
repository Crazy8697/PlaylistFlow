"""Playlist Flow — harmonic and tempo sequencing for playlists.

Native Qt. No browser, no local server.
"""

from __future__ import annotations

import sys

from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QIcon

from playlistflow.mainwindow import MainWindow
from playlistflow.config import app_dir


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

QSS = """
QWidget {
    background: #101216;
    color: #E9E7E1;
    font-size: 14px;
}
QMainWindow, QDialog { background: #101216; }
QMenuBar, QStatusBar { background: #101216; color: #8C939D; }
QMenuBar::item:selected { background: #20242B; }
QMenu { background: #181B21; border: 1px solid #2C313A; }
QMenu::item:selected { background: #20242B; }

QGroupBox {
    background: #181B21;
    border: 1px solid #2C313A;
    border-radius: 3px;
    margin-top: 14px;
    padding: 10px 8px 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #8C939D;
    font-size: 11px;
    letter-spacing: 1px;
}

QPushButton {
    background: #181B21;
    border: 1px solid #2C313A;
    border-radius: 3px;
    color: #8C939D;
    padding: 7px 13px;
    font-size: 12px;
}
QPushButton:hover { border-color: #3D444F; color: #E9E7E1; }
QPushButton:pressed { background: #20242B; }
QPushButton:checked { background: #20242B; border-color: #E9E7E1; color: #E9E7E1; }

QLineEdit, QPlainTextEdit {
    background: #101216;
    border: 1px solid #2C313A;
    border-radius: 3px;
    color: #E9E7E1;
    padding: 6px 9px;
    selection-background-color: #3D444F;
}
QLineEdit:focus, QPlainTextEdit:focus { border-color: #3D444F; }
QPlainTextEdit { font-family: Consolas, 'JetBrains Mono', monospace; font-size: 11px; }

QListWidget {
    background: #181B21;
    border: 1px solid #2C313A;
    border-radius: 3px;
    outline: none;
}
QListWidget::item { padding: 6px 8px; }
QListWidget::item:selected { background: #20242B; color: #E9E7E1; }

QTableWidget {
    background: #181B21;
    border: 1px solid #2C313A;
    border-radius: 3px;
    gridline-color: transparent;
    outline: none;
    selection-background-color: #20242B;
    selection-color: #E9E7E1;
}
QTableWidget::item { padding-left: 6px; border-bottom: 1px solid #2C313A; }
QHeaderView::section {
    background: #101216;
    color: #5C636D;
    border: none;
    border-bottom: 1px solid #2C313A;
    padding: 6px;
    font-size: 11px;
    letter-spacing: 1px;
}
QScrollBar:vertical { background: #101216; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #2C313A; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #3D444F; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }

QLabel#stat { color: #5C636D; font-family: Consolas, monospace; font-size: 12px; }
QLabel#busy { color: #8C939D; font-size: 12px; }
QLabel#now { color: #E9E7E1; font-size: 13px; }
QLabel#clock { color: #5C636D; font-family: Consolas, monospace; font-size: 11px; }
QLabel#plname { color: #E9E7E1; font-size: 15px; font-weight: 600; }
/* Inline buttons that share a text line. The default 7px padding makes a
   ~32px-tall button, which gets cropped when squeezed onto a label row. */
QPushButton#inline { padding: 2px 10px; font-size: 11px; }
/* Covers carry their own edge; a border keeps a dark album art from bleeding
   into the background, and holds the slot's shape before one has loaded. */
QLabel#cover, QLabel#art { background: #181B21; border: 1px solid #2C313A; border-radius: 3px; }
QSlider::groove:horizontal { height: 4px; background: #2C313A; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #3FBFA8; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #E9E7E1; width: 10px; margin: -4px 0; border-radius: 5px;
}
QSpinBox {
    background: #101216; border: 1px solid #2C313A; border-radius: 3px;
    color: #E9E7E1; padding: 4px 6px;
}
QToolTip { background: #20242B; color: #E9E7E1; border: 1px solid #3D444F; padding: 4px; }
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Playlist Flow")
    app.setOrganizationName("darkrelay")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(QSS)
    app.setWindowIcon(app_icon())

    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
