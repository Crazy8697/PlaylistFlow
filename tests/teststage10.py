import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import nonet  # noqa: F401  (no network in tests)
"""Stage 10: FreqBlog's usage guidance (one request at a time, Retry-After, names on
every request, the first re-check, the hint, the allowance running out) and the
refresh of saved playlists from Spotify.

All synthetic: every HTTP reply is mocked, settings are a throwaway .ini, nothing is
shown on screen.

    .venv\\Scripts\\python tests\\teststage10.py
"""

import json
import os
import shutil
import tempfile
import threading
import time

TMP = pathlib.Path(tempfile.mkdtemp(prefix="pf-stage10-"))
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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])

from playlistflow import config
config.app_dir = lambda: TMP
from playlistflow import providers as pv
from playlistflow.domain import Track
from playlistflow.store import Store, QUEUED_DELAYS
import playlistflow.mainwindow as mw

RESULTS = []
SYN = "synthetic_freqblog_key_0123456789"


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


class Resp:
    def __init__(self, code, body=None, headers=None):
        self.status_code = code
        self._b = body if body is not None else {}
        self.headers = headers or {}
        self.text = json.dumps(self._b)
        self.content = self.text.encode()

    def json(self):
        return self._b


class Sess:
    """A Session stand-in: answers from a list or a function, records every call and
    how many were in flight at once."""

    def __init__(self, answer, hold=0.0):
        self.answer, self.hold = answer, hold
        self.calls, self.headers = [], {}
        self.now = self.peak = 0
        self.lock = threading.Lock()

    def request(self, method, url, **kw):
        with self.lock:
            self.now += 1
            self.peak = max(self.peak, self.now)
            self.calls.append((method, url, kw))
        time.sleep(self.hold)
        with self.lock:
            self.now -= 1
            a = self.answer
            return a(method, url, kw) if callable(a) else a.pop(0)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)


def rows_found(items):
    return {"results": [{"found": True, "result": {"bpm": 120, "camelot": "8A"}} for _ in items]}


# ---------------------------------------------------------------------------
print("1. FreqBlog: one request at a time")
fbs = [pv.FreqBlog(SYN) for _ in range(3)]
shared = Sess(lambda m, u, kw: Resp(200, rows_found(kw["json"])), hold=0.05)
for f in fbs:
    f._s = shared
threads = [threading.Thread(target=f.bulk, args=([{"track": "Synthetic", "artist": "A"}],)) for f in fbs]
[t.start() for t in threads]
[t.join() for t in threads]
ok("three threads asking at once: never more than 1 in flight", shared.peak == 1 and len(shared.calls) == 3,
   f"peak={shared.peak}")
import inspect
src = "".join(inspect.getsource(m) for m in (pv, mw))
ok("no thread pools or parallel FreqBlog callers in the program",
   "ThreadPool" not in src and "concurrent.futures" not in src and "asyncio" not in src)

# ---------------------------------------------------------------------------
print("2. every 429 waits the full Retry-After before retrying")
fb = pv.FreqBlog(SYN)
slept = []
fb._sleep = slept.append
fb._s = Sess([Resp(429, {"detail": "Too many concurrent requests"}, {"Retry-After": "5"}),
              Resp(429, {}, {"Retry-After": "7"}),
              Resp(429, {}, {}),
              Resp(200, rows_found([1]))])
fb.bulk([{"track": "Synthetic", "artist": "A"}])
ok("waits 5, 7, then the 5 s default when the header is missing, never less",
   slept == [5.0, 7.0, 5.0], str(slept))
fb._s = Sess([Resp(429, {"detail": "Too many concurrent"}, {"Retry-After": "300"})])
slept.clear()
try:
    fb.bulk([{"track": "x"}])
    ok("a Retry-After too long for a fetch: gives up, no early retry", False)
except pv.ProviderError:
    ok("a Retry-After too long for a fetch: gives up, no early retry", slept == [] and len(fb._s.calls) == 1)
from email.utils import format_datetime
import datetime as dt
r = Resp(429, {}, {"Retry-After": format_datetime(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=30))})
ok("an HTTP-date Retry-After is honoured too", 25 <= pv.retry_after_seconds(r) <= 31)
fb._s = Sess([Resp(429, {}, {"Retry-After": "3"}), Resp(200, {"bpm": 100, "camelot": "8A"})])
slept.clear()
f = fb.lookup("Synthetic", "A")
ok("/lookup honours it the same way", slept == [3.0] and f.bpm == 100, str(slept))

