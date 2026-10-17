import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import nonet  # noqa: F401  (no network in tests)
"""1.0.1: the toolbar layout sticks, the "Refused by Spotify" section, and a double-click
always plays the track that was clicked.

All synthetic: Spotify is a fake object, settings are a throwaway .ini, nothing is shown.

    .venv\\Scripts\\python tests\\testpatch101.py
"""

import json
import logging
import math
import os
import shutil
import tempfile
import time

TMP = pathlib.Path(tempfile.mkdtemp(prefix="pf-101-"))
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
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
app = QApplication([])

from playlistflow import config
config.app_dir = lambda: TMP
from playlistflow import providers as pv
from playlistflow.config import Prefs
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
    app.processEvents()
    return w


def layout(w):
    """(row, x-order) of each group: rows by y, order by x."""
    app.processEvents()
    pos = {b.objectName(): (b.geometry().y(), b.geometry().x()) for b in w.tool_groups}
    ys = sorted({y for y, _ in pos.values()})
    return {n: (ys.index(y), x) for n, (y, x) in pos.items()}


def order(w):
    lay = layout(w)
    return [n for n, _ in sorted(lay.items(), key=lambda kv: kv[1])]


# ---------------------------------------------------------------------------
print("1. the toolbar layout sticks")
w = window()
default = order(w)
ok("four groups with their own names", sorted(default) ==
   ["tools_data", "tools_playlist", "tools_sort", "tools_view"], str(default))
bars = {b.objectName(): b for b in w.tool_groups}
# VIEW to the far right of the first row, DATA and PLAYLIST down to a second row
w.removeToolBar(bars["tools_view"])
w.insertToolBar(bars["tools_data"], bars["tools_view"])
bars["tools_view"].show()
w.insertToolBarBreak(bars["tools_data"])
moved = layout(w)
ok("moved: VIEW last on row 1, DATA and PLAYLIST on row 2",
   moved["tools_view"][0] == 0 and moved["tools_data"][0] == 1 and moved["tools_playlist"][0] == 1
   and moved["tools_view"][1] > moved["tools_sort"][1], str(moved))
w._save_layout()
w.close()
w2 = window()
ok("after a restart the same rows and order come back", order(w2) == order(w) and
   {n: r for n, (r, _) in layout(w2).items()} == {n: r for n, (r, _) in moved.items()},
   str(layout(w2)))


def clear_space(win, where):
    bad_all = []
    for lab in (win.pl_spotify, win.sp_logo, win.player.spotify_logo):
        if not lab.isVisible():
            continue
        pm = lab.pixmap()
        zone = math.ceil(pm.height() / pm.devicePixelRatio() / 2)
        r = lab.contentsRect()
        need = QRect(lab.mapTo(win, r.topLeft()), r.size()).adjusted(-zone, -zone, zone, zone)
        for o in win.findChildren(QWidget):
            if (o.isVisible() and o is not lab and not o.isAncestorOf(lab) and not lab.isAncestorOf(o)
                    and not o.isWindow()
                    and QRect(o.mapTo(win, o.rect().topLeft()), o.size()).intersects(need)):
                g = QRect(o.mapTo(win, o.rect().topLeft()), o.size())
                bad_all.append(f"{lab.objectName()}:{o.objectName() or type(o).__name__}"
                               f"@{g.x()},{g.y()},{g.width()}x{g.height()} vs {need.x()},{need.y()},"
                               f"{need.width()}x{need.height()}")
    ok(f"Spotify logos keep their clear space ({where})", not bad_all, ", ".join(bad_all[:5]))


w2.current_pid = "SYNTHETICPL"
w2.current_name = "Synthetic"
w2.tracks = [Track(title="S", artist="A", uri="spotify:track:S1", bpm=100, key="8A")]
w2.player.set_state(True, "S", "A", 0, 1000, "", uri="spotify:track:S1")
w2.refresh()
for _ in range(3):                       # let the layout settle its minimum first
    app.processEvents()
    w2.resize(w2.minimumSizeHint().expandedTo(w2.minimumSize()))
