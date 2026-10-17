"""The onboarding wizard: Spotify, FreqBlog, GetSongBPM and the storage folder,
one step at a time.

Required on first launch and whenever the stored setup no longer works; it can
be rerun from Settings. It replaces the old first-run Settings dialog.

Where things go, unchanged from before:
  - the Spotify client ID, the redirect port and the API keys: the user's own
    %APPDATA%\\PlaylistFlow\\.env (config.save_env); only what this wizard
    collected is written there, beside any display settings already in it,
  - the Spotify sign-in: HKCU (QSettings), through SpotifyAuth, as before,
  - the storage folder choice: QSettings storage_dir. Playlists are never moved.

Sign-in is PKCE. While the sign-in step waits for the browser, callback.py listens
on 127.0.0.1 at the chosen port, catches Spotify's redirect and the step finishes by
itself; the listener stops right after (and on cancel, timeout or leaving the step).
If the port can't be bound, the user pastes the address from the browser instead.
A port some other program is listening on would receive the sign-in code, so the
wizard picks a free one before showing the redirect URI.

The FreqBlog key is checked with one GET /me/stats call (free, it doesn't count
against the monthly allowance), which also gives the usage line shown on that step.
"""

from __future__ import annotations

import re
import socket
from html import escape as html_escape
from pathlib import Path

import requests
from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QStackedWidget, QTabWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from . import theme
from .auth import AuthError, redirect_uri
from .callback import CallbackListener
from .config import (DEFAULT_REDIRECT_PORT, _read_env_file, env_path, load_env, save_env)
from .docs import AGREEMENT_VERSION, read_doc
from .freqcheck import check_key, usage_text
from .providers import UA

DASHBOARD_URL = "https://developer.spotify.com/dashboard"
FREQBLOG_URL = "https://freqblog.com"
GETSONGBPM_URL = "https://getsongbpm.com/api"
BACKLINK_SITES = ("darkrelay.net", "github.com/Crazy8697/PlaylistFlow")
PORT_CANDIDATES = tuple(range(8888, 8900))

# step indices, used by the key-failure popups to jump straight to a step
WELCOME, SPOTIFY, AGREE, LOGIN, FREQBLOG, GETSONGBPM, STORAGE, DONE = range(8)
TITLES = ("Welcome", "Spotify app", "Privacy and terms", "Sign in", "FreqBlog key",
          "GetSongBPM key", "Storage folder", "Done")

# Formats, checked before anything is saved. Loose enough for any real key,
# tight enough to catch a paste of the wrong thing.
SPOTIFY_ID_RE = re.compile(r"[A-Za-z0-9]{32}")
FREQBLOG_RE = re.compile(r"[A-Za-z0-9_\-]{20,128}")
GETSONGBPM_RE = re.compile(r"[A-Za-z0-9]{16,64}")
SIGNIN_TIMEOUT_MS = 5 * 60 * 1000     # how long the automatic sign-in waits for the browser

# A label pasted along with a key: "Spotify client ID:", "Client ID =", "API key -", ...
_LABEL_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9 _()./]*?\s*(?::|=|\s-\s)\s*")


def clean_key(text: str) -> str:
    """A pasted key without the extras that come with a copy: surrounding and inner
    whitespace and line breaks, quotes, and a leading label such as "Spotify client
    ID:". What's left is what gets validated and saved."""
    t = (text or "").strip()
    for _ in range(3):                       # "Client ID: Key: abc" and the like
        m = _LABEL_RE.match(t)
        if not m or not t[m.end():].strip():
            break
        t = t[m.end():]
    t = "".join(t.split())                   # spaces, tabs, line breaks, anywhere
    return t.strip("\"'`<>[]{}()")


def valid_client_id(v: str) -> bool:
    return bool(SPOTIFY_ID_RE.fullmatch(clean_key(v)))


def valid_freqblog(v: str) -> bool:
    return bool(FREQBLOG_RE.fullmatch(clean_key(v)))


def valid_getsongbpm(v: str) -> bool:
    return bool(GETSONGBPM_RE.fullmatch(clean_key(v)))


def _bg_thread(fn, done, parent):
    """Run fn() off the UI thread, then done(result) on it."""
    class _T(QThread):
        result = Signal(object)

        def run(self):
            try:
                self.result.emit(fn())
            except Exception as e:                  # never raised into the UI
                self.result.emit(e)
    t = _T(parent)
    t.result.connect(done)
    t.finished.connect(t.deleteLater)
    t.start()
    return t


# ---------------- ports ----------------

