import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QTimer
import main
from playlistflow.domain import Track

app = QApplication([]); app.setStyleSheet(main.QSS)
# Same font main() installs -- without it the offscreen renderer has no
# glyphs and every label comes out as tofu boxes.
app.setFont(QFont("Segoe UI", 10))
from playlistflow.mainwindow import MainWindow
w = MainWindow()
w.resize(1400, 880)
w.current_name = "Ache"
w.current_desc = ("Slow-burn country for the drive home. Nothing above 100 BPM, "
                  "nothing cheerful. If it doesn't ache, it doesn't belong.")
w.tracks = [Track(title="Cowpoke", artist="Colter Wall", bpm=92, key="8A", uri="spotify:track:a"),
            Track(title="Seneca Creek", artist="Charles Wesley Godwin", bpm=88, key="9A", uri="spotify:track:b"),
            Track(title="Sawtoothed Jericho", artist="Pony Bradshaw", bpm=96, key="8A", uri="spotify:track:c")]
w.show()
w.refresh()
def snap():
    pc = w.pl_cover.pixmap(); pa = w.player.art.pixmap()
    print("playlist cover: null=%s size=%s" % (pc.isNull() if pc else "None",
                                               pc.size() if pc else None))
    print("player art    : null=%s size=%s url=%r" % (pa.isNull() if pa else "None",
                                                      pa.size() if pa else None,
                                                      w.player._art_url))
    print("current_image :", repr(w.current_image))
    w.grab().save("shot_layout.png")
    app.quit()
QTimer.singleShot(900, snap)
app.exec()
print("wrote shot_layout.png")
