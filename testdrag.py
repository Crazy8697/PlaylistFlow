"""Reorder integrity: the view must never drift out of step with the list."""

import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, QPointF, Qt


class FakeDrop:
    """QDropEvent's source() is read-only in PySide6, so stand in for it.
    dropEvent only ever calls these four."""

    def __init__(self, widget, point):
        self._w = widget
        self._p = QPointF(point)
        self.action = Qt.MoveAction
        self.accepted = False

    def source(self):
        return self._w

    def position(self):
        return self._p

    def setDropAction(self, a):
        self.action = a

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False

    def dropAction(self):
        return self.action

from playlistflow.table import TrackTable, COL_N
from playlistflow.domain import Track, seams

app = QApplication(sys.argv)

tracks = [Track(title=f"T{i}", artist="A", bpm=100 + i, key="1A",
                uri=f"spotify:track:{i}") for i in range(10)]

table = TrackTable()
moves = []


def do_move(src, dst):
    t = tracks.pop(src)
    tracks.insert(max(0, min(dst, len(tracks))), t)
    moves.append((src, dst))
    table.set_data(tracks, seams(tracks), False)


def resync():
    table.set_data(tracks, seams(tracks), False)


table.reordered.connect(do_move)
table.dragFinished.connect(resync)
table.set_data(tracks, seams(tracks), False)
table.resize(900, 600)
table.show()

ok = True


def check(label):
    global ok
    rows = table.rowCount()
    good = rows == len(tracks)
    nums = [table.item(r, COL_N).text() for r in range(rows)]
    seq = nums == [str(i + 1) for i in range(rows)]
    titles = [table.item(r, 1).text() for r in range(rows)]
    aligned = titles == [t.title for t in tracks]
    if not (good and seq and aligned):
        ok = False
    print(f"{label}")
    print(f"   rowCount={rows} tracks={len(tracks)} {'ok' if good else 'MISMATCH'}")
    print(f"   numbering {'sequential' if seq else 'BROKEN: ' + ','.join(nums)}")
    print(f"   titles    {'aligned' if aligned else 'MISALIGNED'}")
    print(f"   order     {[t.title for t in tracks]}")


check("initial")

# The gate that a direct dropEvent() call skips entirely: in InternalMove mode
# QAbstractItemView::dragMoveEvent refuses the drag unless MoveAction is among
# possibleActions(). Overriding startDrag to strip MoveAction silently disables
# reordering while every dropEvent-level test still passes.
print("\ndrag-accept gate")
from PySide6.QtGui import QDragMoveEvent
from PySide6.QtCore import QMimeData

rect = table.visualRect(table.model().index(3, 0))
dm = QDragMoveEvent(rect.center(), Qt.MoveAction | Qt.CopyAction,
                    QMimeData(), Qt.LeftButton, Qt.NoModifier)
has_move = bool(dm.possibleActions() & Qt.MoveAction)
print(f"   dragDropMode is InternalMove: {table.dragDropMode() == table.DragDropMode.InternalMove}")
print(f"   MoveAction in possibleActions: {has_move}")
if not has_move:
    ok = False
    print("   BROKEN — InternalMove will reject every drop")

# Simulate a drop of row 0 onto row 4, the way the view would deliver it.
for src, dst in ((0, 4), (7, 1), (3, 9)):
    table.clearSelection()
    table.selectRow(src)
    rect = table.visualRect(table.model().index(dst, 0))
    ev = FakeDrop(table, QPoint(rect.center().x(), rect.top() + 2))
    table.dropEvent(ev)

    # Reproduce what Qt actually does next: startDrag() sees the drag resolve
    # to MoveAction and calls clearOrRemove(), deleting the dragged row from
    # the view AFTER dropEvent has rebuilt it. Previously this silently left
    # the view one row short and every row below misaligned.
    table.removeRow(min(src, table.rowCount() - 1))
    table.dragFinished.emit()
    check(f"\nafter drop row {src} -> {dst}  (drop action now "
          f"{'Copy' if ev.dropAction() == Qt.CopyAction else 'MOVE — will delete source'})")

print("\n" + ("DRAG TESTS PASSED" if ok else "DRAG TESTS FAILED"))
raise SystemExit(0 if ok else 1)
