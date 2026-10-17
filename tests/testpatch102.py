import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import nonet  # noqa: F401  (no network in tests)
"""1.0.2: the shuffle button on the player bar. Spotify is a fake object, settings are a
throwaway .ini, nothing is shown on screen.

    .venv\\Scripts\\python tests\\testpatch102.py
"""

import logging
import math
import os
import shutil
import subprocess
import tempfile
import time

CHILD = "--clearspace-only" in sys.argv
TMP = pathlib.Path(tempfile.mkdtemp(prefix="pf-102-"))
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
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication([])

from playlistflow import config, theme
config.app_dir = lambda: TMP
from playlistflow import providers as pv
from playlistflow.domain import Track
import playlistflow.mainwindow as mw
mw.setup_needed = lambda env, state: ""

RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def window():
    w = mw.MainWindow()
    w.setAttribute(Qt.WA_DontShowOnScreen, True)
    w.resize(1400, 900)
    w.show()
    end = time.time() + 10
    while w.store is None and time.time() < end:
        app.processEvents()
        time.sleep(0.02)
    return w


def playing_state(shuffle=False, smart=None, disallow=False):
    st = {"is_playing": True, "progress_ms": 1000, "shuffle_state": shuffle,
          "item": {"uri": "spotify:track:S1", "name": "Synthetic", "duration_ms": 200000,
                   "artists": [{"name": "Sample"}], "album": {"images": []}}}
    if smart is not None:
        st["smart_shuffle"] = smart
    if disallow:
        st["actions"] = {"disallows": {"toggling_shuffle": True}}
    return st


def clear_space(w, where):
    bad = []
    lab = w.player.spotify_logo
    pm = lab.pixmap()
    zone = math.ceil(pm.height() / pm.devicePixelRatio() / 2)
    r = lab.contentsRect()
    need = QRect(lab.mapTo(w, r.topLeft()), r.size()).adjusted(-zone, -zone, zone, zone)
    for o in w.findChildren(QWidget):
        if (o.isVisible() and o is not lab and not o.isAncestorOf(lab) and not lab.isAncestorOf(o)
                and not o.isWindow() and QRect(o.mapTo(w, o.rect().topLeft()), o.size()).intersects(need)):
            bad.append(o.objectName() or type(o).__name__)
    ok(f"player logo clear space ({where})", not bad, ", ".join(bad))


def position_and_space():
    w = window()
    w.player.set_state(True, "Synthetic", "Sample", 0, 1000, "", uri="spotify:track:S1")
    w._show_shuffle(playing_state(True))
    for rows in (1, 2):
        if rows == 2:
            b = {x.objectName(): x for x in w.tool_groups}
            w.insertToolBarBreak(b["tools_data"])
        for label, size in (("smallest", None), ("default", (1280, 860)), ("large", (2560, 1440))):
            for _ in range(3):
                app.processEvents()
                m = w.minimumSizeHint().expandedTo(w.minimumSize())
                w.resize(*(size or (m.width(), m.height())))
            app.processEvents()
            p = w.player
            xs = [p.open_link.geometry().x(), p.btn_shuffle.geometry().x(), p.btn_prev.geometry().x()]
            ok(f"[{rows} row(s), {label}] shuffle sits between OPEN SPOTIFY and back",
               xs[0] < xs[1] < xs[2] and p.btn_shuffle.width() == p.btn_prev.width(), str(xs))
            clear_space(w, f"{rows} row(s), {label}, {os.environ.get('QT_SCALE_FACTOR', '1')}x")
    w.close()


if CHILD:
    position_and_space()
    passed = sum(1 for _, r in RESULTS if r)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"CHILD {passed} of {len(RESULTS)}")
    raise SystemExit(0 if passed == len(RESULTS) else 1)