app.processEvents()
print(f"     smallest window with two rows: {w2.width()}x{w2.height()} (minimum {w2.minimumWidth()})")
clear_space(w2, "groups on two rows, smallest window")
w2.resize(2560, 1440)
app.processEvents()
clear_space(w2, "groups on two rows, large window")

w2.reset_toolbars()
ok("Reset toolbar layout: the default order on one row, at once",
   order(w2) == default and len({r for r, _ in layout(w2).values()}) == 1, str(layout(w2)))
ok("... and that is what gets saved", Prefs().toolbar_state is not None)
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu
ra = w2.findChild(QAction, "reset_toolbars")
homes = [o.title().replace("&", "") for o in (ra.associatedObjects() if ra else []) if isinstance(o, QMenu)]
ok("it lives in the Edit menu", homes == ["Edit"], str(homes))
w2.close()

for label, state in (("damaged bytes", b"not a toolbar state at all"),
                     ("an older layout version", None), ("nothing saved", "")):
    p = Prefs()
    if label == "an older layout version":
        tmpw = window()
        state = tmpw.saveState(mw.TOOLBAR_STATE_VERSION - 1 if mw.TOOLBAR_STATE_VERSION > 0 else 99)
        tmpw.close()
    p.toolbar_state = state
    try:
        w3 = window()
        ok(f"saved layout is {label}: default layout, no error", order(w3) == default
           and all(b.isVisible() for b in w3.tool_groups), str(order(w3)))
        w3.close()
    except Exception as e:
        ok(f"saved layout is {label}: default layout, no error", False, repr(e))

# ---------------------------------------------------------------------------
print("2. the 'Refused by Spotify' section")
P = pv.SpotifyPlaylist


class FakeSpotify:
    def __init__(self):
        self.calls = []
        self.refuse = set()
        self.readable = {}
        self.played = []

    def my_playlists(self):
        self.calls.append("my_playlists")
        return [P("MINE1", "Mine One", 10, "me", True),
                P("COLLAB", "Shared With Me", 5, "friend", False, collaborative=True),
                P("OTHER", "Someone Else's", 7, "friend", False),
                P("MINE2", "Mine Two", 3, "me", True)]

    def playlist_name(self, pid):
        self.calls.append(f"name:{pid}")
        return "x"

    def playlist_tracks(self, pid, progress=None):
        self.calls.append(f"tracks:{pid}")
        if pid in self.refuse:
            raise pv.PlaylistRefused()
        return [pv.SpotifyTrack(title="T", artist="A", uri="spotify:track:T1", isrc="", duration_ms=1000)]

    def can_read_items(self, pid):
        self.calls.append(f"probe:{pid}")
        return self.readable.get(pid)

    def playlist_details(self, pid):
        return {"name": "x", "description": "", "public": False, "image": ""}

    def player_state(self):
        return None

    def play(self, *a, **k):
        self.played.append(a)


popups = []
QMessageBox.warning = staticmethod(lambda *a, **k: (popups.append(a[2] if len(a) > 2 else ""),
                                                    QMessageBox.Ok)[1])
w = window()
fake = FakeSpotify()
w.spotify = fake
w.prefs.refresh_token = "synthetic-refresh"


def names(lst):
    return [lst.item(i).text().split("  (")[0] for i in range(lst.count())]


w.refresh_spotify()
ok("someone else's, not collaborative: in the section straight away",
   names(w.refused_list) == ["Someone Else's"] and w.refused_list.isVisibleTo(w)
   and w.refused_head.text() == "REFUSED BY SPOTIFY")
ok("owned and collaborative stay in the normal list",
   names(w.sp_list) == ["Mine One", "Shared With Me", "Mine Two"])
