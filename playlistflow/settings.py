"""Setup and settings, one dialog, two tabs.

Connections holds the keys and the playlist folder, what the app talks to.
Display holds the choices that depend on what the user listens to rather than
on music theory: axis ceiling, felt fold, tempo tolerance, preview length,
autosave. Camelot/key rules are deliberately NOT here, those are theory, not
preference, and should not be adjustable.

First run shows the dialog as a setup step because nothing works without a
Spotify client ID and a FreqBlog key. Each key has a Test button: a wrong key
fails in a confusing place later, a 401 mid-fetch reads like an app bug, so
it is worth proving each one here, once, against the real service.

Everything, Display included, persists to the same .env.
"""

from __future__ import annotations

import requests

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QDialogButtonBox, QFileDialog, QWidget, QApplication,
    QTabWidget, QSpinBox, QCheckBox, QComboBox, QFormLayout,
)

from .config import (load_env, save_env, env_path, REQUIRED,
                     DISPLAY_DEFAULTS, display_settings, redirect_port)
from .auth import redirect_uri
from .freqcheck import UNAVAILABLE, check_key, usage_text
from .providers import UA

WARN = "#E8B04F"

OK = "#5FBF6B"
BAD = "#E8544F"
DIM = "#8b96a5"


def _note(text: str) -> QLabel:
    lab = QLabel(f"<span style='color:{DIM};font-size:11px'>{text}</span>")
    lab.setWordWrap(True)
    return lab


class Field(QWidget):
    """One key: label, input, a link to where to get it, and a Test button."""

    def __init__(self, title: str, note: str, url: str,
                 required: bool = False, tester=None, parent=None):
        super().__init__(parent)
        self.tester = tester
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 10)
        lay.setSpacing(4)

        head = QLabel(f"<b>{title}</b>" + ("" if required else
                                           " <span style='color:#5c6672'>· optional</span>"))
        lay.addWidget(head)

        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Normal)
        row.addWidget(self.edit, 1)
        if url:
            b = QPushButton("Get one")
            b.setFixedWidth(78)
            b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
            row.addWidget(b)
        if tester:
            self.btn_test = QPushButton("Test")
            self.btn_test.setFixedWidth(60)
            self.btn_test.clicked.connect(self._test)
            row.addWidget(self.btn_test)
        lay.addLayout(row)

        self.note = _note(note)
        self.note.setOpenExternalLinks(True)
        lay.addWidget(self.note)

        self.result = QLabel("")
        self.result.setWordWrap(True)
        lay.addWidget(self.result)

    def value(self) -> str:
        from .wizard import clean_key            # the same paste cleanup as the wizard
        return clean_key(self.edit.text())

    def set_value(self, v: str):
        self.edit.setText(v or "")

    def _test(self):
        key = self.value()
        if not key:
            self._say("Nothing to test yet.", DIM)
            return
        self.btn_test.setEnabled(False)
        self._say("Checking…", DIM)
        QApplication.processEvents()
        try:
            good, msg = self.tester(key)
        except Exception as e:                      # network, DNS, anything
            good, msg = False, f"Could not reach it: {e}"
        finally:
            self.btn_test.setEnabled(True)
        self._say(msg, OK if good else BAD)

    def _say(self, msg: str, colour: str):
        self.result.setText(f"<span style='color:{colour};font-size:11px'>{msg}</span>")


# ---------------- testers ----------------

def test_freqblog(key: str) -> tuple[bool, str]:
    """GET /me/stats, the same check as the setup wizard's (free: it doesn't count
    against the monthly allowance). A 401 shows FreqBlog's own explanation."""
    res = check_key(key)
    if res.status == "ok":
        return True, "Working. FreqBlog accepted the key."
    if res.status == "rejected":
        return False, f"Rejected: {res.message}"
    return False, res.message


