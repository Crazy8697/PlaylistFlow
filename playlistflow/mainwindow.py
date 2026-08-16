"""Main window."""

from __future__ import annotations

import copy
import time

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import (QAction, QKeySequence, QGuiApplication,
                           QDesktopServices, QShortcut)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QSplitter, QPlainTextEdit,
    QMessageBox, QFileDialog, QInputDialog, QDialog, QDialogButtonBox,
    QGroupBox, QFormLayout, QApplication, QAbstractItemView, QSplitter,
    QScrollArea,
)

from .domain import Track, seams, summary, valid_key, felt_bpm
from .providers import Spotify, FreqBlog, GetSongBPM, ProviderError, Features
from .auth import SpotifyAuth, AuthError
from .keys import clean_title, primary_artist
from .store import Store
from pathlib import Path

from . import __version__, __url__
from .config import Prefs, load_env, missing_required
from .settings import SettingsDialog
from .chart import BarChart
from .table import TrackTable, COL_BPM, COL_KEY
from .spinner import Spinner
from .player import PlayerBar
from .brand import spotify_icon, spotify_pixmap, icon_size
from .websearch import BraveLookup

UNDO_CAP = 40
AUTOSAVE_MS = 1500


# --------------------------------------------------------------------------
# Fetch worker
# --------------------------------------------------------------------------

class FetchWorker(QThread):
    resolved = Signal(int, object)   # index, Features
    message = Signal(str)
    done = Signal()

    def __init__(self, fb: FreqBlog, gs: GetSongBPM, web: BraveLookup,
                 jobs: list[tuple[int, Track]], parent=None):
        super().__init__(parent)
        self.fb = fb
        self.gs = gs
        self.web = web
        self.jobs = jobs
        self._stop = False
        self._got = 0

    def stop(self):
        self._stop = True

    # -- helpers ---------------------------------------------------------

    def _sleep(self, seconds: int) -> bool:
        for _ in range(seconds):
            if self._stop:
                return False
            time.sleep(1)
        return True

    def _emit(self, idx: int, feat: Features, source: str):
        feat.source = source
        self._got += 1
        self.resolved.emit(idx, feat)

    def _bulk_pass(self, jobs, build, source):
        """Run jobs through /bulk. Returns (pending, missed)."""
        pending, missed = [], []
        for start in range(0, len(jobs), 50):
            if self._stop:
                return pending, missed + jobs[start:]
            chunk = jobs[start:start + 50]
            try:
                rows = self.fb.bulk([build(t) for _, t in chunk])
            except ProviderError as e:
                self.message.emit(str(e))
                missed.extend(chunk)
                continue
            for (idx, trk), row in zip(chunk, rows):
                feat = FreqBlog.features_from_row(row)
                if feat.pending:
                    pending.append((idx, trk))
                elif feat.terminal or not (feat.bpm or feat.camelot):
                    missed.append((idx, trk))
                else:
                    self._emit(idx, feat, source)
        return pending, missed

    # -- main ------------------------------------------------------------

    def run(self):
        total = len(self.jobs)

        remaining = self.jobs

        def full(t: Track) -> dict:
            item = {"track": t.title}
            if t.artist:
                item["artist"] = t.artist
            if t.isrc:
                item["isrc"] = t.isrc
            return item

        # Pass 1 — ISRC + name together.
        self.message.emit(f"Looking up {len(remaining)} track(s)…")
        pending, missed = self._bulk_pass(remaining, full, "freqblog")

        # Pass 2 — re-poll whatever got queued for on-demand analysis (~15s each).
        rounds = 0
        while pending and rounds < 5 and not self._stop:
            rounds += 1
            self.message.emit(
                f"{len(pending)} being analysed by FreqBlog — waiting (round {rounds})…")
            if not self._sleep(20):
                break
            still, gone = self._bulk_pass(pending, full, "freqblog")
            pending, missed = still, missed + gone

        missed += pending  # never resolved in the time we allowed

        # Pass 3 — ISRC alone. An exact key; catches names that matched wrongly.
        if missed and not self._stop:
            have_isrc = [(i, t) for i, t in missed if t.isrc]
            if have_isrc:
                self.message.emit(f"Retrying {len(have_isrc)} by ISRC…")
                still = []
                for idx, trk in have_isrc:
                    if self._stop:
                        break
                    try:
                        feat = self.fb.lookup_isrc(trk.isrc, wait=8)
                    except ProviderError as e:
                        self.message.emit(str(e))
                        still.append((idx, trk))
                        continue
                    if feat.bpm or feat.camelot:
                        self._emit(idx, feat, "freqblog")
                    else:
                        still.append((idx, trk))
                missed = still + [(i, t) for i, t in missed if not t.isrc]

        # Pass 4 — cleaned title / first artist only.
        if missed and not self._stop:
            retry = []
            for idx, trk in missed:
                ct = clean_title(trk.title)
                pa = primary_artist(trk.artist)
                if ct or (pa and pa != trk.artist):
                    retry.append((idx, trk))
            if retry:
                self.message.emit(f"Retrying {len(retry)} with cleaned titles…")

                def cleaned(t: Track) -> dict:
                    return {"track": clean_title(t.title) or t.title,
                            "artist": primary_artist(t.artist) or t.artist}

                _, still = self._bulk_pass(retry, cleaned, "freqblog")
                done_ids = {i for i, _ in retry} - {i for i, _ in still}
                missed = [(i, t) for i, t in missed if i not in done_ids]

        # Pass 5 — GetSongBPM. Thin coverage here, but free and already keyed.
        if missed and not self._stop and self.gs.api_key:
            self.message.emit(f"Trying GetSongBPM for the last {len(missed)}…")
            still = []
            for idx, trk in missed:
                if self._stop:
                    break
                feat = self.gs.lookup(trk.title, trk.artist)
                if feat.bpm or feat.camelot:
                    self._emit(idx, feat, "getsongbpm")
                else:
                    still.append((idx, trk))
            missed = still

        # Pass 6 — web search. Fills real gaps, but measured against known-good
        # values its keys were right about 4 times in 10, so everything from
        # here is marked unverified rather than trusted.
        if missed and not self._stop and self.web.api_key:
            self.message.emit(f"Searching the web for the last {len(missed)}…")
            still = []
            for idx, trk in missed:
                if self._stop:
                    break
                h = self.web.lookup(trk.title, trk.artist)
                if h.bpm or h.camelot:
                    self._emit(idx, Features(bpm=h.bpm, camelot=h.camelot),
                               "web:" + ",".join(s.split(".")[0] for s in h.sources))
                else:
                    still.append((idx, trk))
            missed = still

        if missed:
            self.message.emit(
                f"Fetched {self._got} of {total}. {len(missed)} not found anywhere "
                f"— type those in.")
        else:
            self.message.emit(f"Fetched {self._got} of {total}.")
        self.done.emit()


# --------------------------------------------------------------------------
# About
# --------------------------------------------------------------------------

