import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
from playlistflow.mainwindow import MainWindow
from playlistflow.domain import Track

w = MainWindow()
w.current_pid = "PID"
w.current_name = "Ache"
type(w.auth).authorised = property(lambda self: True)

ANSWER = {"v": QMessageBox.Yes}
seen = []
QMessageBox.question = staticmethod(lambda *a, **k: (seen.append(("q", a[2][:40])), ANSWER["v"])[1])
QMessageBox.warning = staticmethod(lambda *a, **k: (seen.append(("warn", a[2][:40])), QMessageBox.Ok)[1])
QMessageBox.information = staticmethod(lambda *a, **k: (seen.append(("info", a[2][:40])), QMessageBox.Ok)[1])

calls = {}
def stub(current):
    calls.clear(); seen.clear()
    w.spotify.playlist_uris = lambda pid: list(current)
    def add_items(pid, uris, progress=None):
        calls["added"] = list(uris); return len(uris)
    def reorder(pid, target, progress=None):
        calls["reordered"] = list(target); return 1
    w.spotify.add_items = add_items
    w.spotify.reorder_playlist = reorder

def mk(u): return Track(title=u[-1], artist="A", uri="spotify:track:" + u)
def short(k): return [u[-1] for u in calls.get(k, [])] if k in calls else None

# 1. window holds 2 tracks Spotify has never seen
w.tracks = [mk("A"), mk("B"), mk("C")]
stub(["spotify:track:A"]); ANSWER["v"] = QMessageBox.Yes
w.push_order()
print("new tracks  -> added=%s reordered=%s" % (short("added"), short("reordered")))

# 2. same, declined
stub(["spotify:track:A"]); ANSWER["v"] = QMessageBox.No
w.push_order()
print("declined    -> added=%s reordered=%s   (expect None None)" % (short("added"), short("reordered")))

# 3. Spotify holds one the window dropped
stub(["spotify:track:A", "spotify:track:Z"]); ANSWER["v"] = QMessageBox.Yes
w.push_order()
print("extra on spf-> added=%s reordered=%s   %s" % (short("added"), short("reordered"), seen[-1:]))

# 4. sets already match
stub(["spotify:track:C", "spotify:track:B", "spotify:track:A"]); ANSWER["v"] = QMessageBox.Yes
w.push_order()
print("sets match  -> added=%s reordered=%s" % (short("added"), short("reordered")))

# 5. duplicate in the window
w.tracks = [mk("A"), mk("A")]
stub(["spotify:track:A"]); ANSWER["v"] = QMessageBox.Yes
w.push_order()
print("dupe in win -> added=%s reordered=%s   %s" % (short("added"), short("reordered"), seen[-1:]))
