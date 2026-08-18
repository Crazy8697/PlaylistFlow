"""Bulk track finder — paste a song list, get a URI block.

The handoff asked for a QTableWidget with rows "expandable to show the
candidates". A QTableWidget cannot nest rows, so this is a QTreeWidget: line
nodes at the top level, candidates as children. Same native-widget constraint,
the structure the job actually needs.

Year and duration are the columns that resolve the ambiguity — a 2011 original
and a 2025 re-release differ on one or both — so they are the ones highlighted.
Popularity is not shown: the search response does not carry the field.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QProgressBar, QTreeWidget, QTreeWidgetItem, QAbstractItemView, QSplitter,
    QWidget,
)

from .domain import Track
from .finder import (Line, Result, SearchWorker, parse_lines, artist_named,
                     norm, AUTO, REVIEW, NOTFOUND, DUP)
from .providers import Spotify

ACCENT = "#E8A93E"     # year / duration — the disambiguating fields
DIM = "#8C939D"
OK = "#5FBF6B"
BAD = "#E8544F"

COL_TRACK, COL_ARTIST, COL_ALBUM, COL_YEAR, COL_DUR, COL_NOTE = range(6)

PLACEHOLDER = ("Fighting Tears Wade Forster\n"
               "Stoic Faces Drayton Farley\n"
               "Tishomingo Zach Bryan\n"
               "\n"
               "One per line. Title then artist, no delimiter needed.\n"
               "A tab or \" - \" is used as an explicit split if present.")


class FinderDialog(QDialog):
    """Resolve a pasted list to track URIs, with review for anything uncertain."""

    send_to_playlist = Signal(list)     # list[Track], in input order

    def __init__(self, sp: Spotify, parent=None):
        super().__init__(parent)
        self.sp = sp
        self.worker: SearchWorker | None = None
        self.lines: list[Line] = []
        self.results: dict[int, Result] = {}
        self._groups: dict[str, QTreeWidgetItem] = {}
        self._syncing = False

        self.setWindowTitle("Find tracks in bulk")
        self.setMinimumSize(1040, 720)

        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Vertical)
        lay.addWidget(split, 1)

        # ---------------- input ----------------
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(QLabel("Paste your list — one track per line."))
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText(PLACEHOLDER)
        tl.addWidget(self.input, 1)
        split.addWidget(top)

        # ---------------- review ----------------
        bot = QWidget()
        bl = QVBoxLayout(bot)
        bl.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(
            ["Track", "Artist", "Album", "Year", "Length", "Why"])
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.tree.itemChanged.connect(self._item_changed)
        hdr = self.tree.header()
        hdr.resizeSection(COL_TRACK, 300)
        hdr.resizeSection(COL_ARTIST, 190)
        hdr.resizeSection(COL_ALBUM, 210)
        hdr.resizeSection(COL_YEAR, 60)
        hdr.resizeSection(COL_DUR, 70)
        bl.addWidget(self.tree, 1)
        split.addWidget(bot)
        split.setSizes([200, 520])

        # ---------------- progress ----------------
        row = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.hide()
        row.addWidget(self.bar, 1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.hide()
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)

        # ---------------- buttons ----------------
        row2 = QHBoxLayout()
        self.resolve_btn = QPushButton("Resolve list")
        self.resolve_btn.clicked.connect(self._resolve)
        row2.addWidget(self.resolve_btn)
        row2.addStretch(1)
        self.copy_btn = QPushButton("Copy URI block")
        self.copy_btn.clicked.connect(self._copy)
        self.copy_btn.setEnabled(False)
        row2.addWidget(self.copy_btn)
        self.send_btn = QPushButton("Send to playlist view")
        self.send_btn.clicked.connect(self._send)
        self.send_btn.setEnabled(False)
        row2.addWidget(self.send_btn)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row2.addWidget(close)
        lay.addLayout(row2)

    # ------------------------------------------------------------------
    # running
    # ------------------------------------------------------------------

    def _resolve(self):
        if self.worker and self.worker.isRunning():
            return
        self.lines = parse_lines(self.input.toPlainText())
        if not self.lines:
            self.msg.setText("Nothing to resolve — paste a list first.")
            return

        self.results.clear()
        self.tree.clear()
        self._groups.clear()
        self.copy_btn.setEnabled(False)
        self.send_btn.setEnabled(False)

        self.bar.setRange(0, len(self.lines))
        self.bar.setValue(0)
        self.bar.show()
        self.cancel_btn.show()
        self.resolve_btn.setEnabled(False)

        self.worker = SearchWorker(self.sp, self.lines, self)
        self.worker.progress.connect(self._progress)
        self.worker.resolved.connect(self._resolved)
        self.worker.message.connect(self.msg.setText)
        self.worker.done.connect(self._finished)
        self.worker.start()

    def _cancel(self):
        """Whatever resolved before the cancel is kept."""
        if self.worker:
            self.worker.stop()
        self.msg.setText("Cancelling — keeping what resolved so far.")

    def _progress(self, done: int, total: int, line: str):
        self.bar.setValue(done)
        self.bar.setFormat("%d of %d — %s" % (done, total, line[:60]) if line
                           else "%d of %d" % (done, total))

    def _resolved(self, idx: int, res: Result):
        self.results[idx] = res
        self._add_row(idx, res)

    def _finished(self):
        self.bar.hide()
        self.cancel_btn.hide()
        self.resolve_btn.setEnabled(True)
        n = sum(1 for r in self.results.values() if r.pick)
        self.copy_btn.setEnabled(n > 0)
        self.send_btn.setEnabled(n > 0)
        self._retitle_groups()
        self.msg.setText("%d of %d lines have a track selected." %
                         (n, len(self.results)))

    # ------------------------------------------------------------------
    # tree
    # ------------------------------------------------------------------

    GROUPS = (
        (REVIEW, "Needs review", True),
        (NOTFOUND, "Not found", True),
        (DUP, "Duplicate lines", False),
        (AUTO, "Auto-accepted", False),   # collapsed; spot-check via the arrow
    )

    def _group(self, status: str) -> QTreeWidgetItem:
        if status in self._groups:
            return self._groups[status]
        label, expand = next((l, e) for s, l, e in self.GROUPS if s == status)
        node = QTreeWidgetItem(self.tree, [label])
        f = node.font(0)
        f.setBold(True)
        node.setFont(0, f)
        node.setFirstColumnSpanned(True)
        node.setExpanded(expand)
        node.setFlags(Qt.ItemIsEnabled)
        self._groups[status] = node
        # Keep the groups in a stable order rather than order-of-arrival.
        order = [s for s, _, _ in self.GROUPS]
        self.tree.sortItems(-1, Qt.AscendingOrder)
        for s in order:
            if s in self._groups:
                n = self._groups[s]
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(n))
                self.tree.addTopLevelItem(n)
                n.setExpanded(next(e for st, _, e in self.GROUPS if st == s))
        return node

    def _retitle_groups(self):
        for status, label, _ in self.GROUPS:
            node = self._groups.get(status)
            if not node:
                continue
            n = sum(1 for r in self.results.values() if r.status == status)
            node.setText(0, "%s (%d)" % (label, n))

    def _add_row(self, idx: int, res: Result):
        self._syncing = True
        try:
            parent = QTreeWidgetItem(self._group(res.status))
            parent.setText(COL_TRACK, "%2d. %s" % (idx + 1, res.line.raw))
            parent.setText(COL_NOTE, res.note)
            parent.setForeground(COL_NOTE, QBrush(QColor(DIM)))
            parent.setData(0, Qt.UserRole, idx)

            if res.candidates:
                # Unchecking the line is how a line is skipped.
                parent.setFlags(parent.flags() | Qt.ItemIsUserCheckable)
                parent.setCheckState(0, Qt.Checked)
            else:
                parent.setForeground(COL_TRACK, QBrush(QColor(BAD)))

            qn = norm(res.line.title if res.line.explicit else res.line.raw)
            for i, c in enumerate(res.candidates):
                ch = QTreeWidgetItem(parent)
                ch.setText(COL_TRACK, c.name)
                if not artist_named(qn, c):
                    # The outlier flag: a credited artist the user never typed.
                    ch.setText(COL_NOTE, "artist not in your line")
                    for col in (COL_TRACK, COL_ARTIST, COL_NOTE):
                        ch.setForeground(col, QBrush(QColor(BAD)))
                ch.setText(COL_ARTIST, c.artists)
                ch.setText(COL_ALBUM, c.album)
                ch.setText(COL_YEAR, c.year)
                ch.setText(COL_DUR, c.duration)
                ch.setToolTip(COL_TRACK, c.uri + ("\nISRC " + c.isrc if c.isrc else ""))
                for col in (COL_YEAR, COL_DUR):
                    ch.setForeground(col, QBrush(QColor(ACCENT)))
                    f = ch.font(col)
                    f.setBold(True)
                    ch.setFont(col, f)
                ch.setFlags(ch.flags() | Qt.ItemIsUserCheckable)
                ch.setCheckState(0, Qt.Checked if i == res.chosen else Qt.Unchecked)
                ch.setData(0, Qt.UserRole, idx)
                ch.setData(1, Qt.UserRole, i)

            if res.status == AUTO and res.candidates:
                parent.setForeground(COL_TRACK, QBrush(QColor(OK)))
        finally:
            self._syncing = False

    def _item_changed(self, item: QTreeWidgetItem, column: int):
        """Radio behaviour: checking a candidate clears its siblings."""
        if self._syncing or column != 0:
            return
        idx = item.data(0, Qt.UserRole)
        if idx is None:
            return
        res = self.results.get(idx)
        if not res:
            return

        cand_i = item.data(1, Qt.UserRole)
        self._syncing = True
        try:
            if cand_i is None:
                # Parent toggled — that is the skip switch.
                res.skip = item.checkState(0) != Qt.Checked
            else:
                if item.checkState(0) == Qt.Checked:
                    parent = item.parent()
                    for j in range(parent.childCount()):
                        sib = parent.child(j)
                        if sib is not item:
                            sib.setCheckState(0, Qt.Unchecked)
                    res.chosen = cand_i
                    # Picking a candidate implies the line is wanted.
                    res.skip = False
                    parent.setCheckState(0, Qt.Checked)
                elif res.chosen == cand_i:
                    res.chosen = -1
        finally:
            self._syncing = False

        n = sum(1 for r in self.results.values() if r.pick)
        self.copy_btn.setEnabled(n > 0)
        self.send_btn.setEnabled(n > 0)
        self.msg.setText("%d of %d lines have a track selected." %
                         (n, len(self.results)))

    # ------------------------------------------------------------------
    # output
    # ------------------------------------------------------------------

    def _picked_in_order(self) -> list:
        """Input order, always — the paste into Spotify has to preserve it."""
        out = []
        for i in sorted(self.results):
            res = self.results[i]
            c = res.pick
            if c and c.uri:
                out.append(c)
        return out

    def _copy(self):
        picks = self._picked_in_order()
        if not picks:
            self.msg.setText("Nothing selected.")
            return
        QGuiApplication.clipboard().setText("\n".join(c.uri for c in picks))
        self.msg.setText("Copied %d URIs — paste straight into a Spotify "
                         "playlist, the order survives." % len(picks))

    def _send(self):
        picks = self._picked_in_order()
        if not picks:
            self.msg.setText("Nothing selected.")
            return
        tracks = [
            Track(title=c.name, artist=c.artists, uri=c.uri, isrc=c.isrc,
                  duration_ms=c.duration_ms, source="spotify")
            for c in picks
        ]
        self.send_to_playlist.emit(tracks)
        self.msg.setText("Sent %d tracks to the playlist view." % len(tracks))

    # ------------------------------------------------------------------

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        super().closeEvent(e)
