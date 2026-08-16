"""Render the setup dialog for a look."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QTimer

from main import QSS
from playlistflow.settings import SettingsDialog
from playlistflow.config import Prefs

app = QApplication(sys.argv)
app.setOrganizationName("darkrelay")
app.setApplicationName("PlaylistFlow")
app.setStyle("Fusion")
app.setFont(QFont("Segoe UI", 10))
app.setStyleSheet(QSS)

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
first = "--first" in sys.argv

dlg = SettingsDialog(first_run=first, prefs=Prefs())
if first:
    # Setup should look like a fresh machine, not this one.
    for f in dlg.fields.values():
        f.set_value("")
dlg.show()

name = "shot_setup.png" if first else "shot_settings.png"
QTimer.singleShot(700, lambda: (dlg.grab().save(str(out / name)),
                                print("saved", out / name), app.quit()))
sys.exit(app.exec())
