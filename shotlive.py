"""Render the real window against the live Spotify account and grab a screenshot."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QTimer

from main import QSS
from playlistflow.mainwindow import MainWindow
from playlistflow.store import Store

app = QApplication(sys.argv)
app.setOrganizationName("darkrelay")
app.setApplicationName("PlaylistFlow")
# The harness must never write prefs.storage_dir: Prefs() opens the real
# QSettings regardless of the app name here, so assigning it would repoint the
# installed app at a temp folder. Set w.store directly instead (below).
app.setStyle("Fusion")
app.setFont(QFont("Segoe UI", 10))
app.setStyleSheet(QSS)

out = Path(sys.argv[1])

w = MainWindow()
w.store = Store(out / "livestore")
w.refresh_saved()
w.refresh_spotify()
w.resize(1280, 900)
w.show()


def step1():
    print("spotify list:", w.sp_list.count())
    for i in range(w.sp_list.count()):
        print("   ", w.sp_list.item(i).text())
    if w.sp_list.count():
        w.sp_list.setCurrentRow(0)
        w.load_from_spotify()
    QTimer.singleShot(2500, step2)


def step2():
    print("tracks loaded:", len(w.tracks))
    for t in w.tracks[:4]:
        print(f"    {t.artist} — {t.title}  isrc={t.isrc}  {t.uri}")
    w.grab().save(str(out / "shot_live.png"))
    print("saved", out / "shot_live.png")
    print("summary:", w.stat.text())
    app.quit()


QTimer.singleShot(3000, step1)
sys.exit(app.exec())
