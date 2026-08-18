"""Transport bar — a remote control for the user's own Spotify client.

No audio passes through this app. Spotify only permits playback from their own
clients and SDKs, so this drives whatever Spotify instance the user already has
running. Needs Premium and an active device.

The one feature here that Spotify's own client cannot do is the transition
preview: cue the last N seconds of one track and let the next start, so a seam
can be heard rather than inferred from two numbers.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QSlider, QSpinBox,
)

from .artwork import remote_pixmap

PREVIEW_TAIL_DEFAULT = 20      # seconds of the outgoing track
ART = 44                       # now-playing cover, square


def ms_to_clock(ms: int) -> str:
    if ms <= 0:
        return "0:00"
    s = int(ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


class PlayerBar(QWidget):
    playPauseClicked = Signal()
    prevClicked = Signal()
    nextClicked = Signal()
    previewClicked = Signal(int)      # tail seconds
    seekRequested = Signal(int)       # ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration = 0
        self._dragging = False

        # Two rows: what is playing and the transport on top, the scrubber and
        # the preview controls underneath. One long row pushed the seek bar and
        # the preview button far away from the buttons they belong with.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)

        # Cover of whatever is playing. Decorative, but it also makes it
        # obvious at a glance that the transport is bound to a live device.
        self.art = QLabel()
        self.art.setFixedSize(ART, ART)
        self.art.setObjectName("art")
        self.art.setScaledContents(False)
        top.addWidget(self.art)
        self._art_url = ""

        self.now = QLabel("Nothing playing")
        self.now.setObjectName("now")
        self.now.setMinimumWidth(180)
        top.addWidget(self.now, 1)

        self.btn_prev = QPushButton("◀◀")
        self.btn_prev.setFixedWidth(44)
        self.btn_prev.clicked.connect(self.prevClicked)
        top.addWidget(self.btn_prev)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(44)
        self.btn_play.clicked.connect(self.playPauseClicked)
        top.addWidget(self.btn_play)

        self.btn_next = QPushButton("▶▶")
        self.btn_next.setFixedWidth(44)
        self.btn_next.clicked.connect(self.nextClicked)
        top.addWidget(self.btn_next)

        outer.addLayout(top)

        bot = QHBoxLayout()
        bot.setSpacing(8)

        self.pos = QLabel("0:00")
        self.pos.setObjectName("clock")
        bot.addWidget(self.pos)

        self.bar = QSlider(Qt.Horizontal)
        self.bar.setRange(0, 1000)
        self.bar.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self.bar.sliderReleased.connect(self._released)
        bot.addWidget(self.bar, 1)

        self.dur = QLabel("0:00")
        self.dur.setObjectName("clock")
        bot.addWidget(self.dur)

        self.btn_preview = QPushButton("Preview transition")
        self.btn_preview.setToolTip(
            "Play the end of the selected track straight into the next one, so "
            "the seam can be heard rather than read off two numbers.")
        self.btn_preview.clicked.connect(
            lambda: self.previewClicked.emit(self.tail.value()))
        bot.addWidget(self.btn_preview)

        self.tail = QSpinBox()
        self.tail.setRange(5, 60)
        self.tail.setValue(PREVIEW_TAIL_DEFAULT)
        self.tail.setSuffix(" s")
        self.tail.setFixedWidth(64)
        self.tail.setToolTip("How much of the outgoing track to play.")
        bot.addWidget(self.tail)

        outer.addLayout(bot)

    def _released(self):
        self._dragging = False
        if self._duration > 0:
            self.seekRequested.emit(
                int(self._duration * self.bar.value() / 1000))

    def set_art(self, url: str):
        """Only touches the pixmap when the URL actually changes -- this is
        called on a two-second poll."""
        if url == self._art_url:
            return
        self._art_url = url
        # 2px under the widget so the 1px border stays visible all round.
        pm = remote_pixmap(url, ART - 2) if url else None
        if pm and not pm.isNull():
            self.art.setPixmap(pm)
        else:
            self.art.clear()

    def set_state(self, playing: bool, title: str, artist: str,
                  position_ms: int, duration_ms: int, art_url: str = ""):
        self.set_art(art_url)
        self.btn_play.setText("❚❚" if playing else "▶")
        self.now.setText(f"{title} — {artist}" if title else "Nothing playing")
        self._duration = duration_ms
        self.pos.setText(ms_to_clock(position_ms))
        self.dur.setText(ms_to_clock(duration_ms))
        if not self._dragging:
            self.bar.setValue(
                int(1000 * position_ms / duration_ms) if duration_ms else 0)

    def set_offline(self, msg: str = "Spotify not running"):
        self.set_art("")
        self.btn_play.setText("▶")
        self.now.setText(msg)
        self.pos.setText("0:00")
        self.dur.setText("0:00")
        self._duration = 0
        if not self._dragging:
            self.bar.setValue(0)