# ---------------------------------------------------------------------------
print("3. the track name goes with every request (no ISRC-only)")
fb._s = Sess([Resp(200, {"bpm": 100, "camelot": "8A"})])
fb.lookup("Synthetic Song", "Synthetic Artist", isrc="ZZ0000000001")
params = fb._s.calls[0][2]["params"]
ok("/lookup with an ISRC still sends track and artist",
   params.get("track") == "Synthetic Song" and params.get("artist") == "Synthetic Artist"
   and params.get("isrc") == "ZZ0000000001", str(params))
ok("the ISRC-only lookup is gone", not hasattr(pv.FreqBlog, "lookup_isrc"))


class RecFB:
    api_key = SYN
    last_hint = ""

    def __init__(self, answer):
        self.answer, self.sent = answer, []

    def bulk(self, items):
        items = list(items)
        self.sent.append(items)
        return self.answer(items)

    def stats(self):
        raise AssertionError("not expected")


def mixed(items):
    out = []
    for it in items:
        import re
        n = int(re.search(r"\d+", it["track"]).group())
        out.append({"found": True, "result": {"bpm": 100, "camelot": "8A"}} if n % 3 == 0 else
                   {"found": False, "backfill_status": "processing"} if n % 3 == 1 else {"found": False})
    return out


class NoGS:
    api_key = ""


tracks = [Track(title=f"Synthetic {i} (Remastered)", artist="Synthetic Artist feat. Someone",
                isrc=f"ZZ{i:010d}", uri=f"spotify:track:S{i:04d}") for i in range(60)]
rf = RecFB(mixed)
wk = mw.FetchWorker(rf, NoGS(), tracks)
waits = []
wk.waiting.connect(lambda t, k, d: waits.append(k))
wk.run()
items = [i for call in rf.sent for i in call]
ok("first sends and retries all carry the name and artist",
   items and all(i.get("track") and i.get("artist") for i in items), f"{len(items)} items")
ok("'processing' counts as being analysed, not missing", waits.count("queued") == 20, str(waits.count("queued")))
# a re-check goes through the same first pass: build a re-check of the queued ones
st = Store(TMP / "store3")
q = Track(title="Queued Song", artist="Queued Artist", isrc="ZZ0000009999", uri="spotify:track:Q1")
st.mark_waiting(q, "queued", now=0)
rf2 = RecFB(lambda it: [{"found": True, "result": {"bpm": 90, "camelot": "1A"}}])
mw.FetchWorker(rf2, NoGS(), [q]).run()
ok("a re-check of a queued track sends it by name (collected free)",
   rf2.sent[0][0].get("track") == "Queued Song" and rf2.sent[0][0].get("artist") == "Queued Artist")

# ---------------------------------------------------------------------------
print("4. the first re-check")
ok("first re-check of a queued track after 45 s (30 to 60 asked for)", QUEUED_DELAYS[0] == 45)
s4 = Store(TMP / "store4")
t4 = Track(title="Q", artist="A", uri="spotify:track:Q4")
ok("mark_waiting: first wait 45 s, the next keep the old schedule",
   s4.mark_waiting(t4, "queued", now=1000) == 1045 and s4.mark_waiting(t4, "queued", now=1000) == 1600)
ok("retry_after_days still wins", s4.mark_waiting(t4, "queued", retry_after_days=1, now=0) == 86400)

# ---------------------------------------------------------------------------
print("5. FreqBlog's hint, as-is, only while fetching")
HINT = "12 of 20 tracks are still being analysed. Send them again in about a minute to collect them."
fb = pv.FreqBlog(SYN)
fb._s = Sess([Resp(200, {"results": [{"found": False, "backfill_status": "queued"}], "hint": HINT})])
fb.bulk([{"track": "x", "artist": "y"}])
ok("bulk keeps the hint text exactly", fb.last_hint == HINT)
fb._s = Sess([Resp(200, {"results": []})])
fb.bulk([{"track": "x"}])
ok("a reply without one clears it", fb.last_hint == "")

mw.setup_needed = lambda env, state: ""
w = mw.MainWindow()
w.setAttribute(Qt.WA_DontShowOnScreen, True)
w.show()
end = time.time() + 10
while w.store is None and time.time() < end:
    app.processEvents()
    time.sleep(0.02)
hints = []


class HintFB(RecFB):
    def bulk(self, items):
        self.last_hint = HINT
        return [{"found": False, "backfill_status": "queued"} for _ in items]


wk = mw.FetchWorker(HintFB(None), NoGS(), [Track(title="H 1", artist="A", uri="spotify:track:H1")])
wk.hint.connect(hints.append)
wk.run()
ok("the worker passes the hint on", hints == [HINT])
w._show_hint(HINT)
ok("shown as-is in the status area", w.fb_hint.text() == HINT and w.fb_hint.isVisible())
w._fetch_done()
ok("gone when the fetch finishes", w.fb_hint.text() == "" and not w.fb_hint.isVisible())