class SignInDialog(QDialog):
    """Spotify sign-in without a callback listener.

    The redirect lands on a dead 127.0.0.1 URL the browser can't load. The user
    copies that URL out of the address bar and pastes it here.
    """

    def __init__(self, auth: SpotifyAuth, parent=None):
        super().__init__(parent)
        self.auth = auth
        self.setWindowTitle("Sign in to Spotify")
        self.setMinimumWidth(560)

        lay = QVBoxLayout(self)
        lab = QLabel(
            "<p>Spotify no longer lets an app read playlist contents without a "
            "signed-in user, so this is a one-time sign-in.</p>"
            "<ol style='margin-left:-18px'>"
            "<li>Click <b>Open Spotify</b> — your browser opens the login page.</li>"
            "<li>Approve the request.</li>"
            "<li>The browser will land on a page that <b>fails to load</b>. "
            "That is expected — nothing is listening on that address.</li>"
            "<li>Copy the whole URL from the address bar and paste it below.</li>"
            "</ol>"
        )
        lab.setWordWrap(True)
        lay.addWidget(lab)

        b = QPushButton("Open Spotify")
        b.clicked.connect(self._open)
        lay.addWidget(b)

        self.paste = QLineEdit()
        self.paste.setPlaceholderText("http://127.0.0.1:8888/callback?code=…")
        lay.addWidget(self.paste)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._finish)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _open(self):
        try:
            url = self.auth.begin()
        except AuthError as e:
            self.msg.setText(f"<span style='color:#E8544F'>{e}</span>")
            return
        QDesktopServices.openUrl(QUrl(url))
        self.msg.setText("Browser opened. Paste the URL it lands on below.")

    def _finish(self):
        try:
            self.auth.complete(self.paste.text())
        except AuthError as e:
            self.msg.setText(f"<span style='color:#E8544F'>{e}</span>")
            return
        self.accept()


