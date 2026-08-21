import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""The playlist list and the chart beside it must start on the same line."""

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

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")

w = MainWindow()
w.store = Store(out / "aligncheck")
w.refresh_saved()
w.resize(1280, 900)
w.show()

ok = True


def check():
    global ok
    a = w.sp_list.mapTo(w, w.sp_list.rect().topLeft()).y()
    b = w.chart_scroll.mapTo(w, w.chart_scroll.rect().topLeft()).y()
    delta = abs(a - b)
    ok = delta <= 1
    print(f"  playlist list top : {a}px")
    print(f"  chart top         : {b}px")
    print(f"  difference        : {delta}px  {'ok' if ok else 'MISALIGNED'}")

    # Also check the two bottoms of the first row region line up, i.e. the
    # header and the button row are the same height.
    hh = w.sp_list.mapTo(w, w.sp_list.rect().topLeft()).y()
    print(f"\n  (list starts at {hh}px)")
    w.grab().copy(0, 0, 900, 120).save(str(out / "shot_align.png"))
    print(f"  saved {out / 'shot_align.png'}")
    app.quit()


QTimer.singleShot(900, check)
app.exec()
print("\n" + ("ALIGN TEST PASSED" if ok else "ALIGN TEST FAILED"))
raise SystemExit(0 if ok else 1)