# ---------------------------------------------------------------------------
print("1. placement and clear space")
position_and_space()
for factor in ("1.25", "1.5"):
    r = subprocess.run([sys.executable, __file__, "--clearspace-only"],
                       env=dict(os.environ, QT_SCALE_FACTOR=factor),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
    fails = [l.strip() for l in r.stdout.splitlines() if "[FAIL]" in l]
    last = [l for l in r.stdout.splitlines() if l.startswith("CHILD")]
    ok(f"the same at {float(factor):.0%}: {last[-1] if last else 'no output'}",
       r.returncode == 0 and not fails, "; ".join(fails[:3]))

# ---------------------------------------------------------------------------
print("2. looks, tooltip and state from the poll")


class FakeSpotify:
    def __init__(self):
        self.state = playing_state(False)
        self.shuffle_calls = []
        self.refuse = False
        self.played = []

    def player_state(self):
        return self.state

    def set_shuffle(self, state):
        self.shuffle_calls.append(state)
        if self.refuse:
            raise pv.ProviderError("Spotify refused playback control. This needs Spotify Premium.")
        self.state = dict(self.state, shuffle_state=state)

    def play(self, *a, **k):
        self.played.append((a, k))

    def resume(self, *a, **k):
        self.played.append((a, k))

    def pause(self):
        pass

    def playlist_details(self, pid):
        return {"name": "", "description": "", "public": False, "image": ""}


w = window()
fake = FakeSpotify()
w.spotify = fake
w.prefs.refresh_token = "synthetic-refresh"
p = w.player
w.poll_player()
ok("off: not lit, no glow, tooltip 'Shuffle: off', enabled", not p.btn_shuffle.isChecked()
   and p.btn_shuffle.graphicsEffect() is None and p.btn_shuffle.toolTip() == "Shuffle: off"
   and p.btn_shuffle.isEnabled())
fake.state = playing_state(True)
w.poll_player()
glow = p.btn_shuffle.graphicsEffect()
ok("on (read from the poll): lit, #19C2E6 glow, tooltip 'Shuffle: on'", p.btn_shuffle.isChecked()
   and glow is not None and glow.color().name() == "#19c2e6" and p.btn_shuffle.toolTip() == "Shuffle: on")
ok("lit style: the cyan fill of an active toolbar button",
   f"QPushButton#shuffle:checked {{ background: {theme.ACCENT}" in theme.QSS)
ok("the bundled mdi6 shuffle icon", not p.btn_shuffle.icon().isNull())

# ---------------------------------------------------------------------------
print("3. clicking")
fake.state = playing_state(False)
w.poll_player()
fake.shuffle_calls.clear()
p.btn_shuffle.click()
ok("a click sends exactly one shuffle request, for 'on'", fake.shuffle_calls == [True])
ok("the button shows it at once", p.btn_shuffle.isChecked())
w.poll_player()
ok("the next poll confirms it, no message", p.btn_shuffle.isChecked()
   and "kept shuffle" not in w.statusBar().currentMessage())
p.btn_shuffle.click()
ok("clicking again sends one request, for 'off'", fake.shuffle_calls == [True, False]
   and not p.btn_shuffle.isChecked())
w.poll_player()

fake.refuse = True
fake.shuffle_calls.clear()
p.btn_shuffle.click()
ok("refused: back to the real state, with a short message", fake.shuffle_calls == [True]
   and not p.btn_shuffle.isChecked() and "Shuffle wasn't changed" in w.statusBar().currentMessage())
fake.refuse = False

real_set = fake.set_shuffle
fake.set_shuffle = lambda st: fake.shuffle_calls.append(st)      # accepted, but nothing changes
p.btn_shuffle.click()
ok("an accepted click shows lit at once", p.btn_shuffle.isChecked())
w.poll_player()
ok("the first disagreeing poll waits for one more look", p.btn_shuffle.isChecked())
w.poll_player()
ok("the second: the real state (off) and 'Spotify kept shuffle off.'", not p.btn_shuffle.isChecked()
   and w.statusBar().currentMessage() == "Spotify kept shuffle off.")
fake.set_shuffle = real_set

# ---------------------------------------------------------------------------
print("4. smart shuffle, Spotify disallowing it, nothing playing")
fake.state = playing_state(False, smart=True)
w.poll_player()
fake.shuffle_calls.clear()
ok("smart shuffle on: lit, with its own tooltip", p.btn_shuffle.isChecked()
   and p.btn_shuffle.toolTip() == "Smart shuffle is on. Turn it off in Spotify.")
p.btn_shuffle.click()
ok("clicking it sends nothing and says so", fake.shuffle_calls == [] and p.btn_shuffle.isChecked()
   and w.statusBar().currentMessage() == "Smart shuffle is on. Turn it off in Spotify.")
fake.state = playing_state(True, disallow=True)
w.poll_player()
ok("Spotify disallows toggling: disabled, says why", not p.btn_shuffle.isEnabled()
   and "doesn't allow" in p.btn_shuffle.toolTip())
fake.state = playing_state(True)
w.poll_player()
fake.state = None
w.poll_player()
ok("nothing playing: last known state (on), disabled, start playback first",
   p.btn_shuffle.isChecked() and not p.btn_shuffle.isEnabled()
   and "Start playback in Spotify first" in p.btn_shuffle.toolTip())
fake.shuffle_calls.clear()
w.toggle_shuffle(False)
ok("a click with no playback sends nothing", fake.shuffle_calls == [])

# ---------------------------------------------------------------------------
print("5. nothing else ever touches shuffle")
lines = []


class Grab(logging.Handler):
    def emit(self, rec):
        lines.append(rec.getMessage())


lg = logging.getLogger("playlistflow")
lg.addHandler(Grab())
lg.setLevel(logging.DEBUG)
fake.state = playing_state(True)
w.poll_player()
fake.shuffle_calls.clear()
fake.played.clear()
w.tracks = [Track(title=f"Synthetic {i}", artist="Sample", uri=f"spotify:track:T{i}", bpm=100 + i,
                  key="8A", duration_ms=200000) for i in range(5)]
w.refresh()
w.table.itemDoubleClicked.emit(w.table.item(2, 1))
w.play_from(0)
w.preview_row(1, 10)
w._last_player_state = None
w.toggle_play()
w.worker = None
w.sort_tracks("bpm")
ok("double-click, Play from here, Play, Preview transition, sort: no shuffle request",
   fake.shuffle_calls == [] and len(fake.played) >= 4, f"{fake.shuffle_calls} played={len(fake.played)}")
ok("... and no play request carries anything about shuffle",
   all("shuffle" not in (repr(a) + repr(k)) for a, k in fake.played))
ok("debug: play lines carry the shuffle state last seen",
   any(l.startswith("play:") and "shuffle_last_seen=" in l for l in lines))
w.close()
w.prefs.refresh_token = ""               # new windows must not reach the real Spotify
w2 = window()
ok("startup: the button disabled until Spotify reports playback; nothing sent",
   not w2.player.btn_shuffle.isEnabled())
w2.close()
src = "".join(open(f, encoding="utf-8").read() for f in (
    mw.__file__, pv.__file__, sys.modules["playlistflow.player"].__file__))
ok("set_shuffle is called from exactly one place (the button's handler)",
   src.count("spotify.set_shuffle(") == 1)
ok("sync and push code never mention shuffle", "shuffle" not in (
    __import__("inspect").getsource(mw.MainWindow.sync_playlist) +
    __import__("inspect").getsource(mw.MainWindow.push_order)))

w3 = window()
w3.spotify = fake
w3.prefs.refresh_token = "synthetic-refresh"
fake.state = playing_state(False)
w3.poll_player()
lines.clear()
w3.player.btn_shuffle.click()
ok("a debug line for the click: the state asked and the result", lines == ["shuffle: click want=on result=sent"],
   str(lines))
ok("no ids, names or tokens in debug lines", not any(("spotify:" in l or "Synthetic" in l or "refresh" in l)
                                                    for l in lines))
w3.close()

ok("no network was attempted", not nonet.BLOCKED, str(nonet.BLOCKED))
passed = sum(1 for _, r in RESULTS if r)
print(f"\n{passed} of {len(RESULTS)} passed")
shutil.rmtree(TMP, ignore_errors=True)
print("1.0.2 TESTS PASSED" if passed == len(RESULTS) else "1.0.2 TESTS FAILED")
raise SystemExit(0 if passed == len(RESULTS) else 1)