class AboutDialog(QDialog):
    """Carries the attribution backlinks. GetSongBPM require a visible link
    and suspend accounts without one."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Playlist Flow")
        self.setMinimumWidth(430)
        lay = QVBoxLayout(self)
        lab = QLabel(
            "<h3 style='margin-bottom:2px'>Playlist Flow</h3>"
            f"<p style='color:#5C636D;margin-top:0'>Version {__version__}</p>"
            "<p style='color:#8C939D'>Harmonic and tempo sequencing for playlists.</p>"
            "<p>Built by <a style='color:#3FA8D9' href='https://darkrelay.net'>"
            "darkrelay.net</a> &nbsp;·&nbsp; "
            f"<a style='color:#3FA8D9' href='{__url__}'>Crazy8697 on GitHub</a></p>"
            "<hr style='border:none;border-top:1px solid #2C313A'>"
            "<p>BPM and musical key data by "
            "<a style='color:#3FA8D9' href='https://freqblog.com'>FreqBlog</a>.</p>"
            "<p>Additional BPM data by "
            "<a style='color:#3FA8D9' href='https://getsongbpm.com'>GetSongBPM</a>.</p>"
            "<p>Playlist and track metadata from "
            "<a style='color:#3FA8D9' href='https://spotify.com'>Spotify</a>.</p>"
            "<p style='color:#5C636D;font-size:11px'>Felt BPM halves anything at 130 or "
            "above — in trap-influenced music the snare lands on 3 rather than 2 and 4, "
            "so a 140 reads as 70.</p>"
        )
        lab.setOpenExternalLinks(True)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Playlist Flow {__version__}")
        self.resize(1280, 860)

        self.env = load_env()
        self.prefs = Prefs()
        self.tracks: list[Track] = []
        self.undo_stack: list[list[Track]] = []
        self.felt = self.prefs.felt
        self.current_name = ""
        self.current_pid = ""          # Spotify playlist id, when it came from there
        self.worker: FetchWorker | None = None
        self._refreshing_spotify = False
        self._sort_field = ""
        self._sort_desc = False

        self.auth = SpotifyAuth(self.env.get("SPOTIFY_CLIENT_ID", ""), self.prefs)
        self.spotify = Spotify(self.auth)
        self.freqblog = FreqBlog(self.env.get("FREQBLOG_API_KEY", ""))
        self.getsongbpm = GetSongBPM(self.env.get("GETSONGBPM_API_KEY", ""))
        self.web = BraveLookup(self.env.get("BRAVE_API_KEY", ""))

        self.store: Store | None = None
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(AUTOSAVE_MS)
        self._autosave.timeout.connect(self._write_auto)

        # Transport polling. Spotify has no push channel, so the bar is driven
        # by polling — slow when idle, quicker while something is playing.
        self._last_player_state = None
        self._poll = QTimer(self)
        self._poll.setInterval(2000)
        self._poll.timeout.connect(self.poll_player)

        # Coalesces table/chart redraws while results stream in.
        self._live = QTimer(self)
        self._live.setSingleShot(True)
        self._live.setInterval(200)
        self._live.timeout.connect(lambda: self.refresh(keep_undo=True))

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._restore_layout()
        QTimer.singleShot(0, self._start)

    def _start(self):
        self._first_run()
        self._ensure_storage()

    # ---------------- ui ----------------

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer_l = QHBoxLayout(root)
        outer_l.setContentsMargins(10, 10, 10, 10)
        outer_l.setSpacing(0)
        # Everything sits in splitters so panes can be resized; the sizes are
        # remembered between runs.
        self.hsplit = QSplitter(Qt.Horizontal)
        outer_l.addWidget(self.hsplit)
        outer = self.hsplit

        # sidebar
        side = QWidget()
        side.setMinimumWidth(150)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        # Same spacing as the main column, or the sidebar's list sits a few
        # pixels higher than the chart next to it.
        sl.setSpacing(9)

        head = QHBoxLayout()
        head.setSpacing(6)
        mark = QLabel()
        mark.setPixmap(spotify_pixmap(15))
        head.addWidget(mark)
        head.addWidget(QLabel("SPOTIFY"))
        head.addStretch(1)
        b = QPushButton("Sync")
        b.setToolTip(
            "Re-read the loaded playlist from Spotify.\n\n"
            "Tracks added there are appended, tracks removed there are removed "
            "here, and everything else keeps the order and the BPM/key it "
            "already has.")
        b.clicked.connect(self.sync_playlist)
        head.addWidget(b)
        # Match the main button row's height exactly, so the playlist list and
        # the chart below start on the same line.
        self.sp_head = head
        sl.addLayout(head)

        self.sp_list = QListWidget()
        self.sp_list.itemDoubleClicked.connect(lambda _: self.load_from_spotify())
        sl.addWidget(self.sp_list, 1)
        row = QHBoxLayout()
        b = QPushButton("Load")
        b.clicked.connect(self.load_from_spotify)
        row.addWidget(b)
        b = QPushButton("Refresh")
        b.clicked.connect(self.refresh_spotify)
        row.addWidget(b)
        sl.addLayout(row)

        sl.addSpacing(8)
        sl.addWidget(QLabel("SAVED PLAYLISTS"))
        self.saved_list = QListWidget()
        self.saved_list.itemDoubleClicked.connect(lambda _: self.load_saved())
        sl.addWidget(self.saved_list, 1)
        for text, slot in (
            ("Load", self.load_saved),
            ("Rename", self.rename_saved),
            ("Delete", self.delete_saved),
            ("Delete all", self.delete_all_saved),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            sl.addWidget(b)
        b = QPushButton("Change folder…")
        b.clicked.connect(self.choose_storage)
        sl.addWidget(b)
        outer.addWidget(side)

        # main column
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(9)

        # controls — one row, no separate load bar. Loading by URL lives under
        # File, since it is a once-in-a-while thing next to these.
        ctl = QHBoxLayout()
        self.btn_rep = QPushButton("Reported BPM")
        self.btn_felt = QPushButton("Felt BPM")
        for b in (self.btn_rep, self.btn_felt):
            b.setCheckable(True)
        self.btn_rep.setChecked(not self.felt)
        self.btn_felt.setChecked(self.felt)
        self.btn_rep.clicked.connect(lambda: self.set_felt(False))
        self.btn_felt.clicked.connect(lambda: self.set_felt(True))
        ctl.addWidget(self.btn_rep)
        ctl.addWidget(self.btn_felt)
        self.btn_timeline = QPushButton("Timeline")
        self.btn_timeline.setCheckable(True)
        self.btn_timeline.setToolTip(
            "Width becomes track length, so the set reads as elapsed time.\n"
            "Ctrl+wheel over the chart to zoom. Fit button restores equal bars.")
        self.btn_timeline.clicked.connect(self.toggle_timeline)
        ctl.addWidget(self.btn_timeline)
        b = QPushButton("Fit")
        b.setToolTip("Scale the timeline so the whole set fits the window.")
        b.clicked.connect(self.zoom_fit)
        ctl.addWidget(b)
        b = QPushButton("Sort: key")
        b.setToolTip("Sort straight down the wheel — 1A, 1B, 2A, 2B…\n"
                     "Click again to reverse. Tracks with no key go last.")
        b.clicked.connect(lambda: self.sort_tracks("key"))
        ctl.addWidget(b)
        b = QPushButton("Sort: BPM")
        b.setToolTip("Sort by the BPM currently shown (reported or felt).\n"
                     "Click again to reverse. Tracks with no BPM go last.")
        b.clicked.connect(lambda: self.sort_tracks("bpm"))
        ctl.addWidget(b)
        b = QPushButton("Undo")
        b.clicked.connect(self.undo)
        ctl.addWidget(b)
        b = QPushButton("Save")
        b.clicked.connect(self.save_playlist)
        ctl.addWidget(b)
        b = QPushButton("Fetch BPM/key")
        b.setToolTip("Look up anything still missing.")
        b.clicked.connect(self.fetch_features)
        ctl.addWidget(b)
        b = QPushButton("Analyze")
        b.setToolTip("Recompute the chart and the key/tempo readout between "
                     "every pair of tracks from the current BPM and key values.")
        b.clicked.connect(self.reanalyze)
        ctl.addWidget(b)
        ctl.addStretch(1)
        self.spinner = Spinner(16)
        ctl.addWidget(self.spinner)
        self.busy = QLabel("")
        self.busy.setObjectName("busy")
        ctl.addWidget(self.busy)
        ctl.addSpacing(10)
        self.stat = QLabel("")
        self.stat.setObjectName("stat")
        ctl.addWidget(self.stat)
        cl.addLayout(ctl)

        # chart
        self.chart = BarChart()
        self.chart.barClicked.connect(self.select_row)
        self.chart.reordered.connect(self.move_row)
        self.vsplit = QSplitter(Qt.Vertical)
        cl.addWidget(self.vsplit, 1)
        # In timeline mode the chart is wider than the window, so it lives in a
        # scroll area. In fit mode it is told to match the viewport instead.
        self.chart_scroll = QScrollArea()
        self.chart_scroll.setWidget(self.chart)
        self.chart_scroll.setWidgetResizable(True)
        self.chart_scroll.setFrameShape(QScrollArea.NoFrame)
        self.chart_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chart_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chart_scroll.setMinimumHeight(110)
        self.vsplit.addWidget(self.chart_scroll)

        # table
        self.table = TrackTable()
        self.table.reordered.connect(self.move_row)
        self.table.dragFinished.connect(lambda: self.refresh(keep_undo=True))
        self.table.playRequested.connect(self.play_from)
        self.table.previewRequested.connect(self.preview_row)
        self.table.crossCheckRequested.connect(self.cross_check)
        self.table.edited.connect(self.edit_cell)
        self.table.deleteRequested.connect(self.delete_rows)
        self.table.itemSelectionChanged.connect(self._sync_selection)
        # Double-click plays from that row — but BPM and Key use double-click
        # to start editing, so leave those two columns alone.
        self.table.itemDoubleClicked.connect(
            lambda it: None if it.column() in (COL_BPM, COL_KEY)
            else self.play_from(it.row()))
        self.table.setMinimumHeight(120)
        self.vsplit.addWidget(self.table)
        self.vsplit.setStretchFactor(0, 0)
        self.vsplit.setStretchFactor(1, 1)

        # bottom strip — add and export side by side so the table keeps the height
        bottom = QHBoxLayout()
        bottom.setSpacing(9)

        add = QGroupBox("Add a track")
        al = QVBoxLayout(add)
        r1 = QHBoxLayout()
        self.f_title = QLineEdit(); self.f_title.setPlaceholderText("Title")
        self.f_artist = QLineEdit(); self.f_artist.setPlaceholderText("Artist")
        r1.addWidget(self.f_title, 2)
        r1.addWidget(self.f_artist, 1)
        al.addLayout(r1)
        r2 = QHBoxLayout()
        self.f_bpm = QLineEdit(); self.f_bpm.setPlaceholderText("BPM")
        self.f_key = QLineEdit(); self.f_key.setPlaceholderText("11A")
        r2.addWidget(self.f_bpm, 1)
        r2.addWidget(self.f_key, 1)
        b = QPushButton("Add")
        b.clicked.connect(self.add_track)
        r2.addWidget(b, 1)
        al.addLayout(r2)
        for w in (self.f_title, self.f_artist, self.f_bpm, self.f_key):
            w.returnPressed.connect(self.add_track)
        bottom.addWidget(add, 2)

        exp = QGroupBox("Export — paste into a Spotify playlist")
        el = QVBoxLayout(exp)
        self.uri_box = QPlainTextEdit()
        self.uri_box.setReadOnly(True)
        self.uri_box.setMaximumHeight(58)
        el.addWidget(self.uri_box)
        row = QHBoxLayout()
        b = QPushButton("Copy to clipboard")
        b.clicked.connect(self.copy_uris)
        row.addWidget(b)
        b = QPushButton("Push order to Spotify")
        b.setToolTip("Reorder the Spotify playlist to match this window.\n"
                     "Moves tracks rather than replacing them, so nothing is "
                     "removed and the dates added are kept.")
        b.setIcon(spotify_icon(15))
        b.setIconSize(icon_size(15))
        b.clicked.connect(self.push_order)
        row.addWidget(b)
        el.addLayout(row)
        bottom.addWidget(exp, 3)

        bottom_w = QWidget()
        bottom_w.setLayout(bottom)
        bottom_w.setMinimumHeight(90)
        self.vsplit.addWidget(bottom_w)
        self.vsplit.setStretchFactor(2, 0)

        self.player = PlayerBar()
        self.player.playPauseClicked.connect(self.toggle_play)
        self.player.prevClicked.connect(lambda: self._player_do("previous"))
        self.player.nextClicked.connect(lambda: self._player_do("next"))
        self.player.seekRequested.connect(lambda ms: self._player_do("seek", ms))
        self.player.previewClicked.connect(self.preview_transition)
        cl.addWidget(self.player)

        outer.addWidget(col)
        outer.setStretchFactor(0, 0)
        outer.setStretchFactor(1, 1)
        outer.setSizes([240, 1040])

        # The sidebar header and the main button row are separate layouts, so
        # nothing makes them the same height on its own — and any difference
        # offsets the playlist list from the chart beside it. Pin the shorter
        # one to the taller.
        h = max(self.btn_rep.sizeHint().height(), 24)
        self.sp_head.addStretch(0)
        for i in range(self.sp_head.count()):
            w = self.sp_head.itemAt(i).widget()
            if w is not None:
                w.setMinimumHeight(h)
        ctl.setContentsMargins(0, 0, 0, 0)
        head.setContentsMargins(0, 0, 0, 0)

    def _build_menu(self):
        m = self.menuBar().addMenu("&File")
        a = QAction("Load playlist from a &link…", self)
        a.setShortcut(QKeySequence("Ctrl+L"))
        a.setIcon(spotify_icon(15))
        a.triggered.connect(self.load_playlist); m.addAction(a)
        a = QAction("S&ync from Spotify", self)
        a.setShortcut(QKeySequence("Ctrl+R"))
        a.setIcon(spotify_icon(15))
        a.triggered.connect(self.sync_playlist); m.addAction(a)
        m.addSeparator()
        a = QAction("&Save", self); a.setShortcut(QKeySequence.Save)
        a.triggered.connect(self.save_playlist); m.addAction(a)
        a = QAction("&Settings…", self)
        a.triggered.connect(self.open_settings); m.addAction(a)
        a = QAction("Change storage folder…", self)
        a.triggered.connect(self.choose_storage); m.addAction(a)
        m.addSeparator()
        a = QAction("Sign in to Spotify…", self)
        a.triggered.connect(self.sign_in); m.addAction(a)
        a = QAction("Sign out of Spotify", self)
        a.triggered.connect(self.sign_out); m.addAction(a)
        m.addSeparator()
        a = QAction("E&xit", self); a.triggered.connect(self.close); m.addAction(a)

        e = self.menuBar().addMenu("&Edit")
        a = QAction("&Undo", self); a.setShortcut(QKeySequence.Undo)
        a.triggered.connect(self.undo); e.addAction(a)

        e.addSeparator()
        for label, seq, slot in (
            ("Move track up", "Ctrl+Up", lambda: self._nudge(-1)),
            ("Move track down", "Ctrl+Down", lambda: self._nudge(1)),
            ("Next missing BPM/key", "Ctrl+B", self.jump_next_blank),
            ("Preview transition", "Ctrl+P",
             lambda: self.preview_transition(self.player.tail.value())),
            ("Play / pause", "Space", self._space),
        ):
            a = QAction(label, self)
            a.setShortcut(QKeySequence(seq))
            a.setShortcutVisibleInContextMenu(True)
            a.triggered.connect(slot)
            # The QShortcut objects do the work; these are here so the bindings
            # are discoverable rather than folklore.
            a.setShortcutContext(Qt.WidgetShortcut)
            e.addAction(a)

        h = self.menuBar().addMenu("&Help")
        a = QAction("&About", self)
        a.triggered.connect(lambda: AboutDialog(self).exec())
        h.addAction(a)

    def _build_shortcuts(self):
        def add(seq, slot):
            a = QShortcut(QKeySequence(seq), self)
            a.setContext(Qt.ApplicationShortcut)
            a.activated.connect(slot)
            return a

        add("Space", self._space)
        add("Ctrl+Up", lambda: self._nudge(-1))
        add("Ctrl+Down", lambda: self._nudge(1))
        add("Ctrl+B", self.jump_next_blank)
        add("Ctrl+P", lambda: self.preview_transition(self.player.tail.value()))
        add("Ctrl+F", self.fetch_features)

    def _space(self):
        # Space is a normal character while a cell is being edited.
        if self.table.state() == QAbstractItemView.EditingState:
            return
        self.toggle_play()

    def _nudge(self, delta: int):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return
        src = rows[0]
        dst = src + delta
        if not (0 <= dst < len(self.tracks)):
            return
        self.move_row(src, dst)

    def jump_next_blank(self):
        """Walk to the next missing BPM or key and open it for typing."""
        cur = self.table.currentItem()
        after_row = cur.row() if cur else -1
        after_col = cur.column() if cur else -1
        row, col = self.table.next_blank(after_row, after_col)
        if row < 0:
            self.status("No blanks left.")
            return
        self.table.selectRow(row)
        self.table.edit_cell(row, col)
        t = self.tracks[row]
        what = "BPM" if col == COL_BPM else "key"
        self.status(f"{t.artist} — {t.title}: type the {what}. Ctrl+B for the next.")

    def cross_check(self, row: int):
        """Ask the web what it thinks, and show it beside the current value.

        Deliberately manual and one track at a time: the web sources agreed with
        a known-good reference on key only about 4 times in 10, so this exists
        to inform a decision, not to overwrite anything on its own.
        """
        if not (0 <= row < len(self.tracks)):
            return
        t = self.tracks[row]
        if not self.web.api_key:
            self.status("No Brave API key set — add BRAVE_API_KEY to your .env")
            return
        self.busy_on(f"Checking '{t.title}'…")
        try:
            hit = self.web.lookup(t.title, t.artist)
        finally:
            self.busy_off()

        cur = (f"{round(t.bpm)} / {t.key}" if t.resolved
               else f"{round(t.bpm) if t.bpm else '—'} / {t.key or '—'}")
        if not (hit.bpm or hit.camelot):
            QMessageBox.information(
                self, "Cross-check",
                f"{t.artist} — {t.title}\n\nHere: {cur}\n\n"
                f"Nothing found on the web for this one.")
            return
        found = f"{round(hit.bpm) if hit.bpm else '—'} / {hit.camelot or '—'}"
        agree = (hit.bpm and abs(hit.bpm - t.bpm) < 1) and hit.camelot == t.key
        srcs = ", ".join(hit.sources) or "web"
        box = QMessageBox(self)
        box.setWindowTitle("Cross-check")
        box.setText(
            f"<b>{t.artist} — {t.title}</b><br><br>"
            f"Here:&nbsp;&nbsp;<b>{cur}</b><br>"
            f"Web:&nbsp;&nbsp;&nbsp;<b>{found}</b><br><br>"
            f"<span style='color:#8C939D'>from {srcs}</span><br><br>"
            + ("These agree." if agree else
               "These disagree. The web sources are often wrong about key — "
               "check Spotify before taking theirs."))
        if not agree:
            take = box.addButton("Use the web value", QMessageBox.AcceptRole)
            box.addButton("Keep mine", QMessageBox.RejectRole)
        else:
            take = None
            box.addButton(QMessageBox.Close)
        box.exec()
        if take is not None and box.clickedButton() is take:
            self.snapshot()
            if hit.bpm:
                t.bpm = hit.bpm
            if hit.camelot:
                t.key = hit.camelot
            t.manual = True          # a decision you made — never overwritten
            t.source = "manual"
            t.bpm_conf = t.key_conf = None
            self.store.cache_put(t)
            self.refresh()
            self.status(f"Took the web value for '{t.title}'.")

    # ---------------- storage ----------------

    def _first_run(self):
        """Nothing works without the two required keys, so ask up front rather
        than failing later with a 401 that reads like a bug."""
        if not missing_required(self.env):
            return
        dlg = SettingsDialog(self, first_run=True, prefs=self.prefs)
        if dlg.exec() == QDialog.Accepted:
            self._reload_env()
            self.status("Setup saved.")
        else:
            self.status("Setup skipped — add your keys under File → Settings.")

    def open_settings(self):
        dlg = SettingsDialog(self, first_run=False, prefs=self.prefs)
        if dlg.exec() != QDialog.Accepted:
            return
        old_dir = self.store.root if self.store else None
        self._reload_env()
        if self.prefs.storage_dir and str(old_dir) != self.prefs.storage_dir:
            self.store = Store(self.prefs.storage_dir)
            self.refresh_saved()
        self.status("Settings saved.")

    def _reload_env(self):
        """Rebuild every client so new keys take effect without a restart."""
        self.env = load_env()
        self.auth.client_id = self.env.get("SPOTIFY_CLIENT_ID", "")
        self.freqblog.api_key = self.env.get("FREQBLOG_API_KEY", "")
        self.getsongbpm.api_key = self.env.get("GETSONGBPM_API_KEY", "")
        self.web.api_key = self.env.get("BRAVE_API_KEY", "")

    def _ensure_storage(self):
        d = self.prefs.storage_dir
        if not d:
            d = str(Path.home() / "Documents" / "PlaylistFlow")
            self.prefs.storage_dir = d
        self.store = Store(d)
        self.refresh_saved()
        if self.auth.authorised:
            QTimer.singleShot(0, self.refresh_spotify)
            self._poll.start()
            QTimer.singleShot(400, self.poll_player)

    def choose_storage(self):
        d = QFileDialog.getExistingDirectory(self, "Pick a folder for saved playlists",
                                             self.prefs.storage_dir or "")
        if d:
            self.prefs.storage_dir = d
            self.store = Store(d)
            self.refresh_saved()
            self.status(f"Storage folder is now {d}")

    def refresh_saved(self):
        self.saved_list.clear()
        if not self.store:
            return
        for name in self.store.list_playlists():
            it = QListWidgetItem(name)
            if self.store.has_newer_auto(name):
                it.setText(f"{name}  •")
                it.setToolTip("Has unsaved auto-changes newer than the manual save.")
            it.setData(Qt.UserRole, name)
            self.saved_list.addItem(it)

    def _selected_saved(self) -> str:
        it = self.saved_list.currentItem()
        return it.data(Qt.UserRole) if it else ""

    def load_saved(self):
        name = self._selected_saved()
        if not name:
            return
        self.snapshot()
        self.tracks = self.store.load(name)
        self.current_pid = self.store.last_loaded_pid
        self.current_name = name
        self.refresh()
        self.status(f"Loaded {name} — {len(self.tracks)} tracks.")

    def rename_saved(self):
        name = self._selected_saved()
        if not name:
            return
        new, ok = QInputDialog.getText(self, "Rename playlist", "New name:", text=name)
        if ok and new.strip():
            self.store.rename(name, new.strip())
            if self.current_name == name:
                self.current_name = new.strip()
            self.refresh_saved()

    def delete_saved(self):
        name = self._selected_saved()
        if not name:
            return
        if QMessageBox.question(
            self, "Delete playlist",
            f"Delete '{name}'? This removes both the saved file and its auto-save."
        ) == QMessageBox.Yes:
            self.store.delete(name)
            if self.current_name == name:
                self.current_name = ""
            self.refresh_saved()

    def delete_all_saved(self):
        if not self.store.list_playlists():
            return
        if QMessageBox.question(
            self, "Delete all playlists",
            "Delete every saved playlist and auto-save in this folder? "
            "The track cache is kept."
        ) == QMessageBox.Yes:
            self.store.delete_all()
            self.current_name = ""
            self.refresh_saved()

    def save_playlist(self):
        if not self.tracks:
            return
        name = self.current_name
        if not name:
            name, ok = QInputDialog.getText(self, "Save playlist", "Name:")
            if not ok or not name.strip():
                return
            name = name.strip()
        self.current_name = name
        self.store.save(name, self.tracks, auto=False, pid=self.current_pid)
        self.refresh_saved()
        self.status(f"Saved {name}.")

    def _write_auto(self):
        if self.store and self.current_name and self.tracks:
            self.store.save(self.current_name, self.tracks, auto=True,
                            pid=self.current_pid)

    # ---------------- undo ----------------

    def snapshot(self):
        self.undo_stack.append(copy.deepcopy(self.tracks))
        if len(self.undo_stack) > UNDO_CAP:
            self.undo_stack.pop(0)

    def undo(self):
        if not self.undo_stack:
            self.status("Nothing to undo.")
            return
        self.tracks = self.undo_stack.pop()
        self.refresh()
        self.status("Undone.")

    # ---------------- data ops ----------------

    def load_playlist(self):
        """Load by pasted URL or ID — for playlists that aren't on the account,
        or someone else's link."""
        text, ok = QInputDialog.getText(
            self, "Load playlist from a link",
            "Paste a Spotify playlist link or ID:\n"
            "(Development Mode only serves playlists you created or "
            "collaborate on.)")
        if not ok or not text.strip():
            return
        try:
            pid = Spotify.playlist_id(text.strip())
        except ProviderError as e:
            self.status(str(e))
            return
        self._load_pid(pid)

    def refresh_spotify(self):
        # processEvents() below lets a second call run to completion inside the
        # first, which would append a duplicate set. Guard against re-entry.
        if self._refreshing_spotify:
            return
        if not self.auth.authorised and not self.sign_in():
            return
        self._refreshing_spotify = True
        self.busy_on("Reading your playlists…")
        try:
            try:
                lists = self.spotify.my_playlists()
            except AuthError:
                if not self.sign_in():
                    return
                try:
                    lists = self.spotify.my_playlists()
                except (ProviderError, AuthError) as e:
                    self.status(str(e))
                    return
            except ProviderError as e:
                self.status(str(e))
                return
            self._fill_spotify_list(lists)
        finally:
            self._refreshing_spotify = False
            self.busy_off()

    def _fill_spotify_list(self, lists):
        self.sp_list.clear()
        for pl in lists:
            it = QListWidgetItem(f"{pl.name}  ({pl.count})")
            it.setData(Qt.UserRole, pl.id)
            if not pl.mine:
                # Development Mode only serves items for playlists you created
                # or collaborate on, so someone else's list will refuse to load.
                it.setForeground(Qt.gray)
                it.setToolTip(
                    f"Owned by {pl.owner} — Spotify will refuse to send its "
                    f"tracks to a Development Mode app."
                )
            self.sp_list.addItem(it)
        self.status(f"{len(lists)} playlists on your account.")

    def load_from_spotify(self):
        it = self.sp_list.currentItem()
        if not it:
            self.status("Pick a playlist first.")
            return
        self._load_pid(it.data(Qt.UserRole))

    def sync_playlist(self):
        """Re-read the playlist from Spotify without losing local work.

        A plain reload would throw away the ordering, which is the whole point
        of the app. So this only reconciles membership: tracks added on Spotify
        are appended, tracks removed there are removed here, and everything
        else keeps its position and its BPM/key exactly as it is.
        """
        if not self.current_pid:
            self.status("This playlist did not come from Spotify.")
            return
        if not self.auth.authorised and not self.sign_in():
            return
        self.busy_on("Syncing…")
        try:
            rows = self.spotify.playlist_tracks(self.current_pid)
        except AuthError:
            if not self.sign_in():
                return
            try:
                rows = self.spotify.playlist_tracks(self.current_pid)
            except (ProviderError, AuthError) as e:
                QMessageBox.warning(self, "Sync", str(e))
                return
        except ProviderError as e:
            QMessageBox.warning(self, "Sync", str(e))
            return
        finally:
            self.busy_off()

        remote = {r.uri: r for r in rows if r.uri}
        here = {t.uri for t in self.tracks if t.uri}

        gone = [t for t in self.tracks if t.uri and t.uri not in remote]
        added = [r for uri, r in remote.items() if uri not in here]
        local_only = [t for t in self.tracks if not t.uri]

        if not gone and not added:
            self.status(f"Already in sync — {len(self.tracks)} tracks.")
            return

        msg = []
        if added:
            msg.append(f"{len(added)} added on Spotify → appended to the end")
        if gone:
            names = ", ".join(f"'{t.title}'" for t in gone[:3])
            more = f" and {len(gone) - 3} more" if len(gone) > 3 else ""
            msg.append(f"{len(gone)} removed on Spotify → removed here ({names}{more})")
        if local_only:
            msg.append(f"{len(local_only)} track(s) you added by hand are kept")
        if QMessageBox.question(
            self, "Sync from Spotify",
            "\n\n".join(msg) + "\n\nYour ordering is kept for everything else."
        ) != QMessageBox.Yes:
            return

        self.snapshot()
        kept = [t for t in self.tracks if not t.uri or t.uri in remote]
        for r in added:
            t = Track(title=r.title, artist=r.artist, uri=r.uri, isrc=r.isrc,
                      duration_ms=r.duration_ms)
            self.store.apply_cache(t)
            kept.append(t)
        self.tracks = kept
        self.refresh()
        unresolved = sum(1 for t in self.tracks if not t.resolved)
        tail = f" {unresolved} need BPM/key." if unresolved else ""
        self.status(f"Synced — {len(added)} added, {len(gone)} removed.{tail}")

    def _load_pid(self, pid: str):
        if not pid:
            return
        if not self.auth.authorised and not self.sign_in():
            return
        self.busy_on("Reading playlist…")
        try:
            try:
                name = self.spotify.playlist_name(pid)
                rows = self.spotify.playlist_tracks(pid)
            except AuthError:
                # Refresh token revoked or expired — retry once after re-auth.
                if not self.sign_in():
                    return
                try:
                    name = self.spotify.playlist_name(pid)
                    rows = self.spotify.playlist_tracks(pid)
                except (ProviderError, AuthError) as e:
                    QMessageBox.warning(self, "Spotify", str(e))
                    self.status(str(e))
                    return
            except ProviderError as e:
                QMessageBox.warning(self, "Spotify", str(e))
                self.status(str(e))
                return
        finally:
            self.busy_off()
        self.snapshot()
        self.tracks = []
        for r in rows:
            t = Track(title=r.title, artist=r.artist, uri=r.uri, isrc=r.isrc,
                      duration_ms=r.duration_ms)
            self.store.apply_cache(t)
            self.tracks.append(t)
        self.current_pid = pid
        self.current_name = name or "Untitled playlist"
        self.refresh()
        cached = sum(1 for t in self.tracks if t.resolved)
        self.status(
            f"Loaded {len(self.tracks)} tracks from '{self.current_name}' "
            f"({cached} already known). Hit Fetch BPM/key for the rest."
        )

    def sign_in(self) -> bool:
        """Returns True once a refresh token is held."""
        dlg = SignInDialog(self.auth, self)
        if dlg.exec() == QDialog.Accepted and self.auth.authorised:
            self.status("Signed in to Spotify.")
            QTimer.singleShot(0, self.refresh_spotify)
            self._poll.start()
            QTimer.singleShot(400, self.poll_player)
            return True
        self.status("Spotify sign-in cancelled.")
        return False

    def sign_out(self):
        self.auth.forget()
        self.sp_list.clear()
        self.status("Signed out of Spotify.")

    def reanalyze(self):
        """Recompute the seams and redraw the chart from the current values.

        Everything downstream of a BPM or key is derived, so this rebuilds the
        chart, the key/tempo readout between every pair, and the counts.
        """
        if not self.tracks:
            self.status("Nothing loaded.")
            return
        self._live.stop()
        self.refresh(keep_undo=True)
        sm = seams(self.tracks)
        judged = [s for s in sm if s.known]
        unknown = len(sm) - len(judged)
        bits = [f"Reanalysed {len(self.tracks)} tracks",
                f"{len(judged)} seams scored"]
        if unknown:
            bits.append(f"{unknown} skipped (missing BPM/key)")
        self.status(" · ".join(bits) + ".")

    def fetch_features(self, force: bool = False):
        if not self.tracks:
            return
        if self.worker and self.worker.isRunning():
            self.status("Already fetching.")
            return
        jobs = [(i, t) for i, t in enumerate(self.tracks)
                if not t.manual and (force or not t.resolved)]
        if not jobs:
            self.status("Everything is already resolved.")
            return
        self.worker = FetchWorker(self.freqblog, self.getsongbpm, self.web, jobs, self)
        self.worker.resolved.connect(self._apply_feature)
        self.worker.message.connect(self.status)
        self.worker.done.connect(self._fetch_done)
        self.busy_on(f"Looking up {len(jobs)} track(s)…")
        self.worker.start()

    def _apply_feature(self, idx: int, feat: Features):
        if idx >= len(self.tracks):
            return
        t = self.tracks[idx]
        if t.manual:          # a manual value is never replaced by a fetch
            return
        if feat.bpm > 0:
            t.bpm = feat.bpm
        if valid_key(feat.camelot):
            t.key = feat.camelot.upper()
        t.bpm_conf = feat.bpm_conf
        t.key_conf = feat.key_conf
        if feat.isrc and not t.isrc:
            t.isrc = feat.isrc
        t.source = feat.source or "freqblog"
        if t.resolved:
            self.store.cache_put(t)
        # Update the counts immediately — that is the number being watched —
        # but coalesce the expensive full table rebuild, or 49 results in quick
        # succession starve the repaint and nothing appears to move.
        self.stat.setText(summary(self.tracks))
        self._live.start()

    def _fetch_done(self):
        self.busy_off()
        self.refresh(keep_undo=True)
        self._autosave.start()

    def add_track(self):
        title = self.f_title.text().strip()
        bpm_s = self.f_bpm.text().strip()
        key_s = self.f_key.text().strip().upper()
        if not title:
            self.status("Needs a title.")
            return
        try:
            bpm = float(bpm_s) if bpm_s else 0.0
        except ValueError:
            self.status("BPM must be a number.")
            return
        if key_s and not valid_key(key_s):
            self.status("Key needs to look like 11A or 5B.")
            return
        self.snapshot()
        t = Track(title=title, artist=self.f_artist.text().strip(),
                  bpm=bpm, key=key_s, source="manual" if (bpm or key_s) else "",
                  manual=bool(bpm or key_s))
        if not t.resolved:
            self.store.apply_cache(t)
        self.tracks.append(t)
        for w in (self.f_title, self.f_artist, self.f_bpm, self.f_key):
            w.clear()
        self.f_title.setFocus()
        self.refresh()
        self.status("Added at the end — drag it where it belongs.")

    def delete_rows(self, rows: list[int]):
        if not rows:
            return
        self.snapshot()
        for r in sorted(rows, reverse=True):
            if 0 <= r < len(self.tracks):
                self.tracks.pop(r)
        self.refresh()

    def sort_tracks(self, field: str):
        """Plain sort, no sequencing cleverness — that is the user's job.

        Repeating the same sort reverses it. Rows with nothing to sort on go to
        the end either way, so an unresolved track never lands mid-run.
        """
        if len(self.tracks) < 2:
            return
        if self._sort_field == field:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_field, self._sort_desc = field, False

        def key_of(t: Track):
            if field == "key":
                # Down the wheel: 1A, 1B, 2A, 2B …
                return (t.n, 0 if t.letter == "A" else 1)
            return (felt_bpm(t.bpm) if self.felt else t.bpm,)

        known = [t for t in self.tracks if (t.n if field == "key" else t.bpm)]
        unknown = [t for t in self.tracks if not (t.n if field == "key" else t.bpm)]
        known.sort(key=key_of, reverse=self._sort_desc)

        new = known + unknown
        if new == self.tracks:
            return
        self.snapshot()
        self.tracks = new
        self.table.clearSelection()
        self.refresh()
        which = "key" if field == "key" else ("felt BPM" if self.felt else "BPM")
        order = "high to low" if self._sort_desc else "low to high"
        tail = f", {len(unknown)} with no {which} at the end" if unknown else ""
        self.status(f"Sorted by {which}, {order}{tail}.")

    def move_row(self, src: int, dst: int):
        if src == dst or not (0 <= src < len(self.tracks)):
            return
        self.snapshot()
        t = self.tracks.pop(src)
        self.tracks.insert(max(0, min(dst, len(self.tracks))), t)
        self.refresh()
        self.table.selectRow(dst)

    def edit_cell(self, row: int, field: str, text: str):
        if not (0 <= row < len(self.tracks)):
            return
        t = self.tracks[row]
        text = text.strip()
        if field == "bpm":
            try:
                v = float(text) if text else 0.0
            except ValueError:
                self.status("BPM must be a number.")
                self.refresh(keep_undo=True)
                return
            # The cell shows felt BPM in felt view; store the reported value.
            if self.felt and v > 0:
                reported = t.bpm
                if reported >= 130 and abs(v - reported / 2) > 0.6:
                    v = v * 2
            if v == t.bpm:
                return
            self.snapshot()
            t.bpm = v
        else:
            key = text.upper()
            if key and not valid_key(key):
                self.status("Key needs to look like 11A or 5B.")
                self.refresh(keep_undo=True)
                return
            if key == t.key:
                return
            self.snapshot()
            t.key = key
        t.manual = True
        t.source = "manual"
        t.bpm_conf = None
        t.key_conf = None
        if t.resolved:
            self.store.cache_put(t)
        self.refresh()

    def select_row(self, i: int):
        if 0 <= i < len(self.tracks):
            self.table.selectRow(i)
            self.table.scrollToItem(self.table.item(i, 0))

    def _sync_selection(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        sel = rows[0] if rows else -1
        self.chart.set_data(self.tracks, seams(self.tracks), self.felt, sel)

    def toggle_timeline(self):
        on = self.btn_timeline.isChecked()
        self.chart_scroll.setWidgetResizable(not on)
        self.chart.set_mode("time" if on else "fit")
        if on:
            self.zoom_fit()
            self.status("Timeline — width is track length. Ctrl+wheel to zoom.")
        else:
            self.chart.resize(self.chart_scroll.viewport().size())
            self.status("Equal-width bars.")

    def zoom_fit(self):
        if self.chart.mode() != "time":
            return
        self.chart.set_zoom(self.chart.fit_zoom(
            self.chart_scroll.viewport().width()))
        self.chart.resize(self.chart.minimumWidth(),
                          self.chart_scroll.viewport().height())

    def set_felt(self, felt: bool):
        self.felt = felt
        self.prefs.felt = felt
        self.btn_rep.setChecked(not felt)
        self.btn_felt.setChecked(felt)
        self.refresh(keep_undo=True)

    def push_order(self):
        """Reorder the Spotify playlist to match this window."""
        if not self.tracks:
            return
        if not self.current_pid:
            QMessageBox.information(
                self, "Push order",
                "This playlist did not come from Spotify, so there is nothing "
                "to push to. Use the URI block instead.")
            return
        no_uri = [t for t in self.tracks if not t.uri]
        if no_uri:
            QMessageBox.warning(
                self, "Push order",
                f"{len(no_uri)} track(s) here are not from Spotify "
                f"(e.g. \"{no_uri[0].title}\"), so the orders cannot be made to "
                f"match. Remove them, or use the URI block.")
            return
        if not self.auth.authorised and not self.sign_in():
            return
        if QMessageBox.question(
            self, "Push order",
            f"Reorder '{self.current_name}' on Spotify to match this window?\n\n"
            f"{len(self.tracks)} tracks. Nothing is added or removed — tracks "
            f"are moved, so dates added are preserved."
        ) != QMessageBox.Yes:
            return

        target = [t.uri for t in self.tracks]
        self.busy_on("Pushing order…")
        try:
            moves = self.spotify.reorder_playlist(
                self.current_pid, target,
                progress=lambda m, i, n: self.status(f"Moved {m} — track {i} of {n}…"))
        except (ProviderError, AuthError) as e:
            QMessageBox.warning(self, "Push order", str(e))
            self.status(str(e))
            return
        finally:
            self.busy_off()
        if moves:
            self.status(f"Pushed — {moves} move(s) applied to '{self.current_name}'.")
        else:
            self.status("Spotify already matches this order — nothing to do.")

    # ---------------- playback ----------------

    def _player_do(self, what: str, arg=None):
        """Every transport action funnels through here so one missing device or
        expired token is reported once, in plain terms."""
        if not self.auth.authorised:
            self.status("Sign in to Spotify first.")
            return
        try:
            if what == "pause":
                self.spotify.pause()
            elif what == "resume":
                self.spotify.resume()
            elif what == "next":
                self.spotify.next_track()
            elif what == "previous":
                self.spotify.previous_track()
            elif what == "seek":
                self.spotify.seek(int(arg))
            elif what == "play":
                self.spotify.play(*arg)
        except (ProviderError, AuthError) as e:
            self.status(str(e))
            return
        QTimer.singleShot(250, self.poll_player)

    def toggle_play(self):
        st = self._last_player_state
        if st and st.get("is_playing"):
            self._player_do("pause")
        elif st:
            self._player_do("resume")
        else:
            # Nothing playing — start the playlist from the selected row.
            rows = sorted({i.row() for i in self.table.selectedIndexes()})
            self.play_from(rows[0] if rows else 0)

    def play_from(self, row: int):
        """Play from this row onward, in the order shown here — which may not
        be the order on Spotify yet."""
        uris = [t.uri for t in self.tracks[row:] if t.uri]
        if not uris:
            self.status("That track has no Spotify link.")
            return
        self._player_do("play", (uris, 0, ""))
        t = self.tracks[row]
        self.status(f"Playing '{t.title}' and onward in this order.")

    def preview_transition(self, tail_s: int):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            self.status("Select the track you want to hear the transition out of.")
            return
        self.preview_row(rows[0], tail_s)

    def preview_row(self, i: int, tail_s: int = 0):
        """Cue the tail of track i so the seam into the next can be heard."""
        tail_s = tail_s or self.player.tail.value()
        if i + 1 >= len(self.tracks):
            self.status("That is the last track — nothing to transition into.")
            return
        a, b = self.tracks[i], self.tracks[i + 1]
        if not a.uri or not b.uri:
            self.status("Both tracks need a Spotify link for this.")
            return
        if a.duration_ms <= 0:
            # Manually added rows have no duration; just start the incoming one.
            self._player_do("play", ([b.uri], 0, ""))
            self.status(f"No length known for '{a.title}' — playing '{b.title}'.")
            return
        start = max(0, a.duration_ms - tail_s * 1000)
        self._player_do("play", ([a.uri, b.uri], start, ""))
        sm = seams(self.tracks)
        s = sm[i] if i < len(sm) else None
        detail = f"  ({s.key.txt}, {s.tempo.txt})" if s and s.known else ""
        self.status(f"Last {tail_s}s of '{a.title}' → '{b.title}'{detail}")

    def poll_player(self):
        if not self.auth.authorised:
            self.player.set_offline("Not signed in to Spotify")
            return
        try:
            st = self.spotify.player_state()
        except (ProviderError, AuthError):
            self.player.set_offline("Spotify unreachable")
            return
        self._last_player_state = st
        if not st or not st.get("item"):
            self.player.set_offline()
            self.table.set_playing_row(-1, follow=False)
            return
        item = st["item"]
        # Follow along in the table.
        uri = item.get("uri", "")
        row = next((i for i, t in enumerate(self.tracks) if t.uri and t.uri == uri), -1)
        self.table.set_playing_row(row)
        self.chart.set_playhead(row, st.get("progress_ms") or 0)
        self.player.set_state(
            playing=bool(st.get("is_playing")),
            title=item.get("name", ""),
            artist=", ".join(a.get("name", "") for a in item.get("artists", [])),
            position_ms=st.get("progress_ms") or 0,
            duration_ms=item.get("duration_ms") or 0,
        )

    def copy_uris(self):
        text = self.uri_box.toPlainText()
        if not text.strip():
            self.status("Nothing to copy — no track URIs in this playlist.")
            return
        QGuiApplication.clipboard().setText(text)
        n = len(text.strip().splitlines())
        self.status(f"Copied {n} URIs.")

    # ---------------- render ----------------

    def refresh(self, keep_undo: bool = False):
        sm = seams(self.tracks)
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        sel = rows[0] if rows else -1
        self.table.set_data(self.tracks, sm, self.felt)
        self.chart.set_data(self.tracks, sm, self.felt, sel)
        self.stat.setText(summary(self.tracks))
        self.uri_box.setPlainText(
            "\n".join(t.uri for t in self.tracks if t.uri)
        )
        if self.store and self.current_name:
            self._autosave.start()

    def status(self, msg: str):
        self.statusBar().showMessage(msg, 12000)
        if self.spinner.running:
            # While something is running, mirror progress next to the spinner —
            # the status bar is easy to miss at the bottom of the window.
            self.busy.setText(msg)

    def busy_on(self, msg: str = ""):
        self.busy.setText(msg)
        self.spinner.start()
        QApplication.processEvents()

    def busy_off(self):
        self.spinner.stop()
        self.busy.setText("")

    def _restore_layout(self):
        g = self.prefs.geometry
        if g:
            self.restoreGeometry(g)
        for name, sp in (("h", self.hsplit), ("v", self.vsplit)):
            st = self.prefs.splitter(name)
            if st:
                sp.restoreState(st)

    def _save_layout(self):
        self.prefs.geometry = self.saveGeometry()
        self.prefs.set_splitter("h", self.hsplit.saveState())
        self.prefs.set_splitter("v", self.vsplit.saveState())

    def closeEvent(self, e):
        self._save_layout()
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        self._write_auto()
        if self.store:
            self.store.flush_cache()
        super().closeEvent(e)