# ---------------------------------------------------------------------------
print("6. the allowance runs out")
boxes = []
QMessageBox.exec = lambda self: (boxes.append(self.objectName() or self.windowTitle()), 0)[1]
stats_calls = []
STATS = {"requests_this_month": 1000, "monthly_quota": 1000, "quota_used_pct": 100.0,
         "quota_reset_date": "2026-11-01"}


def bulk_then_out(method, url, kw):
    if url.endswith("/me/stats"):
        stats_calls.append(1)
        return Resp(200, STATS)
    n = sum(1 for c in fb6._s.calls if c[1].endswith("/bulk"))
    if n == 1:
        return Resp(200, rows_found(kw["json"]))
    return Resp(429, {"detail": "Monthly quota exceeded for this key."}, {"Retry-After": "1209600"})


fb6 = pv.FreqBlog(SYN)
fb6._sleep = lambda s: (_ for _ in ()).throw(AssertionError("no sleeping on the allowance"))
fb6._s = Sess(bulk_then_out)
tracks6 = [Track(title=f"Out {i}", artist="A", uri=f"spotify:track:O{i:03d}") for i in range(130)]
wk = mw.FetchWorker(fb6, NoGS(), tracks6)
got_usage, waits6 = [], []
wk.allowanceUsed.connect(got_usage.append)
wk.waiting.connect(lambda t, k, d: waits6.append(k))
wk.run()
bulks = [c for c in fb6._s.calls if c[1].endswith("/bulk")]
ok("after the allowance 429, nothing more goes to FreqBlog in that fetch", len(bulks) == 2, str(len(bulks)))
ok("/me/stats asked exactly once, for the reset date", len(stats_calls) == 1 and got_usage
   and got_usage[0].reset == "2026-11-01")
ok("tracks FreqBlog never answered aren't marked missing", waits6 == [], str(waits6[:3]))

# body silent, long Retry-After: /me/stats decides
fb7 = pv.FreqBlog(SYN)
stats_calls.clear()


def silent(method, url, kw):
    if url.endswith("/me/stats"):
        stats_calls.append(1)
        return Resp(200, STATS)
    return Resp(429, {}, {"Retry-After": "86400"})


fb7._s = Sess(silent)
try:
    fb7.bulk([{"track": "x", "artist": "y"}])
    ok("a silent long 429: /me/stats says the month is used", False)
except pv.AllowanceUsed as e:
    ok("a silent long 429: /me/stats says the month is used", len(stats_calls) == 1 and e.usage is not None)
fb7._s = Sess([Resp(429, {"detail": "Too many concurrent batch requests"}, {"Retry-After": "5"}),
               Resp(200, rows_found([1]))])
fb7._sleep = lambda s: None
stats_calls.clear()
fb7.bulk([{"track": "x", "artist": "y"}])
ok("the concurrency 429 is not taken for the allowance (no stats call)", not stats_calls)

w._warned.clear()
before = len(boxes)
w._allowance_used(got_usage[0])
w._allowance_used(got_usage[0])
ok("one message per session", len(boxes) - before == 1 and boxes[-1] == "allowance_used", str(boxes))
ok("it names the reset date", "resets on November 1, 2026" in w.statusBar().currentMessage(),
   w.statusBar().currentMessage())

# ---------------------------------------------------------------------------
print("7. saved playlists refresh from Spotify when opened signed in")
st7 = Store(TMP / "store")
w.store = st7
saved = [Track(title="Old Title A", artist="Old Artist", uri="spotify:track:A1", bpm=128, key="8A",
               manual=True, source="manual"),
         Track(title="Old Title B", artist="Old Artist", uri="spotify:track:B2", bpm=100, key="1A"),
         Track(title="Gone From Spotify", artist="Someone", uri="spotify:track:GONE", bpm=90, key="2B"),
         Track(title="Typed By Hand", artist="Me", uri="", bpm=70, key="3A")]
st7.save("Synthetic Set", saved, auto=False, ear_checked=["seamX"])
time.sleep(0.05)
saved[1].bpm = 101                                  # the auto-save is newer, with an edit
st7.save("Synthetic Set", saved, auto=True, ear_checked=["seamX"])
m_before = [p.stat().st_mtime_ns for p in st7._paths("Synthetic Set")]
NEW = {"spotify:track:A1": ("New Title A", "New Artist"), "spotify:track:B2": ("New Title B", "New Artist")}
asked = []


def track_meta(uris):
    asked.append(list(uris))
    time.sleep(0.3)
    return {u: NEW[u] for u in uris if u in NEW}


