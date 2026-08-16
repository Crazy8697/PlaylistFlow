"""Render the About dialog."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QTimer

from main import QSS
from playlistflow.mainwindow import AboutDialog

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setFont(QFont("Segoe UI", 10))
app.setStyleSheet(QSS)

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
dlg = AboutDialog()
dlg.show()
QTimer.singleShot(600, lambda: (dlg.grab().save(str(out / "shot_about.png")),
                                print("saved", out / "shot_about.png"), app.quit()))
sys.exit(app.exec())
