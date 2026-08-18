import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, Qt

from playlistflow.config import Prefs, load_env
from playlistflow.auth import SpotifyAuth
from playlistflow.providers import Spotify
from playlistflow.finderdialog import FinderDialog
from playlistflow.finder import AUTO, REVIEW

app = QApplication([])
env = load_env()
sp = Spotify(SpotifyAuth(env.get("SPOTIFY_CLIENT_ID", ""), Prefs()))

dlg = FinderDialog(sp)
dlg.input.setPlainText(
    "Kate McCannon Colter Wall\n"
    "Linger Royel Otis\n"
    "\n"
    "Vienna Matt Schuster\n"
    "Kate McCannon Colter Wall\n"
    "zzzz nonexistent track qqqq\n"
)

got = {}

def finished():
    tree = dlg.tree
    print("groups:")
    for i in range(tree.topLevelItemCount()):
        g = tree.topLevelItem(i)
        print("   %-24s children=%d expanded=%s" % (g.text(0), g.childCount(), g.isExpanded()))
    print()
    print("results by line:")
    for i in sorted(dlg.results):
        r = dlg.results[i]
        pick = r.pick
        print("   %d %-32s %-9s %s" % (
            i, r.line.raw[:32], r.status, pick.uri if pick else "(none)"))
    print()
    uris = [c.uri for c in dlg._picked_in_order()]
    print("URI block (%d):" % len(uris))
    for u in uris:
        print("   ", u)

    # exercise skip on line 0
    print()
    rev = None
    for i in range(tree.topLevelItemCount()):
        g = tree.topLevelItem(i)
        for j in range(g.childCount()):
            it = g.child(j)
            if it.data(0, Qt.UserRole) == 0:
                rev = it
    if rev is not None:
        rev.setCheckState(0, Qt.Unchecked)
        print("after skipping line 0: %d URIs" % len(dlg._picked_in_order()))
        rev.setCheckState(0, Qt.Checked)

    # exercise choosing the 2nd candidate on a review row
    for i in sorted(dlg.results):
        r = dlg.results[i]
        if r.status == REVIEW and len(r.candidates) > 1:
            for k in range(tree.topLevelItemCount()):
                g = tree.topLevelItem(k)
                for j in range(g.childCount()):
                    it = g.child(j)
                    if it.data(0, Qt.UserRole) == i and it.childCount() > 1:
                        it.child(1).setCheckState(0, Qt.Checked)
                        print("line %d chosen -> %d (expected 1)" % (i, dlg.results[i].chosen))
                        break
            break
    app.quit()

dlg.worker_done = finished
orig = dlg._finished
def patched():
    orig()
    finished()
dlg._finished = patched
dlg._resolve()
dlg.worker.done.disconnect()
dlg.worker.done.connect(patched)

QTimer.singleShot(90000, app.quit)
app.exec()
