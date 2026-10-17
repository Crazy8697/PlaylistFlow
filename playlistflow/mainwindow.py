"""Main window."""

from __future__ import annotations

import copy
import os
import time

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QSize
from PySide6.QtGui import (QAction, QActionGroup, QKeySequence, QGuiApplication,
                           QDesktopServices, QShortcut, QPainter, QPixmap,
                           QColor, QLinearGradient, QBrush)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QSplitter, QPlainTextEdit,
    QMessageBox, QFileDialog, QInputDialog, QDialog, QDialogButtonBox,
    QGroupBox, QFormLayout, QApplication, QAbstractItemView, QSplitter,
    QScrollArea, QRadioButton, QComboBox, QButtonGroup, QTextBrowser,
    QToolBar, QToolButton, QTabWidget, QCheckBox,
)

from .domain import (Track, seams, summary, valid_key, felt_bpm, folded, reported_from_felt,
                     seam_key, set_display)
from .providers import Spotify, FreqBlog, GetSongBPM, ProviderError, Features, KeyRejected
from .auth import SpotifyAuth, AuthError
from .keys import clean_title, primary_artist
from .store import Store, StoreError
from pathlib import Path

from . import __version__, __url__
from .config import Prefs, load_env, missing_required, display_settings, TOLERANCES, redirect_port
from .settings import SettingsDialog
from .chart import BarChart
from .table import TrackTable, COL_BPM, COL_KEY
from .spinner import Spinner
from .player import PlayerBar
from .brand import logo_label, full_logo_pixmap, spotify_link, set_link_target, open_in_spotify
from . import theme
from .artwork import about_pixmap, icon_pixmap, remote_pixmap
from .wheel import KeyWheelDialog
from .updater import (UpdateChecker, UpdateDownloader, can_install, launch_setup,
                      RELEASES_URL, UPDATE_STARTUP_DELAY_MS)
from .finderdialog import FinderDialog

UNDO_CAP = 40
# A queued track's re-check runs by itself only when it is due this soon; later ones
# wait for the next Fetch BPM/key (or the next time the playlist is opened).
AUTO_RECHECK_MAX_S = 15 * 60
COVER = 88                 # playlist cover in the bottom strip
AUTOSAVE_MS = 1500


# --------------------------------------------------------------------------
# Fetch worker
# --------------------------------------------------------------------------

class FetchWorker(QThread):
    """BPM/key lookups for a list of tracks, off the UI thread.

    FreqBlog counts every lookup against the key's monthly allowance, a 202 "queued"
    answer too and on /bulk too. So: /bulk, 50 tracks a call; only tracks that aren't
    cached or waiting reach here (fetch_features filters them); and nothing is re-polled.
    A queued track is reported through `waiting` and asked about again later on the
    Store's schedule, never in a loop inside this fetch.

    Results are matched to tracks by the Track object, not by row, so nothing lands
    on the wrong row even if the list changed; the window also locks reordering while
    a fetch runs.
    """
    resolved = Signal(object, object)   # Track, Features
    waiting = Signal(object, str, object)   # Track, "queued" | "missing", retry_after_days
    message = Signal(str)
    done = Signal()
    keyRejected = Signal(str)        # provider name: its key was refused

    def __init__(self, fb: FreqBlog, gs: GetSongBPM,
                 jobs: list[Track], parent=None):
        super().__init__(parent)
        self.fb = fb
        self.gs = gs
        self.jobs = list(jobs)
        self._stop = False
        self._got = 0
        self.fb_rejected = False      # once FreqBlog refuses the key, stop asking it
        self.requests = 0             # FreqBlog track lookups sent (what the allowance counts)
        self.calls = 0                # FreqBlog HTTP calls made

    def stop(self):
        self._stop = True

    # -- helpers ---------------------------------------------------------

    def _emit(self, trk: Track, feat: Features, source: str):
        feat.source = source
        self._got += 1
        self.resolved.emit(trk, feat)

    def _bulk_pass(self, jobs, build, source):
        """Run tracks through /bulk, 50 a call. Returns (queued, missed), each a list of
        (Track, Features)."""
        queued, missed = [], []
        for start in range(0, len(jobs), 50):
            if self._stop or self.fb_rejected:
                return queued, missed + [(t, Features(terminal=True)) for t in jobs[start:]]
            chunk = jobs[start:start + 50]
            try:
                self.calls += 1
                self.requests += len(chunk)
                rows = self.fb.bulk([build(t) for t in chunk])
            except KeyRejected:
                self.fb_rejected = True
                self.keyRejected.emit("FreqBlog")
                missed.extend((t, Features(terminal=True)) for t in chunk)
                continue
            except ProviderError as e:
                self.message.emit(str(e))
                missed.extend((t, Features(terminal=True)) for t in chunk)
                continue
            rows = list(rows) + [{}] * (len(chunk) - len(rows))
            for trk, row in zip(chunk, rows):
                feat = FreqBlog.features_from_row(row)
                if feat.pending:
                    queued.append((trk, feat))
                elif feat.terminal or not (feat.bpm or feat.camelot):
                    missed.append((trk, feat))
                else:
                    self._emit(trk, feat, source)
        return queued, missed

    # -- main ------------------------------------------------------------

    def run(self):
        total = len(self.jobs)

        def full(t: Track) -> dict:
            item = {"track": t.title}
            if t.artist:
                item["artist"] = t.artist
            if t.isrc:
                item["isrc"] = t.isrc
            return item

        # Pass 1, ISRC + name together, through /bulk.
        self.message.emit(f"Looking up {total} track(s)…")
        queued, missed = self._bulk_pass(self.jobs, full, "freqblog")

        # No re-poll here: queued tracks are being analysed and get asked about again
        # later (Store.mark_waiting), which is what keeps a free key inside its allowance.

        # Pass 2, ISRC alone, for tracks FreqBlog said it doesn't have. An exact key;
        # catches names that matched wrongly.
        if missed and not self._stop and not self.fb_rejected:
            have_isrc = [(t, f) for t, f in missed if t.isrc]
            if have_isrc:
                self.message.emit(f"Retrying {len(have_isrc)} by ISRC…")
                still = []
                for n, (trk, f) in enumerate(have_isrc):
                    if self._stop:
                        still.extend(have_isrc[n:])
                        break
                    try:
                        self.calls += 1
                        self.requests += 1
                        feat = self.fb.lookup_isrc(trk.isrc)
                    except KeyRejected:
                        self.fb_rejected = True
                        self.keyRejected.emit("FreqBlog")
                        still.extend(have_isrc[n:])
                        break
                    except ProviderError as e:
                        self.message.emit(str(e))
                        still.append((trk, f))
                        continue
                    if feat.bpm or feat.camelot:
                        self._emit(trk, feat, "freqblog")
                    elif feat.pending:
                        queued.append((trk, feat))
                    else:
                        still.append((trk, feat))
                missed = still + [(t, f) for t, f in missed if not t.isrc]

        # Pass 3, cleaned title / first artist only, through /bulk.
        if missed and not self._stop and not self.fb_rejected:
            retry = [t for t, _ in missed
                     if clean_title(t.title) or
                     (primary_artist(t.artist) and primary_artist(t.artist) != t.artist)]
            if retry:
                self.message.emit(f"Retrying {len(retry)} with cleaned titles…")

                def cleaned(t: Track) -> dict:
                    return {"track": clean_title(t.title) or t.title,
                            "artist": primary_artist(t.artist) or t.artist}

                q2, m2 = self._bulk_pass(retry, cleaned, "freqblog")
                settled = {id(t) for t in retry} - {id(t) for t, _ in m2}
                missed = [(t, f) for t, f in missed if id(t) not in settled]
                queued += q2

        # Pass 4, GetSongBPM. Thin coverage here, but free and already keyed. It also
        # gets a try at queued tracks: an answer there saves FreqBlog a re-check.
        if (missed or queued) and not self._stop and self.gs.api_key:
            pool = missed + queued
            self.message.emit(f"Trying GetSongBPM for the last {len(pool)}…")
            found = set()
            for n, (trk, _) in enumerate(pool):
                if self._stop:
                    break
                try:
                    feat = self.gs.lookup(trk.title, trk.artist)
                except KeyRejected:
                    self.keyRejected.emit("GetSongBPM")
                    break
                except ProviderError:
                    continue
                if feat.bpm or feat.camelot:
                    self._emit(trk, feat, "getsongbpm")
                    found.add(id(trk))
            missed = [(t, f) for t, f in missed if id(t) not in found]
            queued = [(t, f) for t, f in queued if id(t) not in found]

        # when to ask again: recorded by the window (Store.mark_waiting)
        if not self.fb_rejected:
            for trk, f in queued:
                self.waiting.emit(trk, "queued", f.retry_after_days)
            for trk, f in missed:
                self.waiting.emit(trk, "missing", f.retry_after_days)

        tail = []
        if queued:
            tail.append(f"{len(queued)} being analysed by FreqBlog, checked again in a few "
                        "minutes")
        if missed:
            tail.append(f"{len(missed)} not found anywhere, type those in")
        self.message.emit(f"Fetched {self._got} of {total}." +
                          (" " + "; ".join(tail) + "." if tail else ""))
        self.done.emit()


# --------------------------------------------------------------------------
# About
# --------------------------------------------------------------------------

