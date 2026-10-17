import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
"""Render every window and dialog to PNG, isolated, for a visual review.

    .venv\\Scripts\\python tests\\shotall.py <output folder>

Nothing is shown on screen and nothing takes the focus: widgets are laid out with
WA_DontShowOnScreen and captured with grab(). Settings live in a throwaway .ini
(PLAYLISTFLOW_SETTINGS_INI), APPDATA points at a temp folder holding synthetic
placeholder keys, the update check is off, and nothing signs in or calls a provider.
Modal dialogs are captured by swapping QDialog.exec for a grab while this runs.
"""

import os
import shutil
import tempfile

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "shots").resolve()
OUT.mkdir(parents=True, exist_ok=True)
TMP = pathlib.Path(tempfile.mkdtemp(prefix="pf-shots-"))
os.environ["APPDATA"] = str(TMP / "appdata")
os.environ["PLAYLISTFLOW_SETTINGS_INI"] = str(TMP / "settings.ini")
os.environ["PLAYLISTFLOW_UPDATE_URL"] = "http://127.0.0.1:9/never"
for k in ("SPOTIFY_CLIENT_ID", "FREQBLOG_API_KEY", "GETSONGBPM_API_KEY"):
    os.environ.pop(k, None)
(TMP / "appdata" / "PlaylistFlow").mkdir(parents=True)
(TMP / "appdata" / "PlaylistFlow" / ".env").write_text(
    "SPOTIFY_CLIENT_ID=synthetic-client-id\nFREQBLOG_API_KEY=synthetic-freqblog-key\n",
    encoding="utf-8")
(TMP / "store").mkdir()
(TMP / "settings.ini").write_text(
    "[General]\nstorage_dir=" + (TMP / "store").as_posix() + "\nupdate_check=false\n",
    encoding="ascii")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QInputDialog, QWidget

import main as program
from playlistflow import config as _config
# a source run also reads a .env next to the code (the repo root): never here
_config.app_dir = lambda: TMP
import playlistflow.mainwindow as _mw
_mw.setup_needed = lambda env, state: ""   # no setup wizard over these windows
app = QApplication([])
for step in ("setup_app", "_setup_app"):
    if hasattr(program, step):
        getattr(program, step)(app)
        break
else:                                     # the pre-Stage-5 main.py
    from PySide6.QtGui import QFont
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(program.QSS)

from playlistflow.domain import Track


def sample_tracks(n=40):
    """A synthetic set for the screenshots: made-up titles and artists, BPM and keys spread the
    way a real playlist's are (fixed seed, so every run draws the same picture)."""
    import random
    rnd = random.Random(7)
    keys = [f"{i}{l}" for i in range(1, 13) for l in "AB"]
    out = []
    for i in range(n):
        out.append(Track(title=f"Sample Track {i + 1:02d}", artist=f"Sample Artist {'ABCDEFGH'[i % 8]}",
                         bpm=float(rnd.choice([60, 65, 70, 74, 80, 85, 89, 98, 103, 110, 117, 122, 128,
                                               135, 140, 144, 150, 156, 160, 172, 180])),
                         key=rnd.choice(keys), source="manual", manual=True,
                         uri=f"spotify:track:sample{i:04d}", duration_ms=rnd.randint(150, 260) * 1000))
    return out
from playlistflow.mainwindow import MainWindow
from playlistflow import mainwindow as mw
from playlistflow.settings import SettingsDialog

SAVED = []


def save(widget: QWidget, name: str, size=None):
    widget.setAttribute(Qt.WA_DontShowOnScreen, True)
    if size:
        widget.resize(*size)
    widget.show()
    app.processEvents()
    widget.grab().save(str(OUT / f"{name}.png"))
    SAVED.append(f"{name}.png")
    widget.hide()


# modal dialogs: capture instead of blocking
_name = {"next": None}


def _grab_exec(self, *a, **k):
    nm = _name["next"] or type(self).__name__.lower()
    _name["next"] = None
    save(self, nm)
    return 0


QDialog.exec = _grab_exec

w = MainWindow()
import time as _t
_end = _t.time() + 15
while w.store is None and _t.time() < _end:      # the startup check runs in a thread
    app.processEvents()
    _t.sleep(0.02)
w._ensure_storage()
w.tracks = sample_tracks()
w.current_name = "Demo Set"
w.current_desc = "Synthetic sample set for the screenshots."
w.sp_list.addItems(["Demo Set", "Road Trip (sample)", "Late Night (sample)", "Warmup (sample)"])
w.refresh_saved() if hasattr(w, "refresh_saved") else None
w.refresh()
w.show_playlist_info()
save(w, "01-main-reported", (1440, 900))
w.set_felt(True)
save(w, "02-main-felt", (1440, 900))
w.set_felt(False)

# the update bar, as a newer release would show it
w._update_info = {"version": "1.0.1", "notes": "## 1.0.1\n\n- Sample release notes.\n- Shown for review only.",
                  "page": "https://github.com/Crazy8697/PlaylistFlow/releases"}