def test_getsongbpm(key: str) -> tuple[bool, str]:
    try:
        r = requests.get("https://api.getsong.co/search/",
                         params={"api_key": key, "type": "both",
                                 "lookup": "song:Blinding Lights artist:The Weeknd"},
                         headers={"User-Agent": UA}, timeout=25)
    except requests.RequestException as e:
        return False, f"Couldn't reach GetSongBPM ({type(e).__name__})."
    if r.status_code != 200:
        return False, f"Unexpected response ({r.status_code})."
    try:
        j = r.json()
    except ValueError:
        return False, "Unreadable response, the key is probably not active yet."
    if not isinstance(j, dict):
        return False, "Unreadable response, the key is probably not active yet."
    search = j.get("search")
    if isinstance(search, dict) and search.get("error"):
        return False, f"Rejected: {search['error']}"
    return True, "Working."


def test_spotify_id(client_id: str) -> tuple[bool, str]:
    """No secret involved, ask the authorize endpoint whether it knows the ID."""
    try:
        r = requests.get("https://accounts.spotify.com/authorize",
                         params={"client_id": client_id, "response_type": "code",
                                 "redirect_uri": redirect_uri(redirect_port()),
                                 "code_challenge_method": "S256",
                                 "code_challenge": "x" * 43},
                         allow_redirects=False, timeout=25)
    except requests.RequestException as e:
        return False, f"Couldn't reach Spotify ({type(e).__name__})."
    body = r.text.lower()
    if "invalid client" in body or "invalid_client" in body:
        return False, "Spotify does not recognise that client ID."
    if "invalid redirect" in body or "redirect_uri" in body and r.status_code >= 400:
        return False, ("The redirect URI is not registered. Add "
                       f"{redirect_uri(redirect_port())} to the app in the "
                       "Spotify dashboard.")
    if r.status_code in (200, 302, 303):
        return True, "Recognised. You will still need to sign in."
    return False, f"Unexpected response ({r.status_code})."


# ---------------- dialog ----------------

TOL_ITEMS = [("Tight (±3%)", "tight"),
             ("Normal (±6%)", "normal"),
             ("Loose (±8%)", "loose")]


_LIVE = set()       # running usage fetches; unparented so closing Settings never kills one


class _UsageFetch(QThread):
    done = Signal(object)

    def __init__(self, key, check, parent=None):
        super().__init__(parent)
        self.key, self.check = key, check

    def run(self):
        try:
            self.done.emit(self.check(self.key))
        except Exception as e:                    # said as "Usage unavailable", never raised
            self.done.emit(e)


