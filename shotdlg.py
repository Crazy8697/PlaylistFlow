"""Render the sign-in dialog for a look."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QTimer

from main import QSS
from playlistflow.config import Prefs, load_env
from playlistflow.auth import SpotifyAuth
from playlistflow.mainwindow import SignInDialog

app = QApplication(sys.argv)
app.setOrganizationName("darkrelay")
app.setApplicationName("PlaylistFlow")
app.setStyle("Fusion")
app.setFont(QFont("Segoe UI", 10))
app.setStyleSheet(QSS)

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
env = load_env()
dlg = SignInDialog(SpotifyAuth(env.get("SPOTIFY_CLIENT_ID", ""), Prefs()))
dlg.show()
QTimer.singleShot(700, lambda: (dlg.grab().save(str(out / "shot_signin.png")),
                                print("saved", out / "shot_signin.png"),
                                app.quit()))
sys.exit(app.exec())
