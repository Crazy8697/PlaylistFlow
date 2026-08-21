import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""Render the timeline mode for a look."""

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
app.setStyle("Fusion")
app.setFont(QFont("Segoe UI", 10))
app.setStyleSheet(QSS)

out = Path(sys.argv[1])

w = MainWindow()
w.store = Store(out / "livestore")
w.refresh_saved()
w.tracks = w.store.load("Ruin")
w.current_name = "Ruin"
w.refresh()
w.resize(1280, 900)
w.show()


def go():
    known = sum(1 for t in w.tracks if t.duration_ms > 0)
    total = sum(t.duration_ms for t in w.tracks)
    print(f"tracks with a known length: {known}/{len(w.tracks)}")
    print(f"total run time: {total/60000:.1f} min")
    w.btn_timeline.setChecked(True)
    w.toggle_timeline()
    w.chart.set_playhead(3, 40_000)
    QTimer.singleShot(400, save)


def save():
    w.grab().save(str(out / "shot_timeline.png"))
    print("zoom (px/sec):", round(w.chart.zoom(), 3))
    print("saved", out / "shot_timeline.png")
    app.quit()


QTimer.singleShot(700, go)
sys.exit(app.exec())
