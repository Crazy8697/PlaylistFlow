"""Render the table mid-drag so the drop indicator can be inspected."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QTimer

from main import QSS
from playlistflow.table import TrackTable
from playlistflow.domain import Track, seams

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setFont(QFont("Segoe UI", 10))
app.setStyleSheet(QSS)

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")

titles = ["LET ME IN", "Curiosity", "Don't You Dare Look Away", "Addict",
          "Believe It", "Devil in Her Eyes", "Red Room", "Straitjackets & Roses"]
keys = ["12A", "12B", "12A", "12A", "12A", "12B", "10A", "12A"]
bpms = [162, 96, 142, 129, 172, 110, 120, 105]
tracks = [Track(title=t, artist="Artist", bpm=b, key=k)
          for t, b, k in zip(titles, bpms, keys)]

table = TrackTable()
table.set_data(tracks, seams(tracks), False)
table.resize(980, 420)
table.show()


def shot():
    # Pretend a drag is hovering just above row 4.
    table._drop_row = 4
    table.selectRow(1)
    table.viewport().update()
    QTimer.singleShot(200, save)


def save():
    table.grab().save(str(out / "shot_drop.png"))
    print("saved", out / "shot_drop.png")
    app.quit()


QTimer.singleShot(500, shot)
sys.exit(app.exec())
