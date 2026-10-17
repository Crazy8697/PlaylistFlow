import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""The setup wizard: skip logic, ports, step locks, what it saves. No network, no real settings.

Everything is isolated: a temp APPDATA and user profile, a throwaway settings .ini, the
repo-root .env blocked, and every Spotify call mocked. Windows are never shown.

    .venv\\Scripts\\python tests\\testwizard.py
"""

import os
import shutil
import socket
import tempfile

TMP = pathlib.Path(tempfile.mkdtemp(prefix="pf-wiztest-"))
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
(TMP / "settings.ini").write_text("[General]\nupdate_check=false\n", encoding="ascii")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
app = QApplication([])
app.setOrganizationName("darkrelay")
app.setApplicationName("PlaylistFlow")

from playlistflow import config
config.app_dir = lambda: TMP                  # never the repo-root .env
from playlistflow import auth as authmod
from playlistflow import wizard as wz
from playlistflow.auth import SpotifyAuth, AuthError
from playlistflow.config import Prefs, env_path, _read_env_file
import playlistflow.mainwindow as mw

GOOD_ID = "0123456789abcdef0123456789abcdef"          # synthetic
GOOD_FB = "synthetic_freqblog_key_0123456789"          # synthetic
GOOD_GS = "abcdef0123456789abcdef0123456789"          # synthetic
RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


class Resp:
    def __init__(self, code, body=None):
        self.status_code = code
        self._b = body or {}
        self.headers = {}
        self.text = str(body)

    def json(self):
        return self._b


def write_env(text):
    env_path().write_text(text, encoding="utf-8")


def fresh_prefs(token=""):
    p = Prefs()
    p.refresh_token = token
    p.storage_dir = ""
    return p


def wizard(prefs, scan=None, verify=None, start=0, auth=None, required=False):
    a = auth or SpotifyAuth("", prefs)
    return wz.SetupWizard(a, prefs, None, start=start, required=required,
                          scan=scan if scan is not None else [(p, False) for p in wz.PORT_CANDIDATES],
                          verify=verify or (lambda tok: (True, "Signed in.")),
                          open_url=lambda url: None)


print("1. skip logic")
ok("no keys -> wizard", mw.setup_needed({}, "none") == "no Spotify client ID")
ok("no FreqBlog key -> wizard", mw.setup_needed({"SPOTIFY_CLIENT_ID": GOOD_ID}, "ok") == "no FreqBlog key")
both = {"SPOTIFY_CLIENT_ID": GOOD_ID, "FREQBLOG_API_KEY": GOOD_FB}
ok("not signed in -> wizard", mw.setup_needed(both, "none") == "not signed in to Spotify")
ok("dead token -> wizard", mw.setup_needed(both, "dead") == "the Spotify sign-in no longer works")
ok("working setup -> no wizard", mw.setup_needed(both, "ok") == "")
ok("offline -> no forced wizard", mw.setup_needed(both, "offline") == "")

real_post = authmod.requests.post
p = fresh_prefs("synthetic-refresh-token")
a = SpotifyAuth(GOOD_ID, p)
authmod.requests.post = lambda *x, **k: Resp(400, {"error": "invalid_grant"})
ok("stale token: check() says dead", a.check() == "dead")
authmod.requests.post = lambda *x, **k: Resp(401, {"error": "invalid_client"})
ok("broken client ID: check() says dead", a.check() == "dead")
authmod.requests.post = lambda *x, **k: Resp(200, {"access_token": "synthetic-access", "expires_in": 3600})
ok("working token: check() says ok", a.check() == "ok")


def boom(*x, **k):
    raise authmod.requests.ConnectionError("synthetic offline")


authmod.requests.post = boom
ok("no connection: check() says offline", a.check() == "offline")
ok("no token: check() says none", SpotifyAuth(GOOD_ID, fresh_prefs("")).check() == "none")
authmod.requests.post = real_post

print("2. ports")
scan = wz.scan_ports(candidates=(8888, 8889, 8890, 8891), busy=lambda p: p in (8888, 8889))
ok("scan marks busy ports", scan == [(8888, True), (8889, True), (8890, False), (8891, False)])
ok("pick skips busy ports", wz.pick_port(scan, 8888) == 8890)
ok("pick keeps a free preferred port", wz.pick_port(scan, 8891) == 8891)
s = socket.socket()
s.bind(("127.0.0.1", 0))
s.listen(1)
held = s.getsockname()[1]
ok("port_busy sees a real listener", wz.port_busy(held))
s.close()
ok("port_busy frees it after close", not wz.port_busy(held))
w = wizard(fresh_prefs(), scan=scan + [(p, False) for p in range(8892, 8900)])
ok("wizard auto-picks the first free port", w.port() == 8890, str(w.port()))
ok("redirect URI matches the port", w.uri_box.text() == "http://127.0.0.1:8890/callback", w.uri_box.text())
ok("redirect URI is read-only", w.uri_box.isReadOnly())
ok("busy ports are greyed out", not w.port_box.model().item(0).isEnabled()
   and "in use" in w.port_box.itemText(0))
ok("the note says which port it took", "8888 is in use, using 8890" in w.port_note.text())
w.port_box.setCurrentIndex(3)
ok("changing the port updates the URI", w.uri_box.text() == "http://127.0.0.1:8891/callback")

print("3. step locks")
w = wizard(fresh_prefs(), start=wz.SPOTIFY)
w.client_id.setText("not a client id")
ok("bad client ID locks Next", not w.btn_next.isEnabled())
w.client_id.setText(GOOD_ID)
ok("good client ID unlocks Next", w.btn_next.isEnabled())
w.go(wz.LOGIN)
ok("Next locked until the sign-in test passes", not w.btn_next.isEnabled())
w.auth.complete = lambda pasted: None
w.auth.access_token = lambda: "synthetic-access"
w.verify = lambda tok: (False, "Spotify accepted the sign-in but refused to share your data. "
                                "Your Spotify account is probably not on the app's allowlist")
w.paste.setText("http://127.0.0.1:8888/callback?code=synthetic&state=x")
ok("failed test keeps Next locked", not w.check_signin() and not w.btn_next.isEnabled())
ok("failure is explained (allowlist)", "allowlist" in w.login_msg.text())


def bad_complete(pasted):
    raise AuthError("Token exchange failed (400): {\"error\":\"invalid_client\"}")


w.auth.complete = bad_complete
w.check_signin()
ok("bad client ID during sign-in is explained", "doesn't recognise that client ID" in w.login_msg.text())
w.auth.complete = lambda pasted: None
w.verify = lambda tok: (True, "Signed in as Synthetic.")
ok("passing test unlocks Next", w.check_signin() and w.btn_next.isEnabled())
w.go(wz.SPOTIFY)
w.port_box.setCurrentIndex(2)
w.go(wz.LOGIN)
ok("changing the port relocks the sign-in step", not w.btn_next.isEnabled())
real_get = wz.requests.get
wz.requests.get = lambda *x, **k: Resp(403, {"error": {"status": 403}})
good, msg = wz.spotify_me("synthetic-access")
ok("spotify_me reads 403 as the allowlist / Premium trap", not good and "allowlist" in msg and "Premium" in msg)
wz.requests.get = lambda *x, **k: Resp(200, {"display_name": "Synthetic User"})
ok("spotify_me accepts a 200", wz.spotify_me("synthetic-access")[0])
wz.requests.get = real_get

w.go(wz.FREQBLOG)
w.freqblog.setText("")
ok("FreqBlog is required (empty locks Next)", not w.btn_next.isEnabled())
w.freqblog.setText("bad key with spaces")
ok("FreqBlog bad format locks Next", not w.btn_next.isEnabled())
w.freqblog.setText(GOOD_FB)
ok("FreqBlog good format unlocks Next", w.btn_next.isEnabled())
ok("FreqBlog step says one key per person", "One free key per person. Never share it."
   in "".join(l.text() for l in w.stack.widget(wz.FREQBLOG).findChildren(type(w.step_label))))

w.go(wz.GETSONGBPM)
w.getsongbpm.setText("")
ok("GetSongBPM is skippable (empty keeps Next on)", w.btn_next.isEnabled())
w.getsongbpm.setText("no!")
ok("GetSongBPM bad format locks Next", not w.btn_next.isEnabled())
w.getsongbpm.setText(GOOD_GS)
ok("GetSongBPM good key unlocks Next", w.btn_next.isEnabled())
texts = "".join(l.text() for l in w.stack.widget(wz.GETSONGBPM).findChildren(type(w.uri_box)))
ok("both backlink sites offered", "darkrelay.net" in texts and "github.com/Crazy8697/PlaylistFlow" in texts)

print("4. storage folder")
w = wizard(fresh_prefs())
ok("default is Documents\\PlaylistFlow", w.folder.text() == str(TMP / "home" / "Documents" / "PlaylistFlow"),
   w.folder.text())
p = fresh_prefs()
p.storage_dir = str(TMP / "existing-store")
w = wizard(p)
ok("existing storage_dir is prefilled", w.folder.text() == str(TMP / "existing-store"))

print("5. what gets saved")
write_env("SPOTIFY_CLIENT_ID=ffffffffffffffffffffffffffffffff\nSPOTIFY_CLIENT_SECRET=synthetic-old-secret\n"
          "BRAVE_API_KEY=synthetic-old-brave\nGETSONGBPM_API_KEY=synthetic0old0getsongbpm0key\n"
          "GRAPH_MAX_BPM=300\n")
p = fresh_prefs()
w = wizard(p, scan=[(8888, True)] + [(q, False) for q in range(8889, 8900)])
w.client_id.setText(GOOD_ID)
w.login_ok = True
w.freqblog.setText(GOOD_FB)
w.getsongbpm.setText("")                 # skipped
w.folder.setText(str(TMP / "chosen-store"))
w.go(wz.DONE)
w._next()                                # Finish
saved = _read_env_file(env_path())
ok("Finish saves and closes", w.saved and w.result() == QDialog.Accepted)
ok(".env holds the collected keys", saved.get("SPOTIFY_CLIENT_ID") == GOOD_ID
   and saved.get("FREQBLOG_API_KEY") == GOOD_FB and saved.get("SPOTIFY_REDIRECT_PORT") == "8889")
ok("a skipped GetSongBPM key is not written", "GETSONGBPM_API_KEY" not in saved)
ok("client secret and Brave never written", "SPOTIFY_CLIENT_SECRET" not in saved and "BRAVE_API_KEY" not in saved)
ok("display settings already there are kept", saved.get("GRAPH_MAX_BPM") == "300")
ok("nothing else added", set(saved) == {"SPOTIFY_CLIENT_ID", "SPOTIFY_REDIRECT_PORT", "FREQBLOG_API_KEY",
                                        "GRAPH_MAX_BPM"}, ",".join(sorted(saved)))
ok("storage folder saved to settings", p.storage_dir == str(TMP / "chosen-store"))
ok("keys only in AppData, not the storage folder", not any((TMP / "chosen-store").glob("*.env"))
   and env_path() == TMP / "appdata" / "PlaylistFlow" / ".env")

print("6. cancel leaves everything as it was")
write_env(f"SPOTIFY_CLIENT_ID={GOOD_ID}\nFREQBLOG_API_KEY={GOOD_FB}\n")
before = env_path().read_text(encoding="utf-8")
p = fresh_prefs("synthetic-old-token")
a = SpotifyAuth(GOOD_ID, p)
w = wizard(p, auth=a, start=wz.LOGIN)


def sets_token(pasted):
    p.refresh_token = "synthetic-new-token"


a.complete = sets_token
a.access_token = lambda: "synthetic-access"
w.paste.setText("http://127.0.0.1:8888/callback?code=x")
w.check_signin()
w.reject()
ok("cancel restores the old sign-in", p.refresh_token == "synthetic-old-token")
ok("cancel leaves the .env untouched", env_path().read_text(encoding="utf-8") == before)
asked = {}
real_q = QMessageBox.question
QMessageBox.question = staticmethod(lambda *x, **k: (asked.setdefault("n", 1), QMessageBox.No)[1])
w = wizard(fresh_prefs(), required=True)
closed = []
w.finished.connect(lambda r: closed.append(r))
w.reject()
ok("a required run asks before quitting, and stays on no", asked.get("n") == 1 and closed == [])
QMessageBox.question = staticmethod(lambda *x, **k: QMessageBox.Yes)
w.reject()
ok("and quits on yes", closed == [QDialog.Rejected])
QMessageBox.question = real_q

print("7. first launch and rerun from Settings")
write_env("")
opened = []
real_exec = wz.SetupWizard.exec


def fake_exec(self):
    opened.append(self.stack.currentIndex())
    return QDialog.Rejected


wz.SetupWizard.exec = fake_exec
win = mw.MainWindow()
quits = []
real_quit = QApplication.quit
QApplication.quit = staticmethod(lambda: quits.append(1))
for _ in range(30):
    app.processEvents()
ok("first launch with no keys opens the wizard, required", opened[:1] == [wz.WELCOME], str(opened))
ok("quitting a required wizard closes the program", bool(quits) or not win.isVisible())
QApplication.quit = real_quit
opened.clear()
mw.setup_needed = lambda env, state: ""
win2 = mw.MainWindow()
for _ in range(10):
    app.processEvents()
ok("working setup starts without the wizard", opened == [], str(opened))
from playlistflow.settings import SettingsDialog
real_sexec = SettingsDialog.exec


def settings_exec(self):
    self.btn_setup.click()
    return self.result()


SettingsDialog.exec = settings_exec
win2.open_settings()
ok("Settings > Run setup again opens the wizard at the start", opened == [wz.WELCOME], str(opened))
SettingsDialog.exec = real_sexec
wz.SetupWizard.exec = real_exec

shutil.rmtree(TMP, ignore_errors=True)
bad = [n for n, g in RESULTS if not g]
print(f"\n{len(RESULTS) - len(bad)} of {len(RESULTS)} passed")
print("FAILED: " + ", ".join(bad) if bad else "WIZARD TESTS PASSED")
sys.stdout.flush()
os._exit(1 if bad else 0)
