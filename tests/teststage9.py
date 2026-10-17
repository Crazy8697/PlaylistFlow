import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import nonet  # noqa: F401  (no network in tests)
"""Stage 9: the startup agreement, the Spotify logos' clear space, artwork and the
links back to Spotify.

All synthetic and offscreen; settings are a throwaway .ini. The clear-space check runs
again in child processes at 125% and 150% scaling (QT_SCALE_FACTOR).

    .venv\\Scripts\\python tests\\teststage9.py
"""

import os
import shutil
import subprocess
import tempfile

SCALE_CHILD = "--clearspace-only" in sys.argv
TMP = pathlib.Path(tempfile.mkdtemp(prefix="pf-stage9-"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = str(TMP / "appdata")
os.environ["USERPROFILE"] = str(TMP / "home")
os.environ["HOME"] = str(TMP / "home")
os.environ["PLAYLISTFLOW_SETTINGS_INI"] = str(TMP / "settings.ini")
os.environ["PLAYLISTFLOW_UPDATE_URL"] = "http://127.0.0.1:9/never"
for k in ("SPOTIFY_CLIENT_ID", "FREQBLOG_API_KEY", "GETSONGBPM_API_KEY"):
    os.environ.pop(k, None)
(TMP / "appdata" / "PlaylistFlow").mkdir(parents=True)
(TMP / "home").mkdir()
(TMP / "store").mkdir()
(TMP / "settings.ini").write_text("[General]\nupdate_check=false\nstorage_dir=" +
                                  (TMP / "store").as_posix() + "\n", encoding="ascii")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget
app = QApplication([])

from playlistflow import config
config.app_dir = lambda: TMP                  # never the repo-root .env
from playlistflow import brand, docs
from playlistflow import wizard as wz
from playlistflow.artwork import cover_pixmap, ART_RADIUS
from playlistflow.config import Prefs, save_env
from playlistflow.domain import Track
import playlistflow.mainwindow as mw

RESULTS = []
SCALE = os.environ.get("QT_SCALE_FACTOR", "1")


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


# ---------------------------------------------------------------------------
def clear_space_checks():
    print(f"clear space around the Spotify logos at {float(SCALE):.0%} scaling")
    mw.setup_needed = lambda env, state: ""
    w = mw.MainWindow()
    w.setAttribute(Qt.WA_DontShowOnScreen, True)
    w.current_pid = "SYNTHETICPLAYLISTID0001"
    w.current_name = "A Synthetic Playlist With A Long Name For Squeezing"
    w.tracks = [Track(title=f"Synthetic {i}", artist="Sample", uri=f"spotify:track:S{i:04d}",
                      bpm=100 + i, key="8A", duration_ms=200000) for i in range(30)]
    w.player.set_state(True, "Synthetic Track", "Sample Artist", 1000, 200000, "",
                       uri="spotify:track:SYNTHETICTRACK01")
    w.show()
    w.refresh()
    app.processEvents()

    def zone_clear(label: QWidget, where: str):
        import math
        pm = label.pixmap()
        ph = pm.height() / pm.devicePixelRatio()
        zone = math.ceil(ph / 2)                       # the guidelines: half the icon height
        r = label.contentsRect()                      # the logo itself (fixed size label)
        top_left = label.mapTo(w, r.topLeft())
        logo = QRect(top_left, r.size())
        need = logo.adjusted(-zone, -zone, zone, zone)
        bad = []
        for o in w.findChildren(QWidget):
            if not o.isVisible() or o is label or o.isAncestorOf(label) or label.isAncestorOf(o):
                continue
            if o.isWindow():
                continue
            g = QRect(o.mapTo(w, o.rect().topLeft()), o.size())
            if g.intersects(need):
                bad.append(f"{type(o).__name__}:{o.objectName() or '-'}")
        ok(f"{where}: logo {logo.width()}x{logo.height()}, clear space {zone}px "
           f"(half the {ph:g}px icon height), nothing inside it", not bad, ", ".join(bad[:6]))

    smallest = w.minimumSizeHint().expandedTo(w.minimumSize())   # header filled
    for label_txt, size in ((f"smallest {smallest.width()}x{smallest.height()}", smallest),
                            ("1280x860 default", None), ("2560x1440 large", (2560, 1440))):
        if size is None:
            w.resize(1280, 860)
        elif isinstance(size, tuple):
            w.resize(*size)
        else:
            w.resize(size)
        app.processEvents()
        w.refresh()
        app.processEvents()
        for lab, where in ((w.pl_spotify, "playlist header"), (w.sp_logo, "Spotify playlists box"),
                           (w.player.spotify_logo, "player bar")):
            ok(f"[{label_txt}] {where}: logo visible", lab.isVisible())
            zone_clear(lab, f"[{label_txt}] {where}")
    w.close()


if SCALE_CHILD:
    clear_space_checks()
    passed = sum(1 for _, r in RESULTS if r)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"CHILD {passed} of {len(RESULTS)}")
    raise SystemExit(0 if passed == len(RESULTS) else 1)

# ---------------------------------------------------------------------------
print("1. the startup agreement")
GOOD = {"SPOTIFY_CLIENT_ID": "0123456789abcdef0123456789abcdef",
        "FREQBLOG_API_KEY": "synthetic_freqblog_key_0123456789"}
p = Prefs()
p.refresh_token = "synthetic-refresh"
shown = []


class FakeDialog:
    answer = QDialog.Accepted

    def __init__(self, prefs):
        shown.append(prefs.agreement_version)
        self.prefs = prefs

    def exec(self):
        if FakeDialog.answer == QDialog.Accepted:
            self.prefs.agreement_version = docs.AGREEMENT_VERSION
        return FakeDialog.answer


for label, stored in (("missing", ""), ("older", "2026-10-17")):
    p.agreement_version = stored
    shown.clear()
    ok(f"set up, {label} version: shown", wz.startup_agreement_needed(GOOD, p))
    FakeDialog.answer = QDialog.Accepted
    ok(f"set up, {label} version: agree carries on and stores the version",
       wz.run_startup_agreement(GOOD, p, FakeDialog) and shown == [stored]
       and Prefs().agreement_version == docs.AGREEMENT_VERSION)
    ok(f"set up, {label} version: not shown again afterwards",
       not wz.startup_agreement_needed(GOOD, p))
p.agreement_version = "2026-10-17"
shown.clear()
FakeDialog.answer = QDialog.Rejected
ok("declined: the program doesn't start, nothing stored",
   not wz.run_startup_agreement(GOOD, p, FakeDialog) and Prefs().agreement_version == "2026-10-17")
p.agreement_version = docs.AGREEMENT_VERSION
shown.clear()
ok("current version: skipped", wz.run_startup_agreement(GOOD, p, FakeDialog) and not shown)
p.agreement_version = ""
for label, env, tok in (("no keys", {}, "synthetic-refresh"),
                        ("no FreqBlog key", {"SPOTIFY_CLIENT_ID": GOOD["SPOTIFY_CLIENT_ID"]}, "x"),
                        ("never signed in", GOOD, "")):
    p.refresh_token = tok
    shown.clear()
    ok(f"first-time user ({label}): not shown at startup, the wizard has it",
       not wz.startup_agreement_needed(env, p) and wz.run_startup_agreement(env, p, FakeDialog)
       and not shown)
p.refresh_token = "synthetic-refresh"

# the real dialog
asked = []
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[1]), asked_answer[0])[1])
asked_answer = [QMessageBox.No]
p.agreement_version = "2026-10-17"
d = wz.AgreementDialog(p)
d.setAttribute(Qt.WA_DontShowOnScreen, True)
d.show()
app.processEvents()
docs_text = {tb.objectName(): tb.toPlainText() for tb in d.findChildren(wz.QTextBrowser)}
ok("same documents as the wizard step", "privacy policy" in docs_text.get("doc_privacy", "").lower()
   and "end user agreement" in docs_text.get("doc_terms", "").lower())
