import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""Sort order: down the wheel, reversible, unresolved rows always last."""

import sys

from PySide6.QtWidgets import QApplication

from playlistflow.domain import Track, felt_bpm

app = QApplication(sys.argv)

from playlistflow.mainwindow import MainWindow  # needs a QApplication first


def mk(title, bpm, key):
    return Track(title=title, artist="A", bpm=bpm, key=key)


w = MainWindow.__new__(MainWindow)      # no UI needed for the sort itself
w._sort_field, w._sort_desc = "", False
w.felt = False
w.snapshot = lambda: None
w.refresh = lambda *a, **k: None
w.status = lambda *a: None
w.table = type("T", (), {"clearSelection": lambda self: None})()

w.tracks = [
    mk("c", 100, "2A"),
    mk("a", 140, "1A"),
    mk("e", 0, ""),          # nothing to sort on
    mk("b", 90, "1B"),
    mk("d", 120, "12A"),
    mk("f", 75, ""),         # bpm but no key
]

ok = True


def show(label):
    print(f"{label}: " + ", ".join(
        f"{t.title}({t.bpm:g}/{t.key or '-'})" for t in w.tracks))


show("initial")

w.sort_tracks("key")
got = [t.title for t in w.tracks]
exp = ["a", "b", "c", "d", "e", "f"]   # 1A,1B,2A,12A then the two keyless
ok &= got[:4] == exp[:4] and set(got[4:]) == {"e", "f"}
show("by key")
print(f"   expected 1A,1B,2A,12A then keyless — {'ok' if ok else 'MISMATCH'}")

w.sort_tracks("key")                    # same field again reverses
got = [t.title for t in w.tracks]
rev_ok = got[:4] == ["d", "c", "b", "a"] and set(got[4:]) == {"e", "f"}
ok &= rev_ok
show("by key again")
print(f"   expected reversed, keyless still last — {'ok' if rev_ok else 'MISMATCH'}")

w.sort_tracks("bpm")
got = [t.title for t in w.tracks]
bpm_ok = got[:5] == ["f", "b", "c", "d", "a"] and got[5] == "e"
ok &= bpm_ok
show("by bpm")
print(f"   expected 75,90,100,120,140 then no-bpm — {'ok' if bpm_ok else 'MISMATCH'}")

# Felt view sorts by what is displayed.
w.felt = True
w._sort_field = ""
w.tracks = [mk("slow", 140, "1A"), mk("fast", 100, "1A")]
w.sort_tracks("bpm")
felt_ok = [t.title for t in w.tracks] == ["slow", "fast"]   # 140 felts to 70
ok &= felt_ok
print(f"\nfelt view: 140 -> {felt_bpm(140):g}, 100 -> {felt_bpm(100):g}")
show("by felt bpm")
print(f"   expected slow first — {'ok' if felt_ok else 'MISMATCH'}")

print("\n" + ("SORT TESTS PASSED" if ok else "SORT TESTS FAILED"))
raise SystemExit(0 if ok else 1)
