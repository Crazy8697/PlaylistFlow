"""The chart above the table. Height is tempo, colour is key.

Two modes:

  fit       every track the same width, whole playlist visible at once.
  timeline  each track as wide as it is long, so the set reads as elapsed time
            and you can see where the long stretches sit. Scrolls and zooms.

Hand-painted with QPainter — no charting library for something this simple.
The baseline sits below the minimum value rather than at zero; with a 60-185
range a zero baseline flattens every visible difference.

There is no waveform here and there cannot be: Spotify never exposes the audio,
and preview clips are gone. Everything drawn is derived from tempo, key and
duration, which are values we actually have.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget, QToolTip

from .domain import Track, Seam, felt_bpm

BG = QColor("#181B21")
EDGE = QColor("#2C313A")
INK = QColor("#E9E7E1")
FAINT = QColor("#5C636D")
BAD = QColor("#E8544F")
UNRESOLVED = QColor("#3D444F")
PLAYHEAD = QColor("#3FBFA8")
DROP_LINE = QColor("#3FBFA8")

GAP = 2
STRIP_GAP = 2         # whole pixels — keeps every gap identical
STRIP_H = 16
STRIP_PAD = 5
FLAG_R = 3
TOP_PAD = 14
RULER_H = 16

DEFAULT_DURATION_MS = 180_000      # when a manually added row has no length
MIN_PPS, MAX_PPS = 0.15, 12.0      # pixels per second


def clock(ms: int) -> str:
    s = int(ms // 1000)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class BarChart(QWidget):
    barClicked = Signal(int)
    reordered = Signal(int, int)      # from index, to index — same as the table

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks: list[Track] = []
        self._seams: list[Seam] = []
        self._felt = False
        self._sel = -1
        self._mode = "fit"
        self._pps = 1.0
        self._play_row = -1
        self._play_ms = 0
        self._drag_src = -1
        self._drag_dst = -1
        self._press_x = 0.0
        self._dragging = False
        self.setMinimumHeight(90)
        self.setMouseTracking(True)
        self.setAutoFillBackground(False)

    # ---------- data ----------

    def set_data(self, tracks: list[Track], seams: list[Seam], felt: bool, sel: int):
        self._tracks = tracks
        self._seams = seams
        self._felt = felt
        self._sel = sel
        self._resize_to_content()
        self.update()

    def set_playhead(self, row: int, position_ms: int):
        self._play_row = row
        self._play_ms = position_ms
        self.update()

    def set_mode(self, mode: str):
        self._mode = "time" if mode == "time" else "fit"
        self._resize_to_content()
        self.update()

    def mode(self) -> str:
        return self._mode

    def set_zoom(self, pps: float):
        self._pps = max(MIN_PPS, min(MAX_PPS, pps))
        self._resize_to_content()
        self.update()

    def zoom(self) -> float:
        return self._pps

    def fit_zoom(self, viewport_w: int) -> float:
        total = self._total_ms() / 1000.0
        return max(MIN_PPS, min(MAX_PPS, (viewport_w - 4) / total)) if total else 1.0

    # ---------- geometry ----------

    def _dur(self, t: Track) -> int:
        return t.duration_ms if t.duration_ms > 0 else DEFAULT_DURATION_MS

    def _total_ms(self) -> int:
        return sum(self._dur(t) for t in self._tracks)

    def _resize_to_content(self):
        if self._mode == "time" and self._tracks:
            w = int(self._total_ms() / 1000.0 * self._pps) + 4
            self.setMinimumWidth(max(w, 200))
        else:
            self.setMinimumWidth(0)

    def _shown(self, t: Track) -> float:
        return felt_bpm(t.bpm) if self._felt else t.bpm

    def _plot_h(self) -> float:
        return self.height() - STRIP_H - STRIP_PAD - TOP_PAD - RULER_H

    def _pps_for(self, mode: str) -> float:
        total_s = self._total_ms() / 1000.0
        if not total_s:
            return 1.0
        if mode == "time":
            return self._pps
        return (self.width() - 4) / total_s

    def _time_edges(self, pps: float, x0: float = 2.0) -> list[int]:
        """Cumulative pixel boundaries, snapped to whole pixels.

        Positions have to be rounded from the running total rather than each
        width rounded on its own: rounding widths independently makes the gaps
        come out one or two pixels at random, which is visible as a ragged strip.
        """
        edges = [int(round(x0))]
        acc = 0.0
        for t in self._tracks:
            acc += self._dur(t) / 1000.0
            edges.append(int(round(x0 + acc * pps)))
        return edges

    def _strip_rects(self) -> list[QRectF]:
        """The bottom strip is always a timeline — width is track length.

        In fit mode the whole set is squeezed into the window; in timeline mode
        it uses the same pixels-per-second as the bars above, so the two line up.
        """
        if not self._tracks or self._total_ms() <= 0:
            return []
        edges = self._time_edges(self._pps_for(self._mode))
        y = self.height() - STRIP_H - RULER_H
        out = []
        for i in range(len(self._tracks)):
            w = max(1, edges[i + 1] - edges[i] - STRIP_GAP)
            out.append(QRectF(edges[i], y, w, STRIP_H))
        return out

    def _scale(self) -> tuple[float, float]:
        vals = [self._shown(t) for t in self._tracks if t.resolved]
        if not vals:
            return 1.0, 0.0
        hi, lo = max(vals), min(vals)
        return hi, max(0.0, lo - (hi - lo) * 0.3)

    def _bar_rects(self) -> list[QRectF]:
        n = len(self._tracks)
        if not n:
            return []
        plot_h = self._plot_h()
        hi, floor = self._scale()

        widths, xs = [], []
        if self._mode == "time":
            # Same snapped boundaries as the strip, so the two rows line up.
            edges = self._time_edges(self._pps)
            for i in range(n):
                xs.append(float(edges[i]))
                widths.append(float(max(1, edges[i + 1] - edges[i] - STRIP_GAP)))
        else:
            bw = max(1.0, (self.width() - GAP * (n - 1)) / n)
            for i in range(n):
                xs.append(i * (bw + GAP))
                widths.append(bw)

        rects = []
        for t, x, w in zip(self._tracks, xs, widths):
            if not t.resolved:
                h = 3.0
            elif hi == floor:
                h = plot_h
            else:
                h = max(2.0, (self._shown(t) - floor) / (hi - floor) * plot_h)
            rects.append(QRectF(x, TOP_PAD + plot_h - h, w, h))
        return rects

    def _index_at(self, x: float, y: float = -1) -> int:
        # Clicking the strip should select by time position, not by bar.
        if y >= 0 and self._strip_rects() and y >= self._strip_rects()[0].top() - 2:
            for i, s in enumerate(self._strip_rects()):
                if s.left() <= x < s.right() + STRIP_GAP:
                    return i
        for i, r in enumerate(self._bar_rects()):
            if r.left() <= x < r.right():
                return i
        return -1

    def _flagged(self, i: int) -> bool:
        if i > 0 and i - 1 < len(self._seams) and self._seams[i - 1].both:
            return True
        return i < len(self._seams) and self._seams[i].both

    def _playhead_x(self) -> float | None:
        """Positioned on the strip, which is the timeline in both modes."""
        if self._play_row < 0 or self._play_row >= len(self._tracks):
            return None
        strips = self._strip_rects()
        if not strips:
            return None
        s = strips[self._play_row]
        dur = self._dur(self._tracks[self._play_row])
        frac = min(1.0, max(0.0, self._play_ms / dur)) if dur else 0.0
        return s.left() + (s.width() + STRIP_GAP) * frac

    # ---------- painting ----------

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), BG)

        rects = self._bar_rects()
        if not rects:
            p.setPen(QPen(FAINT))
            p.drawText(self.rect(), Qt.AlignCenter, "No tracks loaded")
            p.end()
            return

        strips = self._strip_rects()

        for i, (t, r) in enumerate(zip(self._tracks, rects)):
            col = QColor(t.colour()) if t.resolved else UNRESOLVED
            if self._dragging and i == self._drag_src:
                col.setAlpha(70)          # ghost the one being moved
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(col))
            p.drawRect(r)

            if i == self._sel:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(INK, 1))
                p.drawRect(r.adjusted(-1, -1, 0, 0))
            if i == self._play_row:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(PLAYHEAD, 1))
                p.drawRect(r.adjusted(-1, -1, 0, 0))

            if self._flagged(i):
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(BAD))
                p.drawEllipse(QPointF(r.center().x(), TOP_PAD - 7), FLAG_R, FLAG_R)

        # The strip is the timeline: real durations, always.
        for i, (t, s) in enumerate(zip(self._tracks, strips)):
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(t.colour()) if t.resolved else UNRESOLVED))
            p.drawRect(s)
            if i == self._sel:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(INK, 1))
                p.drawRect(s)

        self._paint_ruler(p)
        self._paint_drop_line(p, rects, strips)

        x = self._playhead_x()
        if x is not None and strips:
            top = strips[0].top() - 4
            p.setPen(QPen(PLAYHEAD, 2))
            p.drawLine(QPointF(x, top), QPointF(x, strips[0].bottom() + 2))
            p.setBrush(PLAYHEAD)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x, top), 3.5, 3.5)

        p.end()

    def _paint_drop_line(self, p: QPainter, rects, strips):
        """Where the dragged track will land, spanning bars and strip."""
        if not self._dragging or self._drag_dst < 0 or not rects:
            return
        i = min(self._drag_dst, len(rects) - 1)
        x = rects[i].left() - 1
        if self._drag_dst >= len(rects) - 1 and self._drag_src < self._drag_dst:
            x = rects[i].right() + 1
        bottom = (strips[0].bottom() + 2) if strips else self.height()
        pen = QPen(DROP_LINE, 2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(x, TOP_PAD - 10), QPointF(x, bottom))
        p.setBrush(DROP_LINE)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(x, TOP_PAD - 10), 3, 3)
        p.drawEllipse(QPointF(x, bottom), 3, 3)

    def _paint_ruler(self, p: QPainter):
        """Elapsed time into the set, under the strip."""
        total_ms = self._total_ms()
        if not total_ms:
            return
        total_s = total_ms / 1000.0
        pps = self._pps_for(self._mode)

        y = self.height() - RULER_H
        p.setPen(QPen(EDGE, 1))
        p.drawLine(0, y, self.width(), y)

        f = QFont("Consolas")
        f.setPointSize(8)
        p.setFont(f)

        # Coarsest spacing that still leaves ~70px between labels.
        step_s = 3600
        for cand in (30, 60, 120, 300, 600, 900, 1800, 3600):
            if cand * pps >= 70:
                step_s = cand
                break
        t = 0.0
        while t <= total_s:
            x = 2 + t * pps
            p.setPen(QPen(EDGE, 1))
            p.drawLine(QPointF(x, y), QPointF(x, y + 4))
            p.setPen(QPen(FAINT))
            p.drawText(QPointF(x + 3, y + 11), clock(int(t * 1000)))
            t += step_s

    # ---------- interaction ----------

    def sizeHint(self) -> QSize:
        return QSize(max(400, self.minimumWidth()), 170)

    def _drop_target(self, x: float) -> int:
        """Index the dragged track would land on — same convention the table
        uses, so both routes go through move_row unchanged."""
        rects = self._bar_rects()
        if not rects:
            return -1
        n = len(rects)
        if x < rects[0].left():
            return 0
        for i, r in enumerate(rects):
            if r.left() <= x < r.right() or (i == n - 1 and x >= r.left()):
                return min(i + 1, n - 1) if x > r.center().x() else i
        return n - 1

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self._press_x = e.position().x()
        self._drag_src = self._index_at(e.position().x(), e.position().y())
        self._dragging = False

    def mouseMoveEvent(self, e):
        if (e.buttons() & Qt.LeftButton) and self._drag_src >= 0:
            if not self._dragging and abs(e.position().x() - self._press_x) > 4:
                self._dragging = True
                self.setCursor(Qt.ClosedHandCursor)
            if self._dragging:
                self._drag_dst = self._drop_target(e.position().x())
                QToolTip.hideText()
                self.update()
                return
        self._hover(e)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self.unsetCursor()
        if self._dragging and self._drag_src >= 0 and self._drag_dst >= 0:
            if self._drag_dst != self._drag_src:
                self.reordered.emit(self._drag_src, self._drag_dst)
        elif self._drag_src >= 0:
            self.barClicked.emit(self._drag_src)
        self._drag_src = self._drag_dst = -1
        self._dragging = False
        self.update()

    def leaveEvent(self, e):
        QToolTip.hideText()
        super().leaveEvent(e)

    def wheelEvent(self, e):
        # Ctrl+wheel zooms the timeline; plain wheel scrolls the parent view.
        if self._mode == "time" and (e.modifiers() & Qt.ControlModifier):
            factor = 1.25 if e.angleDelta().y() > 0 else 1 / 1.25
            self.set_zoom(self._pps * factor)
            e.accept()
            return
        e.ignore()

    def _hover(self, e):
        i = self._index_at(e.position().x(), e.position().y())
        if 0 <= i < len(self._tracks):
            t = self._tracks[i]
            if t.resolved:
                txt = (f"{t.title} — {round(self._shown(t))} — {t.key}"
                       f"  ({clock(self._dur(t))})")
            else:
                txt = f"{t.title} — not resolved"
            QToolTip.showText(e.globalPosition().toPoint(), txt, self)
        else:
            QToolTip.hideText()
