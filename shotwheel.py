"""Render the Camelot wheel dialog."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QTimer

from main import QSS
from playlistflow.wheel import KeyWheelDialog

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setFont(QFont("Segoe UI", 10))
app.setStyleSheet(QSS)

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
dlg = KeyWheelDialog()
dlg.resize(430, 580)
dlg.follow("12A", "Jared Benjamin — LET ME IN")
dlg.show()
QTimer.singleShot(700, lambda: (dlg.grab().save(str(out / "shot_wheel.png")),
                                print("saved", out / "shot_wheel.png"), app.quit()))
sys.exit(app.exec())