def port_busy(port: int) -> bool:
    """True when something on this PC already has 127.0.0.1:port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", int(port)))
        return False
    except OSError:
        return True
    finally:
        s.close()


def scan_ports(candidates=PORT_CANDIDATES, busy=port_busy) -> list[tuple[int, bool]]:
    return [(p, bool(busy(p))) for p in candidates]


def pick_port(scan: list[tuple[int, bool]], preferred: int | None = None) -> int | None:
    """The preferred port when free, else the first free one, else None."""
    free = [p for p, b in scan if not b]
    if preferred in free:
        return preferred
    return free[0] if free else None


# ---------------- Spotify checks ----------------

def spotify_me(token: str) -> tuple[bool, str]:
    """Can this sign-in read the user's data? 403 here is the allowlist (or the
    app owner not having Premium), the classic Development Mode trap."""
    try:
        r = requests.get("https://api.spotify.com/v1/me",
                         headers={"Authorization": f"Bearer {token}", "User-Agent": UA},
                         timeout=15)
    except requests.RequestException:
        return False, "Couldn't reach Spotify. Check your connection and try again."
    if r.status_code == 200:
        name = ""
        try:
            name = (r.json() or {}).get("display_name") or ""
        except ValueError:
            pass
        return True, f"Signed in{(' as ' + name) if name else ''}. Spotify answered."
    if r.status_code == 403:
        return False, ("Spotify accepted the sign-in but refused to share your data. Your Spotify "
                       "account is probably not on the app's allowlist: Dashboard > your app > "
                       "Settings > User Management, add your name and Spotify email. The app's "
                       "owner also needs Spotify Premium.")
    return False, f"Spotify answered with an error ({r.status_code}). Try signing in again."


def explain_auth_error(e: Exception, uri: str) -> str:
    t = str(e).lower()
    if "invalid_client" in t or "invalid client" in t:
        return ("Spotify doesn't recognise that client ID. Copy it again from the app's "
                "settings in the Spotify dashboard (Back to the previous step).")
    if "redirect" in t or "invalid_grant" in t:
        return (f"The sign-in didn't match. Make sure {uri} is saved as a Redirect URI on your "
                "Spotify app (exactly, same port), then open the sign-in again and paste the "
                "new address.")
    if "state mismatch" in t or "state missing" in t or "session was lost" in t:
        return "That address came from an older sign-in. Click Open Spotify sign-in again."
    if "couldn't find a code" in t or "nothing pasted" in t:
        return "Paste the whole address from the browser's address bar, starting with http://127.0.0.1."
    if "couldn't reach spotify" in t:
        return str(e)
    return f"Sign-in failed: {e}"


# ---------------- the wizard ----------------

def _h(text: str) -> QLabel:
    lab = QLabel(f"<span style='font-size:18px;font-weight:700;color:#ffffff'>{text}</span>")
    lab.setStyleSheet("background: transparent;")
    return lab


def _p(html: str) -> QLabel:
    lab = QLabel(html)
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.RichText)
    lab.setOpenExternalLinks(True)
    lab.setStyleSheet("background: transparent;")
    return lab


def _say(label: QLabel, text: str, good: bool | None):
    colour = theme.MUTED if good is None else ("#5FBF6B" if good else "#E8544F")
    label.setText(f"<span style='color:{colour}'>{text}</span>")


def _copy_row(text: str, name: str) -> tuple[QHBoxLayout, QLineEdit, QPushButton]:
    row = QHBoxLayout()
    box = QLineEdit(text)
    box.setReadOnly(True)
    box.setObjectName(name)
    btn = QPushButton("Copy")
    btn.clicked.connect(lambda: (QGuiApplication.clipboard().setText(box.text()),
                                 btn.setText("Copied")))
    row.addWidget(box, 1)
    row.addWidget(btn)
    return row, box, btn


class SetupWizard(QDialog):
    """Eight steps; Next is locked until the step's job is done. finished() data
    is written only on Finish; Cancel leaves everything as it was.

    key_check, run_bg and listener_factory are there so tests can stand in for
    FreqBlog, the background thread and the sign-in listener."""

    _caught = Signal(str)         # the listener's redirect address, carried to the UI thread

    def __init__(self, auth, prefs, parent=None, start: int = WELCOME, required: bool = False,
                 scan=None, verify=spotify_me, open_url=None, key_check=None,
                 run_bg=None, listener_factory=CallbackListener):
        super().__init__(parent)
        self.auth = auth
        self.prefs = prefs
        self.required = required
        self.verify = verify
        self.key_check = key_check or (lambda key: check_key(key))
        self._run_bg = run_bg or (lambda fn, done: _bg_thread(fn, done, self))
        self._listener_factory = listener_factory
        self.listener = None
        self.fb_check = None              # None (not checked) | "ok" | "rejected" | "offline"
        self.fb_checking = False
        self._signin_timer = QTimer(self)
        self._signin_timer.setSingleShot(True)
        self._signin_timer.timeout.connect(self._signin_timed_out)
        self._caught.connect(self._on_caught)
        self._open_url = open_url or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        env = load_env()
        self.env_before = dict(_read_env_file(env_path()))
        # restored on Cancel: a test sign-in must not outlive an abandoned setup
        self._token_before = prefs.refresh_token
        self._client_before = auth.client_id
        self._port_before = auth.port
        self.login_ok = False
        self.saved = False
        self.setWindowTitle("Playlist Flow setup")
        self.setMinimumSize(720, 560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 14)
        self.step_label = QLabel("")
        self.step_label.setObjectName("wizard_step")
        self.step_label.setStyleSheet(f"color:{theme.ACCENT};font-size:11px;font-weight:700;"
                                      "letter-spacing:1px;background:transparent;")
        outer.addWidget(self.step_label)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        scan = scan if scan is not None else scan_ports()
        self.scan = scan
        for build in (self._welcome, lambda: self._spotify(env, scan), self._agree, self._login,
                      lambda: self._freqblog(env), lambda: self._getsongbpm(env),
                      self._storage, self._done):
            self.stack.addWidget(build())

        nav = QHBoxLayout()
        self.btn_cancel = QPushButton("Quit setup" if required else "Cancel")
        self.btn_cancel.setObjectName("wizard_cancel")
        self.btn_cancel.clicked.connect(self.reject)
        nav.addWidget(self.btn_cancel)
        nav.addStretch(1)
        self.btn_back = QPushButton("Back")
        self.btn_back.setObjectName("wizard_back")
        self.btn_back.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
        nav.addWidget(self.btn_back)
        self.btn_next = QPushButton("Next")
        self.btn_next.setObjectName("wizard_next")
        self.btn_next.setDefault(True)
        self.btn_next.clicked.connect(self._next)
        nav.addWidget(self.btn_next)
        outer.addLayout(nav)
        # the sign-in step is never reached without the current documents accepted
        if start == LOGIN and not self.agreed():
            start = AGREE
        self.go(start)

    # ---------------- navigation ----------------

    def agreed(self) -> bool:
        return self.prefs.agreement_version == AGREEMENT_VERSION

    def go(self, i: int):
        i = max(0, min(DONE, i))
        # already accepted this version: the step is passed over (shown again only
        # when the documents change)
        if i == AGREE and self.agreed() and self.stack.currentIndex() != AGREE:
            i = LOGIN if self.stack.currentIndex() < AGREE else SPOTIFY
        if i != LOGIN:
            self.stop_listening()         # leaving the sign-in step: nothing keeps listening
        if i == DONE:
            self._fill_summary()
        self.stack.setCurrentIndex(i)
        self.step_label.setText(f"STEP {i + 1} OF {len(TITLES)}  ·  {TITLES[i].upper()}")
        self.btn_back.setEnabled(i > 0)
        self.btn_next.setText("Finish" if i == DONE else "Next")
        self.btn_cancel.setVisible(i != DONE)       # the last page has Back and Finish only
        self._refresh_next()

    def _refresh_next(self):
        self.btn_next.setEnabled(self.can_advance(self.stack.currentIndex()))

    def can_advance(self, i: int) -> bool:
        if i == SPOTIFY:
            return valid_client_id(self.client_id.text()) and self.port() is not None
        if i == AGREE:
            return self.agree_box.isChecked()
        if i == LOGIN:
            return self.login_ok
        if i == FREQBLOG:
            return (valid_freqblog(self.freqblog.text()) and not self.fb_checking
                    and self.fb_check != "rejected")
        if i == GETSONGBPM:
            v = self.getsongbpm.text().strip()
            return not v or valid_getsongbpm(v)          # optional: blank is fine
        if i == STORAGE:
            return bool(self.folder.text().strip())
        return True

    def _next(self):
        i = self.stack.currentIndex()
        if not self.can_advance(i):
            return
        if i == DONE:
            self.save()
            self.accept()
            return
        if i == FREQBLOG and self.fb_check is None:
            self.check_freqblog()     # one /me/stats call; Next again goes on
            return
        if i == AGREE:
            self.prefs.agreement_version = AGREEMENT_VERSION     # accepted: not asked again
        self.go(i + 1)

    def reject(self):
        if self.required and not self.saved:
            ans = QMessageBox.question(
                self, "Quit setup?",
                "Playlist Flow needs this setup before it can work. Quit Playlist Flow now? "
                "You can run setup the next time you open it.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        self.stop_listening()
        self._restore()
        super().reject()

    def accept(self):
        self.stop_listening()
        super().accept()

    def closeEvent(self, e):
        self.stop_listening()
        super().closeEvent(e)

    def _restore(self):
        if not self.saved:
            self.prefs.refresh_token = self._token_before
            self.auth.client_id = self._client_before
            self.auth.port = self._port_before
            self.auth._access, self.auth._expires = "", 0.0

    # ---------------- 1 welcome ----------------

    def _welcome(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_h("Welcome to Playlist Flow"))
        v.addWidget(_p(
            "<p>Playlist Flow orders playlists so they flow, by musical key and tempo. It loads a "
            "Spotify playlist, fills in BPM and Camelot key, shows where the transitions will "
            "fight you, and pushes the new order back to Spotify.</p>"
            "<p><b>Setup takes a few minutes. You will need:</b></p>"
            "<ul>"
            "<li>a <b>Spotify Premium</b> account,</li>"
            "<li>a free <b>Spotify developer app</b> of your own (the next step shows how),</li>"
            "<li>a free <b>FreqBlog</b> key, for BPM and key estimates,</li>"
            "<li>optionally, a free <b>GetSongBPM</b> key, a fallback for tracks FreqBlog misses.</li>"
            "</ul>"
            f"<p style='color:{theme.MUTED}'>Your keys and playlists stay on this PC. Your keys are "
            "yours alone: never share or publish them.</p>"))
        v.addStretch(1)
        return w

    # ---------------- 2 Spotify app ----------------

    def port(self) -> int | None:
        p = self.port_box.currentData()
        return int(p) if p is not None else None

    def _spotify(self, env: dict, scan) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_h("Your Spotify developer app"))
        v.addWidget(_p(
            "<ol style='margin-left:-18px'>"
            "<li>Open the Spotify dashboard and log in with your normal Spotify account.</li>"
            "<li><b>Create app</b>. Any name and description, but don't put \"Spotify\" in the name.</li>"
            "<li>Add the <b>Redirect URI</b> below exactly, and tick <b>Web API</b>.</li>"
            "<li>Copy the app's <b>Client ID</b> into the box at the bottom.</li>"
            "</ol>"))
        b = QPushButton("Open Spotify Dashboard")
        b.setObjectName("open_dashboard")
        b.clicked.connect(lambda: self._open_url(DASHBOARD_URL))
        v.addWidget(b, 0, Qt.AlignLeft)

        # port first: the redirect URI is only shown once a free port is chosen
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Redirect port"))
        self.port_box = QComboBox()
        self.port_box.setObjectName("port_box")
        try:
            preferred = int(env.get("SPOTIFY_REDIRECT_PORT") or DEFAULT_REDIRECT_PORT)
        except ValueError:
            preferred = DEFAULT_REDIRECT_PORT
        chosen = pick_port(scan, preferred)
        for p, busy in scan:
            self.port_box.addItem(f"{p}  (in use)" if busy else str(p), None if busy else p)
            if busy:
                item = self.port_box.model().item(self.port_box.count() - 1)
                item.setEnabled(False)
        if chosen is not None:
            self.port_box.setCurrentIndex([p for p, _ in scan].index(chosen))
        self.port_box.setFixedWidth(140)
        prow.addWidget(self.port_box)
        self.port_note = QLabel("")
        self.port_note.setObjectName("port_note")
        self.port_note.setWordWrap(True)
        prow.addWidget(self.port_note, 1)
        v.addLayout(prow)
        if chosen is None:
            _say(self.port_note, "Every port from 8888 to 8899 is in use. Close something that "
                                 "uses one and reopen setup.", False)
        elif chosen != preferred:
            _say(self.port_note, f"{preferred} is in use, using {chosen} instead.", None)
        else:
            _say(self.port_note, "Free on this PC.", True)

        row, self.uri_box, _ = _copy_row(redirect_uri(chosen or preferred), "redirect_uri")
        v.addWidget(QLabel("Redirect URI (add this exact address to your Spotify app)"))
        v.addLayout(row)
        self.port_box.currentIndexChanged.connect(self._port_changed)

        v.addWidget(_p(
            f"<p style='color:#E8B04F'><b>Spotify Development Mode:</b> the app's owner needs "
            "<b>Spotify Premium</b>, and only accounts on the app's allowlist (up to 5) can sign "
            "in. Add your own account: Dashboard &gt; your app &gt; Settings &gt; User Management "
            "&gt; your name and Spotify email. Without that, sign-in works but reading your "
            "playlists fails.</p>"))

        v.addWidget(QLabel("Client ID"))
        self.client_id = QLineEdit(env.get("SPOTIFY_CLIENT_ID", ""))
        self.client_id.setObjectName("client_id")
        self.client_id.setPlaceholderText("32 letters and digits, from the app's settings")
        self.client_id.textChanged.connect(self._client_changed)
        v.addWidget(self.client_id)
        self.client_note = QLabel("")
        self.client_note.setObjectName("client_note")
        self.client_note.setWordWrap(True)
        v.addWidget(self.client_note)
        self._client_changed()
        v.addStretch(1)
        return w

    def _port_changed(self):
        p = self.port()
        if p is not None:
            self.uri_box.setText(redirect_uri(p))
            _say(self.port_note, "Free on this PC.", True)
        self.login_ok = False          # a different redirect needs a fresh sign-in test
        self._refresh_next()

    def _tidy(self, box: QLineEdit, valid) -> tuple[str, bool]:
        """Clean a pasted key in place when that makes it valid. Returns (value, tidied)."""
        raw = box.text()
        v = clean_key(raw)
        if v != raw and v and valid(v):
            box.blockSignals(True)
            box.setText(v)
            box.blockSignals(False)
            return v, True
        return v, False

    def _client_changed(self):
        v, tidied = self._tidy(self.client_id, valid_client_id)
        if not v:
            _say(self.client_note, "Paste the Client ID.", None)
        elif valid_client_id(v):
            _say(self.client_note, "Looks right." + (" (Extra text around it was removed.)"
                                                     if tidied else ""), True)
        else:
            _say(self.client_note, f"That isn't a Spotify Client ID: it should be 32 letters and "
                                   f"digits, and this is {len(v)} character(s)"
                                   + ("" if v.isalnum() else ", with symbols in it")
                                   + ". Copy it again from the app's settings.", False)
        self.login_ok = False
        if hasattr(self, "btn_next"):
            self._refresh_next()

    # ---------------- 3 privacy and terms ----------------

    def _agree(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_h("Privacy policy and end user agreement"))
        v.addWidget(_p("<p>Please read both before signing in to Spotify. In short: Playlist Flow "
                       "has no server and collects nothing; your keys, sign-in and playlists stay "
                       "on this PC.</p>"))
        tabs = QTabWidget()
        tabs.setObjectName("agree_tabs")
        for title, name in (("Privacy policy", "PRIVACY.md"), ("End user agreement", "TERMS.md")):
            tb = QTextBrowser()
            tb.setObjectName(f"doc_{name.split('.')[0].lower()}")
            tb.setOpenExternalLinks(True)
            tb.setMarkdown(read_doc(name))
            tabs.addTab(tb, title)
        v.addWidget(tabs, 1)
        self.agree_box = QCheckBox("I have read and agree to the Playlist Flow end user agreement "
                                   "and privacy policy")
        self.agree_box.setObjectName("agree_box")
        self.agree_box.toggled.connect(lambda _: self._refresh_next())
        v.addWidget(self.agree_box)
        return w

    # ---------------- 4 sign in ----------------

    def _login(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_h("Sign in to Spotify"))
        v.addWidget(_p(
            "<ol style='margin-left:-18px'>"
            "<li>Click <b>Open Spotify sign-in</b>. Your browser opens Spotify's login.</li>"
            "<li>Approve. The browser shows <b>\"You can close this tab\"</b> and this step "
            "finishes by itself.</li>"
            "</ol>"
            f"<p style='color:{theme.MUTED}'>While it waits, Playlist Flow listens on "
            "127.0.0.1 (this PC only) for Spotify's answer, and stops as soon as it arrives. "
            "If the browser shows an error page instead, copy the whole address from its "
            "address bar, paste it below and click <b>Check sign-in</b>.</p>"))
        row = QHBoxLayout()
        b = QPushButton("Open Spotify sign-in")
        b.setObjectName("open_signin")
        b.clicked.connect(self._open_signin)
        row.addWidget(b)
        self.btn_existing = QPushButton("Check current sign-in")
        self.btn_existing.setObjectName("check_existing")
        self.btn_existing.setToolTip("Use the sign-in Playlist Flow already has, if it still works")
        self.btn_existing.clicked.connect(self._check_existing)
        row.addWidget(self.btn_existing)
        row.addStretch(1)
        v.addLayout(row)
        self.paste = QLineEdit()
        self.paste.setObjectName("paste")
        self.paste.setPlaceholderText("http://127.0.0.1:…/callback?code=…")
        v.addWidget(self.paste)
        b = QPushButton("Check sign-in")
        b.setObjectName("check_signin")
        b.clicked.connect(self.check_signin)
        v.addWidget(b, 0, Qt.AlignLeft)
        self.login_msg = QLabel("")
        self.login_msg.setObjectName("login_msg")
        self.login_msg.setWordWrap(True)
        v.addWidget(self.login_msg)
        v.addStretch(1)
        return w

    def _apply_auth(self):
        self.auth.client_id = clean_key(self.client_id.text())
        self.auth.port = self.port() or DEFAULT_REDIRECT_PORT

    def _open_signin(self):
        self._apply_auth()
        try:
            url = self.auth.begin()
        except AuthError as e:
            _say(self.login_msg, explain_auth_error(e, self.auth.redirect_uri), False)
            return
        self.login_ok = False
        self._refresh_next()
        listening = self.start_listening()
        self._open_url(url)
        if listening:
            _say(self.login_msg, "Browser opened. Approve there, and this step finishes by "
                                 "itself.", None)
        else:
            _say(self.login_msg, f"Browser opened. Playlist Flow couldn't listen on port "
                                 f"{self.auth.port}, so once you approve, paste the address "
                                 "the browser lands on above and click Check sign-in.", None)

    # automatic sign-in: the listener

    def start_listening(self) -> bool:
        """Listen for the redirect of the sign-in begin() just started. False when the
        port can't be bound (the paste box is the fallback)."""
        self.stop_listening()
        lst = self._listener_factory(self.auth.port, self._caught.emit)
        try:
            ok = lst.start(self.auth._state)
        except Exception:
            ok = False
        if not ok:
            return False
        self.listener = lst
        self._signin_timer.start(SIGNIN_TIMEOUT_MS)
        return True

    def stop_listening(self):
        self._signin_timer.stop()
        lst, self.listener = self.listener, None
        if lst is not None:
            try:
                lst.stop()
            except Exception:
                pass

    def _signin_timed_out(self):
        if self.listener is None:
            return
        self.stop_listening()
        if not self.login_ok:
            _say(self.login_msg, "Stopped waiting for Spotify. Click Open Spotify sign-in to try "
                                 "again, or paste the address the browser landed on.", None)

    def _on_caught(self, url: str):
        if self.listener is None:
            return                         # stopped meanwhile (cancel, timeout, other step)
        self.stop_listening()
        self.finish_signin(url)

    def check_signin(self) -> bool:
        self.stop_listening()
        return self.finish_signin(self.paste.text())

    def finish_signin(self, address: str) -> bool:
        self._apply_auth()
        self.login_ok = False
        try:
            self.auth.complete(address)
            ok, msg = self.verify(self.auth.access_token())
        except AuthError as e:
            ok, msg = False, explain_auth_error(e, self.auth.redirect_uri)
        except Exception as e:                       # network, anything: said, never raised
            ok, msg = False, (f"Sign-in failed: {e}" if str(e) else
                              f"Sign-in failed ({type(e).__name__}). Check your connection and retry.")
        self.login_ok = ok
        _say(self.login_msg, msg, ok)
        self._refresh_next()
        return ok

    def _check_existing(self) -> bool:
        self._apply_auth()
        self.login_ok = False
        state = self.auth.check()
        if state == "ok":
            try:
                ok, msg = self.verify(self.auth.access_token())
            except Exception as e:                   # offline between the two calls
                ok, msg = False, f"Couldn't finish the check: {e}"
        elif state == "none":
            ok, msg = False, "There is no saved sign-in for this client ID yet. Use Open Spotify sign-in."
        elif state == "dead":
            ok, msg = False, "The saved sign-in no longer works. Use Open Spotify sign-in."
        else:
            ok, msg = False, "Couldn't reach Spotify. Check your connection and try again."
        self.login_ok = ok
        _say(self.login_msg, msg, ok)
        self._refresh_next()
        return ok

    # ---------------- 4 FreqBlog ----------------

    def _freqblog(self, env: dict) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_h("FreqBlog key (required)"))
        v.addWidget(_p(
            "<p>FreqBlog supplies the BPM and musical key estimates. Their free tier has a "
            "monthly allowance of requests, plenty for normal use because looked-up tracks are "
            "remembered and never asked about twice.</p>"
            "<p><b>One free key per person. Never share it.</b></p>"))
        b = QPushButton("Get a free FreqBlog key")
        b.setObjectName("get_freqblog")
        b.clicked.connect(lambda: self._open_url(FREQBLOG_URL))
        v.addWidget(b, 0, Qt.AlignLeft)
        v.addWidget(QLabel("FreqBlog API key"))
        self.freqblog = QLineEdit(env.get("FREQBLOG_API_KEY", ""))
        self.freqblog.setObjectName("freqblog_key")
        self.freqblog.setPlaceholderText("Paste the key from FreqBlog's email")
        self.freqblog.textChanged.connect(self._freqblog_changed)
        v.addWidget(self.freqblog)
        self.freqblog_note = QLabel("")
        self.freqblog_note.setObjectName("freqblog_note")
        self.freqblog_note.setWordWrap(True)
        v.addWidget(self.freqblog_note)
        crow = QHBoxLayout()
        self.btn_fb_check = QPushButton("Check key")
        self.btn_fb_check.setObjectName("freqblog_check")
        self.btn_fb_check.clicked.connect(lambda: self.check_freqblog())
        crow.addWidget(self.btn_fb_check)
        self.fb_usage = QLabel("")
        self.fb_usage.setObjectName("freqblog_usage")
        self.fb_usage.setWordWrap(True)
        crow.addWidget(self.fb_usage, 1)
        v.addLayout(crow)
        v.addWidget(_p(f"<p style='color:{theme.MUTED}'>The check asks FreqBlog about the key "
                       "itself, which doesn't come out of your allowance. If FreqBlog ever "
                       "rejects the key later, Playlist Flow tells you once and brings you back "
                       "to this step.</p>"))
        v.addStretch(1)
        self._freqblog_changed()
        return w

    def _freqblog_changed(self):
        v, tidied = self._tidy(self.freqblog, valid_freqblog)
        self.fb_check = None              # a different key needs its own check
        if hasattr(self, "fb_usage"):
            self.fb_usage.setText("")
        if not v:
            _say(self.freqblog_note, "Required.", None)
        elif valid_freqblog(v):
            _say(self.freqblog_note, "Looks right. Click Check key (or Next) to ask FreqBlog."
                 + (" Extra text around it was removed." if tidied else ""), None)
        else:
            _say(self.freqblog_note, f"That doesn't look like a FreqBlog key: it should be 20 or "
                                     f"more letters, digits, - and _, and this is {len(v)} "
                                     "character(s)" + ("" if all(c.isalnum() or c in "-_" for c in v)
                                                       else ", with other symbols in it")
                                     + ". Copy it again from FreqBlog's email.", False)
        if hasattr(self, "btn_next"):
            self._refresh_next()

    def check_freqblog(self):
        """One GET /me/stats. ok: key good, usage shown. rejected: FreqBlog's own words,
        Next stays locked. offline: said plainly, and Next goes on with the format check."""
        key = clean_key(self.freqblog.text())
        if not valid_freqblog(key) or self.fb_checking:
            return
        self.fb_checking = True
        self.btn_fb_check.setEnabled(False)
        _say(self.freqblog_note, "Checking the key with FreqBlog…", None)
        self.fb_usage.setText("")
        self._refresh_next()
        self._run_bg(lambda: self.key_check(key), lambda res: self._freqblog_checked(key, res))

    def _freqblog_checked(self, key: str, res):
        self.fb_checking = False
        self.btn_fb_check.setEnabled(True)
        if clean_key(self.freqblog.text()) != key:
            self._refresh_next()           # the key was changed while checking: ignore this one
            return
        status = getattr(res, "status", "offline")
        msg = getattr(res, "message", "") or (str(res) if res else "")
        self.fb_check = status
        if status == "ok":
            _say(self.freqblog_note, "FreqBlog accepted the key. Click Next to continue.", True)
            text, warn = usage_text(res.usage)
            colour = "#E8B04F" if warn else theme.MUTED
            self.fb_usage.setText(f"<span style='color:{colour}'>{html_escape(text, quote=False)}</span>")
        elif status == "rejected":
            _say(self.freqblog_note, "FreqBlog rejected the key: " + html_escape(msg, quote=False), False)
        else:
            self.fb_check = "offline"
            _say(self.freqblog_note, html_escape(msg or "Couldn't reach FreqBlog.", quote=False) +
                 " Only the key's format was checked, so you can go on with Next.", None)
        self._refresh_next()

    # ---------------- 5 GetSongBPM ----------------

    def _getsongbpm(self, env: dict) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_h("GetSongBPM key (optional)"))
        v.addWidget(_p(
            "<p>A fallback for tracks FreqBlog doesn't know. Skip this step if you like: leave the "
            "box empty and click Next.</p>"
            "<p>GetSongBPM's sign-up asks for a <b>website that links back to getsongbpm.com</b>. "
            "If you don't have one, use one of these, both already carry that link:</p>"))
        for site in BACKLINK_SITES:
            row, _, _ = _copy_row(site, "backlink_site")
            v.addLayout(row)
        b = QPushButton("Get a GetSongBPM key")
        b.setObjectName("get_getsongbpm")
        b.clicked.connect(lambda: self._open_url(GETSONGBPM_URL))
        v.addWidget(b, 0, Qt.AlignLeft)
        v.addWidget(QLabel("GetSongBPM API key (optional)"))
        self.getsongbpm = QLineEdit(env.get("GETSONGBPM_API_KEY", ""))
        self.getsongbpm.setObjectName("getsongbpm_key")
        self.getsongbpm.setPlaceholderText("Leave empty to skip")
        self.getsongbpm.textChanged.connect(self._getsongbpm_changed)
        v.addWidget(self.getsongbpm)
        self.getsongbpm_note = QLabel("")
        self.getsongbpm_note.setObjectName("getsongbpm_note")
        self.getsongbpm_note.setWordWrap(True)
        v.addWidget(self.getsongbpm_note)
        v.addStretch(1)
        self._getsongbpm_changed()
        return w

    def _getsongbpm_changed(self):
        v, tidied = self._tidy(self.getsongbpm, valid_getsongbpm)
        if not v:
            _say(self.getsongbpm_note, "Optional. Empty means skipped.", None)
        elif valid_getsongbpm(v):
            _say(self.getsongbpm_note, "Looks right." + (" (Extra text around it was removed.)"
                                                         if tidied else ""), True)
        else:
            _say(self.getsongbpm_note, f"That doesn't look like a GetSongBPM key: it should be 16 "
                                       f"or more letters and digits, and this is {len(v)} "
                                       "character(s)" + ("" if v.isalnum() else ", with symbols "
                                                         "in it") + ". Copy it again, or leave "
                                       "the box empty to skip.", False)
        if hasattr(self, "btn_next"):
            self._refresh_next()

    # ---------------- 6 storage ----------------

    @staticmethod
    def default_storage() -> str:
        return str(Path.home() / "Documents" / "PlaylistFlow")

    def _storage(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_h("Where to keep your playlists"))
        v.addWidget(_p("<p>Saved playlists and the remembered BPM/key values live here. Keys are "
                       "never stored in this folder. Changing it later never moves or deletes "
                       "files that are already somewhere else.</p>"))
        row = QHBoxLayout()
        self.folder = QLineEdit(self.prefs.storage_dir or self.default_storage())
        self.folder.setObjectName("storage_folder")
        self.folder.textChanged.connect(lambda _: self._refresh_next())
        row.addWidget(self.folder, 1)
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse)
        row.addWidget(b)
        v.addLayout(row)
        v.addStretch(1)
        return w

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Folder for saved playlists", self.folder.text())
        if d:
            self.folder.setText(d)

    # ---------------- 7 done ----------------

    def _done(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_h("All set"))
        self.summary = _p("")
        self.summary.setObjectName("summary")
        v.addWidget(self.summary)
        v.addWidget(_p(f"<p style='color:{theme.MUTED}'>Click Finish to save. You can run this "
                       "setup again any time: Settings &gt; Run setup again.</p>"))
        v.addStretch(1)
        return w

    def _fill_summary(self):
        gs = "added" if clean_key(self.getsongbpm.text()) else "skipped"
        fb = {"ok": "saved, accepted by FreqBlog",
              "offline": "saved (format checked; FreqBlog couldn't be reached)"}.get(
            self.fb_check, "saved")
        self.summary.setText(
            "<ul>"
            f"<li>Spotify app: client ID saved, redirect {redirect_uri(self.port() or DEFAULT_REDIRECT_PORT)}</li>"
            f"<li>Spotify sign-in: {'working' if self.login_ok else 'not tested'}</li>"
            f"<li>FreqBlog key: {fb}</li>"
            f"<li>GetSongBPM key: {gs}</li>"
            f"<li>Playlists folder: {self.folder.text().strip()}</li>"
            "</ul>"
            f"<p style='color:{theme.MUTED}'>Keys are in {env_path()}. "
            "The Spotify sign-in stays in your Windows user settings.</p>")

    # ---------------- save ----------------

    def collected(self) -> dict:
        """Exactly what this wizard gathered, as .env entries."""
        out = {"SPOTIFY_CLIENT_ID": clean_key(self.client_id.text()),
               "SPOTIFY_REDIRECT_PORT": str(self.port() or DEFAULT_REDIRECT_PORT),
               "FREQBLOG_API_KEY": clean_key(self.freqblog.text())}
        gs = clean_key(self.getsongbpm.text())
        out["GETSONGBPM_API_KEY"] = gs                # empty removes a skipped key
        return out

    def save(self):
        """Merge into the user's own .env: display settings already there stay, the
        collected entries replace theirs, nothing else is added (save_env writes only
        known names, so no client secret or retired key can come back)."""
        vals = dict(self.env_before)
        vals.update(self.collected())
        save_env(vals)
        self.prefs.storage_dir = self.folder.text().strip()
        self.saved = True
