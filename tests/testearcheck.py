import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import os, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
import main as app_main

app = QApplication([])
app.setStyleSheet(app_main.QSS)
app.setFont(QFont("Segoe UI", 10))

from playlistflow.mainwindow import MainWindow
from playlistflow.domain import Track, seams, seam_key, summary
from playlistflow.store import Store

w = MainWindow()
tmp = tempfile.mkdtemp(prefix="pfear")
_real = w.prefs.storage_dir
w.prefs.storage_dir = tmp
w.store = Store(tmp)

def mk(u, n): return Track(title=n, artist="A", uri="spotify:track:" + u,
                           bpm=90, key="8A", source="manual")
w.tracks = [mk("X", "One"), mk("Y", "Two"), mk("Z", "Three")]
w.current_name = "EarTest"
w.refresh()

# 1. toggle on
w.toggle_ear_check(0)
sm = seams(w.tracks, w.approved)
print("mark 0->1  :", sm[0].checked, sm[1].checked, "(expect True False)")
print("summary    :", summary(w.tracks, w.approved))

# 2. survives reordering elsewhere (swap rows 1 and 2 -> pair X,Y broken!)
#    swap 2 and 3 instead: pair X->Y intact
w.tracks[1], w.tracks[2] = w.tracks[2], w.tracks[1]
sm = seams(w.tracks, w.approved)
print("after swap :", sm[0].checked, "(expect False - Y no longer follows X)")
w.tracks[1], w.tracks[2] = w.tracks[2], w.tracks[1]
sm = seams(w.tracks, w.approved)
print("swap back  :", sm[0].checked, "(expect True - pair restored)")

# 3. last-row guard
w.toggle_ear_check(2)
print("last row   : approved size", len(w.approved), "(expect 1)")

# 4. persistence round-trip
w.save_playlist()
w2_approved = None
st = Store(tmp)
tracks = st.load("EarTest")
print("persisted  :", st.last_loaded_checked == [seam_key(w.tracks[0], w.tracks[1])])

# 5. toggle off
w.toggle_ear_check(0)
sm = seams(w.tracks, w.approved)
print("unmark     :", sm[0].checked, "(expect False)")

# 6. table menu label logic sanity: seams list on table
w.refresh()
print("table seams:", len(w.table._seams), "rows", len(w.tracks))

w.prefs.storage_dir = _real
shutil.rmtree(tmp, ignore_errors=True)
print("done, prefs restored")

# 7. Spotify-load path restores from local meta (the close/reopen bug)
import tempfile as _tf
tmp2 = _tf.mkdtemp(prefix="pfear2")
st2 = Store(tmp2)
st2.save("Ache2", [mk("X", "One"), mk("Y", "Two")], auto=False,
         ear_checked=["spotify:track:X >> spotify:track:Y"])
m = st2.meta("Ache2")
print("meta round-trip:", m.get("ear_checked") == ["spotify:track:X >> spotify:track:Y"])
print("meta missing   :", st2.meta("Nope") == {})
shutil.rmtree(tmp2, ignore_errors=True)