ok("'I agree' starts unticked and Agree is locked", not d.agree_box.isChecked()
   and not d.btn_agree.isEnabled())
d.btn_agree.click()
ok("Agree does nothing while unticked", d.isVisible() and Prefs().agreement_version == "2026-10-17")
d.btn_decline.click()
ok("Decline asks 'Quit Playlist Flow?'; No keeps the agreement open",
   asked == ["Quit Playlist Flow?"] and d.isVisible() and not d.quit_confirmed)
asked_answer[0] = QMessageBox.Yes
d.close()
ok("closing the window asks the same; Yes quits and stores nothing",
   len(asked) == 2 and d.quit_confirmed and d.result() == QDialog.Rejected
   and Prefs().agreement_version == "2026-10-17")
d2 = wz.AgreementDialog(p)
d2.setAttribute(Qt.WA_DontShowOnScreen, True)
d2.show()
d2.agree_box.setChecked(True)
ok("ticking unlocks Agree", d2.btn_agree.isEnabled())
d2.btn_agree.click()
ok("Agree stores the current version", d2.result() == QDialog.Accepted
   and Prefs().agreement_version == docs.AGREEMENT_VERSION)
ok("wizard's own step is skipped afterwards (never twice in one launch)",
   wz.SetupWizard(mw.SpotifyAuth("", p), p, None, start=wz.LOGIN,
                  scan=[(8888, False)], open_url=lambda u: None).stack.currentIndex() == wz.LOGIN)
