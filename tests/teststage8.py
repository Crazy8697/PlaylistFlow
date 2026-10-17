import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import nonet  # noqa: F401  (no network in tests)
"""Stage 8: the review fixes, the FreqBlog allowance, the key check and usage line,
paste cleanup, the automatic sign-in listener and the wizard's last page.

All synthetic: every HTTP reply is mocked, settings are a throwaway .ini, the only
socket opened is the sign-in listener on 127.0.0.1, and no window is shown.

    .venv\\Scripts\\python tests\\teststage8.py
"""

import json
import os
import shutil
import socket
import tempfile
import time
import urllib.error
import urllib.request

TMP = pathlib.Path(tempfile.mkdtemp(prefix="pf-stage8-"))
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

from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])

from playlistflow import config
config.app_dir = lambda: TMP                  # never the repo-root .env
from playlistflow import auth as authmod
from playlistflow import domain
from playlistflow import freqcheck
from playlistflow import providers as pv
from playlistflow import settings as setmod
from playlistflow import wizard as wz
from playlistflow.auth import AuthError, SpotifyAuth
from playlistflow.callback import CallbackListener
from playlistflow.config import Prefs, save_env
from playlistflow.domain import Track
from playlistflow.store import Store, StoreError, QUEUED_DELAYS, MISSING_DAYS
import playlistflow.mainwindow as mw

GOOD_ID = "0123456789abcdef0123456789abcdef"          # synthetic
GOOD_FB = "synthetic_freqblog_key_0123456789"          # synthetic
GOOD_GS = "abcdef0123456789abcdef0123456789"          # synthetic
RESULTS = []

# a popup anywhere in this run is a failure of "never a popup"
POPUPS = []
for name in ("warning", "information", "critical", "question"):
    setattr(QMessageBox, name, staticmethod(lambda *a, _n=name, **k: (POPUPS.append(_n),
                                                                     QMessageBox.No)[1]))
QMessageBox.exec = lambda self: (POPUPS.append("exec"), 0)[1]


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


class Resp:
    def __init__(self, code, body=None, raw=None):
        self.status_code = code
        self._b = body
        self._raw = raw
        self.headers = {}
        self.text = raw if raw is not None else json.dumps(body)
        self.content = self.text.encode()

    def json(self):
        if self._raw is not None:
            return json.loads(self._raw)          # raises ValueError like requests
        return self._b


