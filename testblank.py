"""next_blank walks every gap, in row order, BPM before key, and wraps."""

import sys

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from playlistflow.table import TrackTable, COL_BPM, COL_KEY
from playlistflow.domain import Track, seams

t = TrackTable()
tracks = [
    Track(title="full", bpm=100, key="1A"),
    Track(title="no bpm", bpm=0, key="2A"),
    Track(title="no key", bpm=120, key=""),
    Track(title="neither", bpm=0, key=""),
    Track(title="full2", bpm=90, key="3B"),
]
t.set_data(tracks, seams(tracks), False)

names = {COL_BPM: "BPM", COL_KEY: "key"}
ok = True

# Row 3 is missing BOTH, so it must be visited twice — BPM then key — before
# moving on. Skipping straight past it was the bug this covers.
expected = [(1, COL_BPM), (2, COL_KEY), (3, COL_BPM), (3, COL_KEY), (1, COL_BPM)]
row, col = -1, -1
for exp in expected:
    got = t.next_blank(row, col)
    good = got == exp
    ok &= good
    print(f"  from ({row:>2},{names.get(col, '-'):<4}) -> row {got[0]} "
          f"{names.get(got[1], '?'):<4} expected row {exp[0]} "
          f"{names.get(exp[1], '?'):<4} {'ok' if good else 'MISMATCH'}")
    row, col = got

print("\nnothing missing:")
full = [Track(title="a", bpm=100, key="1A"), Track(title="b", bpm=110, key="2A")]
t.set_data(full, seams(full), False)
got = t.next_blank(-1)
good = got == (-1, -1)
ok &= good
print(f"  {got} expected (-1, -1) {'ok' if good else 'MISMATCH'}")

print("\n" + ("BLANK TESTS PASSED" if ok else "BLANK TESTS FAILED"))
raise SystemExit(0 if ok else 1)