import main as program_main
import inspect
src = inspect.getsource(program_main.main)
ok("main() asks before the main window is created",
   src.index("run_startup_agreement(") < src.index("MainWindow()"))

# ---------------------------------------------------------------------------
print("2. artwork: whole, uncropped, 4 px corners")
img = QImage(300, 150, QImage.Format_ARGB32)
img.fill(QColor("#ff0000"))
for x in range(150):
    img.setPixelColor(x, 75, QColor("#00ff00"))            # a marker on the left half
pm = cover_pixmap(img, 86).toImage()
ok("not cropped: the far left of the art is still there",
   pm.pixelColor(1, 43).red() > 200 or pm.pixelColor(1, 43).green() > 200)
ok("letterboxed, not stretched or cut: transparent above and below",
   pm.pixelColor(43, 2).alpha() == 0 and pm.pixelColor(43, 84).alpha() == 0)
sq = cover_pixmap(QImage(img.copy(0, 0, 150, 150)), 86).toImage()
ok(f"corners rounded ({ART_RADIUS} px): the corner pixel is clear, the edge middle is not",
   sq.pixelColor(0, 0).alpha() == 0 and sq.pixelColor(43, 0).alpha() > 0)
ok("radius is the guidelines' 4 px for small and medium devices", ART_RADIUS == 4)

# ---------------------------------------------------------------------------
print("3. links back to Spotify")
ok("app installed: 'OPEN SPOTIFY' to the item in the app",
   brand.link_text(True) == "OPEN SPOTIFY"
   and brand.spotify_target("playlist", "PL1", True) == "spotify:playlist:PL1")
ok("not installed: 'GET SPOTIFY FREE' to Spotify's download page",
   brand.link_text(False) == "GET SPOTIFY FREE"
   and brand.spotify_target("track", "T1", False) == brand.GET_SPOTIFY_URL)
lab = brand.spotify_link()
brand.set_link_target(lab, "playlist", "PL1", installed=True)
ok("the header link names and targets the playlist", lab.property("target") == "spotify:playlist:PL1"
   and "OPEN SPOTIFY" in lab.text())
brand.set_link_target(lab, "playlist", "")
ok("no playlist from Spotify: no link", lab.property("target") == "" and not lab.isVisibleTo(lab.parentWidget() or lab))
opened = []
brand.open_in_spotify("track", "T9", opener=opened.append)
ok("open_in_spotify uses the same target", opened and opened[0] in ("spotify:track:T9", brand.GET_SPOTIFY_URL))
ok("every Spotify logo in the program is the full logo",
   "full=False" not in inspect.getsource(mw) and "full=False" not in
   inspect.getsource(sys.modules["playlistflow.player"]))
from playlistflow.table import TrackTable
tsrc = inspect.getsource(TrackTable)
ok("track rows: an Open Spotify action, and the full title and artist in tooltips",
   "openInSpotify" in tsrc and "title.setToolTip(t.title" in tsrc and "art.setToolTip(t.artist)" in tsrc)
ok("program name has no 'Spotify' and doesn't start with 'Spot'",
   "spotify" not in "Playlist Flow".lower() and not "Playlist Flow".lower().startswith("spot"))

# ---------------------------------------------------------------------------
Prefs().refresh_token = ""          # the window below must not try to reach Spotify
clear_space_checks()
for factor in ("1.25", "1.5"):
    env = dict(os.environ, QT_SCALE_FACTOR=factor)
    r = subprocess.run([sys.executable, __file__, "--clearspace-only"], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    lines = [l for l in r.stdout.splitlines() if l.strip().startswith("[") or l.startswith("CHILD")]
    fails = [l for l in lines if "[FAIL]" in l]
    for l in fails:
        print("   ", l.strip())
    ok(f"clear space at {float(factor):.0%} scaling: {lines[-1] if lines else 'no output'}",
       r.returncode == 0 and not fails, r.stderr.strip().splitlines()[-1] if r.returncode and r.stderr.strip() else "")

ok("no network was attempted", not nonet.BLOCKED, str(nonet.BLOCKED))
passed = sum(1 for _, r in RESULTS if r)
print(f"\n{passed} of {len(RESULTS)} passed")
shutil.rmtree(TMP, ignore_errors=True)
print("STAGE 9 TESTS PASSED" if passed == len(RESULTS) else "STAGE 9 TESTS FAILED")
raise SystemExit(0 if passed == len(RESULTS) else 1)
