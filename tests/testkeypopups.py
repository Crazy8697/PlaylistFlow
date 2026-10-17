import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""Key-failure handling: rejected keys, rate limits, misses, a dead Spotify sign-in.

Every HTTP response is mocked; settings are a throwaway .ini; no window is shown and
message boxes are answered by the test.

    .venv\\Scripts\\python tests\\testkeypopups.py
"""

import os
import shutil
import tempfile

TMP = pathlib.Path(tempfile.mkdtemp(prefix="pf-keytest-"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = str(TMP / "appdata")
os.environ["USERPROFILE"] = str(TMP / "home")
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
config.app_dir = lambda: TMP
from playlistflow import providers as pv
from playlistflow import auth as authmod
from playlistflow.providers import FreqBlog, GetSongBPM, KeyRejected, ProviderError
from playlistflow.domain import Track
import playlistflow.mainwindow as mw
import playlistflow.wizard as wz

mw.setup_needed = lambda env, state: ""          # no wizard over the test window
RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


class Resp:
    def __init__(self, code, body=None, headers=None):
        self.status_code = code
        self._b = body if body is not None else {}
        self.headers = headers or {}
        self.text = str(body)

    def json(self):
        return self._b


class Seq:
    """A fake session: hands out the queued responses in order and counts calls."""

    def __init__(self, *resps):
        self.resps = list(resps)
        self.calls = 0
        self.headers = {}

    def _next(self):
        self.calls += 1
        r = self.resps.pop(0) if len(self.resps) > 1 else self.resps[0]
        return r

    def request(self, method, url, **kw):
        return self._next()

    def get(self, url, **kw):
        return self._next()


print("1. FreqBlog")
fb = FreqBlog("synthetic-freqblog-key-0123456789")
slept = []
fb._sleep = slept.append
for code in (401, 403):
    fb._s = Seq(Resp(code))
    try:
        fb.bulk([{"track": "x"}])
        ok(f"{code} raises KeyRejected", False)
    except KeyRejected as e:
        ok(f"{code} raises KeyRejected", e.provider == "FreqBlog")
fb._s = Seq(Resp(429, headers={"Retry-After": "1"}), Resp(200, {"results": [{"found": False}]}))
rows = fb.bulk([{"track": "x"}])
ok("429 is retried quietly and then succeeds", rows == [{"found": False}] and slept == [1.0], str(slept))
slept.clear()
fb._s = Seq(Resp(429))
try:
    fb.bulk([{"track": "x"}])
    ok("429 that never clears is a plain error, not a key problem", False)
except KeyRejected:
    ok("429 that never clears is a plain error, not a key problem", False)
except ProviderError:
    ok("429 that never clears is a plain error, not a key problem", len(slept) == pv.RATE_LIMIT_TRIES - 1)
fb._s = Seq(Resp(404, {"terminal": True}))
f = fb.lookup("Unknown Song", "Nobody")
ok("track not found is a quiet miss", f.terminal and not f.bpm)
ok("User-Agent is PlaylistFlow/<version> (+https://darkrelay.net)",
   FreqBlog("k").__dict__["_s"].headers["User-Agent"] == f"PlaylistFlow/{pv.__version__} (+https://darkrelay.net)",
   pv.UA)

print("2. GetSongBPM")
gs = GetSongBPM("abcdef0123456789abcdef0123456789")
gs._sleep = slept.append
for case, resp in (("401", Resp(401)), ("403", Resp(403)),
                   ("error: Invalid API key", Resp(200, {"error": "Invalid API key"})),
                   ("search error: API key suspended", Resp(200, {"search": {"error": "API key suspended"}}))):
    gs._s = Seq(resp)
    try:
        gs.lookup("Song", "Artist")
        ok(f"{case} raises KeyRejected", False)
    except KeyRejected as e:
        ok(f"{case} raises KeyRejected", e.provider == "GetSongBPM")
gs._s = Seq(Resp(200, {"search": {"error": "no result"}}))
ok("'no result' is a quiet miss", gs.lookup("Song", "Artist").terminal)
slept.clear()
gs._s = Seq(Resp(429), Resp(200, {"search": [{"title": "Song", "artist": {"name": "Artist"},
                                              "tempo": "120", "key_of": "Am"}]}))
f = gs.lookup("Song", "Artist")
ok("429 is retried quietly", f.bpm == 120 and len(slept) == 1)

print("3. fetch worker")


class FakeFB:
    def __init__(self):
        self.calls = 0
        self.api_key = "x"

    def bulk(self, items):
        self.calls += 1
        raise KeyRejected("FreqBlog")

    def lookup_isrc(self, isrc, wait=0):
        self.calls += 1
        raise KeyRejected("FreqBlog")


class FakeGS:
    api_key = "x"

    def __init__(self):
        self.calls = 0

    def lookup(self, t, a):
        self.calls += 1
        return pv.Features(bpm=100, camelot="8A")


ffb, fgs = FakeFB(), FakeGS()
tracks = [Track(title=f"T{i}", artist="A", isrc=f"ISRC{i}") for i in range(3)]
wk = mw.FetchWorker(ffb, fgs, list(enumerate(tracks)))
emitted, resolved = [], []
wk.keyRejected.connect(emitted.append)
wk.resolved.connect(lambda i, f: resolved.append(i))
wk._sleep = lambda s: True
wk.run()
ok("a rejected FreqBlog key is reported once", emitted == ["FreqBlog"], str(emitted))
ok("FreqBlog is not asked again in that run", ffb.calls == 1, f"calls={ffb.calls}")
ok("GetSongBPM still fills the gaps", fgs.calls == 3 and len(resolved) == 3)


class RejectGS(FakeGS):
    def lookup(self, t, a):
        self.calls += 1
        raise KeyRejected("GetSongBPM")


class MissFB(FakeFB):
    def bulk(self, items):
        self.calls += 1
        return [{"found": False} for _ in items]

    def lookup_isrc(self, isrc, wait=0):
        self.calls += 1
        return pv.Features(terminal=True)


rgs = RejectGS()
wk = mw.FetchWorker(MissFB(), rgs, list(enumerate(tracks)))
emitted.clear()
wk.keyRejected.connect(emitted.append)
wk._sleep = lambda s: True
wk.run()
ok("a rejected GetSongBPM key is reported once and that pass stops", emitted == ["GetSongBPM"] and rgs.calls == 1,
   f"{emitted} calls={rgs.calls}")

print("4. popups: once per session, with a route to the fix")
w = mw.MainWindow()
for _ in range(10):
    app.processEvents()
shown, opened = [], []
w.open_wizard = lambda start=0, required=False: opened.append(start) or True
real_exec = QMessageBox.exec
choice = {"button": "fix"}


def answer(self):
    shown.append((self.objectName(), self.windowTitle()))
    for b in self.buttons():
        if (choice["button"] == "fix") == (self.buttonRole(b) == QMessageBox.AcceptRole):
            b.click()
            break
    return 0


QMessageBox.exec = answer
w._key_rejected("FreqBlog")
w._key_rejected("FreqBlog")
ok("FreqBlog popup shows once per session", [s for s in shown if "FreqBlog" in s[1]] ==
   [("key_rejected", "FreqBlog key not working")], str(shown))
ok("its button jumps to the FreqBlog step", opened == [wz.FREQBLOG], str(opened))
opened.clear()
choice["button"] = "later"
w._key_rejected("GetSongBPM")
w._key_rejected("GetSongBPM")
ok("GetSongBPM popup shows once too", sum(1 for s in shown if "GetSongBPM" in s[1]) == 1)
ok("'Later' opens nothing", opened == [])
choice["button"] = "fix"
w._key_rejected("GetSongBPM")
ok("still once even after Later", sum(1 for s in shown if "GetSongBPM" in s[1]) == 1)
w._warned.clear()
w._key_rejected("GetSongBPM")
ok("GetSongBPM button jumps to the GetSongBPM step", opened == [wz.GETSONGBPM], str(opened))

print("5. Spotify sign-in dies")
opened.clear()
shown.clear()
w._warned.clear()
w.auth.client_id = "0123456789abcdef0123456789abcdef"
w.prefs.refresh_token = "synthetic-refresh"
w.auth._access = ""
real_post = authmod.requests.post
authmod.requests.post = lambda *x, **k: Resp(400, {"error": "invalid_grant"})
for _ in range(2):
    try:
        w.auth.access_token()
    except authmod.AuthError:
        pass
    w.prefs.refresh_token = "synthetic-refresh"
for _ in range(10):
    app.processEvents()
authmod.requests.post = real_post
ok("a dead token shows one plain popup", [s[0] for s in shown] == ["spotify_dead"], str(shown))
ok("its button jumps to the sign-in step", opened == [wz.LOGIN], str(opened))
opened.clear()
w.prefs.refresh_token = ""
ok("after the popup, an automatic sign-in fallback doesn't ask again", not w.sign_in() and opened == [])
w.sign_in_now()
ok("File > Sign in still opens the sign-in step", opened == [wz.LOGIN], str(opened))
QMessageBox.exec = real_exec

w._dirty = False
w.close()
shutil.rmtree(TMP, ignore_errors=True)
bad = [n for n, g in RESULTS if not g]
print(f"\n{len(RESULTS) - len(bad)} of {len(RESULTS)} passed")
print("FAILED: " + ", ".join(bad) if bad else "KEY POPUP TESTS PASSED")
sys.stdout.flush()
os._exit(1 if bad else 0)