class SettingsDialog(QDialog):
    def __init__(self, parent=None, first_run: bool = False, prefs=None,
                 key_check=None, fetch_usage=True):
        super().__init__(parent)
        self.prefs = prefs
        self.key_check = key_check or (lambda key: check_key(key))
        self._usage_threads = []
        self.first_run = first_run
        self.setWindowTitle("Setup" if first_run else "Settings")
        self.setMinimumWidth(640)

        lay = QVBoxLayout(self)

        if first_run:
            intro = QLabel(
                "<h3 style='margin-bottom:2px'>One-time setup</h3>"
                "<p style='color:#8b96a5'>Two keys are needed before anything "
                "works. Both are free. The other two are optional and only fill "
                "gaps for obscure tracks.</p>")
        else:
            intro = QLabel(
                f"<p style='color:#8b96a5'>Saved to<br><code>{env_path()}</code></p>")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        tabs = QTabWidget()
        tabs.addTab(self._build_connections(), "Connections")
        tabs.addTab(self._build_display(), "Display")
        if first_run:
            tabs.setCurrentIndex(0)
        lay.addWidget(tabs, 1)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)

        # Rerun the onboarding wizard: the window opens it once this closes.
        self.run_setup_requested = False
        row = QHBoxLayout()
        self.btn_setup = QPushButton("Run setup again")
        self.btn_setup.setObjectName("run_setup")
        self.btn_setup.setToolTip("Walk through Spotify, FreqBlog, GetSongBPM and the "
                                  "storage folder again, step by step.")
        self.btn_setup.clicked.connect(self._run_setup)
        row.addWidget(self.btn_setup)
        # Spotify Developer Terms, Section V: a working, easy way to disconnect
        self.disconnect_requested = False
        self.btn_disconnect = QPushButton("Disconnect Spotify")
        self.btn_disconnect.setObjectName("disconnect_spotify")
        self.btn_disconnect.setToolTip("Remove Playlist Flow's Spotify sign-in from this PC, and "
                                       "optionally your saved playlists.")
        self.btn_disconnect.clicked.connect(self._disconnect)
        row.addWidget(self.btn_disconnect)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(
            "Finish setup" if first_run else "Save")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        lay.addLayout(row)

        self._load()
        # the usage line: fetched now and on Test, never polled
        fb = self.fields["FREQBLOG_API_KEY"]
        fb.tester = self._test_freqblog
        if fetch_usage:
            self.refresh_usage()

    # ---------------- Connections tab ----------------

    def _build_connections(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        self.fields: dict[str, Field] = {}

        self.fields["SPOTIFY_CLIENT_ID"] = Field(
            "Spotify client ID",
            "Create an app in the Spotify developer dashboard. Add "
            f"<code>{redirect_uri(redirect_port())}</code> as a redirect URI, and "
            "add your own Spotify account under the app's User Management, "
            "without that, reading your playlists fails with a 403. "
            "Run setup again (below) to change the port or sign in again.",
            "https://developer.spotify.com/dashboard",
            required=True, tester=test_spotify_id)

        self.fields["FREQBLOG_API_KEY"] = Field(
            "FreqBlog API key",
            "BPM and musical key estimates. The free tier has a monthly allowance of "
            "requests. Values that are found are kept in the playlist folder's cache "
            "until you delete it, so a found track is looked up once. Tracks FreqBlog "
            "is still analysing are checked again later, a few times at growing "
            "intervals, and tracks it doesn't know are asked about again after a week. "
            "Test (and opening Settings) asks FreqBlog about the key itself, which "
            "doesn't count against the allowance.",
            "https://freqblog.com",
            required=True, tester=test_freqblog)
        self.usage = QLabel("")
        self.usage.setObjectName("freqblog_usage")
        self.usage.setWordWrap(True)
        self.fields["FREQBLOG_API_KEY"].layout().insertWidget(2, self.usage)

        self.fields["GETSONGBPM_API_KEY"] = Field(
            "GetSongBPM API key",
            "A fallback with thin coverage of independent artists. They require "
            "a visible link back to getsongbpm.com, the About dialog carries "
            "it, so leave that in place if you use this.",
            "https://getsongbpm.com/api",
            required=False, tester=test_getsongbpm)

        for f in self.fields.values():
            lay.addWidget(f)

        box = QWidget()
        g = QGridLayout(box)
        g.setContentsMargins(0, 0, 0, 0)
        g.addWidget(QLabel("<b>Playlist folder</b>"), 0, 0, 1, 2)
        self.folder = QLineEdit()
        g.addWidget(self.folder, 1, 0)
        b = QPushButton("Browse…")
        b.setFixedWidth(90)
        b.clicked.connect(self._browse)
        g.addWidget(b, 1, 1)
        g.addWidget(_note("Saved playlists and the BPM/key cache live here."),
                    2, 0, 1, 2)
        lay.addWidget(box)
        lay.addStretch(1)
        return page

    # ---------------- Display tab ----------------

    def _build_display(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        form = QFormLayout()
        form.setVerticalSpacing(6)

        def spin(key):
            default, lo, hi = DISPLAY_DEFAULTS[key]
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setValue(default)
            s.setFixedWidth(90)
            return s

        self.d_graph_max = spin("GRAPH_MAX_BPM")
        form.addRow("<b>Graph max BPM</b>", self.d_graph_max)
        form.addRow("", _note("Fixed axis maximum. Raise it if you listen to "
                              "anything above 200 BPM."))

        self.d_timeline = QCheckBox("Timeline mode")
        self.d_timeline.setChecked(False)
        form.addRow("", self.d_timeline)
        form.addRow("", _note("Bar width becomes track length, so the set "
                              "reads as elapsed time. Ctrl+wheel over the "
                              "chart to zoom."))

        self.d_fold = spin("FELT_FOLD")
        form.addRow("<b>Fold threshold</b>", self.d_fold)
        form.addRow("", _note("Where the felt column halves. 165 is the top of "
                              "the range a listener can track as a pulse."))

        self.d_tol = QComboBox()
        for label, _ in TOL_ITEMS:
            self.d_tol.addItem(label)
        self.d_tol.setCurrentIndex(1)
        self.d_tol.setFixedWidth(140)
        form.addRow("<b>Tempo tolerance</b>", self.d_tol)
        form.addRow("", _note("Tight for blended sets, loose for cut sets. "
                              "Scales the doubles/halves/shifts windows "
                              "together; holds and the reciprocal symmetry "
                              "rule follow automatically."))

        self.d_warn_both = QCheckBox("Warn on both axes off")
        self.d_warn_both.setChecked(True)
        form.addRow("", self.d_warn_both)
        form.addRow("", _note("Controls the both-off counter and its row "
                              "highlighting."))

        self.d_preview = spin("PREVIEW_SECONDS")
        self.d_preview.setSuffix(" s")
        form.addRow("<b>Preview length</b>", self.d_preview)
        form.addRow("", _note("Default for the transport bar's preview "
                              "control; the bar can still change it per "
                              "session."))

        auto_row = QHBoxLayout()
        self.d_autosave = QCheckBox("Auto-save")
        self.d_autosave.setChecked(True)
        auto_row.addWidget(self.d_autosave)
        self.d_autosave_s = spin("AUTOSAVE_SECONDS")
        self.d_autosave_s.setSuffix(" s")
        auto_row.addWidget(self.d_autosave_s)
        auto_row.addStretch(1)
        wrap = QWidget()
        wrap.setLayout(auto_row)
        form.addRow("<b>Auto-save</b>", wrap)
        form.addRow("", _note("Writes the working copy this long after the "
                              "last edit. The explicit Save file is separate "
                              "and never overwritten by this."))

        self.d_autosave.toggled.connect(self.d_autosave_s.setEnabled)

        self.d_update = QCheckBox("Check for updates at startup")
        self.d_update.setObjectName("set_update_check")
        self.d_update.setChecked(True)
        form.addRow("<b>Updates</b>", self.d_update)
        form.addRow("", _note("Asks GitHub for the latest Playlist Flow release in "
                              "the background a few seconds after startup. Nothing "
                              "else is sent. Help > Check for updates works either way."))

        lay.addLayout(form)
        lay.addStretch(1)
        return page

    # ---------------- load / save ----------------

    def _browse(self):
        d = QFileDialog.getExistingDirectory(
            self, "Folder for saved playlists", self.folder.text() or "")
        if d:
            self.folder.setText(d)

    def _load(self):
        env = load_env()
        for k, f in self.fields.items():
            f.set_value(env.get(k, ""))
        if self.prefs is not None:
            default = str(__import__("pathlib").Path.home() / "Documents" / "PlaylistFlow")
            self.folder.setText(self.prefs.storage_dir or default)
            self.d_update.setChecked(self.prefs.update_check)

        d = display_settings(env)
        self.d_graph_max.setValue(d["graph_max"])
        self.d_timeline.setChecked(d["timeline"])
        self.d_fold.setValue(d["felt_fold"])
        self.d_tol.setCurrentIndex(
            next(i for i, (_, v) in enumerate(TOL_ITEMS) if v == d["tolerance"]))
        self.d_warn_both.setChecked(d["warn_both"])
        self.d_preview.setValue(d["preview_s"])
        self.d_autosave.setChecked(d["autosave_on"])
        self.d_autosave_s.setValue(d["autosave_s"])
        self.d_autosave_s.setEnabled(d["autosave_on"])

    # ---------------- FreqBlog usage ----------------

    def show_usage(self, res):
        """Set the usage line from a KeyCheck: the line on success (warning colour at
        90% or more), "Usage unavailable" on any failure. Never a popup."""
        usage = getattr(res, "usage", None)
        if getattr(res, "status", "") != "ok" or usage is None:
            text, warn = UNAVAILABLE, False
        else:
            text, warn = usage_text(usage)
        self.usage_warn = warn
        colour = WARN if warn else DIM
        self.usage.setText(f"<span style='color:{colour};font-size:11px'>{text}</span>")

    def refresh_usage(self):
        key = self.fields["FREQBLOG_API_KEY"].value()
        if not key:
            self.usage.setText("")                # no key: nothing to show
            return
        t = _UsageFetch(key, self.key_check)
        t.done.connect(self.show_usage)
        t.finished.connect(lambda t=t: _LIVE.discard(t))
        _LIVE.add(t)
        self._usage_threads.append(t)
        t.start()

    def _test_freqblog(self, key: str) -> tuple[bool, str]:
        """Settings' Test button: one /me/stats call gives both the answer and the usage."""
        res = self.key_check(key)
        self.show_usage(res)
        if getattr(res, "status", "") == "ok":
            return True, "Working. FreqBlog accepted the key."
        if getattr(res, "status", "") == "rejected":
            return False, f"Rejected: {res.message}"
        return False, getattr(res, "message", "") or "Couldn't reach FreqBlog."

    def done(self, r):
        for t in self._usage_threads:             # a late answer has nowhere to go
            try:
                t.done.disconnect(self.show_usage)
            except (RuntimeError, TypeError):
                pass
        super().done(r)

    def _run_setup(self):
        self.run_setup_requested = True
        self.reject()

    def _disconnect(self):
        self.disconnect_requested = True
        self.reject()

    def values(self) -> dict:
        vals = {k: f.value() for k, f in self.fields.items()}
        # set by the wizard, not edited here: carried over so a Save keeps it
        port = load_env().get("SPOTIFY_REDIRECT_PORT", "")
        if port:
            vals["SPOTIFY_REDIRECT_PORT"] = port
        vals.update({
            "GRAPH_MAX_BPM": str(self.d_graph_max.value()),
            "TIMELINE_ON": "1" if self.d_timeline.isChecked() else "0",
            "FELT_FOLD": str(self.d_fold.value()),
            "TEMPO_TOLERANCE": TOL_ITEMS[self.d_tol.currentIndex()][1],
            "WARN_BOTH_OFF": "1" if self.d_warn_both.isChecked() else "0",
            "PREVIEW_SECONDS": str(self.d_preview.value()),
            "AUTOSAVE_ON": "1" if self.d_autosave.isChecked() else "0",
            "AUTOSAVE_SECONDS": str(self.d_autosave_s.value()),
        })
        return vals

    def _save(self):
        vals = self.values()
        missing = [k for k in REQUIRED if not vals.get(k)]
        if missing:
            pretty = {"SPOTIFY_CLIENT_ID": "Spotify client ID",
                      "FREQBLOG_API_KEY": "FreqBlog API key"}
            names = ", ".join(pretty.get(m, m) for m in missing)
            self.msg.setText(
                f"<span style='color:{BAD}'>Still needed: {names}</span>")
            return
        save_env(vals)
        if self.prefs is not None and self.folder.text().strip():
            self.prefs.storage_dir = self.folder.text().strip()
        if self.prefs is not None:
            self.prefs.update_check = self.d_update.isChecked()
        self.accept()
