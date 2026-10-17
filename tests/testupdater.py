import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""The updater against a fake local GitHub. No real network, no real settings.

Everything runs isolated: a temp APPDATA (keys are synthetic placeholders), a throwaway
settings .ini (PLAYLISTFLOW_SETTINGS_INI), PLAYLISTFLOW_UPDATE_URL pointed at a local HTTP
server that serves GitHub-shaped release JSON and assets, and PLAYLISTFLOW_UPDATE_DRYRUN so
the installer is never started: its command line is written to a file instead. Windows are
offscreen and never shown.

    .venv\\Scripts\\python tests\\testupdater.py
"""

import hashlib
import http.server
import json
import os
import shutil
import tempfile
import threading
import time

TMP = pathlib.Path(tempfile.mkdtemp(prefix="pf-updtest-"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = str(TMP / "appdata")
os.environ["PLAYLISTFLOW_SETTINGS_INI"] = str(TMP / "settings.ini")
os.environ["PLAYLISTFLOW_UPDATE_DRYRUN"] = str(TMP / "dryrun.json")
os.environ["PLAYLISTFLOW_UPDATE_TIMEOUT"] = "3"
for k in ("SPOTIFY_CLIENT_ID", "FREQBLOG_API_KEY", "GETSONGBPM_API_KEY"):
    os.environ.pop(k, None)
(TMP / "appdata" / "PlaylistFlow").mkdir(parents=True)
# synthetic placeholders so the first-run dialog stays shut; never real keys
(TMP / "appdata" / "PlaylistFlow" / ".env").write_text(
    "SPOTIFY_CLIENT_ID=synthetic-test-id\nFREQBLOG_API_KEY=synthetic-test-key\n", encoding="utf-8")
(TMP / "storage").mkdir()
(TMP / "settings.ini").write_text(
    "[General]\nstorage_dir=" + (TMP / "storage").as_posix() + "\n", encoding="ascii")

# ---- fake GitHub ----------------------------------------------------------
SETUP_BYTES = b"MZ fake installer for the update test " * 4096
STATE = {"release": None, "sha": hashlib.sha256(SETUP_BYTES).hexdigest(), "hits": [], "raw": None}


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        STATE["hits"].append(self.path)
        if self.path == "/latest":
            body = STATE["raw"] if STATE["raw"] is not None else json.dumps(STATE["release"]).encode()
            ctype = "application/json"
        elif self.path == "/PlaylistFlow-Setup.exe":
            body, ctype = SETUP_BYTES, "application/octet-stream"
        elif self.path == "/PlaylistFlow-Setup.exe.sha256":
            body = f"{STATE['sha']} *PlaylistFlow-Setup.exe".encode()
            ctype = "text/plain"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ["PLAYLISTFLOW_UPDATE_URL"] = BASE + "/latest"


def release(tag, assets=("PlaylistFlow-Setup.exe", "PlaylistFlow-Setup.exe.sha256"), body="Notes"):
    STATE["raw"] = None
    STATE["release"] = {
        "tag_name": tag, "body": body, "html_url": BASE + "/page", "draft": False,
        "prerelease": False,
        "assets": [{"name": a, "browser_download_url": f"{BASE}/{a}"} for a in assets]}


# ---- program under test (imported after the environment is set) ----------
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
app = QApplication([])
app.setApplicationName("Playlist Flow")
app.setOrganizationName("darkrelay")

from playlistflow import config as _config
_config.app_dir = lambda: TMP     # never the repo-root .env a source run would also read
import playlistflow.mainwindow as _mw
_mw.setup_needed = lambda env, state: ""   # no setup wizard over these windows
from playlistflow import __version__
from playlistflow import updater
from playlistflow.config import Prefs
from playlistflow.mainwindow import MainWindow

RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def wait(pred, secs=8.0):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.02)
    app.processEvents()
    return pred()


def new_window():
    w = MainWindow()          # never shown
    wait(lambda: False, 0.3)  # let the deferred _start run
    return w


def quiet_check(w):
    w._update_last = None
    w.check_updates(quiet=True)
    return wait(lambda: w._update_last is not None)


def close(w):
    w._dirty = False
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


print(f"version under test: {__version__}, fake GitHub at {BASE}")

# 1. a proper 1.0.1 is offered
print("1. newer release with the installer and checksum")
release("v1.0.1")
w = new_window()
quiet_check(w)
ok("1.0.1 offered", w._update_last.get("status") == "newer" and w.update_bar.isVisibleTo(w),
   w.update_label.text())
ok("bar text", w.update_label.text() == "Playlist Flow 1.0.1 is available")

# 2. the old zip-only shape is invisible
print("2. a release shaped like the old v1.2.0 (zip only)")
release("v1.2.0", assets=("PlaylistFlow-v1.2.0-win64.zip",))
w.update_bar.hide()
quiet_check(w)
ok("zip-only ignored", w._update_last.get("status") == "none" and not w.update_bar.isVisibleTo(w))
release("v1.2.0", assets=("PlaylistFlow-Setup.exe",))          # installer but no checksum
quiet_check(w)
ok("no-checksum ignored", w._update_last.get("status") == "none" and not w.update_bar.isVisibleTo(w))

# 3. same and older are not offered
print("3. same and older versions")
_cur = updater.parse_version(__version__)
older = f"v{_cur[0]}.{max(0, _cur[1] - 1)}.0" if _cur[1] else "v0.0.1"
for tag in (f"v{__version__}", older, f"{__version__}-rc1"):
    release(tag)
    quiet_check(w)
    ok(f"{tag} not offered", w._update_last.get("status") == "current"
       and not w.update_bar.isVisibleTo(w))

print("3b. version order across the test builds and 1.0.0")
for tag, cur, want in (("v0.7.0", "0.6.0", True), ("v1.0.0", "0.6.0", True), ("v1.0.0", "0.9.0", True),
                       ("v0.10.0", "0.9.0", True),          # numeric, not text: 10 > 9
                       ("v0.6.0", "0.6.0", False), ("v0.5.0", "0.6.0", False),
                       ("v0.6.0", "1.0.0", False), ("v1.0.0-rc1", "1.0.0", False),
                       ("v1.0.0", "1.0.0-rc1", True), ("v1.0.1", "1.0.0", True), ("1.1", "1.0.9", True)):
    ok(f"is_newer({tag}, {cur}) == {want}", updater.is_newer(tag, cur) == want)
for cur, tag in (("0.5.0", "v0.6.0"), ("0.6.0", "v0.6.0"), ("0.7.0", "v0.6.0")):
    release(tag)
    r = updater.check_release(cur)
    ok(f"installed {cur} vs release {tag}: "
       f"{'offered' if cur == '0.5.0' else 'not offered'}",
       r.get("status") == ("newer" if cur == "0.5.0" else "current"), r.get("status"))

# 4. skip persists across restarts, a newer one still shows; later lasts a session
print("4. skip this version / later")
release("v1.0.1")
quiet_check(w)
w._skip_update()
ok("skip hides the bar", not w.update_bar.isVisibleTo(w))
ok("skip stored", Prefs().update_skip == "1.0.1")
close(w)
w = new_window()                                                 # "restart"
quiet_check(w)
ok("skipped 1.0.1 stays quiet after restart", not w.update_bar.isVisibleTo(w))
release("v1.0.2")
quiet_check(w)
ok("1.0.2 still offered", w.update_bar.isVisibleTo(w), w.update_label.text())
w._later_update()
ok("later hides the bar", not w.update_bar.isVisibleTo(w))
close(w)
w = new_window()                                                 # "restart"
quiet_check(w)
ok("later comes back after restart", w.update_bar.isVisibleTo(w))
close(w)

# 5. startup toggle off: no request at all; on: one request after the delay
print("5. startup toggle")
p = Prefs()
p.update_check = False
STATE["hits"].clear()
w = new_window()
wait(lambda: False, updater.UPDATE_STARTUP_DELAY_MS / 1000 + 1.5)
ok("toggle off: no network call", STATE["hits"] == [], f"hits={STATE['hits']}")
close(w)
p.update_check = True
STATE["hits"].clear()
w = new_window()
wait(lambda: bool(STATE["hits"]), updater.UPDATE_STARTUP_DELAY_MS / 1000 + 3)
ok("toggle on: startup check runs", STATE["hits"] == ["/latest"], f"hits={STATE['hits']}")
wait(lambda: w._update_last is not None)
close(w)

# 6. a wrong checksum is refused and nothing is left behind
print("6. bad SHA-256")
release("v1.0.2")
info = updater.check_release()
good = STATE["sha"]
STATE["sha"] = "0" * 64
stage = updater.staging_dir()
try:
    updater.download_update(info)
    ok("bad hash refused", False, "no error raised")
except updater.UpdateError as e:
    ok("bad hash refused", "SHA-256" in str(e), str(e))
left = list(stage.glob("*")) if stage.exists() else []
ok("nothing left in update-staging", left == [], f"left={[x.name for x in left]}")
STATE["sha"] = good

# 7. a good download verifies, and the installer command is right (dry run, nothing runs)
print("7. good download and install command")
path = updater.download_update(info)
ok("download verified", pathlib.Path(path).is_file()
   and hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest() == good, path)
ok("download lands in %APPDATA%\\PlaylistFlow\\update-staging",
   pathlib.Path(path).parent == pathlib.Path(os.environ["APPDATA"]) / "PlaylistFlow" / "update-staging")
ok("setup command", updater.setup_command(path) ==
   [path, "/SILENT", "/SP-", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1"])
w = new_window()
quiet_check(w)
w._start_update_download()
wait(lambda: (w._update_last or {}).get("status") in ("installing", "download-error",
                                                      "launch-failed", "postponed"), 15)
dry = TMP / "dryrun.json"
cmd = json.loads(dry.read_text(encoding="utf-8")) if dry.exists() else None
ok("bar flow: download, verify, launch (dry run)", w._update_last.get("status") == "installing"
   and cmd and cmd[1:] == updater.UPDATE_SETUP_ARGS and pathlib.Path(cmd[0]).is_file(),
   f"status={w._update_last.get('status')}")
ok("window closed before Setup", not w.isVisible())
close(w)

# 8. server down or garbage: quiet, never a crash
print("8. failures")
STATE["raw"] = b"<html>not json"
r = updater.check_release()
ok("garbage JSON -> error, no raise", r.get("status") == "error", r.get("reason"))
STATE["raw"] = b"[1, 2, 3]"
r = updater.check_release()
ok("JSON that isn't an object -> error", r.get("status") == "error", r.get("reason"))
STATE["raw"] = None
w = new_window()
os.environ["PLAYLISTFLOW_UPDATE_URL"] = "http://127.0.0.1:9/latest"     # nothing listens there
quiet_check(w)
ok("server down -> quiet error", w._update_last.get("status") == "error"
   and not w.update_bar.isVisibleTo(w), w._update_last.get("reason"))
srv.shutdown()
os.environ["PLAYLISTFLOW_UPDATE_URL"] = BASE + "/latest"
quiet_check(w)
ok("server gone mid-session -> quiet error", w._update_last.get("status") == "error")
close(w)

shutil.rmtree(TMP, ignore_errors=True)
bad = [n for n, good_ in RESULTS if not good_]
print(f"\n{len(RESULTS) - len(bad)} of {len(RESULTS)} passed")
if bad:
    print("FAILED:", ", ".join(bad))
else:
    print("UPDATER TESTS PASSED")
sys.stdout.flush()
# hard exit: PySide can crash tearing down Qt objects at interpreter exit after many
# windows have come and gone, which would turn a pass into a confusing exit code
os._exit(1 if bad else 0)