class Rec:
    """A requests.Session stand-in: records each call, answers from a list or a function."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []
        self.headers = {}

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        a = self.answer
        if callable(a):
            return a(method, url, kw)
        return a.pop(0)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)


def pump(cond, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    app.processEvents()
    return cond()


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def window_stub():
    """A MainWindow without its UI: enough for the list operations."""
    w = mw.MainWindow.__new__(mw.MainWindow)
    w._sort_field, w._sort_desc = "", False
    w.felt = False
    w.undo_stack = []
    w._dirty = False
    w.worker = None
    w.store = None
    msgs = []
    w.status = msgs.append
    w.refresh = lambda *a, **k: None
    w.table = type("T", (), {"clearSelection": lambda self: None, "selectRow": lambda self, r: None})()
    return w, msgs


# ---------------------------------------------------------------------------
print("1. felt-BPM edits use domain.FELT_FOLD and store the reported value")
domain.set_display(felt_fold=165)
w, msgs = window_stub()
w.store = Store(TMP / "felt")
w.felt = True


def edit(reported, typed, felt=True):
    t = Track(title="x", artist="a", uri=f"spotify:track:F{reported}{typed}", bpm=reported, key="8A")
    w.tracks = [t]
    w.felt = felt
    w.edit_cell(0, "bpm", str(typed))
    return t


t = edit(170, 85)
ok("retyping the shown felt value changes nothing", t.bpm == 170 and not t.manual, f"bpm={t.bpm}")
t = edit(170, 86)
ok("a folded row typed 86 stores 172 (shown 86)", t.bpm == 172 and domain.felt_bpm(t.bpm) == 86, f"bpm={t.bpm}")
t = edit(170, 70)
ok("a folded row typed 70 stores 70 (140 would show 140, not 70)", t.bpm == 70, f"bpm={t.bpm}")
t = edit(120, 125)
ok("an unfolded row stores what was typed", t.bpm == 125, f"bpm={t.bpm}")
t = edit(120, 90)
ok("an unfolded row typed 90 is not doubled", t.bpm == 90, f"bpm={t.bpm}")
t = edit(170, 175)
ok("a value at or above the fold is taken as reported", t.bpm == 175, f"bpm={t.bpm}")
t = edit(170, 88, felt=False)
ok("reported view stores what was typed", t.bpm == 88, f"bpm={t.bpm}")
domain.set_display(felt_fold=140)
t = edit(150, 76)
ok("a changed fold (140) is followed, not a hardcoded 130", t.bpm == 152, f"bpm={t.bpm}")
t = edit(135, 135)
ok("135 is under a 140 fold: shown and kept as 135", t.bpm == 135 and not t.manual, f"bpm={t.bpm}")
domain.set_display(felt_fold=165)
import inspect
src = inspect.getsource(mw) + inspect.getsource(sys.modules["playlistflow.table"])
ok("no hardcoded 130 fold left in the window or table", ">= 130" not in src)

# ---------------------------------------------------------------------------
print("2. Spotify: track_names chunks every id, null tracks are skipped, bad JSON is said")


class FakeAuth:
    def access_token(self):
        return "synthetic-token"


sp = pv.Spotify(FakeAuth())


def tracks_answer(method, url, kw):
    ids = kw["params"]["ids"].split(",")
    return Resp(200, {"tracks": [{"uri": f"spotify:track:{i}", "name": f"Song {i}",
                                  "artists": [{"name": "Artist"}, None]} for i in ids] + [None]})


sp._s = Rec(tracks_answer)
uris = [f"spotify:track:ID{i:03d}" for i in range(120)]
names = sp.track_names(uris)
sizes = [len(c[2]["params"]["ids"].split(",")) for c in sp._s.calls]
ok("120 ids go out in chunks of 50, 50, 20", sizes == [50, 50, 20], str(sizes))
ok("all 120 are named, a null artist skipped", len(names) == 120
   and names[uris[-1]] == "Artist - Song ID119", names.get(uris[-1], ""))

sp._s = Rec([Resp(200, {"next": None, "items": [
    None,
    {"item": None},
    {"track": None},
    {"item": {"uri": "spotify:local:x", "name": "local"}},
    {"item": {"uri": "spotify:track:OK1", "name": "Fine", "artists": [None, {"name": "B"}],
              "external_ids": None, "duration_ms": None}},
    "garbage",
]})])
try:
    got = sp.playlist_tracks("PL")
    ok("null and broken playlist entries are skipped, the rest load",
       [t.uri for t in got] == ["spotify:track:OK1"] and got[0].duration_ms == 0, str(got))
except Exception as e:
    ok("null and broken playlist entries are skipped, the rest load", False, repr(e))

sp._s = Rec([Resp(200, raw="<html>not json</html>")])
try:
    sp.playlist_name("PL")
    ok("a non-JSON Spotify reply raises a plain ProviderError", False)
except pv.ProviderError as e:
    ok("a non-JSON Spotify reply raises a plain ProviderError", "could not read" in str(e), str(e))


class Boom(Rec):
    def request(self, *a, **k):
        import requests
        raise requests.ConnectionError("synthetic offline")


sp._s = pv._SpotifySession()
import requests as _rq
_real_req = _rq.Session.request
_rq.Session.request = lambda self, *a, **k: (_ for _ in ()).throw(_rq.ConnectionError("offline"))
try:
    sp.my_playlists()
    ok("offline Spotify calls raise ProviderError, not a requests exception", False)
except pv.ProviderError as e:
    ok("offline Spotify calls raise ProviderError, not a requests exception", "Couldn't reach" in str(e))
finally:
    _rq.Session.request = _real_req

fb = pv.FreqBlog(GOOD_FB)
fb._s = Rec([Resp(200, raw="oops")])
try:
    fb.bulk([{"track": "a"}])
    ok("a non-JSON FreqBlog reply raises ProviderError", False)
except pv.ProviderError:
    ok("a non-JSON FreqBlog reply raises ProviderError", True)

# ---------------------------------------------------------------------------
print("3. Store: bad files and folders are said, not crashed on")
st = Store(TMP / "store3")
(st.root / "Broken.json").write_text("{ not json", encoding="utf-8")
try:
    st.load("Broken")
    ok("a damaged playlist file raises StoreError", False)
except StoreError as e:
    ok("a damaged playlist file raises StoreError", "damaged" in str(e), str(e))
(st.root / "Shape.json").write_text(json.dumps({"tracks": "nope"}), encoding="utf-8")
try:
    st.load("Shape")
    ok("a wrong-shaped file raises StoreError", False)
except StoreError:
    ok("a wrong-shaped file raises StoreError", True)
(st.root / "cache.json").write_text("[1, 2", encoding="utf-8")
st2 = Store(st.root)
ok("a damaged cache.json is treated as empty", st2.cache_get(Track(title="a", uri="spotify:track:Z")) is None)
blocker = TMP / "a-file"
blocker.write_text("x", encoding="utf-8")
try:
    Store(blocker / "sub")
    ok("an unusable folder raises StoreError", False)
except StoreError as e:
    ok("an unusable folder raises StoreError", "Pick another" in str(e), str(e))
ro = Store(TMP / "store-ro")
(ro.root / "Locked.tmp").mkdir()          # the temp file name is taken by a folder: write fails
try:
    ro.save("Locked", [Track(title="a")])
    ok("a failed save raises StoreError", False)
except StoreError as e:
    ok("a failed save raises StoreError", "Couldn't save" in str(e), str(e))

# ---------------------------------------------------------------------------
print("4. no sort, drag, delete, undo or sync while a fetch runs")


class Running:
    def isRunning(self):
        return True


w, msgs = window_stub()
w.tracks = [Track(title=n, artist="a", bpm=b, key="8A") for n, b in (("c", 120), ("a", 100), ("b", 110))]
w.undo_stack = [[Track(title="old")]]
w.current_pid = "PL"
before = [t.title for t in w.tracks]
w.worker = Running()
w.sort_tracks("bpm")
w.move_row(0, 2)
w.delete_rows([0])
w.undo()
w.sync_playlist()
ok("the list is untouched", [t.title for t in w.tracks] == before and len(w.undo_stack) == 1,
   str([t.title for t in w.tracks]))
ok("each refusal is said in the status bar", sum("Wait for the BPM/key lookup" in m for m in msgs) == 5, str(msgs))
w.worker = None
w.sort_tracks("bpm")
ok("after the fetch, sorting works again", [t.title for t in w.tracks] == ["a", "b", "c"])

# results land on the track, not the row
w, msgs = window_stub()
w.store = Store(TMP / "store4")
w.stat = type("L", (), {"setText": lambda self, t: None})()
w.show_playlist_info = lambda: None
w._live = type("Q", (), {"start": lambda self: None})()
w.approved = set()
a1, b1 = Track(title="A", uri="spotify:track:A1"), Track(title="B", uri="spotify:track:B1")
w.tracks = [b1, a1]                       # reordered after the jobs were made
w._apply_feature(a1, pv.Features(bpm=101, camelot="8A", source="freqblog"))
ok("a result goes to its own track, wherever it is now", a1.bpm == 101 and b1.bpm == 0)
gone = Track(title="Gone", uri="spotify:track:G1")
w._apply_feature(gone, pv.Features(bpm=99, camelot="1A", source="freqblog"))
ok("a track no longer listed is still cached (no wasted request)",
   w.store.cache_get(gone) is not None and gone not in w.tracks)

# ---------------------------------------------------------------------------
print("5. OAuth state is sent and verified")
posts = []
_real_post = authmod.requests.post


def fake_post(url, data=None, timeout=None):
    posts.append(data)
    return Resp(200, {"access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
                      "expires_in": 3600})


authmod.requests.post = fake_post
pr = Prefs()
au = SpotifyAuth(GOOD_ID, pr, port=8888)
url = au.begin()
import urllib.parse as up
sent_state = up.parse_qs(up.urlparse(url).query)["state"][0]
ok("begin() sends a random state", len(sent_state) >= 16 and sent_state == au._state)
for label, addr in (("a different state", f"http://127.0.0.1:8888/callback?code=c&state=WRONG"),
                    ("no state", "http://127.0.0.1:8888/callback?code=c"),
                    ("a bare code", "AQBsyntheticcode")):
    posts.clear()
    try:
        au.complete(addr)
        ok(f"{label} is refused", False)
    except AuthError as e:
        ok(f"{label} is refused before any token request", not posts, str(e))
posts.clear()
au.complete(f"http://127.0.0.1:8888/callback?code=c0de&state={sent_state}")
ok("the matching state signs in", posts and posts[0]["code"] == "c0de" and au.refresh_token == "synthetic-refresh")
try:
    au.complete(f"http://127.0.0.1:8888/callback?code=c0de&state={sent_state}")
    ok("the same address can't be used twice", False)
except AuthError:
    ok("the same address can't be used twice", True)


def offline_post(*a, **k):
    raise authmod.requests.ConnectionError("synthetic")


authmod.requests.post = offline_post
au.begin()
try:
    au.complete(f"http://127.0.0.1:8888/callback?code=c&state={au._state}")
    ok("sign-in offline: a plain AuthError", False)
except AuthError as e:
    ok("sign-in offline: a plain AuthError", "Couldn't reach Spotify" in str(e), str(e))
au._access, au._expires = "", 0
try:
    au.access_token()
    ok("token refresh offline: ProviderError, sign-in kept", False)
except pv.ProviderError:
    ok("token refresh offline: ProviderError, sign-in kept", au.refresh_token == "synthetic-refresh")
authmod.requests.post = _real_post

# ---------------------------------------------------------------------------
print("6. FreqBlog: /bulk 50 a call, no re-poll, cached and waiting tracks skipped")


class CountFB:
    """100 synthetic tracks: 80 found, 15 queued (202), 5 unknown."""
    api_key = GOOD_FB

    def __init__(self):
        self.bulk_calls, self.items, self.isrc_calls = 0, [], 0

    def bulk(self, items):
        items = list(items)
        assert len(items) <= 50
        self.bulk_calls += 1
        self.items += [i["track"] for i in items]
        rows = []
        for it in items:
            n = int(it["track"].split()[-1])
            if n < 80:
                rows.append({"found": True, "result": {"bpm": 100 + n % 30, "camelot": "8A"}})
            elif n < 95:
                rows.append({"found": False, "backfill_status": "queued",
                             **({"retry_after_days": 2} if n == 94 else {})})
            else:
                rows.append({"found": False})
        return rows

    def lookup_isrc(self, isrc, wait=0):
        self.isrc_calls += 1
        return pv.Features(terminal=True)


class NoGS:
    api_key = ""


tracks = [Track(title=f"Synthetic Track {i}", artist="Synthetic Artist", isrc=f"ZZ000{i:05d}",
                uri=f"spotify:track:SYN{i:03d}") for i in range(100)]
fbc = CountFB()
wk = mw.FetchWorker(fbc, NoGS(), tracks)
res, waits = [], []
wk.resolved.connect(lambda t, f: res.append(t))
wk.waiting.connect(lambda t, k, d: waits.append((t, k, d)))
t0 = time.time()
wk.run()
took = time.time() - t0
queued_asked = [x for x in fbc.items if 80 <= int(x.split()[-1]) < 95]
ok("100 tracks: 2 /bulk calls in the first pass", fbc.items[:100] and fbc.bulk_calls >= 2)
ok("queued tracks are asked about once, never re-polled", len(queued_asked) == 15, str(len(queued_asked)))
ok("no waiting inside the fetch", took < 2.0, f"{took:.2f}s")
ok("80 resolved", len(res) == 80)
ok("15 queued and 5 missing are reported for later",
   sum(k == "queued" for _, k, _ in waits) == 15 and sum(k == "missing" for _, k, _ in waits) == 5)
ok("retry_after_days from FreqBlog is passed on",
   [d for t, k, d in waits if t.title.endswith(" 94")] == [2.0])
ok("worker's own count of track lookups", wk.requests == len(fbc.items) + fbc.isrc_calls,
   f"requests={wk.requests} items={len(fbc.items)} isrc={fbc.isrc_calls}")
print(f"     lookups for a fresh 100-track playlist: {wk.requests} in {wk.calls} calls")

# fetch_features: cached and waiting tracks never reach the worker
made = []


class SpyWorker:
    def __init__(self, fb, gs, jobs, parent=None):
        made.append(list(jobs))
        self.resolved = self.waiting = self.message = self.done = self.keyRejected = \
            self.hint = self.allowanceUsed = type("S", (), {"connect": lambda self, f: None})()

    def start(self):
        pass

    def isRunning(self):
        return False


real_worker = mw.FetchWorker
mw.FetchWorker = SpyWorker
w, msgs = window_stub()
w.store = Store(TMP / "store6")
w.freqblog = w.getsongbpm = None
w.busy_on = lambda *a: None
known = Track(title="Known", uri="spotify:track:K", bpm=120, key="8A", source="freqblog")
w.store.cache_put(known)
cached = Track(title="Known", uri="spotify:track:K")
w.store.apply_cache(cached)
fresh = Track(title="Fresh", uri="spotify:track:N")
waiting = Track(title="Waiting", uri="spotify:track:W")
missing = Track(title="Missing", uri="spotify:track:M")
manual = Track(title="Typed", uri="spotify:track:T", bpm=0, manual=True)
w.store.mark_waiting(waiting, "queued")
w.store.mark_waiting(missing, "missing")
w.tracks = [cached, fresh, waiting, missing, manual]
w.fetch_features()
ok("only the uncached, not-waiting track is sent", made and [t.title for t in made[-1]] == ["Fresh"],
   str([t.title for t in made[-1]]) if made else "no worker")
made.clear()
w.tracks = [cached, waiting, missing]
w.fetch_features()
ok("nothing due: no request at all, and it says why", not made and "waiting on FreqBlog" in msgs[-1], msgs[-1])
w.fetch_features(force=True)
ok("force ignores the waits but never the cache", made and [t.title for t in made[-1]] == ["Waiting", "Missing"])
mw.FetchWorker = real_worker

# the schedule
s6 = Store(TMP / "store6b")
q = Track(title="Q", uri="spotify:track:Q")
now = 1_000_000.0
n1 = s6.mark_waiting(q, "queued", now=now)
n2 = s6.mark_waiting(q, "queued", now=now)
n3 = s6.mark_waiting(q, "queued", retry_after_days=2, now=now)
ok("queued: re-checked after growing waits",
   n1 - now == QUEUED_DELAYS[0] and n2 - now == QUEUED_DELAYS[1], f"{n1 - now}, {n2 - now}")
ok("retry_after_days wins when FreqBlog sends it", n3 - now == 2 * 86400)
ok("not due inside the wait, due after", not s6.lookup_due(q, now=now + 10) and s6.lookup_due(q, now=n3 + 1))
m = Track(title="M", uri="spotify:track:M")
ok("missing: asked again after a week", s6.mark_waiting(m, "missing", now=now) - now == MISSING_DAYS * 86400)
q.bpm, q.key, q.source = 120, "8A", "freqblog"
s6.cache_put(q)
ok("resolving a track clears its wait", s6.waiting(q) is None)
ok("the wait survives a restart (kept in cache.json)", Store(s6.root).waiting(m) is not None)
ok("the wait record never lists as a playlist", "_lookup_wait" not in " ".join(s6.list_playlists()))

# the one automatic re-check
w, msgs = window_stub()
w.store = Store(TMP / "store6c")
from PySide6.QtCore import QTimer
w._recheck = QTimer()
w._recheck.setSingleShot(True)
qd = Track(title="Queued", uri="spotify:track:QD")
w.tracks = [qd]
w.store.mark_waiting(qd, "queued")
w._schedule_recheck()
ok("a queued track gets one timed re-check", w._recheck.isActive()
   and abs(w._recheck.remainingTime() / 1000 - QUEUED_DELAYS[0]) < 5, str(w._recheck.remainingTime()))
w.store.mark_waiting(qd, "queued", retry_after_days=3)
w._schedule_recheck()
ok("a far-off re-check waits for the next fetch instead", not w._recheck.isActive())

# ---------------------------------------------------------------------------
print("7. /me/stats: 200 is a good key with usage, 401 shows FreqBlog's own words")
fb = pv.FreqBlog(GOOD_FB)
fb._s = Rec([Resp(200, {"requests_this_month": 412, "monthly_quota": 2500, "quota_used_pct": 16.48,
                        "quota_reset_date": "2026-11-01"})])
res = freqcheck.check_key(GOOD_FB, client=fb)
m, url, kw = fb._s.calls[0]
ok("one GET to /me/stats with the X-API-Key header",
   m == "GET" and url.endswith("/me/stats") and kw["headers"].get("X-API-Key") == GOOD_FB)
ok("200: key good, usage read from the reply", res.status == "ok" and res.usage.quota == 2500
   and res.usage.used == 412)
detail = "This key has been deactivated. Request a new one at freqblog.com."
fb._s = Rec([Resp(401, {"detail": detail})])
res = freqcheck.check_key(GOOD_FB, client=fb)
ok("401: rejected, with FreqBlog's detail as-is", res.status == "rejected" and res.message == detail, res.message)
fb._s = Rec(lambda *a: (_ for _ in ()).throw(_rq.ConnectionError("synthetic")))
res = freqcheck.check_key(GOOD_FB, client=fb)
ok("network error: offline, said plainly", res.status == "offline" and "Couldn't check" in res.message)
fb._s = Rec([Resp(500, {})])
ok("a server error is offline, not rejected", freqcheck.check_key(GOOD_FB, client=fb).status == "offline")

# ---------------------------------------------------------------------------
print("8. the usage line")
U = pv.Usage
txt, warn = freqcheck.usage_text(U(used=412, quota=2500, pct=16.48, reset="2026-11-01"))
ok("X of Y requests used this month, resets <date>",
   txt == "412 of 2,500 requests used this month, resets November 1, 2026" and not warn, txt)
txt, warn = freqcheck.usage_text(U(used=900, quota=1000, pct=90.0, reset="2026-11-01T04:00:00Z"))
ok("Y comes from monthly_quota, and 90% is a warning", "of 1,000" in txt and warn, txt)
ok("89.9% is not a warning", not freqcheck.usage_text(U(used=899, quota=1000, pct=89.9, reset=""))[1])
ok("a timestamp is shown as a plain local date", "resets " in txt and "T04" not in txt and "2026" in txt, txt)
ok("no usage: 'Usage unavailable'", freqcheck.usage_text(None)[0] == "Usage unavailable")

save_env({"SPOTIFY_CLIENT_ID": GOOD_ID, "FREQBLOG_API_KEY": GOOD_FB})
checks = []


def fake_check(key, status="ok", pct=16.0):
    checks.append(key)
    if status == "ok":
        return freqcheck.KeyCheck("ok", "fine", U(used=int(pct * 10), quota=1000, pct=pct, reset="2026-11-01"))
    if status == "rejected":
        return freqcheck.KeyCheck("rejected", detail)
    return freqcheck.KeyCheck("offline", "Couldn't check the key with FreqBlog right now (synthetic).")


POPUPS.clear()
d = setmod.SettingsDialog(None, prefs=Prefs(), key_check=fake_check)
ok("Settings fetches the usage once when it opens", pump(lambda: "requests used" in d.usage.text())
   and len(checks) == 1, d.usage.text())
time.sleep(1.0)
pump(lambda: False, 0.5)
ok("and never again on its own (no polling)", len(checks) == 1, str(len(checks)))
d.fields["FREQBLOG_API_KEY"]._test()
ok("the Test button uses /me/stats and refreshes the line", len(checks) == 2
   and "Working" in d.fields["FREQBLOG_API_KEY"].result.text())
d.key_check = lambda key: fake_check(key, pct=93.0)
d.fields["FREQBLOG_API_KEY"]._test()
ok("93% shows in the warning colour", setmod.WARN.lower() in d.usage.text().lower() and d.usage_warn)
d.key_check = lambda key: fake_check(key, status="offline")
d.fields["FREQBLOG_API_KEY"]._test()
ok("a failed call shows 'Usage unavailable'", "Usage unavailable" in d.usage.text())
d.key_check = lambda key: fake_check(key, status="rejected")
d.fields["FREQBLOG_API_KEY"]._test()
ok("a rejected key shows FreqBlog's words under the key", detail in d.fields["FREQBLOG_API_KEY"].result.text())
ok("no popup for any of it", not POPUPS, str(POPUPS))
d.reject()
save_env({"SPOTIFY_CLIENT_ID": GOOD_ID})
checks.clear()
d2 = setmod.SettingsDialog(None, prefs=Prefs(), key_check=fake_check)
pump(lambda: False, 0.3)
ok("no key: no call and no line", not checks and d2.usage.text() == "")
d2.reject()
ok("the usage line is not on the main window", "usage_text" not in inspect.getsource(mw))

# ---------------------------------------------------------------------------
print("9. paste cleanup in all three key boxes")
for raw, want in ((f"Spotify client ID: {GOOD_ID}", GOOD_ID),
                  (f"  {GOOD_ID}\r\n", GOOD_ID),
                  (f"Client ID =\n{GOOD_ID[:16]} {GOOD_ID[16:]}", GOOD_ID),
                  (f'"{GOOD_FB}"', GOOD_FB),
                  (f"FreqBlog API key:\t{GOOD_FB}\n", GOOD_FB),
                  (f"API key - {GOOD_GS}", GOOD_GS)):
    ok(f"clean_key({raw.strip()[:24]!r}...)", wz.clean_key(raw) == want, wz.clean_key(raw))


def wizard(prefs=None, **kw):
    p = prefs or Prefs()
    a = kw.pop("auth", None) or SpotifyAuth("", p)
    kw.setdefault("scan", [(q, False) for q in wz.PORT_CANDIDATES])
    kw.setdefault("verify", lambda tok: (True, "Signed in."))
    kw.setdefault("open_url", lambda url: None)
    kw.setdefault("run_bg", lambda fn, done: done(fn()))
    kw.setdefault("key_check", lambda key: fake_check(key))
    return wz.SetupWizard(a, p, None, **kw)


save_env({})
wd = wizard(start=wz.SPOTIFY)
wd.client_id.setText(f"Spotify client ID:\n {GOOD_ID} \n")
ok("client ID box: a labelled paste is cleaned and accepted",
   wd.client_id.text() == GOOD_ID and "removed" in wd.client_note.text())
wd.client_id.setText("Spotify client ID: 0123456789abcdef")
ok("client ID box: still wrong says why, under the box",
   "isn't a Spotify Client ID" in wd.client_note.text() and "16" in wd.client_note.text()
   and not wd.can_advance(wz.SPOTIFY))
wd.go(wz.FREQBLOG)
wd.freqblog.setText(f"FreqBlog key: {GOOD_FB}\n")
ok("FreqBlog box: cleaned and accepted", wd.freqblog.text() == GOOD_FB)
wd.freqblog.setText("key: short")
ok("FreqBlog box: a wrong key says why", "doesn't look like a FreqBlog key" in wd.freqblog_note.text()
   and not wd.can_advance(wz.FREQBLOG))
wd.go(wz.GETSONGBPM)
wd.getsongbpm.setText(f"GetSongBPM API key: {GOOD_GS}\r\n")
ok("GetSongBPM box: cleaned and accepted", wd.getsongbpm.text() == GOOD_GS)
wd.getsongbpm.setText("abc def!")
ok("GetSongBPM box: a wrong key says why", "doesn't look like a GetSongBPM key" in wd.getsongbpm_note.text())
wd.getsongbpm.setText("")
ok("GetSongBPM box: empty still means skipped", wd.can_advance(wz.GETSONGBPM))

# ---------------------------------------------------------------------------
print("10. the wizard's FreqBlog step checks the key")
checks.clear()
wd = wizard(start=wz.FREQBLOG)
wd.freqblog.setText(GOOD_FB)
wd._next()
ok("Next runs one /me/stats check and stays to show the result",
   checks == [GOOD_FB] and wd.stack.currentIndex() == wz.FREQBLOG and wd.fb_check == "ok")
ok("the usage line appears after a good check", "requests used this month" in wd.fb_usage.text())
wd._next()
ok("Next again goes on", wd.stack.currentIndex() == wz.GETSONGBPM and len(checks) == 1)
wd = wizard(start=wz.FREQBLOG, key_check=lambda k: fake_check(k, status="rejected"))
wd.freqblog.setText(GOOD_FB)
wd.btn_fb_check.click()
ok("401: FreqBlog's message shown as-is, Next locked",
   detail in wd.freqblog_note.text() and not wd.btn_next.isEnabled() and wd.fb_usage.text() == "")
wd.freqblog.setText(GOOD_FB + "x")
ok("changing the key unlocks Next for a new check", wd.btn_next.isEnabled() and wd.fb_check is None)
wd = wizard(start=wz.FREQBLOG, key_check=lambda k: fake_check(k, status="offline"))
wd.freqblog.setText(GOOD_FB)
wd._next()
ok("offline: said plainly, and Next continues on the format check",
   "Couldn't check" in wd.freqblog_note.text() and wd.btn_next.isEnabled())
wd._next()
ok("... and does continue", wd.stack.currentIndex() == wz.GETSONGBPM)
wd = wizard(start=wz.FREQBLOG, key_check=lambda k: fake_check(k, pct=95.0))
wd.freqblog.setText(GOOD_FB)
wd.btn_fb_check.click()
ok("95% in the wizard shows in the warning colour", "#e8b04f" in wd.fb_usage.text().lower())
ok("the popup's 'fix the key' path opens this same step",
   "open_wizard(start=step)" in inspect.getsource(mw.MainWindow._key_rejected))

# ---------------------------------------------------------------------------
print("11. the automatic sign-in listener")
port = free_port()
seen = []
lst = CallbackListener(port, seen.append)
ok("starts on a free port", lst.start("STATE123"))
ok("bound to 127.0.0.1 only", lst.address == ("127.0.0.1", port), str(lst.address))


def get(path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


code, body = get("/callback?code=x&state=WRONG")
ok("a wrong state is refused and ignored", code == 400 and not seen and lst.listening)
code, body = get("/elsewhere?state=STATE123")
ok("other paths are 404", code == 404 and not seen)
code, body = get("/callback?code=x&state=STATE123")
ok("the right state is caught, with a 'you can close this tab' page",
   code == 200 and "close this tab" in body and seen == [f"http://127.0.0.1:{port}/callback?code=x&state=STATE123"])
lst.stop()
probe = socket.socket()
probe.settimeout(1)
ok("stopped: nothing listens on the port any more", probe.connect_ex(("127.0.0.1", port)) != 0)
probe.close()
blk = socket.socket()
if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
    blk.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
blk.bind(("127.0.0.1", port))
blk.listen(1)
ok("a port that's taken can't be bound (start() is False)", not CallbackListener(port, print).start("S"))
blk.close()

# end to end through the wizard
authmod.requests.post = fake_post
pr = Prefs()
pr.agreement_version = wz.AGREEMENT_VERSION
port = free_port()
opened = []
wd = wizard(pr, start=wz.SPOTIFY, scan=[(port, False)], open_url=opened.append)
wd.client_id.setText(GOOD_ID)
wd.go(wz.LOGIN)
wd._open_signin()
ok("Open Spotify sign-in starts the listener on the chosen port",
   wd.listener is not None and wd.listener.address == ("127.0.0.1", port) and opened)
state = up.parse_qs(up.urlparse(opened[-1]).query)["state"][0]
code, body = get(f"/callback?code=wizcode&state={state}")
ok("the browser gets the close-this-tab page", code == 200 and "close this tab" in body)
ok("the step finishes by itself", pump(lambda: wd.login_ok) and wd.btn_next.isEnabled())
ok("the listener stopped right after", wd.listener is None)
probe = socket.socket()
probe.settimeout(1)
ok("and the port is closed again", probe.connect_ex(("127.0.0.1", port)) != 0)
probe.close()

wd._open_signin()
ok("leaving the step stops it", wd.listener is not None)
wd.go(wz.FREQBLOG)
ok("... after go(FREQBLOG)", wd.listener is None)
wd.go(wz.LOGIN)
wd._open_signin()
wd._signin_timed_out()
ok("a timeout stops it and says so", wd.listener is None and "Stopped waiting" in wd.login_msg.text())
wd._open_signin()
wd.reject()
ok("cancel stops it", wd.listener is None)


class NoBind:
    def __init__(self, port, on_url):
        pass

    def start(self, state):
        return False

    def stop(self):
        pass


pr2 = Prefs()
pr2.agreement_version = wz.AGREEMENT_VERSION
wd = wizard(pr2, start=wz.SPOTIFY, listener_factory=NoBind, open_url=opened.append)
wd.client_id.setText(GOOD_ID)
wd.go(wz.LOGIN)
wd._open_signin()
ok("port can't be bound: falls back to pasting, and says so",
   wd.listener is None and "paste the address" in wd.login_msg.text())
state = up.parse_qs(up.urlparse(opened[-1]).query)["state"][0]
wd.paste.setText(f"http://127.0.0.1:{wd.auth.port}/callback?code=pasted&state={state}")
ok("the pasted address still signs in", wd.check_signin() and wd.login_ok)
authmod.requests.post = _real_post

# ---------------------------------------------------------------------------
print("12. the last page has Back and Finish only")
for req in (False, True):
    wd = wizard(required=req)
    wd.go(wz.DONE)
    ok(f"no Quit/Cancel on the last page (required={req})",
       not wd.btn_cancel.isVisibleTo(wd) and wd.btn_back.isVisibleTo(wd)
       and wd.btn_next.text() == "Finish")
    wd.go(wz.STORAGE)
    ok(f"... and it comes back on the other steps (required={req})", wd.btn_cancel.isVisibleTo(wd))
wd = wizard()
txt = wd.stack.widget(wz.WELCOME).findChildren(type(wd.step_label))
ok("Welcome: 'Your keys and playlists stay on this PC.'",
   any("Your keys and playlists stay on this PC." in l.text() for l in txt)
   and not any("Everything stays on this PC" in l.text() for l in txt))

# ---------------------------------------------------------------------------
print("13. dead code gone")
ok("copy_uris is gone", not hasattr(mw.MainWindow, "copy_uris"))
src_all = "".join(inspect.getsource(m) for m in (mw, wz, setmod, pv, authmod, config))
ok("no tunebat and no client secret in the program", "tunebat" not in src_all.lower()
   and "SPOTIFY_CLIENT_SECRET" not in src_all)

# ---------------------------------------------------------------------------
passed = sum(1 for _, r in RESULTS if r)
print(f"\n{passed} of {len(RESULTS)} passed")
shutil.rmtree(TMP, ignore_errors=True)
print("STAGE 8 TESTS PASSED" if passed == len(RESULTS) else "STAGE 8 TESTS FAILED")
raise SystemExit(0 if passed == len(RESULTS) else 1)
