import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QKeyEvent, QGuiApplication
from PySide6.QtCore import Qt, QEvent

app = QApplication([])
from playlistflow.mainwindow import MainWindow
from playlistflow.domain import Track

# Stub the dialogs BEFORE anything can pop one modally.
ANSWER = {"v": QMessageBox.Yes}
msgs = []
QMessageBox.question = staticmethod(lambda *a, **k: (msgs.append(a[2]), ANSWER["v"])[1])
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)

w = MainWindow()
w.current_pid = "PID"; w.current_name = "Ache"
type(w.auth).authorised = property(lambda self: True)
w.tracks = [Track(title="Kate McCannon", artist="Colter Wall", uri="spotify:track:A"),
            Track(title="Tishomingo", artist="Zach Bryan", uri="spotify:track:B"),
            Track(title="23", artist="Chayce Beckham", uri="spotify:track:C")]
w.refresh()

w.copy_tracks([0])
print("copy 1 row  ->", repr(QGuiApplication.clipboard().text()))
w.copy_tracks([0, 2])
print("copy 2 rows ->", repr(QGuiApplication.clipboard().text()))

QGuiApplication.clipboard().setText("")
w.table.selectRow(1)
w.table.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_C, Qt.ControlModifier, "c"))
print("ctrl+c      ->", repr(QGuiApplication.clipboard().text()))

# signal is wired to the handler
got = []
w.table.copyRequested.emit([2])
print("signal      ->", repr(QGuiApplication.clipboard().text()))

# _sel_rows: right-click outside the selection acts on the clicked row
w.table.selectRow(0)
print("sel_rows(0) ->", w.table._sel_rows(0), " sel_rows(2) ->", w.table._sel_rows(2))

calls = {}
def rem(pid, uris, progress=None):
    calls["removed"] = list(uris); return len(uris)
def reo(pid, target, progress=None):
    calls["reordered"] = list(target); return 1
w.spotify.playlist_uris = lambda pid: ["spotify:track:A", "spotify:track:B",
                                       "spotify:track:C", "spotify:track:GONE1",
                                       "spotify:track:GONE2"]
w.spotify.track_names = lambda uris: {
    "spotify:track:GONE1": "Billy Joel - Vienna",
    "spotify:track:GONE2": "The Cranberries - Linger"}
w.spotify.remove_items = rem
w.spotify.reorder_playlist = reo

msgs.clear(); ANSWER["v"] = QMessageBox.Yes
w.push_order()
print("remove      -> removed=%s reordered=%d" % (
    [u.split(':')[-1] for u in calls.get('removed', [])], len(calls.get('reordered', []))))
print("prompt      ->", msgs[0].replace(chr(10), " | ")[:140] if msgs else "(none)")

calls.clear(); msgs.clear(); ANSWER["v"] = QMessageBox.No
w.push_order()
print("declined    -> removed=%s reordered=%s  (expect None None)" % (
    calls.get('removed'), calls.get('reordered')))
