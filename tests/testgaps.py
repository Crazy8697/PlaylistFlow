import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""Every gap in the timeline strip must be exactly STRIP_GAP pixels.

Rounding each width on its own gives 1px and 2px gaps at random, which reads as
a ragged strip. Boundaries are rounded from the running total instead.
"""

import sys

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from playlistflow.chart import BarChart, STRIP_GAP
from playlistflow.domain import Track, seams

# Deliberately awkward lengths, so pixel boundaries land mid-pixel constantly.
durations = [171035, 240991, 187003, 133777, 205111, 159048, 226420,
             141900, 198333, 176666, 212121, 149999]
tracks = [Track(title=f"T{i}", bpm=100 + i, key="1A", duration_ms=d)
          for i, d in enumerate(durations)]

ok = True
for mode, width in (("fit", 1200), ("fit", 987), ("time", 1200), ("time", 640)):
    c = BarChart()
    c.resize(width, 200)
    c.set_data(tracks, seams(tracks), False, -1)
    c.set_mode(mode)
    if mode == "time":
        c.set_zoom(c.fit_zoom(width))
    rects = c._strip_rects()
    gaps = [round(rects[i + 1].left() - rects[i].right())
            for i in range(len(rects) - 1)]
    uniform = set(gaps) == {STRIP_GAP}
    ok &= uniform
    print(f"  mode={mode:<5} width={width:<5} gaps={sorted(set(gaps))} "
          f"{'ok' if uniform else 'UNEVEN: ' + str(gaps)}")

    # No block may be swallowed entirely, however short the track.
    thin = [r.width() for r in rects if r.width() < 1]
    ok &= not thin
    if thin:
        print(f"     {len(thin)} block(s) collapsed to nothing")

print("\n" + ("GAP TESTS PASSED" if ok else "GAP TESTS FAILED"))
raise SystemExit(0 if ok else 1)