class PlaylistTargetDialog(QDialog):
    """Where do freshly-found tracks go when nothing is open?

    Without this the finder dropped tracks into an untitled list that was never
    written to disk, so nothing autosaved and the work was one crash from gone.
    """

    def __init__(self, store, count: int, loose: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add tracks to…")
        self.setMinimumWidth(430)
        self.store = store

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "<p>No playlist is open. Where should these "
            f"<b>{count}</b> track{'s' if count != 1 else ''} go?</p>"))

        self.grp = QButtonGroup(self)

        self.r_new = QRadioButton("New playlist")
        self.r_new.setChecked(True)
        self.grp.addButton(self.r_new)
        lay.addWidget(self.r_new)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name it…")
        lay.addWidget(self.name)

        names = store.list_playlists() if store else []
        self.r_old = QRadioButton("Add to a saved playlist")
        self.r_old.setEnabled(bool(names))
        self.grp.addButton(self.r_old)
        lay.addWidget(self.r_old)
        self.combo = QComboBox()
        self.combo.addItems(names)
        self.combo.setEnabled(False)
        lay.addWidget(self.combo)

        if loose:
            # Loading a saved playlist replaces whatever is on screen, so say so
            # rather than letting unsaved rows vanish.
            self.warn = QLabel(
                f"<span style='color:#E8A93E'>{loose} track"
                f"{'s' if loose != 1 else ''} already on screen "
                "would be replaced by the saved playlist.</span>")
            self.warn.setWordWrap(True)
            self.warn.setVisible(False)
            lay.addWidget(self.warn)
        else:
            self.warn = None

        self.r_new.toggled.connect(self._sync)
        self._sync()

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _sync(self):
        new = self.r_new.isChecked()
        self.name.setEnabled(new)
        self.combo.setEnabled(not new)
        if self.warn is not None:
            self.warn.setVisible(not new)
        (self.name if new else self.combo).setFocus()

    def _ok(self):
        if self.r_new.isChecked() and not self.name.text().strip():
            self.name.setFocus()
            return
        self.accept()

    def choice(self) -> tuple:
        """("new"|"existing", name)"""
        if self.r_new.isChecked():
            return "new", self.name.text().strip()
        return "existing", self.combo.currentText()


SUPPORT_URL = "https://buymeacoffee.com/crazy8697"
SUPPORT_TEXT = "Buy DarkRelay some cheese 🧀"


def _brand_asset(*parts) -> Path:
    import sys as _sys
    base = Path(getattr(_sys, "_MEIPASS", "")) if getattr(_sys, "frozen", False)         else Path(__file__).resolve().parent.parent
    return base.joinpath("assets", *parts)


