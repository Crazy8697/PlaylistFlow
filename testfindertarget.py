import os, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QTimer

app = QApplication([])
from playlistflow.mainwindow import MainWindow, PlaylistTargetDialog
from playlistflow.store import Store
from playlistflow.domain import Track

tmp = tempfile.mkdtemp(prefix="pfstore")
w = MainWindow()
# _absorb_found calls _ensure_storage(), which rebuilds self.store from prefs.
# Point prefs at the temp dir first, or this test writes into the real
# Documents/PlaylistFlow folder.
_real_dir = w.prefs.storage_dir
w.prefs.storage_dir = tmp
w.store = Store(tmp)
w.current_name = ""
w.tracks = []

def mk(u, n): return Track(title=n, artist="A", uri=u, source="spotify")
batch = [mk("spotify:track:AAA", "One"), mk("spotify:track:BBB", "Two")]

# --- 1. cancel adds nothing -------------------------------------------------
def cancel_next():
    for dl in app.topLevelWidgets():
        if isinstance(dl, PlaylistTargetDialog):
            dl.reject()
QTimer.singleShot(120, cancel_next)
w._absorb_found(batch)
print("cancel -> tracks=%d name=%r  (expect 0, '')" % (len(w.tracks), w.current_name))

# --- 2. new playlist --------------------------------------------------------
def choose_new():
    for dl in app.topLevelWidgets():
        if isinstance(dl, PlaylistTargetDialog):
            dl.r_new.setChecked(True)
            dl.name.setText("Test Set")
            dl.accept()
QTimer.singleShot(120, choose_new)
w._absorb_found(batch)
print("new    -> tracks=%d name=%r saved=%s" % (
    len(w.tracks), w.current_name, sorted(p.name for p in __import__('pathlib').Path(tmp).glob('*.json'))))

# --- 3. now a playlist IS open: no dialog, dedupe applies -------------------
w._absorb_found(batch)
print("resend -> tracks=%d  (expect 2, no dialog)" % len(w.tracks))
w._absorb_found(batch + [mk("spotify:track:CCC", "Three")])
print("mixed  -> tracks=%d  (expect 3)" % len(w.tracks))

# --- 4. undo returns to the pre-add state in ONE press ----------------------
w.undo()
print("undo   -> tracks=%d  (expect 2)" % len(w.tracks))

# --- 5. existing playlist path ---------------------------------------------
w.store.save("Other Set", [mk("spotify:track:ZZZ", "Zed")], auto=False)
w.current_name = ""
w.tracks = [mk("spotify:track:QQQ", "Loose")]
def choose_existing():
    for dl in app.topLevelWidgets():
        if isinstance(dl, PlaylistTargetDialog):
            dl.r_old.setChecked(True)
            i = dl.combo.findText("Other Set")
            dl.combo.setCurrentIndex(i)
            print("       warning shown for loose tracks:", dl.warn.isVisible())
            dl.accept()
QTimer.singleShot(120, choose_existing)
w._absorb_found(batch)
print("exist  -> name=%r tracks=%d uris=%s" % (
    w.current_name, len(w.tracks), [t.uri.split(':')[-1] for t in w.tracks]))

w.prefs.storage_dir = _real_dir     # never leave prefs pointing at a temp dir
shutil.rmtree(tmp, ignore_errors=True)