ok("the ownership check cost nothing extra (just the list)", fake.calls == ["my_playlists"], str(fake.calls))
ok("name and track count still shown", w.refused_list.item(0).text() == "Someone Else's  (7)")

fake.calls.clear()
w.refused_list.setCurrentRow(0)
w._explain_refused(w.refused_list.item(0))
w._explain_refused(w.refused_list.item(0))
ok("clicking one: the explanation once, then the status bar; no request",
   popups == [pv.REFUSED_TEXT] and not fake.calls and w.statusBar().currentMessage() == pv.REFUSED_TEXT)

popups.clear()
fake.refuse.add("MINE2")
w._load_pid("MINE2")
ok("an owned playlist Spotify refuses moves into the section",
   "Mine Two" in names(w.refused_list) and "Mine Two" not in names(w.sp_list) and popups == [pv.REFUSED_TEXT])
w._load_pid("MINE2")
ok("its popup isn't shown a second time this session", len(popups) == 1)
for i in range(w.sp_list.count()):
    pass
fake.calls.clear()
fake.readable["MINE2"] = False
w.refresh_spotify()
ok("a fresh check: one small request for it, still refused",
   fake.calls == ["probe:MINE2", "my_playlists"] or fake.calls == ["my_playlists", "probe:MINE2"],
   str(fake.calls))
ok("... and it stays in the section", "Mine Two" in names(w.refused_list))
fake.calls.clear()
fake.readable["MINE2"] = True
fake.refuse.discard("MINE2")
w.refresh_spotify()
ok("served again: back in the normal list on the next check", "Mine Two" in names(w.sp_list)
   and "Mine Two" not in names(w.refused_list) and fake.calls.count("probe:MINE2") == 1)
fake.calls.clear()
w.refresh_spotify()
ok("once it's fine, no more probes", fake.calls == ["my_playlists"], str(fake.calls))

w.sp_list.setCurrentRow(names(w.sp_list).index("Shared With Me"))
fake.refuse.add("COLLAB")
w.load_from_spotify()
ok("a refused collaborative playlist moves in too", "Shared With Me" in names(w.refused_list))
fake.calls.clear()
fake.readable["COLLAB"] = False
w.refresh_spotify()
ok("a refused collaborative playlist costs one small request per check",
   fake.calls.count("probe:COLLAB") == 1 and len(fake.calls) == 2, str(fake.calls))

fake.calls.clear()
w.current_pid = "COLLAB"
w.sync_playlist()
ok("Sync of a refused one: no crash, still in the section, no new popup",
   "Shared With Me" in names(w.refused_list) and popups.count(pv.REFUSED_TEXT) == 2)
fake.refuse.discard("COLLAB")
w.tracks = [Track(title="T", artist="A", uri="spotify:track:T1")]
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
w.sync_playlist()
ok("a Sync that Spotify answers moves it back", "Shared With Me" in names(w.sp_list))

Prefs().refresh_token = ""             # a new window must not reach the real Spotify
w2s = window()
ok("nothing is remembered between launches", not getattr(w2s, "_refused_ids", {1}) and
   w2s.refused_list.count() == 0)
w2s.close()
w.prefs.refresh_token = "synthetic-refresh"

# ---------------------------------------------------------------------------
print("3. double-click plays the clicked track")
lines = []


class Grab(logging.Handler):
    def emit(self, rec):
        lines.append(rec.getMessage())


lg = logging.getLogger("playlistflow")
lg.addHandler(Grab())
lg.setLevel(logging.DEBUG)


def mk(n, uri):
    return Track(title=f"Synthetic {n}", artist="Sample", uri=uri, bpm=100 + n, key="8A",
                 duration_ms=200000)


w.tracks = [mk(1, "spotify:track:AAA"), mk(2, "spotify:track:BBB"), mk(3, "spotify:track:CCC"),
            mk(4, "spotify:track:AAA"), mk(5, "spotify:track:DDD")]
