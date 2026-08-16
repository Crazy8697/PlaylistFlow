"""Camelot wheel reference, ported from the harmonic-mixing prototype.

Inner ring is minor (A), outer is major (B). Selecting a key lights the three
safe moves and the two diagonals.

The diagonal — one step around plus a letter flip — is not on the standard
compatibility list. It is here because it works, and it gets its own colour
rather than being folded in with the safe moves.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy,
)

from .domain import HUE, valid_key

SAFE = QColor("#5FBF6B")
DIAG = QColor("#E8A93E")
INK = QColor("#E9E7E1")
FAINT = QColor("#5C636D")
EDGE = QColor("#2C313A")
BG = QColor("#101216")


def wrap(n: int) -> int:
    return (n - 1) % 12 + 1


def safe_moves(n: int, letter: str) -> list[str]:
    """One step either way on the same ring, plus the relative key."""
    other = "B" if letter == "A" else "A"
    return [f"{wrap(n - 1)}{letter}", f"{wrap(n + 1)}{letter}", f"{n}{other}"]


def diagonals(n: int, letter: str) -> list[str]:
    other = "B" if letter == "A" else "A"
    return [f"{wrap(n - 1)}{other}", f"{wrap(n + 1)}{other}"]


class CamelotWheel(QWidget):
    keyPicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._key = "8A"
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(380, 380)

    def key(self) -> str:
        return self._key

    def set_key(self, key: str):
        if valid_key(key or ""):
            self._key = key.upper()
            self.update()

    # ---------- geometry ----------

    def _metrics(self):
        side = min(self.width(), self.height())
        cx, cy = self.width() / 2, self.height() / 2
        r_out = side * 0.41
        r_in = side * 0.285
        knob = side * 0.052
        return cx, cy, r_out, r_in, knob

    def _pos(self, n: int, r: float) -> QPointF:
        cx, cy, *_ = self._metrics()
        a = (n - 1) * math.pi / 6
        return QPointF(cx + r * math.sin(a), cy - r * math.cos(a))

    def _knobs(self):
        _, _, r_out, r_in, knob = self._metrics()
        for n in range(1, 13):
            for letter in ("B", "A"):
                r = r_out if letter == "B" else r_in
                yield f"{n}{letter}", n, letter, self._pos(n, r), knob

    # ---------- painting ----------

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), BG)

        cx, cy, r_out, r_in, knob = self._metrics()
        p.setPen(QPen(EDGE, 1))
        p.setBrush(Qt.NoBrush)
        for r in (r_out, r_in):
            p.drawEllipse(QPointF(cx, cy), r, r)

        n = int(self._key[:-1])
        letter = self._key[-1]
        safe = set(safe_moves(n, letter))
        diag = set(diagonals(n, letter))

        f = QFont("Consolas")
        f.setPointSizeF(max(7.0, knob * 0.62))
        f.setBold(True)
        p.setFont(f)

        for key, kn, kl, pos, r in self._knobs():
            colour = QColor(HUE[kn - 1])
            if key == self._key:
                ring, width, alpha = INK, 3.0, 255
            elif key in safe:
                ring, width, alpha = SAFE, 2.5, 235
            elif key in diag:
                ring, width, alpha = DIAG, 2.5, 215
            else:
                ring, width, alpha = EDGE, 1.0, 40
            colour.setAlpha(alpha)

            p.setBrush(QBrush(colour))
            p.setPen(QPen(ring, width))
            p.drawEllipse(pos, r, r)

            label = QColor("#101216")
            label.setAlpha(alpha)
            p.setPen(QPen(label))
            p.drawText(QRectF(pos.x() - r, pos.y() - r, r * 2, r * 2),
                       Qt.AlignCenter, key)

        p.setPen(QPen(FAINT))
        f2 = QFont("Segoe UI")
        f2.setPointSize(8)
        p.setFont(f2)
        p.drawText(QRectF(cx - 70, cy - 18, 140, 16), Qt.AlignCenter,
                   "INNER · MINOR")
        p.drawText(QRectF(cx - 70, cy + 2, 140, 16), Qt.AlignCenter,
                   "OUTER · MAJOR")
        p.end()

    # ---------- interaction ----------

    def _hit(self, x: float, y: float) -> str:
        for key, _, _, pos, r in self._knobs():
            if (x - pos.x()) ** 2 + (y - pos.y()) ** 2 <= (r * 1.15) ** 2:
                return key
        return ""

    def mousePressEvent(self, e):
        key = self._hit(e.position().x(), e.position().y())
        if key:
            self.set_key(key)
            self.keyPicked.emit(key)

    def mouseMoveEvent(self, e):
        hit = self._hit(e.position().x(), e.position().y())
        self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)


class KeyWheelDialog(QDialog):
    """Non-modal, so it can sit open and follow the selection in the table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Camelot wheel")
        self.setMinimumSize(430, 560)
        self.setModal(False)

        lay = QVBoxLayout(self)

        self.following = QLabel("")
        self.following.setWordWrap(True)
        self.following.setStyleSheet("background: transparent; color: #8C939D;")
        lay.addWidget(self.following)

        self.wheel = CamelotWheel()
        self.wheel.keyPicked.connect(lambda k: self._refresh(k, manual=True))
        lay.addWidget(self.wheel, 1)

        self.now = QLabel("")
        self.now.setStyleSheet("background: transparent;")
        lay.addWidget(self.now)

        self.safe = QLabel("")
        self.safe.setWordWrap(True)
        self.safe.setStyleSheet("background: transparent;")
        lay.addWidget(self.safe)

        self.diag = QLabel("")
        self.diag.setWordWrap(True)
        self.diag.setStyleSheet("background: transparent;")
        lay.addWidget(self.diag)

        note = QLabel(
            "<span style='color:#5C636D;font-size:11px'>Diagonals are one step "
            "around plus a letter flip. Not on the standard list — a bigger "
            "step that reads as a lift rather than a blend.</span>")
        note.setWordWrap(True)
        note.setStyleSheet("background: transparent;")
        lay.addWidget(note)

        self._refresh("8A")

    def follow(self, key: str, label: str = ""):
        """Point the wheel at the selected track's key."""
        if not valid_key(key or ""):
            self.following.setText(
                f"{label} — no key yet." if label else "No key on that track.")
            return
        self.following.setText(f"Following: {label}" if label else "")
        self.wheel.set_key(key)
        self._refresh(key)

    def _refresh(self, key: str, manual: bool = False):
        if manual:
            self.following.setText("Picked by hand — select a track to follow again.")
        n, letter = int(key[:-1]), key[-1]
        colour = HUE[n - 1]
        self.now.setText(
            f"<span style='font-family:Consolas;font-size:26px;font-weight:600;"
            f"color:{colour}'>{key}</span>"
            f"<span style='color:#8C939D'> &nbsp; "
            f"{'minor' if letter == 'A' else 'major'}</span>")

        def chips(keys, colour_hex):
            out = []
            for k in keys:
                kn = int(k[:-1])
                out.append(
                    f"<span style='font-family:Consolas;font-size:14px;"
                    f"color:{HUE[kn - 1]}'>&nbsp;{k}&nbsp;</span>")
            return (f"<span style='color:{colour_hex};font-size:11px'>"
                    f"{'&nbsp;·&nbsp;'.join(out)}</span>")

        self.safe.setText(
            "<span style='color:#5FBF6B;font-size:11px'>SAFE MOVES</span><br>"
            + chips(safe_moves(n, letter), "#5FBF6B"))
        self.diag.setText(
            "<span style='color:#E8A93E;font-size:11px'>DIAGONALS</span><br>"
            + chips(diagonals(n, letter), "#E8A93E"))