class _Backdrop(QWidget):
    """The DarkRelay banner behind the About content, as in Lazarus PDF: cropped so
    the relay node sits to the right, darkened most on the left where the text is."""

    def __init__(self):
        super().__init__()
        p = _brand_asset("brand", "darkrelay-banner.jpg")
        self._src = QPixmap(str(p)) if p.exists() else QPixmap()
        self._cache = None

    def paintEvent(self, e):
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor(theme.BG))
        if not self._src.isNull():
            if self._cache is None or self._cache.size() != r.size():
                sw, sh = self._src.width(), self._src.height()
                cw = min(sw, int(sh * r.width() / max(1, r.height())))
                x0 = max(0, min(sw - cw, int(sw / 2 - cw * 0.78)))
                self._cache = self._src.copy(x0, 0, cw, sh).scaled(
                    r.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(0, 0, self._cache)
        g = QLinearGradient(0, 0, r.width(), 0)
        g.setColorAt(0.0, QColor(5, 7, 10, 238))
        g.setColorAt(0.62, QColor(5, 7, 10, 210))
        g.setColorAt(1.0, QColor(5, 7, 10, 130))
        p.fillRect(r, QBrush(g))
        p.end()


def about_html() -> str:
    """Built when the dialog opens, so the felt-BPM fold shown is the one in use."""
    from . import domain
    link = theme.LINK
    a = lambda url, text: f"<a href='{url}'><span style='color:{link}'>{text}</span></a>"
    return f"""
<p style="font-size:15px;margin:0 0 10px 0"><b>Orders playlists so they flow, by musical key
and tempo. Works with Spotify.</b></p>
<p>Load a playlist, fill in BPM and Camelot key, see where the seams between tracks will
fight you, reorder, and push the new order back. BPM and key values are estimates from
automated audio analysis, not authoritative data: trust your ears over the numbers.</p>
<p style="color:{theme.MUTED}">Felt BPM halves anything at {domain.FELT_FOLD} BPM or above
(the fold is a Display setting): in trap-influenced music the snare lands on 3 rather than
2 and 4, so a fast count feels half-time.</p>
<p><b>Credits</b><br>
Audio analysis by {a("https://freqblog.com", "FreqBlog")}.<br>
Optional fallback BPM data from {a("https://getsongbpm.com", "GetSongBPM")}, when you add your own key.<br>
Playlist and track metadata from {a("https://open.spotify.com", "Spotify")}.<br>
<span style="color:{theme.MUTED}">Playlist Flow is not made, endorsed or supported by Spotify,
FreqBlog or GetSongBPM.</span></p>
<p><b>Network</b>: besides Spotify and the BPM/key services you set up yourself, the only
request is GitHub's latest-release lookup for Playlist Flow (at startup if Settings &gt;
Display &gt; "Check for updates at startup" is on, or Help &gt; Check for updates) and, if
you choose to update, the installer download. No telemetry. While setup's Spotify sign-in
step waits for your browser, it listens on 127.0.0.1 (this PC only) and stops as soon as the
sign-in arrives.</p>
<p style="margin-top:12px">By <b>DarkRelay</b> &nbsp;&middot;&nbsp; {a("https://darkrelay.net", "darkrelay.net")}
&nbsp;&middot;&nbsp; Version {__version__}<br>
Free software under the Apache License 2.0; it comes with NO WARRANTY. The components it
includes are under their own licenses (Licenses below).<br>
Source code: {a(__url__, __url__)}</p>
"""


class AboutDialog(QDialog):
    """DarkRelay About, the Lazarus PDF layout. Carries the attribution links: the
    FreqBlog credit, GetSongBPM's required backlink, and the Spotify logo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Playlist Flow")
        self.setMinimumSize(680, 620)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.backdrop = _Backdrop()
        outer.addWidget(self.backdrop)
        v = QVBoxLayout(self.backdrop)
        v.setContentsMargins(26, 22, 26, 16)
        head = QHBoxLayout()
        icon = QLabel()
        icon.setStyleSheet("background: transparent;")
        icon.setPixmap(icon_pixmap(64))
        head.addWidget(icon, 0, Qt.AlignTop)
        title = QLabel(
            "<span style='font-size:22px;font-weight:700;color:#ffffff'>Playlist Flow</span><br>"
            f"<span style='color:{theme.MUTED}'>Version {__version__}</span>")
        title.setStyleSheet("background: transparent;")
        head.addSpacing(10)
        head.addWidget(title, 1, Qt.AlignVCenter)
        v.addLayout(head)
        v.addSpacing(8)
        self.body = QLabel(about_html())
        self.body.setObjectName("about_body")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setOpenExternalLinks(True)
        self.body.setStyleSheet(f"color:{theme.TEXT};font-size:13px;background:transparent")
        self.body.setMaximumWidth(580)
        v.addWidget(self.body)
        # the Spotify credit above names Spotify content: the logo attributes it
        sp = logo_label(full=True, size=96, tip="Playlist and track metadata from Spotify")
        sp.setStyleSheet("background: transparent;")
        v.addWidget(sp, 0, Qt.AlignLeft)
        v.addStretch(1)
        row = QHBoxLayout()
        self.btn_licenses = QPushButton("Licenses…")
        self.btn_licenses.clicked.connect(lambda: LicensesDialog(self).exec())
        row.addWidget(self.btn_licenses)
        self.btn_privacy = QPushButton("Privacy policy")
        self.btn_privacy.clicked.connect(lambda: DocDialog("PRIVACY.md", self).exec())
        row.addWidget(self.btn_privacy)
        self.btn_terms = QPushButton("End user agreement")
        self.btn_terms.clicked.connect(lambda: DocDialog("TERMS.md", self).exec())
        row.addWidget(self.btn_terms)
        self.btn_support = QPushButton(SUPPORT_TEXT)
        self.btn_support.setToolTip("Opens DarkRelay's Buy Me a Coffee page in your browser")
        self.btn_support.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SUPPORT_URL)))
        row.addWidget(self.btn_support)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        row.addWidget(bb)
        v.addLayout(row)


DOC_TITLES = {"PRIVACY.md": "Privacy policy", "TERMS.md": "End user agreement"}


class DocDialog(QDialog):
    """One shipped document (the privacy policy or the end user agreement), readable."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        from .docs import read_doc
        self.setWindowTitle(f"Playlist Flow: {DOC_TITLES.get(name, name).lower()}")
        self.resize(760, 640)
        v = QVBoxLayout(self)
        tb = QTextBrowser()
        tb.setObjectName("doc_text")
        tb.setOpenExternalLinks(True)
        tb.setMarkdown(read_doc(name))
        v.addWidget(tb, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


class LicensesDialog(QDialog):
    """Help > Licenses: Playlist Flow's own license and the third-party notices, with
    the folder of full license texts one click away (the Lazarus PDF layout)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from .docs import read_doc, licenses_dir
        self.setWindowTitle("Playlist Flow: licenses")
        self.resize(840, 660)
        v = QVBoxLayout(self)
        intro = QLabel("Playlist Flow is free software under the Apache License 2.0. It includes the "
                       "third-party components listed in the notices, each under its own license; "
                       "their full texts are in the licenses folder next to the program.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        tabs = QTabWidget()
        for title, name, md in (("Third-party notices", "THIRD-PARTY-NOTICES.md", True),
                                ("Playlist Flow (Apache-2.0)", "LICENSE", False)):
            tb = QTextBrowser()
            tb.setOpenExternalLinks(True)
            if md:
                tb.setMarkdown(read_doc(name))
            else:
                tb.setPlainText(read_doc(name))
            tabs.addTab(tb, title)
        v.addWidget(tabs, 1)
        row = QHBoxLayout()
        b = QPushButton("Open the licenses folder")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(licenses_dir()))))
        row.addWidget(b)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        v.addLayout(row)


class DisconnectDialog(QDialog):
    """Settings > Disconnect Spotify: confirm, with a separate, unticked choice to also
    delete the saved playlists and remembered BPM/key values."""

    def __init__(self, folder: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Disconnect Spotify")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        lab = QLabel("<p><b>Disconnect Playlist Flow from your Spotify account?</b></p>"
                     "<p>This removes the Spotify sign-in from this PC straight away and clears "
                     "the Spotify data the program is holding. You can sign in again later "
                     "(File &gt; Sign in to Spotify).</p>"
                     "<p>To also remove its access on Spotify's side, open "
                     "<a href='https://www.spotify.com/account/apps/'>spotify.com/account/apps</a>.</p>")
        lab.setWordWrap(True)
        lab.setOpenExternalLinks(True)
        v.addWidget(lab)
        self.delete_box = QCheckBox(f"Also delete my saved playlists and remembered BPM/key values "
                                    f"in {folder}")
        self.delete_box.setObjectName("delete_box")
        self.delete_box.setChecked(False)
        v.addWidget(self.delete_box)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Disconnect")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------

class _StartupCheck(QThread):
    """auth.check() off the UI thread: one token refresh, a few seconds at most."""
    result = Signal(str)

    def __init__(self, auth, parent=None):
        super().__init__(parent)
        self.auth = auth

    def run(self):
        try:
            self.result.emit(self.auth.check())
        except Exception:
            self.result.emit("offline")


def setup_needed(env: dict, auth_state: str) -> str:
    """Why the wizard has to run, or "" when the setup works. auth_state is
    auth.check(): "ok", "dead", "none" or "offline". Offline is not a reason: the
    stored sign-in can't be judged without a connection, and saved playlists still
    work, so a dead token there is caught later by the sign-in popup."""
    if not env.get("SPOTIFY_CLIENT_ID"):
        return "no Spotify client ID"
    if not env.get("FREQBLOG_API_KEY"):
        return "no FreqBlog key"
    if auth_state == "none":
        return "not signed in to Spotify"
    if auth_state == "dead":
        return "the Spotify sign-in no longer works"
    return ""


class MainWindow(QMainWindow):
    spotifyDead = Signal()            # SpotifyAuth.on_dead, from any thread

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
        self.current_desc = ""
        self.current_image = ""
        # seam_key() ids the user has listened to and approved
        self.approved: set = set()
        self.worker: FetchWorker | None = None
        self.wheel: KeyWheelDialog | None = None
        self._refreshing_spotify = False
        self._sort_field = ""
        self._sort_desc = False

        self.auth = SpotifyAuth(self.env.get("SPOTIFY_CLIENT_ID", ""), self.prefs,
                                port=redirect_port(self.env))
        self.auth.on_dead = self.spotifyDead.emit
        self.spotifyDead.connect(self._spotify_dead)
        self._warned: set[str] = set()     # once-per-session popups already shown
        self._startup_check: _StartupCheck | None = None
        self.spotify = Spotify(self.auth)
        self.freqblog = FreqBlog(self.env.get("FREQBLOG_API_KEY", ""))
        self.getsongbpm = GetSongBPM(self.env.get("GETSONGBPM_API_KEY", ""))

        self.store: Store | None = None
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(AUTOSAVE_MS)
        self._autosave.timeout.connect(self._write_auto)
        # the one automatic re-check of tracks FreqBlog queued (see _schedule_recheck)
        self._recheck = QTimer(self)
        self._recheck.setSingleShot(True)
        self._recheck.timeout.connect(self._run_recheck)

        # Transport polling. Spotify has no push channel, so the bar is driven
        # by polling, slow when idle, quicker while something is playing.
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
        self._build_update_bar()
        self._dirty = False
        self._apply_display()
        self._restore_layout()
        QTimer.singleShot(0, self._start)
        if self.prefs.update_check:
            # tied to this window: a window closed before the delay never checks
            QTimer.singleShot(UPDATE_STARTUP_DELAY_MS, self,
                              lambda: self.check_updates(quiet=True))

    def _start(self):
        """Check the stored setup in the background, then either carry on or run the
        wizard. The window stays disabled until that is decided."""
        self.centralWidget().setEnabled(False)
        for bar in self.tool_groups:
            bar.setEnabled(False)
        self.busy_on("Checking your setup…")
        if setup_needed(self.env, "ok"):              # a key is missing: no need to ask Spotify
            self._after_check("none")
            return
        c = self._startup_check = _StartupCheck(self.auth, self)
        c.result.connect(self._after_check)
        c.start()

    def _after_check(self, state: str):
        self.busy_off()
        need = setup_needed(self.env, state)
        if need:
            self.status(f"Setup needed: {need}.")
            if not self.open_wizard(required=True):
                return                    # quit chosen; the window is closing
        elif state == "offline":
            self.status("Couldn't reach Spotify to check your sign-in. Saved playlists still work.")
        self.centralWidget().setEnabled(True)
        for bar in self.tool_groups:
            bar.setEnabled(True)
        self._ensure_storage()

    # ---------------- setup wizard and key problems ----------------

    def open_wizard(self, start: int = 0, required: bool = False) -> bool:
        """Run the setup wizard. True once it was finished and saved. A required
        run that is quit closes the program."""
        from .wizard import SetupWizard
        old_dir = self.prefs.storage_dir
        dlg = SetupWizard(self.auth, self.prefs, self, start=start, required=required)
        ok = dlg.exec() == QDialog.Accepted and dlg.saved
        if not ok:
            if required:
                QTimer.singleShot(0, self.close)
                QTimer.singleShot(0, QApplication.instance().quit)
            return False
        self._reload_env()
        self._warned.clear()
        if self.prefs.storage_dir != old_dir and self.store is not None:
            self._open_store(self.prefs.storage_dir)
            self.refresh_saved()
        self.status("Setup saved.")
        if self.auth.authorised and self.store is not None:
            QTimer.singleShot(0, self.refresh_spotify)
            self._poll.start()
        return True

    def _key_rejected(self, provider: str):
        """FreqBlog or GetSongBPM refused its key: say so once per session, with a
        straight route to that key's step."""
        from .wizard import FREQBLOG, GETSONGBPM
        if provider in self._warned:
            return
        self._warned.add(provider)
        step = FREQBLOG if provider == "FreqBlog" else GETSONGBPM
        box = QMessageBox(self)
        box.setObjectName("key_rejected")
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(f"{provider} key not working")
        box.setText(f"{provider} turned down your key, so it isn't being used for now.")
        box.setInformativeText("It may be mistyped, revoked or suspended. Tracks still get "
                               "BPM and key from the other sources, and you can type values "
                               "in yourself. Fix the key to bring it back.")
        fix = box.addButton(f"Fix the {provider} key", QMessageBox.AcceptRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is fix:
            self.open_wizard(start=step)

    def _spotify_dead(self):
        """The stored Spotify sign-in was refused and could not be refreshed."""
        from .wizard import LOGIN
        if "Spotify" in self._warned:
            return
        self._warned.add("Spotify")
        box = QMessageBox(self)
        box.setObjectName("spotify_dead")
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Spotify sign-in expired")
        box.setText("Spotify no longer accepts Playlist Flow's sign-in, so playlists and "
                    "playback from Spotify are paused.")
        box.setInformativeText("This happens when access is removed from your Spotify app, the "
                               "app's allowlist changes, or the sign-in simply expired. Signing "
                               "in again fixes it.")
        again = box.addButton("Sign in again", QMessageBox.AcceptRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is again:
            self.open_wizard(start=LOGIN)

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

        # sidebar: two boxed sections, Lazarus PDF's side-panel style
        side = QWidget()
        side.setMinimumWidth(200)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)

        sp_box = QGroupBox()
        sp_box.setObjectName("spotify_box")
        spl = QVBoxLayout(sp_box)
        spl.setContentsMargins(8, 4, 8, 8)
        spl.setSpacing(6)
        sp_head = QHBoxLayout()
        sp_head.setSpacing(4)
        # the playlists listed here are Spotify content: attributed with the logo
        self.sp_logo = logo_label(full=True, size=84,
                                  tip="Your playlists on Spotify")
        sp_head.addWidget(self.sp_logo)
        sp_head.addStretch(1)
        sp_head.addWidget(self._panel_btn("folder-open-outline", "Load the selected playlist",
                                          self.load_from_spotify))
        sp_head.addWidget(self._panel_btn("refresh", "Refresh the list from Spotify",
                                          self.refresh_spotify))
        spl.addLayout(sp_head)
        self.sp_list = QListWidget()
        self.sp_list.itemDoubleClicked.connect(lambda _: self.load_from_spotify())
        # every playlist listed links back to itself on Spotify
        self.sp_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sp_list.customContextMenuRequested.connect(self._sp_list_menu)
        spl.addWidget(self.sp_list, 1)
        sl.addWidget(sp_box, 1)

        saved_box = QGroupBox("SAVED PLAYLISTS")
        svl = QVBoxLayout(saved_box)
        svl.setContentsMargins(8, 8, 8, 8)
        svl.setSpacing(6)
        self.saved_list = QListWidget()
        self.saved_list.itemDoubleClicked.connect(lambda _: self.load_saved())
        svl.addWidget(self.saved_list, 1)
        ops = QHBoxLayout()
        ops.setSpacing(4)
        for icon_name, tip, slot in (
            ("folder-open-outline", "Load the selected playlist", self.load_saved),
            ("pencil-outline", "Rename the selected playlist", self.rename_saved),
            ("delete-outline", "Delete the selected playlist", self.delete_saved),
            ("delete-sweep-outline", "Delete all saved playlists", self.delete_all_saved),
        ):
            ops.addWidget(self._panel_btn(icon_name, tip, slot))
        ops.addStretch(1)
        ops.addWidget(self._panel_btn("folder-cog-outline", "Change the folder playlists are saved in",
                                      self.choose_storage))
        svl.addLayout(ops)
        sl.addWidget(saved_box, 1)
        outer.addWidget(side)

        # main column
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(9)
        self._build_toolbars()

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
        self.table.copyRequested.connect(self.copy_tracks)
        self.table.earCheckToggled.connect(self.toggle_ear_check)
        self.table.edited.connect(self.edit_cell)
        self.table.deleteRequested.connect(self.delete_rows)
        self.table.openInSpotify.connect(self.open_track_in_spotify)
        self.table.itemSelectionChanged.connect(self._sync_selection)
        # Double-click plays from that row, but BPM and Key use double-click
        # to start editing, so leave those two columns alone.
        self.table.itemDoubleClicked.connect(
            lambda it: None if it.column() in (COL_BPM, COL_KEY)
            else self.play_from(it.row()))
        self.table.setMinimumHeight(120)
        self.vsplit.addWidget(self.table)
        self.vsplit.setStretchFactor(0, 0)
        self.vsplit.setStretchFactor(1, 1)

        # bottom strip, what this playlist IS, rather than controls.
        # Adding tracks by hand and the URI block both moved out: the finder
        # covers the first, and the second is a once-per-session action that
        # does not need permanent screen space.
        info = QWidget()
        il = QHBoxLayout(info)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(10)

        self.pl_cover = QLabel()
        self.pl_cover.setFixedSize(COVER, COVER)
        self.pl_cover.setObjectName("cover")
        il.addWidget(self.pl_cover)

        meta = QVBoxLayout()
        meta.setSpacing(4)

        # Name and Save share a line above the box they act on, rather than
        # the button floating in a column of its own beside everything.
        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        # A playlist of Spotify tracks is Spotify content: attributed with the full
        # logo (partner integrations use the full logo, the icon alone is for app
        # icons), inside its clear space, and linked back to the playlist on Spotify.
        self.pl_spotify = logo_label(full=True, size=76,
                                     tip="Track names and artwork from Spotify")
        self.pl_spotify.setObjectName("pl_spotify_logo")
        self.pl_spotify.setVisible(False)
        head_row.addWidget(self.pl_spotify)
        self.pl_name = theme.elided_label("No playlist open", "plname")
        head_row.addWidget(self.pl_name, 1)
        self.pl_count = QLabel("")
        self.pl_count.setObjectName("plcount")
        head_row.addWidget(self.pl_count)
        self.pl_open = spotify_link("Open this playlist in Spotify")
        self.pl_open.setObjectName("pl_open_spotify")
        head_row.addWidget(self.pl_open)
        # an icon button beside the description, so the header row has room for the
        # Spotify logo's clear space at any window size
        self.btn_desc = self._panel_btn("content-save-outline", "Save description: write it "
                                        "back to the Spotify playlist. Saved with the local "
                                        "playlist either way.", self.save_description)
        self.btn_desc.setObjectName("save_desc")
        meta.addLayout(head_row)

        self.pl_desc = QPlainTextEdit()
        self.pl_desc.setPlaceholderText("Add an optional description")
        self.pl_desc.setTabChangesFocus(True)
        # Expands to fill the strip, so its bottom edge lands exactly level
        # with the cover's -- a fixed height left the cover overhanging the
        # text column and looking cropped.
        desc_row = QHBoxLayout()
        desc_row.setSpacing(6)
        desc_row.addWidget(self.pl_desc, 1)
        desc_row.addWidget(self.btn_desc, 0, Qt.AlignTop)
        meta.addLayout(desc_row, 1)
        il.addLayout(meta, 1)

        # Deliberately NOT in the splitter: this is reference material to judge
        # tracks against while working, so it must not be draggable shut.
        # Left half: what this playlist is. Right half: what is playing.
        strip = QHBoxLayout()
        # Default layout margins (~9px a side) were quietly eating the strip's
        # fixed height: the 88px cover only had 70px to live in, and its bottom
        # was clipped -- which is exactly what showed on screen.
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(12)
        strip.addWidget(info, 1)

        self.player = PlayerBar()
        self.player.playPauseClicked.connect(self.toggle_play)
        self.player.prevClicked.connect(lambda: self._player_do("previous"))
        self.player.nextClicked.connect(lambda: self._player_do("next"))
        self.player.seekRequested.connect(lambda ms: self._player_do("seek", ms))
        self.player.previewClicked.connect(self.preview_transition)
        strip.addWidget(self.player, 1)

        strip_w = QWidget()
        strip_w.setLayout(strip)
        strip_w.setFixedHeight(COVER)
        cl.addWidget(strip_w)

        outer.addWidget(col)
        outer.setStretchFactor(0, 0)
        outer.setStretchFactor(1, 1)
        outer.setSizes([250, 1030])

    def _panel_btn(self, icon_name: str, tip: str, slot) -> QToolButton:
        """A compact icon button for the side-panel boxes."""
        b = QToolButton()
        b.setObjectName("panelbtn")
        b.setIcon(theme.icon(icon_name, active_ink=False))
        b.setIconSize(QSize(18, 18))
        b.setToolTip(tip)
        b.setAutoRaise(False)
        b.clicked.connect(slot)
        return b

    def _build_toolbars(self):
        """The controls as grouped toolbars, Lazarus PDF style: a small-caps group
        label, a dotted grip to drag the group along the row, icon over label.
        The working readouts (spinner, progress text, seam summary) live in the
        status bar."""
        self.tool_groups: list[QToolBar] = []

        def group(title: str) -> QToolBar:
            bar = QToolBar(title.title(), self)
            bar.setObjectName("tools")
            bar.setMovable(True)
            bar.setFloatable(False)
            bar.setAllowedAreas(Qt.TopToolBarArea)
            bar.setIconSize(QSize(20, 20))
            bar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            bar.setToolTip(f"{title.title()}: drag the dotted handle to move this group")
            lab = QLabel(f" {title} ")
            lab.setObjectName("grouplabel")
            bar.addWidget(lab)
            self.addToolBar(Qt.TopToolBarArea, bar)
            self.tool_groups.append(bar)
            return bar

        def act(bar, text, icon_name, tip, slot=None, checkable=False):
            a = QAction(theme.icon(icon_name), text, self)
            a.setToolTip(tip)
            a.setCheckable(checkable)
            if slot is not None:
                a.triggered.connect(slot)
            bar.addAction(a)
            return a

        view = group("VIEW")
        self.btn_rep = act(view, "Reported", "metronome",
                           "Show the BPM each track reports.",
                           lambda: self.set_felt(False), checkable=True)
        self.btn_felt = act(view, "Felt", "heart-pulse",
                            "Show felt BPM: anything at or above the fold threshold "
                            "(Settings > Display) is halved, the way the pulse actually reads.",
                            lambda: self.set_felt(True), checkable=True)
        bpm_mode = QActionGroup(self)
        bpm_mode.setExclusive(True)
        bpm_mode.addAction(self.btn_rep)
        bpm_mode.addAction(self.btn_felt)
        self.btn_rep.setChecked(not self.felt)
        self.btn_felt.setChecked(self.felt)
        act(view, "Key wheel", "chart-donut",
            "Camelot wheel. Follows the selected track and lights the keys that mix "
            "with it. Stays open while you work.", self.open_wheel)

        srt = group("SORT")
        act(srt, "By key", "sort-alphabetical-ascending",
            "Sort straight down the wheel, 1A, 1B, 2A, 2B…\n"
            "Click again to reverse. Tracks with no key go last.",
            lambda: self.sort_tracks("key"))
        act(srt, "By BPM", "sort-numeric-ascending",
            "Sort by the BPM currently shown (reported or felt).\n"
            "Click again to reverse. Tracks with no BPM go last.",
            lambda: self.sort_tracks("bpm"))

        data = group("DATA")
        act(data, "Fetch", "cloud-download-outline",
            "Look up any BPM and key still missing (estimates, Ctrl+F).", self.fetch_features)
        act(data, "Analyze", "chart-timeline-variant",
            "Recompute the chart and the key/tempo readout between every pair of "
            "tracks from the current BPM and key values.", self.reanalyze)

        sync = group("PLAYLIST")
        act(sync, "Sync", "sync",
            "Re-read the loaded playlist from Spotify.\n\n"
            "Tracks added there are appended, tracks removed there are removed "
            "here, and everything else keeps the order and the BPM/key it "
            "already has.", self.sync_playlist)
        act(sync, "Push", "upload",
            "Make the Spotify playlist match this window.\n"
            "Adds tracks it does not have, offers to remove ones it has and this "
            "does not, then reorders.", self.push_order)

        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.spinner = Spinner(14)
        sb.addWidget(self.spinner)
        self.busy = QLabel("")
        self.busy.setObjectName("busy")
        sb.addWidget(self.busy)
        self.stat = QLabel("")
        self.stat.setObjectName("stat")
        self.stat.setContentsMargins(0, 0, 10, 0)
        sb.addPermanentWidget(self.stat)


    def _build_menu(self):
        m = self.menuBar().addMenu("&File")
        a = QAction("Load playlist from a &link…", self)
        a.setShortcut(QKeySequence("Ctrl+L"))
        a.triggered.connect(self.load_playlist); m.addAction(a)
        a = QAction("S&ync from Spotify", self)
        a.setShortcut(QKeySequence("Ctrl+R"))
        a.triggered.connect(self.sync_playlist); m.addAction(a)
        a = QAction("&Export URI block…", self)
        a.setShortcut(QKeySequence("Ctrl+E"))
        a.triggered.connect(self.export_uris); m.addAction(a)
        a = QAction("Find tracks in &bulk…", self)
        a.setShortcut(QKeySequence("Ctrl+Shift+F"))
        a.triggered.connect(self.bulk_finder); m.addAction(a)
        m.addSeparator()
        a = QAction("&Save", self); a.setShortcut(QKeySequence.Save)
        a.triggered.connect(self.save_playlist); m.addAction(a)
        a = QAction("&Settings…", self)
        a.triggered.connect(self.open_settings); m.addAction(a)
        a = QAction("Change storage folder…", self)
        a.triggered.connect(self.choose_storage); m.addAction(a)
        m.addSeparator()
        a = QAction("Sign in to Spotify…", self)
        a.triggered.connect(self.sign_in_now); m.addAction(a)
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
            ("Ear-check selected transition", "Ctrl+M", self.ear_check_selected),
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
        a = QAction("Check for &updates…", self)
        a.triggered.connect(lambda: self.check_updates(quiet=False))
        h.addAction(a)
        corner = QWidget()
        cw = QHBoxLayout(corner)
        cw.setContentsMargins(0, 0, 6, 0)
        cw.setSpacing(0)
        for text, tip, slot in (
            ("Undo", "Undo the last change (Ctrl+Z).", self.undo),
            ("Save", "Save this playlist (Ctrl+S).", self.save_playlist),
        ):
            b = QPushButton(text)
            b.setObjectName("menubtn")
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            cw.addWidget(b)
        # Keep a Python-side reference: PySide's wrapper has been seen
        # dropping corner widgets whose only owner is the C++ side.
        self._menu_corner = corner
        self.menuBar().setCornerWidget(corner, Qt.TopRightCorner)
        h.addSeparator()
        a = QAction("&Licenses…", self)
        a.triggered.connect(lambda: LicensesDialog(self).exec())
        h.addAction(a)
        a = QAction("&Privacy policy", self)
        a.triggered.connect(lambda: DocDialog("PRIVACY.md", self).exec())
        h.addAction(a)
        a = QAction("&End user agreement", self)
        a.triggered.connect(lambda: DocDialog("TERMS.md", self).exec())
        h.addAction(a)
        h.addSeparator()
        a = QAction(SUPPORT_TEXT, self)
        a.setToolTip("Opens DarkRelay's Buy Me a Coffee page in your browser")
        a.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(SUPPORT_URL)))
        h.addAction(a)
        a = QAction("&About Playlist Flow", self)
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
        add("Ctrl+M", self.ear_check_selected)
        add("Ctrl+P", lambda: self.preview_transition(self.player.tail.value()))
        add("Ctrl+F", self.fetch_features)
        add("Ctrl+Shift+F", self.bulk_finder)

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
        self.status(f"{t.artist}, {t.title}: type the {what}. Ctrl+B for the next.")

    # ---------------- storage ----------------

    # ---------------- updates ----------------

    def _build_update_bar(self):
        """The update bar: a strip in the status bar, hidden until a newer release is
        found. Never a popup, and none of its buttons take the focus."""
        self._upd_checker: UpdateChecker | None = None
        self._upd_dl: UpdateDownloader | None = None
        self._update_info: dict | None = None
        self._update_last: dict | None = None     # last outcome, read by tests
        bar = self.update_bar = QWidget()
        bar.setObjectName("update_bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(6)
        self.update_label = QLabel("")
        self.update_label.setObjectName("update_label")
        row.addWidget(self.update_label)

        def btn(text, name, slot):
            b = QPushButton(text)
            b.setObjectName(name)
            b.setProperty("class", "inline")
            b.setStyleSheet("padding: 2px 10px; font-size: 11px;")
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b

        self.update_notes_btn = btn("Release notes", "update_notes", self._show_release_notes)
        self.update_install_btn = btn("Download and install", "update_install",
                                      lambda: self._start_update_download())
        self.update_skip_btn = btn("Skip this version", "update_skip", self._skip_update)
        self.update_later_btn = btn("Later", "update_later", self._later_update)
        bar.hide()
        self.statusBar().addPermanentWidget(bar)

    def _update_bar_buttons(self, enabled: bool):
        for b in (self.update_notes_btn, self.update_install_btn,
                  self.update_skip_btn, self.update_later_btn):
            b.setEnabled(enabled)

    def check_updates(self, quiet: bool = True) -> bool:
        """Ask GitHub for the latest release, in a thread. quiet=True is the startup
        check: it says nothing unless a newer version is out, and then only in the
        update bar."""
        try:
            if self._upd_checker is not None and self._upd_checker.isRunning():
                if not quiet:
                    self.status("Already checking for updates…")
                return False
            c = self._upd_checker = UpdateChecker(self)
            c.result.connect(lambda d, q=quiet: self._on_update_result(d, q))
            c.finished.connect(c.deleteLater)
            c.finished.connect(lambda c=c: self._forget_checker(c))
            c.start()
            if not quiet:
                self.status("Checking GitHub for a newer Playlist Flow…")
            return True
        except Exception:
            return False

    def _forget_checker(self, c):
        if self._upd_checker is c:
            self._upd_checker = None

    def _on_update_result(self, res: dict, quiet: bool):
        self._update_last = res
        st = res.get("status")
        if st == "newer":
            if quiet and res["version"] == self.prefs.update_skip:
                return                   # skipped: quiet (a newer one still shows)
            self._update_info = res
            self.update_label.setText(f"Playlist Flow {res['version']} is available")
            self._update_bar_buttons(True)
            self.update_bar.show()
            return
        if quiet:
            return                       # startup: quiet unless there's news
        if st in ("current", "none"):
            QMessageBox.information(self, "Updates",
                                    f"Playlist Flow is up to date ({__version__}).")
        else:
            QMessageBox.warning(self, "Updates", "Couldn't check for updates: "
                                f"{res.get('reason', 'unknown error')}")

    def _show_release_notes(self):
        info = self._update_info
        if not info:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Playlist Flow {info['version']}: release notes")
        dlg.resize(620, 460)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(f"<b>Playlist Flow {info['version']}</b>&nbsp;&nbsp;"
                           f"<span style='color:#8C939D'>this is {__version__}</span>"))
        notes = (info.get("notes") or "").strip()
        page = info.get("page") or RELEASES_URL
        tb = QTextBrowser()
        tb.setObjectName("release_notes")
        tb.setOpenExternalLinks(True)
        if notes:
            tb.setMarkdown(notes)
        else:
            tb.setHtml(f"This release has no notes. See the release page:<br>"
                       f"<a href='{page}'>{page}</a>")
        v.addWidget(tb, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        inst = QPushButton("Download and install")
        inst.clicked.connect(lambda: (dlg.accept(), self._start_update_download()))
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(dlg.reject)
        row.addWidget(inst)
        row.addWidget(close)
        v.addLayout(row)
        dlg.exec()

    def _skip_update(self):
        info = self._update_info
        if info:
            self.prefs.update_skip = info["version"]
            self.status(f"Playlist Flow {info['version']} skipped. A newer version will "
                        "still show.")
        self.update_bar.hide()

    def _later_update(self):
        """Hide the bar for this session; the next startup check offers it again."""
        self.update_bar.hide()

    def _start_update_download(self, info=None) -> bool:
        info = info if isinstance(info, dict) else self._update_info
        if not info:
            return False
        if self._upd_dl is not None and self._upd_dl.isRunning():
            self.status("Already downloading the update…")
            return False
        if not can_install() and not os.environ.get("PLAYLISTFLOW_UPDATE_DRYRUN"):
            self._update_last = {"status": "refused", "reason": "source run"}
            self.update_label.setText(
                f"Playlist Flow {info['version']} is available. This is a source run, "
                "so get the installer from the Releases page.")
            return False
        self._update_bar_buttons(False)
        self.update_label.setText(f"Downloading Playlist Flow {info['version']}…")
        d = self._upd_dl = UpdateDownloader(info, self)
        d.progress.connect(self._update_progress)
        d.done.connect(lambda path, err, info=info: self._on_update_downloaded(path, err, info))
        d.start()
        return True

    def _update_progress(self, done: int, total: int):
        if total:
            self.update_label.setText(
                f"Downloading update… {done * 100 // max(1, total)}% "
                f"({done // 1048576} / {max(1, total // 1048576)} MB)")
        else:
            self.update_label.setText(f"Downloading update… {done // 1048576} MB")

    def _on_update_downloaded(self, path, err: str, info: dict):
        if self._upd_dl is not None:
            self._upd_dl.wait()
        if err:
            self._update_last = {"status": "download-error", "reason": err}
            self.update_label.setText(
                "Update download cancelled." if err == "cancelled" else err)
            self._update_bar_buttons(True)
            return
        self._install_update(path, info)

    def _install_update(self, setup: str, info: dict) -> bool:
        """Close the window the normal way (the unsaved-changes prompt still runs), start
        the verified Setup silently, quit. Setup replaces the files and starts Playlist
        Flow again, unelevated (/RELAUNCH=1)."""
        try:
            if not self.close():
                self._update_last = {"status": "postponed", "setup": setup}
                self.update_label.setText(
                    f"Playlist Flow {info['version']} is downloaded. Install when you're ready.")
                self._update_bar_buttons(True)
                return False
            if not launch_setup(setup):
                self._update_last = {"status": "launch-failed", "setup": setup}
                QMessageBox.warning(None, "Updates",
                                    "Setup couldn't be started (was the Windows prompt "
                                    "declined?). Nothing was changed.")
                QApplication.instance().quit()
                return False
            self._update_last = {"status": "installing", "setup": setup}
            QApplication.instance().quit()
            return True
        except Exception:
            self._update_last = {"status": "launch-failed", "setup": setup}
            return False

    def open_settings(self):
        dlg = SettingsDialog(self, first_run=False, prefs=self.prefs)
        if dlg.exec() != QDialog.Accepted:
            if getattr(dlg, "run_setup_requested", False):
                self.open_wizard()
            elif getattr(dlg, "disconnect_requested", False):
                self.disconnect_spotify()
            return
        old_dir = self.store.root if self.store else None
        self._reload_env()
        if self.prefs.storage_dir and str(old_dir) != self.prefs.storage_dir:
            self._open_store(self.prefs.storage_dir)
            self.refresh_saved()
        self.status("Settings saved.")

    def _reload_env(self):
        """Rebuild every client so new keys take effect without a restart."""
        self.env = load_env()
        self.auth.client_id = self.env.get("SPOTIFY_CLIENT_ID", "")
        self.auth.port = redirect_port(self.env)
        self.freqblog.api_key = self.env.get("FREQBLOG_API_KEY", "")
        self.getsongbpm.api_key = self.env.get("GETSONGBPM_API_KEY", "")
        self._apply_display()

    def _apply_display(self):
        """Push Display settings into the modules that read them.

        Cheap ones (graph max, fold) apply by repaint; the tolerance changes
        what classify_tempo returns, so refresh() re-runs seams afterwards
        that IS the reclassify.
        """
        d = display_settings(self.env)
        self.display = d
        set_display(felt_fold=d["felt_fold"],
                    tolerance=TOLERANCES[d["tolerance"]],
                    warn_both=d["warn_both"])
        self.chart.fixed_max = float(d["graph_max"])
        self.set_timeline(d["timeline"])
        self.player.tail.setValue(d["preview_s"])
        self._autosave.setInterval(max(1, d["autosave_s"]) * 1000)
        self.refresh(keep_undo=True)

    def _open_store(self, folder) -> bool:
        """Point the window at a playlist folder. A folder that can't be used is said
        plainly (and the previous one, if any, stays in use) instead of crashing."""
        try:
            self.store = Store(folder)
            return True
        except StoreError as e:
            QMessageBox.warning(self, "Playlist folder", str(e))
            self.status(str(e))
            return False

    def _ensure_storage(self):
        d = self.prefs.storage_dir
        if not d:
            d = str(Path.home() / "Documents" / "PlaylistFlow")
            self.prefs.storage_dir = d
        self._open_store(d)
        self.refresh_saved()
        if self.auth.authorised:
            QTimer.singleShot(0, self.refresh_spotify)
            self._poll.start()
            QTimer.singleShot(400, self.poll_player)

    def choose_storage(self):
        d = QFileDialog.getExistingDirectory(self, "Pick a folder for saved playlists",
                                             self.prefs.storage_dir or "")
        if d and self._open_store(d):
            self.prefs.storage_dir = d
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
        try:
            tracks = self.store.load(name)
        except StoreError as e:
            QMessageBox.warning(self, "Open playlist", str(e))
            self.status(str(e))
            return
        self.snapshot()
        self.tracks = tracks
        self.current_pid = self.store.last_loaded_pid
        self.current_desc = self.store.last_loaded_desc
        self.approved = set(self.store.last_loaded_checked)
        self.current_name = name
        self._dirty = False
        self.refresh()
        self.load_details()
        self.status(f"Loaded {name}, {len(self.tracks)} tracks.")

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
        try:
            self.store.save(name, self.tracks, auto=False, pid=self.current_pid,
                            description=self.current_desc,
                            ear_checked=sorted(self.approved))
        except StoreError as e:
            QMessageBox.warning(self, "Save playlist", str(e))
            self.status(str(e))
            return
        self._dirty = False
        self.refresh_saved()
        self.status(f"Saved {name}.")

    def _write_auto(self):
        if not self.display.get("autosave_on", True):
            return
        if self.store and self.current_name and self.tracks:
            try:
                self.store.save(self.current_name, self.tracks, auto=True,
                                pid=self.current_pid, description=self.current_desc,
                                ear_checked=sorted(self.approved))
            except StoreError as e:
                self.status(f"Auto-save failed: {e}")     # said in the status bar, no popup loop

    # ---------------- undo ----------------

    def snapshot(self):
        self._dirty = True
        self.undo_stack.append(copy.deepcopy(self.tracks))
        if len(self.undo_stack) > UNDO_CAP:
            self.undo_stack.pop(0)

    def fetching(self) -> bool:
        return bool(self.worker and self.worker.isRunning())

    def _locked(self, what: str) -> bool:
        """True (and said in the status bar) while a BPM/key fetch runs: reordering,
        deleting or undoing then would change the list under it."""
        if self.fetching():
            self.status(f"Wait for the BPM/key lookup to finish before you {what}.")
            return True
        return False

    def undo(self):
        if self._locked("undo"):
            return
        if not self.undo_stack:
            self.status("Nothing to undo.")
            return
        self.tracks = self.undo_stack.pop()
        self.refresh()
        self.status("Undone.")

    # ---------------- data ops ----------------

    def load_playlist(self):
        """Load by pasted URL or ID, for playlists that aren't on the account,
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
                    f"Owned by {pl.owner}, Spotify will refuse to send its "
                    f"tracks to a Development Mode app."
                )
            self.sp_list.addItem(it)
        self.status(f"{len(lists)} playlists on your account.")

    def _sp_list_menu(self, pos):
        it = self.sp_list.itemAt(pos)
        if it is None:
            return
        from PySide6.QtWidgets import QMenu
        from .brand import link_text
        m = QMenu(self)
        a = m.addAction("Load playlist")
        a.triggered.connect(lambda: (self.sp_list.setCurrentItem(it), self.load_from_spotify()))
        a = m.addAction(link_text().capitalize().replace("spotify", "Spotify"))
        a.triggered.connect(lambda: open_in_spotify("playlist", it.data(Qt.UserRole)))
        m.exec(self.sp_list.viewport().mapToGlobal(pos))

    def open_track_in_spotify(self, row: int):
        if 0 <= row < len(self.tracks):
            uri = self.tracks[row].uri or ""
            if uri.startswith("spotify:track:"):
                open_in_spotify("track", uri.split(":")[-1])

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
        if self._locked("sync"):
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
            self.status(f"Already in sync, {len(self.tracks)} tracks.")
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
        self.status(f"Synced, {len(added)} added, {len(gone)} removed.{tail}")

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
                # Refresh token revoked or expired, retry once after re-auth.
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
        # Ear-checks live only in the local save -- a Spotify fetch knows
        # nothing about them. Pull them back in whenever a save by this name
        # exists; pair-keying means they fit the fresh list safely.
        meta = self.store.meta(self.current_name) if self.store else {}
        self.approved = set(meta.get("ear_checked", []))
        self._dirty = False
        self.refresh()
        self.load_details()
        cached = sum(1 for t in self.tracks if t.resolved)
        self.status(
            f"Loaded {len(self.tracks)} tracks from '{self.current_name}' "
            f"({cached} already known). Hit Fetch BPM/key for the rest."
        )

    def bulk_finder(self):
        """Paste a plain-text song list, resolve it to track URIs.

        Search needs the same user token everything else uses, so an unsigned-in
        user is sent through sign-in first rather than watching every line fail.
        """
        if not self.auth.authorised and not self.sign_in():
            return
        known = {t.uri for t in self.tracks if t.uri}
        dlg = FinderDialog(self.spotify, known, self)
        dlg.send_to_playlist.connect(self._absorb_found)
        dlg.exec()

    def _absorb_found(self, tracks: list):
        """Append resolved tracks, then look up BPM/key for them.

        The lookup runs on the *resolved* title and artist rather than the line
        the user pasted, that metadata is canonical and matches far better.

        Anything already in the playlist is skipped. Sending the same batch
        twice is easy to do by accident, and silently doubling the playlist is
        a worse outcome than saying nothing was added.
        """
        if not tracks:
            return

        # One undo should put things back the way they were, so the snapshot
        # is taken once, after the target dialog is accepted, never on cancel.
        snapped = False

        # Nothing open means nothing autosaves, so ask where these belong
        # before they land in an untitled list.
        if not self.current_name:
            self._ensure_storage()
            if not self.store:
                self.status("Pick a storage folder first.")
                return
            dlg = PlaylistTargetDialog(self.store, len(tracks), len(self.tracks), self)
            if dlg.exec() != QDialog.Accepted:
                self.status("Nothing added, no playlist chosen.")
                return
            how, name = dlg.choice()
            if not name:
                self.status("Nothing added, no playlist chosen.")
                return
            if how == "existing":
                try:
                    loaded = self.store.load(name)
                except StoreError as e:
                    QMessageBox.warning(self, "Open playlist", str(e))
                    self.status(str(e))
                    return
            self.snapshot()
            snapped = True
            if how == "existing":
                self.tracks = loaded
                self.current_pid = self.store.last_loaded_pid
                self.approved = set(self.store.last_loaded_checked)
            else:
                self.current_pid = ""
            self.current_name = name

        have = {t.uri for t in self.tracks if t.uri}
        fresh = [t for t in tracks if not t.uri or t.uri not in have]
        skipped = len(tracks) - len(fresh)

        if not fresh:
            self.status("All %d were already in the playlist, nothing added." % skipped)
            return

        if not snapped:
            self.snapshot()
        for t in fresh:
            if not t.resolved and self.store:
                self.store.apply_cache(t)
            self.tracks.append(t)
        self.refresh()
        if self.store and self.current_name:
            try:
                self.store.save(self.current_name, self.tracks, auto=False,
                                pid=self.current_pid, description=self.current_desc,
                                ear_checked=sorted(self.approved))
            except StoreError as e:
                self.status(str(e))
            self.refresh_saved()
        msg = "Added %d tracks to %s" % (len(fresh), self.current_name or "the playlist")
        if skipped:
            msg += " (skipped %d already there)" % skipped
        self.status(msg + ", fetching BPM/key.")
        QTimer.singleShot(0, self.fetch_features)

    def sign_in(self) -> bool:
        """Make sure there is a working Spotify sign-in; True once there is.

        Called when an action needs Spotify. Already signed in (perhaps just now,
        from the expired-sign-in popup): True straight away. If that popup was
        answered Later this session, don't ask again behind the user's back.
        Otherwise the wizard's sign-in step does it."""
        if self.auth.authorised:
            return True
        if "Spotify" in self._warned:
            self.status("Not signed in to Spotify. Use File > Sign in to Spotify… when you're ready.")
            return False
        return self.sign_in_now()

    def sign_in_now(self) -> bool:
        """File > Sign in to Spotify: always opens the wizard's sign-in step."""
        from .wizard import LOGIN
        if self.open_wizard(start=LOGIN) and self.auth.authorised:
            self.status("Signed in to Spotify.")
            QTimer.singleShot(400, self.poll_player)
            return True
        if not self.auth.authorised:
            self.status("Spotify sign-in cancelled.")
        return self.auth.authorised

    def disconnect_spotify(self) -> bool:
        """Settings > Disconnect Spotify. Removes the sign-in (HKCU and memory) and every
        piece of Spotify account data the program holds; saved playlists and the cache
        go only when the user ticks the separate box. Returns True when it disconnected."""
        folder = self.prefs.storage_dir or str(Path.home() / "Documents" / "PlaylistFlow")
        dlg = DisconnectDialog(folder, self)
        if dlg.exec() != QDialog.Accepted:
            return False
        self._poll.stop()
        self.auth.forget()                       # refresh token out of HKCU, tokens out of memory
        self.sp_list.clear()                     # the user's playlist list from Spotify
        self._last_player_state = None
        self.player.set_offline("Not connected to Spotify")   # drops the now-playing art too
        deleted = []
        if dlg.delete_box.isChecked() and self.store is not None:
            deleted = self.store.delete_program_files()
            self.tracks = []
            self.current_name = ""
            self.current_pid = ""
            self.current_desc = ""
            self.current_image = ""
            self._dirty = False
            self.refresh_saved()
            self.refresh()
            self.show_playlist_info()
        self.status("Disconnected from Spotify." + (f" Deleted {len(deleted)} saved file(s)."
                                                    if deleted else ""))
        return True

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

    def fetch_features(self, force: bool = False, only=None):
        """Look up BPM/key for the tracks that need it: not typed in by hand, not
        resolved (cached values were applied when the playlist was opened), and not
        inside a FreqBlog wait (queued or not found, see Store.mark_waiting). force
        ignores the waits, never the cache. only: limit to these cache keys (the
        automatic re-check of queued tracks)."""
        if not self.tracks:
            return
        if self.fetching():
            self.status("Already fetching.")
            return
        st = self.store
        need = [t for t in self.tracks if not t.manual and not t.resolved]
        if only is not None and st is not None:
            need = [t for t in need if st.cache_key(t) in only]
        jobs = [t for t in need if force or st is None or st.lookup_due(t)]
        if not jobs:
            if need:
                self.status(f"{len(need)} track(s) are waiting on FreqBlog (being analysed, "
                            "or not found recently), so nothing was sent.")
            elif only is None:
                self.status("Everything is already resolved.")
            return
        self.worker = FetchWorker(self.freqblog, self.getsongbpm, jobs, self)
        self.worker.keyRejected.connect(self._key_rejected)
        self.worker.resolved.connect(self._apply_feature)
        self.worker.waiting.connect(self._mark_waiting)
        self.worker.message.connect(self.status)
        self.worker.done.connect(self._fetch_done)
        self.busy_on(f"Looking up {len(jobs)} track(s)…")
        self.worker.start()

    def _mark_waiting(self, trk: Track, kind: str, days):
        if self.store is not None:
            self.store.mark_waiting(trk, kind, days)

    def _schedule_recheck(self):
        """One automatic re-check of queued tracks, when the first is due soon. It is
        a single timer, restarted after each fetch; later re-checks happen on the next
        fetch. Only queued tracks of the open playlist are asked about."""
        self._recheck.stop()
        if self.store is None or not self.tracks:
            return
        now = time.time()
        due = {}
        for t in self.tracks:
            if t.manual or t.resolved:
                continue
            w = self.store.waiting(t)
            if w and w.get("kind") == "queued":
                due[self.store.cache_key(t)] = float(w.get("next") or now)
        if not due:
            return
        first = min(due.values())
        if first - now > AUTO_RECHECK_MAX_S:
            return
        self._recheck_keys = set(due)
        self._recheck.start(int(max(1.0, first - now + 1) * 1000))

    def _run_recheck(self):
        keys = getattr(self, "_recheck_keys", set())
        if keys and not self.fetching():
            self.fetch_features(only=keys)

    def _apply_feature(self, t: Track, feat: Features):
        # Matched by the Track itself, never by row. A track no longer in the open list
        # (another playlist was opened meanwhile) still gets cached, so the request
        # that found it isn't wasted, but nothing on screen changes.
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
        if t.resolved and self.store is not None:
            self.store.cache_put(t)
        if not any(x is t for x in self.tracks):
            return
        # Update the counts immediately, that is the number being watched
        # but coalesce the expensive full table rebuild, or 49 results in quick
        # succession starve the repaint and nothing appears to move.
        self.stat.setText(summary(self.tracks, self.approved))
        self.show_playlist_info()
        self._live.start()

    def _fetch_done(self):
        self.busy_off()
        self.refresh(keep_undo=True)
        self._autosave.start()
        self._schedule_recheck()

    def delete_rows(self, rows: list[int]):
        if not rows or self._locked("delete tracks"):
            return
        self.snapshot()
        for r in sorted(rows, reverse=True):
            if 0 <= r < len(self.tracks):
                self.tracks.pop(r)
        self.refresh()

    def sort_tracks(self, field: str):
        """Plain sort, no sequencing cleverness, that is the user's job.

        Repeating the same sort reverses it. Rows with nothing to sort on go to
        the end either way, so an unresolved track never lands mid-run.
        """
        if len(self.tracks) < 2:
            return
        if self._locked("sort"):
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
        if self._locked("move tracks"):
            self.refresh(keep_undo=True)      # put a dragged row back where it was
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
                if t.bpm > 0 and v == round(felt_bpm(t.bpm)):
                    return          # retyped what was shown: nothing changed
                v = reported_from_felt(v, folded(t.bpm))
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

    def open_wheel(self):
        if self.wheel is None:
            self.wheel = KeyWheelDialog(self)
        self.wheel.show()
        self.wheel.raise_()
        self.wheel.activateWindow()
        self._sync_selection()

    def _push_to_wheel(self):
        if self.wheel is None or not self.wheel.isVisible():
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows or rows[0] >= len(self.tracks):
            return
        t = self.tracks[rows[0]]
        self.wheel.follow(t.key, f"{t.artist}, {t.title}")

    def _sync_selection(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        sel = rows[0] if rows else -1
        self.chart.set_data(self.tracks, seams(self.tracks), self.felt, sel)
        self._push_to_wheel()

    def set_timeline(self, on: bool):
        """Timeline mode is a Display setting now, not a toolbar toggle."""
        if (self.chart.mode() == "time") == on:
            return
        self.chart_scroll.setWidgetResizable(not on)
        self.chart.set_mode("time" if on else "fit")
        if on:
            # Start zoomed so the whole set fits; Ctrl+wheel zooms from there.
            self.chart.set_zoom(self.chart.fit_zoom(
                self.chart_scroll.viewport().width()))
            self.chart.resize(self.chart.minimumWidth(),
                              self.chart_scroll.viewport().height())
        else:
            self.chart.resize(self.chart_scroll.viewport().size())

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

        target = [t.uri for t in self.tracks]
        if len(set(target)) != len(target):
            QMessageBox.warning(
                self, "Push order",
                "This window lists the same track more than once, which Spotify "
                "cannot be reordered to match. Remove the repeats and push again.")
            return

        # Reordering refuses unless both sides hold the same set, so work out
        # which way they differ before asking for anything.
        self.busy_on("Checking Spotify...")
        try:
            current = self.spotify.playlist_uris(self.current_pid)
        except (ProviderError, AuthError) as e:
            QMessageBox.warning(self, "Push order", str(e))
            self.status(str(e))
            return
        finally:
            self.busy_off()

        cur = set(current)
        only_there = cur - set(target)
        only_here = [u for u in target if u not in cur]

        if only_there:
            # Tracks on Spotify this window has dropped. Destructive, so it
            # defaults to No and names what it will delete -- these are by
            # definition not in this window, so the titles have to be looked
            # up rather than approving a bare base-62 id.
            try:
                names = self.spotify.track_names(sorted(only_there)[:50])
            except (ProviderError, AuthError):
                names = {}
            shown = [names.get(u) or u.split(":")[-1]
                     for u in sorted(only_there)[:3]]
            listing = ", ".join(shown)
            if len(only_there) > 3:
                listing += ", and %d more" % (len(only_there) - 3)
            if QMessageBox.question(
                self, "Push order",
                f"{len(only_there)} track(s) on Spotify are not in this window:"
                "\n\n"
                f"{listing}"
                "\n\n"
                f"Remove them from '{self.current_name}' on Spotify, then "
                f"reorder the remaining {len(target)}?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes:
                self.status("Nothing pushed.")
                return
            self.busy_on("Removing tracks...")
            try:
                n = self.spotify.remove_items(
                    self.current_pid, sorted(only_there),
                    progress=lambda a, t: self.status(f"Removed {a} of {t}..."))
            except (ProviderError, AuthError) as e:
                QMessageBox.warning(self, "Push order", str(e))
                self.status(str(e))
                return
            finally:
                self.busy_off()
            self.status(f"Removed {n} track(s) from '{self.current_name}'.")

        if only_here:
            # The normal case after using the finder: this window holds tracks
            # Spotify has never seen.
            if QMessageBox.question(
                self, "Push order",
                f"{len(only_here)} track(s) here are not on Spotify yet."
                "\n\n"
                f"Add them to '{self.current_name}', then reorder all "
                f"{len(target)} to match this window?"
            ) != QMessageBox.Yes:
                return
            self.busy_on("Adding tracks...")
            try:
                n = self.spotify.add_items(
                    self.current_pid, only_here,
                    progress=lambda a, t: self.status(f"Added {a} of {t}..."))
            except (ProviderError, AuthError) as e:
                QMessageBox.warning(self, "Push order", str(e))
                self.status(str(e))
                return
            finally:
                self.busy_off()
            self.status(f"Added {n} track(s) to '{self.current_name}'.")
        elif QMessageBox.question(
            self, "Push order",
            f"Reorder '{self.current_name}' on Spotify to match this window?"
        ) != QMessageBox.Yes:
            return

        self.busy_on("Pushing order…")
        try:
            moves = self.spotify.reorder_playlist(
                self.current_pid, target,
                progress=lambda m, i, n: self.status(f"Moved {m}, track {i} of {n}…"))
        except (ProviderError, AuthError) as e:
            QMessageBox.warning(self, "Push order", str(e))
            self.status(str(e))
            return
        finally:
            self.busy_off()
        if moves:
            self.status(f"Pushed, {moves} move(s) applied to '{self.current_name}'.")
        else:
            self.status("Spotify already matches this order, nothing to do.")

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
            # Nothing playing, start the playlist from the selected row.
            rows = sorted({i.row() for i in self.table.selectedIndexes()})
            self.play_from(rows[0] if rows else 0)

    def play_from(self, row: int):
        """Play from this row onward, in the order shown here, which may not
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
            self.status("That is the last track, nothing to transition into.")
            return
        a, b = self.tracks[i], self.tracks[i + 1]
        if not a.uri or not b.uri:
            self.status("Both tracks need a Spotify link for this.")
            return
        # The context handed to Spotify is the seam PLUS the rest of the set.
        # A bare two-track list became Spotify's entire queue, and with repeat
        # enabled in the client it cycled those two forever.
        rest = [t.uri for t in self.tracks[i:] if t.uri]
        if a.duration_ms <= 0:
            # Manually added rows have no duration; start at the incoming one.
            self._player_do("play", (rest[1:], 0, ""))
            self.status(f"No length known for '{a.title}', playing '{b.title}'.")
            return
        start = max(0, a.duration_ms - tail_s * 1000)
        self._player_do("play", (rest, start, ""))
        sm = seams(self.tracks, self.approved)
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
        images = ((item.get("album") or {}).get("images") or [])
        # Smallest image that still covers the 44px slot; the 640px one is a
        # needless download for a thumbnail.
        art = ""
        if images:
            art = (images[-1] if len(images) > 2 else images[0]).get("url", "")
        self.player.set_state(
            playing=bool(st.get("is_playing")),
            title=item.get("name", ""),
            artist=", ".join(a.get("name", "") for a in item.get("artists", [])),
            position_ms=st.get("progress_ms") or 0,
            duration_ms=item.get("duration_ms") or 0,
            art_url=art,
            uri=uri,
        )

    def toggle_ear_check(self, row: int):
        """Flip the listened-and-approved mark on the seam row -> row+1.

        Pair-keyed rather than index-keyed, so the mark follows the two tracks:
        it survives reordering elsewhere and vanishes if something is dragged
        in between -- a new neighbour is a new, unheard transition.
        """
        if not (0 <= row < len(self.tracks) - 1):
            self.status("That is the last track - no transition after it.")
            return
        key = seam_key(self.tracks[row], self.tracks[row + 1])
        a, b = self.tracks[row].title, self.tracks[row + 1].title
        if key in self.approved:
            self.approved.discard(key)
            self.status(f"Unmarked '{a}' -> '{b}'.")
        else:
            self.approved.add(key)
            self.status(f"Ear-checked '{a}' -> '{b}'.")
        self.refresh(keep_undo=True)

    def ear_check_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if rows:
            self.toggle_ear_check(rows[0])

    def copy_tracks(self, rows: list):
        """Copy the selected tracks as "Artist - Title", one per line.

        Separate from the URI export: this is the form that goes into a search box or
        a message to somebody, rather than into Spotify.
        """
        picked = [self.tracks[r] for r in rows if 0 <= r < len(self.tracks)]
        if not picked:
            return
        lines = []
        for t in picked:
            artist = (t.artist or "").strip()
            title = (t.title or "").strip()
            lines.append(f"{artist} - {title}" if artist else title)
        QGuiApplication.clipboard().setText("\n".join(lines))
        if len(lines) == 1:
            self.status(f"Copied '{lines[0]}'.")
        else:
            self.status(f"Copied {len(lines)} tracks as artist - title.")

    def uri_block(self) -> str:
        return "\n".join(t.uri for t in self.tracks if t.uri)

    def export_uris(self):
        """The URI block, on demand.

        It used to occupy a permanent panel for something done once a session,
        so it moved to a dialog under File.
        """
        text = self.uri_block()
        if not text:
            self.status("Nothing to export, no track URIs in this playlist.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Export, paste into a Spotify playlist")
        dlg.setMinimumSize(520, 420)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(
            f"{len(text.splitlines())} track URIs, in this window's order. "
            "Spotify keeps the order when you paste them into a playlist."))
        box = QPlainTextEdit()
        box.setPlainText(text)
        box.setReadOnly(True)
        lay.addWidget(box, 1)
        row = QHBoxLayout()
        b = QPushButton("Copy to clipboard")
        b.clicked.connect(lambda: (QGuiApplication.clipboard().setText(text),
                                   self.status(f"Copied {len(text.splitlines())} URIs.")))
        row.addWidget(b)
        row.addStretch(1)
        c = QPushButton("Close")
        c.clicked.connect(dlg.accept)
        row.addWidget(c)
        lay.addLayout(row)
        dlg.exec()

    def save_description(self):
        """Persist the description locally, and to Spotify when it came from there."""
        desc = self.pl_desc.toPlainText().strip()
        self.current_desc = desc
        if self.store and self.current_name:
            self.store.save(self.current_name, self.tracks, auto=False,
                            pid=self.current_pid, description=desc)
        if not self.current_pid:
            self.status("Description saved with the local playlist.")
            return
        if not self.auth.authorised and not self.sign_in():
            return
        try:
            self.spotify.set_playlist_details(self.current_pid, description=desc)
        except (ProviderError, AuthError) as e:
            QMessageBox.warning(self, "Save description", str(e))
            self.status(str(e))
            return
        self.status("Description saved to Spotify.")

    @staticmethod
    def _fmt_total(ms: int) -> str:
        s = int(ms // 1000)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

    def show_playlist_info(self):
        """Refresh the bottom strip from whatever is currently open."""
        self.pl_name.setText(self.current_name or "No playlist open")
        # the whole name stays readable even when the strip is narrow
        self.pl_name.setToolTip(self.current_name or "")
        self.pl_spotify.setVisible(bool(self.current_pid) or any(
            (t.uri or "").startswith("spotify:") for t in self.tracks))
        set_link_target(self.pl_open, "playlist", self.current_pid or "")
        if self.tracks:
            total = sum(t.duration_ms for t in self.tracks if t.duration_ms > 0)
            missing = sum(1 for t in self.tracks if t.duration_ms <= 0)
            n = len(self.tracks)
            txt = f"{n} track{'s' if n != 1 else ''}"
            if total:
                # A "+" marks a total that undercounts because some rows have
                # no known length (manually added tracks).
                txt += f"  ·  {self._fmt_total(total)}{'+' if missing else ''}"
            self.pl_count.setText(txt)
        else:
            self.pl_count.setText("")
        if self.pl_desc.toPlainText().strip() != (self.current_desc or ""):
            self.pl_desc.setPlainText(self.current_desc or "")
        self.btn_desc.setEnabled(bool(self.current_name))
        # The label draws a 1px border, so the image must be 2px smaller than
        # the widget or it paints over the bottom and right edges of the frame.
        inner = COVER - 2
        pm = remote_pixmap(self.current_image, inner) if self.current_image else None
        if pm and not pm.isNull():
            self.pl_cover.setPixmap(pm)
        else:
            self.pl_cover.setPixmap(icon_pixmap(inner))

    def load_details(self):
        """Pull name/description/cover for a Spotify-backed playlist."""
        if not self.current_pid or not self.auth.authorised:
            self.show_playlist_info()
            return
        try:
            d = self.spotify.playlist_details(self.current_pid)
        except (ProviderError, AuthError):
            self.show_playlist_info()
            return
        self.current_desc = d.get("description", "")
        self.current_image = d.get("image", "")
        self.show_playlist_info()

    # ---------------- render ----------------

    def refresh(self, keep_undo: bool = False):
        sm = seams(self.tracks, self.approved)
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        sel = rows[0] if rows else -1
        self.table.set_data(self.tracks, sm, self.felt)
        self.chart.set_data(self.tracks, sm, self.felt, sel)
        self.stat.setText(summary(self.tracks))
        self.show_playlist_info()
        if self.store and self.current_name:
            self._autosave.start()

    def status(self, msg: str):
        self.statusBar().showMessage(msg, 12000)
        if self.spinner.running:
            # While something is running, mirror progress next to the spinner
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
        if self._dirty and self.tracks and self.store:
            name = self.current_name or "this playlist"
            ans = QMessageBox.question(
                self, "Unsaved changes",
                f"Save changes to '{name}' before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save)
            if ans == QMessageBox.Cancel:
                e.ignore()
                return
            if ans == QMessageBox.Save:
                self.save_playlist()
                if self._dirty:
                    # The name prompt was cancelled, nothing was written, so
                    # do not let the close eat the work either.
                    e.ignore()
                    return
        self._save_layout()
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        # update threads are children of this window: let them finish before it goes,
        # or Qt aborts on a QThread destroyed while running
        if self._upd_dl is not None and self._upd_dl.isRunning():
            self._upd_dl.cancelled = True
            self._upd_dl.wait(5000)
        if self._upd_checker is not None and self._upd_checker.isRunning():
            self._upd_checker.wait(12000)
        self._write_auto()
        if self.store:
            self.store.flush_cache()
        super().closeEvent(e)