w.spotify.track_meta = track_meta
w.prefs.refresh_token = "synthetic-refresh"       # signed in
w.refresh_saved()
for i in range(w.saved_list.count()):
    if w.saved_list.item(i).data(Qt.UserRole) == "Synthetic Set":
        w.saved_list.setCurrentRow(i)
w.load_saved()
ok("opens at once, as stored (not blocked on the refresh)",
   [t.title for t in w.tracks][:2] == ["Old Title A", "Old Title B"] and w.refresher is not None)
ok("the refresh holds the fetch lock while it runs", w.fetching())
order = [t.title for t in w.tracks]
w.sort_tracks("bpm")
ok("sorting waits meanwhile", [t.title for t in w.tracks] == order)
end = time.time() + 5
while w.refresher.isRunning() and time.time() < end:
    app.processEvents()
    time.sleep(0.02)
for _ in range(20):
    app.processEvents()
ok("asked Spotify for the Spotify tracks only", asked and sorted(asked[0]) == sorted(
    ["spotify:track:A1", "spotify:track:B2", "spotify:track:GONE"]))
ok("titles and artists updated on screen", [(t.title, t.artist) for t in w.tracks][:2] ==
   [("New Title A", "New Artist"), ("New Title B", "New Artist")])
ok("nothing else changed: order, BPM/key, manual flag, the hand-typed and the gone track",
   [t.uri for t in w.tracks] == ["spotify:track:A1", "spotify:track:B2", "spotify:track:GONE", ""]
   and [t.bpm for t in w.tracks] == [128, 101, 90, 70] and w.tracks[0].manual
   and w.tracks[2].title == "Gone From Spotify" and w.tracks[3].title == "Typed By Hand")
man = json.loads(st7._paths("Synthetic Set")[0].read_text(encoding="utf-8"))
aut = json.loads(st7._paths("Synthetic Set")[1].read_text(encoding="utf-8"))
ok("both saves refreshed and kept everything else",
   man["tracks"][0]["title"] == "New Title A" and aut["tracks"][1]["title"] == "New Title B"
   and man["tracks"][1]["bpm"] == 100 and aut["tracks"][1]["bpm"] == 101
   and man["ear_checked"] == ["seamX"] and len(man["tracks"]) == 4 and len(aut["tracks"]) == 4)
ok("the track Spotify no longer has is unchanged in the files",
   man["tracks"][2]["title"] == "Gone From Spotify" and aut["tracks"][2]["artist"] == "Someone")
m_after = [p.stat().st_mtime_ns for p in st7._paths("Synthetic Set")]
ok("file times kept, so the auto-save still opens first", m_after == m_before and st7.has_newer_auto("Synthetic Set"))
ok("said in the status bar, including the kept track", "kept as stored" in w.statusBar().currentMessage(),
   w.statusBar().currentMessage())

# offline: nothing changes
st7.save("Offline Set", [Track(title="Stays", artist="Same", uri="spotify:track:Z9")], auto=False)
w.spotify.track_meta = lambda uris: {}
w.refresh_saved()
for i in range(w.saved_list.count()):
    if w.saved_list.item(i).data(Qt.UserRole) == "Offline Set":
        w.saved_list.setCurrentRow(i)
w.load_saved()
end = time.time() + 5
while w.refresher.isRunning() and time.time() < end:
    app.processEvents()
for _ in range(10):
    app.processEvents()
ok("offline: opens as stored, files untouched",
   w.tracks[0].title == "Stays" and json.loads(st7._paths("Offline Set")[0].read_text(
       encoding="utf-8"))["tracks"][0]["title"] == "Stays")
# not signed in: no refresh at all
w.prefs.refresh_token = ""
asked.clear()
w.spotify.track_meta = track_meta
w.load_saved()
ok("not signed in: no refresh is started", not asked and not w.fetching())

# track_meta maps by position (a relinked track comes back under another id)
sp = pv.Spotify(type("A", (), {"access_token": lambda self: "tok"})())
sp._s = Sess([Resp(200, {"tracks": [{"uri": "spotify:track:RELINKED", "name": "Fresh", "artists": [{"name": "X"}]},
                                     None]})])
meta = sp.track_meta(["spotify:track:ORIG", "spotify:track:DEAD"])
ok("track_meta: relinked tracks map to the asked id; null ones are left out",
   meta == {"spotify:track:ORIG": ("Fresh", "X")}, str(meta))

w.close()
ok("no network was attempted", not nonet.BLOCKED, str(nonet.BLOCKED))
passed = sum(1 for _, r in RESULTS if r)
print(f"\n{passed} of {len(RESULTS)} passed")
shutil.rmtree(TMP, ignore_errors=True)
print("STAGE 10 TESTS PASSED" if passed == len(RESULTS) else "STAGE 10 TESTS FAILED")
raise SystemExit(0 if passed == len(RESULTS) else 1)
