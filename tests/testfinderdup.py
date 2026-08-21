import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import Qt

app = QApplication([])
from playlistflow.mainwindow import MainWindow
from playlistflow.finderdialog import FinderDialog
from playlistflow.finder import Result, Line, Candidate, AUTO
from playlistflow.domain import Track

w = MainWindow()

def mk(uri, name):
    return Track(title=name, artist="A", uri=uri, source="spotify")

batch = [mk("spotify:track:AAA", "One"), mk("spotify:track:BBB", "Two")]

print("start:", len(w.tracks), "tracks")
w._absorb_found(batch)
print("after 1st send:", len(w.tracks))
w._absorb_found(batch)
print("after 2nd send (same batch):", len(w.tracks), "<- must not double")
w._absorb_found(batch + [mk("spotify:track:CCC", "Three")])
print("after 3rd send (2 dupes + 1 new):", len(w.tracks), "<- expect 3")
print("uris:", [t.uri for t in w.tracks])

# dialog: dedupe within one batch + close on send
dlg = FinderDialog(w.spotify, {"spotify:track:AAA"})
c1 = Candidate(uri="spotify:track:XXX", name="Dup", artists="A", album="Al",
               year="2024", duration_ms=1000, isrc="I1")
c2 = Candidate(uri="spotify:track:XXX", name="Dup", artists="A", album="Al2",
               year="2024", duration_ms=1000, isrc="I1")
c3 = Candidate(uri="spotify:track:AAA", name="Known", artists="A", album="Al",
               year="2024", duration_ms=1000, isrc="I2")
dlg.results = {
    0: Result(line=Line(raw="a"), status=AUTO, candidates=[c1], chosen=0),
    1: Result(line=Line(raw="b"), status=AUTO, candidates=[c2], chosen=0),
    2: Result(line=Line(raw="c"), status=AUTO, candidates=[c3], chosen=0),
}
picks = dlg._picked_in_order()
print()
print("3 rows, two sharing a URI -> picked:", len(picks), "<- expect 2")
print("uris:", [c.uri for c in picks])

got = {}
dlg.send_to_playlist.connect(lambda t: got.update(n=len(t)))
dlg._send()
print("send emitted:", got.get("n"), "| dialog result:", 
      "Accepted" if dlg.result() == QDialog.Accepted else "still open")
