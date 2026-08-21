import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""Chart drag targets must match the table's, so both go through move_row."""

import sys

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from playlistflow.chart import BarChart
from playlistflow.domain import Track, seams

tracks = [Track(title=f"T{i}", bpm=100 + i, key="1A", duration_ms=180_000)
          for i in range(8)]

c = BarChart()
c.resize(800, 200)
c.set_data(tracks, seams(tracks), False, -1)

rects = c._bar_rects()
ok = True

print("drop targets across each bar:")
for i, r in enumerate(rects):
    left = c._drop_target(r.left() + 1)
    right = c._drop_target(r.right() - 1)
    exp_left = i
    exp_right = min(i + 1, len(rects) - 1)
    good = left == exp_left and right == exp_right
    ok &= good
    print(f"  bar {i}: left->{left} (exp {exp_left})  right->{right} "
          f"(exp {exp_right})  {'ok' if good else 'MISMATCH'}")

# Past either end should clamp rather than return nonsense.
before = c._drop_target(-50)
after = c._drop_target(10_000)
good = before == 0 and after == len(rects) - 1
ok &= good
print(f"\noff the left -> {before} (exp 0), off the right -> {after} "
      f"(exp {len(rects)-1})  {'ok' if good else 'MISMATCH'}")

# A real move through the same path the window uses.
moved = []
c.reordered.connect(lambda a, b: moved.append((a, b)))
c._drag_src = 0
c._dragging = True
c._drag_dst = c._drop_target(rects[4].center().x() + 1)
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
ev = QMouseEvent(QMouseEvent.MouseButtonRelease, QPointF(rects[4].center().x() + 1, 50),
                 Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
c.mouseReleaseEvent(ev)
good = moved == [(0, 5)]
ok &= good
print(f"drag bar 0 past the middle of bar 4 -> {moved} (exp [(0, 5)]) "
      f"{'ok' if good else 'MISMATCH'}")

print("\n" + ("CHART DRAG TESTS PASSED" if ok else "CHART DRAG TESTS FAILED"))
raise SystemExit(0 if ok else 1)