w.update_label.setText("Playlist Flow 1.0.1 is available")
w._update_bar_buttons(True)
w.update_bar.show()
save(w, "03-main-update-bar", (1440, 900))
_name["next"] = "04-release-notes"
w._show_release_notes()
w.update_bar.hide()

# Settings, both tabs
d = SettingsDialog(w, first_run=False, prefs=w.prefs)
tabs = d.findChild(mw.QTabWidget) if hasattr(mw, "QTabWidget") else None
if tabs is None:
    from PySide6.QtWidgets import QTabWidget
    tabs = d.findChild(QTabWidget)
save(d, "05-settings-connections", (720, 640))
tabs.setCurrentIndex(1)
save(d, "06-settings-display", (720, 640))

_name["next"] = "07-about"
(mw.AboutDialog(w)).exec()

_name["next"] = "08-sign-in"
w.sign_in() if hasattr(w, "sign_in") else None

_name["next"] = "09-export-uris"
w.export_uris()

from playlistflow.finderdialog import FinderDialog
fd = FinderDialog(w.spotify, set(), w)       # built directly: no sign-in, no search
_name["next"] = "10-bulk-finder"
fd.exec()

w.open_wheel()
if w.wheel is not None:
    save(w.wheel, "11-key-wheel")

mb = QMessageBox(QMessageBox.Question, "Unsaved changes", "Save changes to 'Demo Set' before closing?",
                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, w)
_name["next"] = "12-message-box"
mb.exec()
mb2 = QMessageBox(QMessageBox.Warning, "Updates",
                  "Couldn't check for updates: No connection to GitHub (offline, or blocked).",
                  QMessageBox.Ok, w)
_name["next"] = "13-warning-box"
mb2.exec()
ib = QInputDialog(w)
ib.setWindowTitle("Rename")
ib.setLabelText("New name:")
ib.setTextValue("Demo Set")
_name["next"] = "14-input-dialog"
ib.exec()

# ---- the setup wizard, every step, synthetic values only ----
from playlistflow import wizard as wz
from playlistflow.auth import SpotifyAuth
scan = [(8888, True)] + [(p, False) for p in range(8889, 8900)]
wiz = wz.SetupWizard(SpotifyAuth("", w.prefs), w.prefs, w, scan=scan,
                     verify=lambda tok: (True, "Signed in as Synthetic User. Spotify answered."),
                     open_url=lambda url: None)
wiz.client_id.setText("0123456789abcdef0123456789abcdef")
wiz.freqblog.setText("synthetic_freqblog_key_0123456789")
wiz.resize(760, 620)
w.prefs.agreement_version = ""           # show the agreement step as a first run would
for i, name in enumerate(("welcome", "spotify-app", "agreement", "sign-in", "freqblog",
                          "getsongbpm", "storage", "done")):
    if i == wz.AGREE:
        wiz.stack.setCurrentIndex(wz.AGREE)
        wiz.step_label.setText(f"STEP {i + 1} OF {len(wz.TITLES)}  ·  {wz.TITLES[i].upper()}")
        wiz._refresh_next()
        save(wiz, f"{20 + i:02d}-wizard-{i + 1}-{name}-unticked")
        wiz.agree_box.setChecked(True)
        save(wiz, f"{20 + i:02d}-wizard-{i + 1}-{name}-ticked")
        continue
    if i == wz.LOGIN:
        wiz.go(i)
        wiz.paste.setText("http://127.0.0.1:8889/callback?code=SYNTHETIC&state=SYNTHETIC")
        wiz.login_ok = False
        wz._say(wiz.login_msg, wz.explain_auth_error(
            Exception("invalid_client"), wiz.auth.redirect_uri), False)
        wiz._refresh_next()
        save(wiz, f"{20 + i:02d}-wizard-{i + 1}-{name}-failed")
        wiz.login_ok = True
        wz._say(wiz.login_msg, "Signed in as Synthetic User. Spotify answered.", True)
        wiz._refresh_next()
        save(wiz, f"{20 + i:02d}-wizard-{i + 1}-{name}-ok")
        continue
    wiz.go(i)
    save(wiz, f"{20 + i:02d}-wizard-{i + 1}-{name}")

# ---- the key-failure popups ----
w.open_wizard = lambda start=0, required=False: False      # don't follow the buttons here
for provider, nm in (("FreqBlog", "30-popup-freqblog-key"), ("GetSongBPM", "31-popup-getsongbpm-key")):
    _name["next"] = nm
    w._key_rejected(provider)
_name["next"] = "32-popup-spotify-signin-expired"
w._spotify_dead()

# ---- Stage 7: licenses, documents, disconnect ----
_name["next"] = "40-licenses"
mw.LicensesDialog(w).exec()
_name["next"] = "41-privacy-policy"
mw.DocDialog("PRIVACY.md", w).exec()
_name["next"] = "42-end-user-agreement"
mw.DocDialog("TERMS.md", w).exec()
_name["next"] = "43-disconnect-spotify"
mw.DisconnectDialog(w.prefs.storage_dir, w).exec()

print("saved to", OUT)
for n in SAVED:
    print(" ", n)
sys.stdout.flush()
shutil.rmtree(TMP, ignore_errors=True)
os._exit(0)