w.refresh()
fake.played.clear()


def dbl(row):
    it = w.table.item(row, mw.COL_BPM - 1 if mw.COL_BPM > 1 else 1)
    w.table.itemDoubleClicked.emit(w.table.item(row, 1))


for row in range(len(w.tracks)):
    fake.played.clear()
    dbl(row)
    uris, pos, dev, start = fake.played[-1]
    ok(f"row {row + 1}: starts exactly on that row's track, then the rows below it",
       start == w.tracks[row].uri and uris[0] == w.tracks[row].uri
       and uris == [t.uri for t in w.tracks[row:]] and pos == 0 and dev == "",
       f"start={start} uris={uris}")
ok("a duplicate further down plays from its own row (the list starts there)",
   fake.played[-1][0][0] == "spotify:track:DDD")
fake.played.clear()
dbl(3)
ok("clicking the second copy of a duplicate: the list starts at that row",
   fake.played[-1][0] == ["spotify:track:AAA", "spotify:track:DDD"])

# sorted, not pushed: what's shown is what's sent
w.worker = None
w.sort_tracks("bpm")
w.sort_tracks("bpm")                      # descending: 105, 104, ...
fake.played.clear()
dbl(0)
ok("after a sort: the row shown is the track played", fake.played[-1][3] == w.tracks[0].uri
   and fake.played[-1][0] == [t.uri for t in w.tracks])
# after a sync/push the list object is replaced: indexes follow it
w.tracks = list(reversed(w.tracks))
w.refresh()
fake.played.clear()
dbl(2)
ok("after the list is replaced (sync, push): still the row shown",
   fake.played[-1][3] == w.tracks[2].uri)
ok("no filtered view: table rows are the tracks one to one", w.table.rowCount() == len(w.tracks)
   and all(w.table.item(i, 1).text() == t.title for i, t in enumerate(w.tracks)))

# preview transition uses the same request shape
fake.played.clear()
w.preview_row(1, 10)
uris, pos, dev, start = fake.played[-1]
ok("preview: starts on the outgoing track near its end, the next row follows",
   start == w.tracks[1].uri and uris[:2] == [w.tracks[1].uri, w.tracks[2].uri] and pos == 190000)

# the request that goes to Spotify carries the offset
sp = pv.Spotify(type("A", (), {"access_token": lambda self: "tok"})())
sent = []


class S:
    headers = {}

    def request(self, method, url, **kw):
        sent.append(kw)
        return type("R", (), {"status_code": 204, "text": ""})()


sp._s = S()
sp.play(["spotify:track:AAA", "spotify:track:BBB"], 0, "", "spotify:track:AAA")
ok("Spotify gets offset {uri}: the clicked track, not a shuffled pick",
   sent[-1]["json"] == {"uris": ["spotify:track:AAA", "spotify:track:BBB"], "position_ms": 0,
                        "offset": {"uri": "spotify:track:AAA"}} and sent[-1]["params"] is None)
ok("nothing about shuffle is sent", "shuffle" not in json.dumps(sent[-1]))
ok("a debug line per play request", any(l.startswith("play: track request=uris+offset_uri") for l in lines),
   lines[-1] if lines else "")
ok("... with no ids, names or tokens in it",
   lines and not any(("spotify:" in l or "AAA" in l or "Synthetic" in l or "tok" in l) for l in lines),
   lines[-1] if lines else "")
print("     log line:", lines[-1] if lines else "")

w.close()
ok("no network was attempted", not nonet.BLOCKED, str(nonet.BLOCKED))
passed = sum(1 for _, r in RESULTS if r)
print(f"\n{passed} of {len(RESULTS)} passed")
shutil.rmtree(TMP, ignore_errors=True)
print("1.0.1 TESTS PASSED" if passed == len(RESULTS) else "1.0.1 TESTS FAILED")
raise SystemExit(0 if passed == len(RESULTS) else 1)
