"""Track table.

Drag reordering is handled by intercepting the drop and reordering the caller's
list — QTableWidget's own InternalMove moves cell contents, which corrupts rows.

The seam readout is painted into a strip at the bottom of each row, so it reads
as sitting between tracks without being a row that can itself be dragged.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QAbstractItemView, QStyledItemDelegate,
    QHeaderView, QStyle, QMenu,
)

from .domain import Track, Seam, felt_bpm, valid_key

COL_N, COL_TITLE, COL_ARTIST, COL_BPM, COL_KEY = range(5)
HEADERS = ["#", "Title", "Artist", "BPM", "Key"]

ROW_H = 46
SEAM_H = 15

INK = QColor("#E9E7E1")
DIM = QColor("#8C939D")
FAINT = QColor("#5C636D")
BAD = QColor("#E8544F")
WARN = QColor("#E8A93E")
RAISED = QColor("#20242B")
# Alternating bands. Each pair of shades is the same hue, one step apart, so a
# row and its seam strip read as one block without the stripes shouting.
ROW_BG = QColor("#181B21")
ROW_BG_ALT = QColor("#1E222A")
UNRESOLVED_BG = QColor("#2A1F22")
UNRESOLVED_BG_ALT = QColor("#31262A")
UNVERIFIED_BG = QColor("#26221A")
UNVERIFIED_BG_ALT = QColor("#2D2921")
SELECTED_BG = QColor("#2C3440")
ROW_LINE = QColor("#22262E")
DROP_LINE = QColor("#3FBFA8")
OKGREEN = QColor("#5FBF6B")
PLAYING_BG = QColor("#173029")
PLAYING_EDGE = QColor("#3FBFA8")


class CellDelegate(QStyledItemDelegate):
    """Keeps cell content in the upper band so the seam strip stays clear, and
    paints the key chip itself — a stylesheet on QTableWidget::item overrides
    per-item backgrounds, so the chip has to be drawn here."""

    def __init__(self, table, parent=None):
        super().__init__(parent)
        self._table = table

    def _track(self, row):
        ts = self._table.tracks()
        # If the view and the list ever disagree, paint nothing rather than
        # showing another track's key on this row.
        if len(ts) != self._table.rowCount():
            return None
        return ts[row] if 0 <= row < len(ts) else None

    def paint(self, painter, option, index):
        upper = QRect(option.rect.x(), option.rect.y(),
                      option.rect.width(), option.rect.height() - SEAM_H)
        t = self._track(index.row())

        # Fill the WHOLE row, seam strip included, so the key/tempo readout
        # reads as belonging to the track above it rather than floating between
        # two rows. Alternating bands make that pairing obvious at a glance.
        selected = bool(option.state & QStyle.State_Selected)
        playing = index.row() == self._table.playing_row()
        if playing:
            base = PLAYING_BG
        elif selected:
            base = SELECTED_BG
        elif t is not None and not t.resolved:
            base = UNRESOLVED_BG if index.row() % 2 == 0 else UNRESOLVED_BG_ALT
        elif t is not None and t.unverified:
            base = UNVERIFIED_BG if index.row() % 2 == 0 else UNVERIFIED_BG_ALT
        else:
            base = ROW_BG if index.row() % 2 == 0 else ROW_BG_ALT
        painter.fillRect(option.rect, base)
        if playing and index.column() == COL_N:
            # A bright edge down the left of the row Spotify is on.
            painter.fillRect(QRect(option.rect.left(), option.rect.top(),
                                   3, option.rect.height()), PLAYING_EDGE)
        # Separator under the seam strip, closing the block off from the next
        # track. The stylesheet's item border never draws once paint() is
        # overridden, so it is drawn here.
        painter.setPen(QPen(ROW_LINE, 1))
        painter.drawLine(option.rect.left(), option.rect.bottom(),
                         option.rect.right(), option.rect.bottom())

        if index.column() == COL_KEY and t is not None and t.resolved:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            chip = upper.adjusted(6, 5, -6, -5)
            if t.unverified:
                # Hollow chip: the colour is a claim, not a measurement.
                pen = QPen(QColor(t.colour()), 1)
                pen.setStyle(Qt.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(chip, 2, 2)
                f = QFont(painter.font())
                f.setBold(True)
                f.setPointSize(9)
                painter.setFont(f)
                painter.setPen(QPen(QColor(t.colour())))
                painter.drawText(chip, Qt.AlignCenter, t.key)
                painter.restore()
                return
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t.colour()))
            painter.drawRoundedRect(chip, 2, 2)
            f = QFont(painter.font())
            f.setBold(True)
            f.setPointSize(9)
            painter.setFont(f)
            painter.setPen(QPen(QColor("#101216")))
            painter.drawText(chip, Qt.AlignCenter, t.key)
            painter.restore()
            return

        option.rect = upper
        # The row background is already painted above; drop the selected flag
        # so the style does not repaint its own over the top of it.
        option.state &= ~QStyle.State_Selected
        super().paint(painter, option, index)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(QRect(
            option.rect.x(), option.rect.y(),
            option.rect.width(), option.rect.height() - SEAM_H
        ))


class TrackTable(QTableWidget):
    reordered = Signal(int, int)        # from_row, to_row
    edited = Signal(int, str, str)      # row, field ("bpm"|"key"), new text
    deleteRequested = Signal(list)      # rows
    dragFinished = Signal()             # re-sync the view after Qt's teardown
    playRequested = Signal(int)         # row
    previewRequested = Signal(int)      # row
    crossCheckRequested = Signal(int)   # row
    copyRequested = Signal(list)        # rows -> "Artist - Title"
    earCheckToggled = Signal(int)       # row: seam into the NEXT track

    def __init__(self, parent=None):
        super().__init__(0, len(HEADERS), parent)
        self._tracks: list[Track] = []
        self._seams: list[Seam] = []
        self._felt = False
        self._loading = False
        self._drop_row = -1
        self._playing_row = -1

        self.setHorizontalHeaderLabels(HEADERS)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(ROW_H)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDragDropOverwriteMode(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setItemDelegate(CellDelegate(self, self))
        self.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.SelectedClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )

        h = self.horizontalHeader()
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setSectionResizeMode(COL_N, QHeaderView.Fixed)
        h.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        h.setSectionResizeMode(COL_ARTIST, QHeaderView.Interactive)
        h.setSectionResizeMode(COL_BPM, QHeaderView.Fixed)
        h.setSectionResizeMode(COL_KEY, QHeaderView.Fixed)
        self.setColumnWidth(COL_N, 42)
        self.setColumnWidth(COL_ARTIST, 190)
        self.setColumnWidth(COL_BPM, 70)
        self.setColumnWidth(COL_KEY, 62)

        self.itemChanged.connect(self._on_item_changed)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos):
        row = self.rowAt(pos.y())
        if row < 0 or row >= len(self._tracks):
            return
        t = self._tracks[row]
        m = QMenu(self)
        a = m.addAction("Play from here")
        a.setEnabled(bool(t.uri))
        a.triggered.connect(lambda: self.playRequested.emit(row))
        a = m.addAction("Preview transition into next")
        a.setEnabled(row + 1 < len(self._tracks))
        a.triggered.connect(lambda: self.previewRequested.emit(row))
        m.addSeparator()
        a = m.addAction("Cross-check BPM && key on the web")
        a.triggered.connect(lambda: self.crossCheckRequested.emit(row))
        a = m.addAction("Unmark ear-checked transition"
                        if row < len(self._seams) and self._seams[row].checked
                        else "Mark transition into next as ear-checked")
        a.setEnabled(row + 1 < len(self._tracks))
        a.triggered.connect(lambda: self.earCheckToggled.emit(row))
        m.addSeparator()
        a = m.addAction("Copy artist - title")
        a.triggered.connect(lambda: self.copyRequested.emit(self._sel_rows(row)))
        m.addSeparator()
        a = m.addAction("Remove from list")
        a.triggered.connect(lambda: self.deleteRequested.emit([row]))
        m.exec(self.viewport().mapToGlobal(pos))

    def _sel_rows(self, clicked: int) -> list:
        """Selected rows, or just the clicked one when it sits outside them.

        Right-clicking a row that is not part of the selection should act on
        that row, not on whatever happened to be highlighted elsewhere.
        """
        rows = sorted({i.row() for i in self.selectedIndexes()})
        return rows if clicked in rows else [clicked]

    def next_blank(self, after_row: int = -1, after_col: int = -1) -> tuple[int, int]:
        """Next missing BPM or key as (row, column); (-1, -1) when none left.

        Finishes the current row before moving on — filling a track's BPM should
        step to its key, not skip to the next track. Wraps around the end.
        """
        n = len(self._tracks)
        if not n:
            return -1, -1

        def blank_in(i: int, min_col: int) -> int:
            t = self._tracks[i]
            if t.bpm <= 0 and COL_BPM > min_col:
                return COL_BPM
            if t.n == 0 and COL_KEY > min_col:
                return COL_KEY
            return -1

        if 0 <= after_row < n:
            col = blank_in(after_row, after_col)
            if col >= 0:
                return after_row, col

        for step in range(1, n + 1):
            i = (after_row + step) % n
            col = blank_in(i, -1)
            if col >= 0:
                return i, col
        return -1, -1

    def edit_cell(self, row: int, col: int):
        item = self.item(row, col)
        if not item:
            return
        self.setCurrentItem(item)
        self.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        self.editItem(item)

    # ---------------- population ----------------

    def tracks(self) -> list[Track]:
        return self._tracks

    def playing_row(self) -> int:
        return self._playing_row

    def set_playing_row(self, row: int, follow: bool = True):
        """Mark the row Spotify is currently on. Scrolls to it only when it
        changes, so it never fights the user scrolling elsewhere."""
        if row == self._playing_row:
            return
        self._playing_row = row
        if follow and 0 <= row < self.rowCount():
            item = self.item(row, COL_TITLE)
            if item:
                self.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        self.viewport().update()

    def set_data(self, tracks: list[Track], seams: list[Seam], felt: bool):
        self._tracks = tracks
        self._seams = seams
        self._felt = felt
        self._loading = True
        try:
            sel = {i.row() for i in self.selectedIndexes()}
            self.setRowCount(len(tracks))
            for i, t in enumerate(tracks):
                self._fill_row(i, t)
            self.clearSelection()
            for r in sel:
                if r < len(tracks):
                    self.selectRow(r)
        finally:
            self._loading = False
        self.viewport().update()

    def _fill_row(self, i: int, t: Track):
        shown = felt_bpm(t.bpm) if self._felt else t.bpm
        halved = self._felt and t.bpm >= 130

        def mk(text, editable=False, align=Qt.AlignLeft | Qt.AlignVCenter):
            it = QTableWidgetItem(text)
            flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled
            if editable:
                flags |= Qt.ItemIsEditable
            it.setFlags(flags)
            it.setTextAlignment(align)
            return it

        n_item = mk(str(i + 1), align=Qt.AlignRight | Qt.AlignVCenter)
        n_item.setForeground(FAINT)
        self.setItem(i, COL_N, n_item)

        title = mk(t.title)
        if not t.resolved:
            title.setToolTip("No BPM/key yet — type them in, or re-run Fetch.")
        elif t.unverified:
            title.setToolTip(
                f"Provisional — scraped from {t.source.split(':', 1)[-1]} via web "
                f"search, not an audio analysis. Keys from this route matched a "
                f"known-good reference about 4 times in 10. Check it, then type "
                f"the value in to lock it."
            )
        elif t.low_confidence:
            title.setToolTip("Low-confidence analysis — worth checking against Serato.")
        self.setItem(i, COL_TITLE, title)

        art = mk(t.artist)
        art.setForeground(DIM)
        self.setItem(i, COL_ARTIST, art)

        bpm_txt = f"{round(shown)}" if t.bpm > 0 else ""
        bpm = mk(bpm_txt, editable=True, align=Qt.AlignRight | Qt.AlignVCenter)
        if halved:
            bpm.setForeground(WARN)
        if self._felt and t.bpm > 0:
            bpm.setToolTip(f"Reported {round(t.bpm)}")
        self.setItem(i, COL_BPM, bpm)

        # The chip and the unresolved tint are painted by CellDelegate.
        self.setItem(i, COL_KEY, mk(t.key, editable=True, align=Qt.AlignCenter))

    # ---------------- editing ----------------

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._loading:
            return
        row, col = item.row(), item.column()
        if col == COL_BPM:
            self.edited.emit(row, "bpm", item.text())
        elif col == COL_KEY:
            self.edited.emit(row, "key", item.text())

    def keyPressEvent(self, e):
        # Ctrl+C copies "Artist - Title". While a cell is being edited it has to
        # stay the ordinary text copy.
        if (e.key() == Qt.Key_C and e.modifiers() & Qt.ControlModifier
                and self.state() != QAbstractItemView.EditingState):
            rows = sorted({i.row() for i in self.selectedIndexes()})
            if rows:
                self.copyRequested.emit(rows)
                return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.state() != QAbstractItemView.EditingState:
            rows = sorted({i.row() for i in self.selectedIndexes()})
            if rows:
                self.deleteRequested.emit(rows)
                return
        super().keyPressEvent(e)

    # ---------------- drag reorder ----------------

    def startDrag(self, supported_actions):
        # Two Qt behaviours collide here and neither can be switched off:
        #
        #   * InternalMove refuses the drag unless MoveAction is among the
        #     possible actions, so MoveAction has to stay offered.
        #   * When the drag resolves to MoveAction, startDrag() calls
        #     clearOrRemove() and deletes the dragged rows from the view —
        #     after dropEvent has already rebuilt the table from the reordered
        #     list. Answering CopyAction in dropEvent does not reliably prevent
        #     this: QTableWidget's model does not advertise CopyAction, so Qt
        #     coerces the action back to MoveAction.
        #
        # So let Qt do whatever it likes, then re-sync the view from the track
        # list, which is the authoritative order.
        super().startDrag(supported_actions)
        self.dragFinished.emit()

    def _drop_target(self, y: int) -> int:
        """Row index the dragged track would land on, from a viewport y."""
        row = self.rowAt(y)
        if row < 0:
            return max(0, self.rowCount() - 1)
        r = self.visualRect(self.model().index(row, 0))
        if y > r.center().y():
            row = min(row + 1, self.rowCount() - 1)
        return row

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)        # keeps Qt's InternalMove gate happy
        if event.source() is self:
            self._drop_row = self._drop_target(event.position().toPoint().y())
            self.viewport().update()

    def dragLeaveEvent(self, event):
        self._drop_row = -1
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._drop_row = -1
        if event.source() is not self:
            event.ignore()
            return
        src_rows = sorted({i.row() for i in self.selectedIndexes()})
        if not src_rows:
            event.ignore()
            return
        drop_row = self._drop_target(event.position().toPoint().y())
        event.setDropAction(Qt.CopyAction)
        event.accept()
        self.reordered.emit(src_rows[0], drop_row)

    # ---------------- seam strip ----------------

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self._seams:
            return
        p = QPainter(self.viewport())
        f = QFont("Consolas")
        f.setPointSize(8)
        p.setFont(f)
        fm = p.fontMetrics()

        for i in range(min(len(self._seams), self.rowCount())):
            rect = self.visualRect(self.model().index(i, 0))
            if not rect.isValid() or rect.height() == 0:
                continue
            y = rect.bottom() - 3
            if y < 0 or y > self.viewport().height():
                continue
            s = self._seams[i]
            x = 46

            p.setPen(QPen(FAINT))
            p.drawText(x, y, "key")
            x += fm.horizontalAdvance("key ") + 2
            p.setPen(QPen(QColor(s.key.colour)))
            p.drawText(x, y, s.key.txt)
            x += fm.horizontalAdvance(s.key.txt) + 14

            p.setPen(QPen(FAINT))
            p.drawText(x, y, "tempo")
            x += fm.horizontalAdvance("tempo ") + 2
            p.setPen(QPen(QColor(s.tempo.colour)))
            p.drawText(x, y, s.tempo.txt)
            x += fm.horizontalAdvance(s.tempo.txt) + 6

            # The raw pair the label was computed from. The BPM column shows
            # felt, so without this the label can look wrong next to the
            # numbers on screen.
            if i + 1 < len(self._tracks):
                ta, tb = self._tracks[i], self._tracks[i + 1]
                if ta.bpm > 0 and tb.bpm > 0:
                    pair = "%d→%d" % (round(ta.bpm), round(tb.bpm))
                    p.setPen(QPen(FAINT))
                    p.drawText(x, y, pair)
                    x += fm.horizontalAdvance(pair) + 14

            if s.both:
                p.setPen(QPen(BAD))
                p.drawText(x, y, "← both off")
                x += fm.horizontalAdvance("← both off") + 14

            if s.checked:
                # Inline with the key/tempo readout, so one glance down the
                # left edge covers everything known about each seam.
                p.setPen(QPen(OKGREEN))
                p.drawText(x, y, "✓ ear-checked")

        self._paint_drop_line(p)
        p.end()

    def _paint_drop_line(self, p: QPainter):
        """Where the dragged track will land. Qt's own drop indicator is a
        hairline that disappears against this palette."""
        if self._drop_row < 0 or not self.rowCount():
            return
        row = min(self._drop_row, self.rowCount() - 1)
        r = self.visualRect(self.model().index(row, 0))
        if not r.isValid():
            return
        # Land above the target row, except at the very bottom of the list.
        y = r.top() if self._drop_row < self.rowCount() else r.bottom()
        w = self.viewport().width()

        pen = QPen(DROP_LINE, 2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(0, y, w, y)
        # End caps, so the line reads as an insertion point rather than a border.
        p.setBrush(DROP_LINE)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(2, y), 3, 3)
        p.drawEllipse(QPoint(w - 2, y), 3, 3)
