import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""The privacy policy / end user agreement step, and Settings > Disconnect Spotify.

Isolated: temp APPDATA and profile, a throwaway settings .ini, synthetic playlists in a temp
storage folder, no network, no window shown, dialogs answered by the test.

    .venv\\Scripts\\python tests\\testagreement.py
"""

import json
import os
import shutil
import tempfile

TMP = pathlib.Path(tempfile.mkdtemp(prefix="pf-agreetest-"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = str(TMP / "appdata")
os.environ["USERPROFILE"] = str(TMP / "home")
os.environ["PLAYLISTFLOW_SETTINGS_INI"] = str(TMP / "settings.ini")
os.environ["PLAYLISTFLOW_UPDATE_URL"] = "http://127.0.0.1:9/never"
for k in ("SPOTIFY_CLIENT_ID", "FREQBLOG_API_KEY", "GETSONGBPM_API_KEY"):
    os.environ.pop(k, None)
STORE = TMP / "store"
(TMP / "appdata" / "PlaylistFlow").mkdir(parents=True)
(TMP / "home").mkdir()
STORE.mkdir()
(TMP / "settings.ini").write_text("[General]\nupdate_check=false\nstorage_dir=" + STORE.as_posix() + "\n",
                                  encoding="ascii")

from PySide6.QtWidgets import QApplication, QDialog, QTextBrowser
app = QApplication([])

from playlistflow import config
config.app_dir = lambda: TMP
from playlistflow import wizard as wz
from playlistflow import docs
from playlistflow.auth import SpotifyAuth
from playlistflow.config import Prefs
from playlistflow.domain import Track
import playlistflow.mainwindow as mw

mw.setup_needed = lambda env, state: ""
RESULTS = []
sys.stdout.reconfigure(errors="replace")


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def wizard(prefs, start=0):
    return wz.SetupWizard(SpotifyAuth("", prefs), prefs, None, start=start,
                          scan=[(p, False) for p in wz.PORT_CANDIDATES],
                          verify=lambda tok: (True, "ok"), open_url=lambda url: None)


print("1. the agreement step")
p = Prefs()
p.agreement_version = ""
w = wizard(p, start=wz.SPOTIFY)
w.client_id.setText("0123456789abcdef0123456789abcdef")
w._next()
ok("first time: Next from the Spotify app step lands on the agreement", w.stack.currentIndex() == wz.AGREE)
shown = {tb.objectName(): tb.toPlainText() for tb in w.stack.widget(wz.AGREE).findChildren(QTextBrowser)}
docs_shown = list(shown.values())
ok("both documents are shown in full", "privacy policy" in shown.get("doc_privacy", "").lower()
   and "end user agreement" in shown.get("doc_terms", "").lower(), str(list(shown)))
ok("Spotify named as third party beneficiary in both",
   all("third party beneficiary" in " ".join(d.split()) for d in docs_shown))
ok("Next locked until 'I agree' is ticked", not w.btn_next.isEnabled())
ok("the box starts unticked", not w.agree_box.isChecked())
w.agree_box.setChecked(True)
ok("ticking unlocks Next", w.btn_next.isEnabled())
w._next()
ok("Next then goes to the sign-in step", w.stack.currentIndex() == wz.LOGIN)
ok("acceptance stored with the current version", Prefs().agreement_version == docs.AGREEMENT_VERSION)
w.go(wz.LOGIN - 1)
ok("Back from sign-in skips an already accepted agreement", w.stack.currentIndex() == wz.SPOTIFY)
w2 = wizard(Prefs(), start=wz.SPOTIFY)
w2.client_id.setText("0123456789abcdef0123456789abcdef")
w2._next()
ok("accepted: a later setup goes straight to sign-in", w2.stack.currentIndex() == wz.LOGIN)
Prefs().agreement_version = "2000-01-01"
w3 = wizard(Prefs(), start=wz.LOGIN)
ok("changed version: a jump to sign-in shows the agreement first", w3.stack.currentIndex() == wz.AGREE)
w4 = wizard(Prefs(), start=wz.SPOTIFY)
w4.client_id.setText("0123456789abcdef0123456789abcdef")
w4._next()
ok("changed version: the setup flow shows it again", w4.stack.currentIndex() == wz.AGREE)
ok("not accepted means not stored", Prefs().agreement_version == "2000-01-01")

from PySide6.QtGui import QTextDocument
for name in ("PRIVACY.md", "TERMS.md", "THIRD-PARTY-NOTICES.md"):
    d = QTextDocument()
    d.setMarkdown(docs.read_doc(name))
    rendered = " ".join(d.toPlainText().split())
    tail = " ".join(docs.read_doc(name).split()[-6:]).replace("**", "").replace("`", "")[:30]
    ok(f"{name} renders to the end (nothing read as an HTML tag)", tail in rendered)

print("2. About and Help")
win = mw.MainWindow()
import time
end = time.time() + 15
while win.store is None and time.time() < end:      # the startup check runs in a thread
    app.processEvents()
    time.sleep(0.02)
about = mw.AboutDialog(win)
html = about.body.text()
ok("About states the license", "Apache License 2.0" in html)
ok("About opens licenses, privacy policy and agreement",
   all(hasattr(about, b) for b in ("btn_licenses", "btn_privacy", "btn_terms")))
help_menu = [a.text().replace("&", "") for m in win.menuBar().actions() if m.text().replace("&", "") == "Help"
             for a in m.menu().actions()]
ok("Help lists Licenses, Privacy policy, End user agreement",
   all(x in help_menu for x in ("Licenses…", "Privacy policy", "End user agreement")), str(help_menu))
lic = mw.LicensesDialog(win)
tabs = [lic.findChild(mw.QTabWidget).tabText(i) for i in range(lic.findChild(mw.QTabWidget).count())]
ok("Licenses shows the notices and the Apache license", tabs == ["Third-party notices", "Playlist Flow (Apache-2.0)"])

print("3. disconnect")


def playlist(name):
    win.store.save(name, [Track(title="Synthetic Song", artist="Synthetic Artist",
                                uri="spotify:track:SYNTHETIC0")], auto=False)
    win.store.save(name, [Track(title="Synthetic Song", artist="Synthetic Artist")], auto=True)


playlist("Sample Set")
win.store.cache_put(Track(title="T", artist="A", uri="spotify:track:SYNTH", bpm=120, key="8A"))
(STORE / "notes.txt").write_text("not ours", encoding="utf-8")
(STORE / "other.json").write_text(json.dumps({"something": "else"}), encoding="utf-8")
before = sorted(x.name for x in STORE.iterdir())
real_exec = mw.DisconnectDialog.exec


def answer(tick, accept=True):
    def ex(self):
        ok("delete box starts unticked", not self.delete_box.isChecked())
        self.delete_box.setChecked(tick)
        return QDialog.Accepted if accept else QDialog.Rejected
    return ex


win.prefs.refresh_token = "synthetic-refresh-token"
win.auth._access, win.auth._expires = "synthetic-access", 9e12
win.sp_list.addItems(["Synthetic list A", "Synthetic list B"])
mw.DisconnectDialog.exec = answer(False, accept=False)
win.disconnect_spotify()
ok("Cancel changes nothing", win.prefs.refresh_token == "synthetic-refresh-token" and win.sp_list.count() == 2)
mw.DisconnectDialog.exec = answer(False)
win.disconnect_spotify()
ok("disconnect removes the sign-in from settings", Prefs().refresh_token == "")
ok("and from memory", win.auth._access == "" and not win.auth.authorised)
ok("and the Spotify account data on screen", win.sp_list.count() == 0)
ok("playlists kept when the box is not ticked", sorted(x.name for x in STORE.iterdir()) == before, str(before))
win.prefs.refresh_token = "synthetic-refresh-token"
mw.DisconnectDialog.exec = answer(True)
win.disconnect_spotify()
after = sorted(x.name for x in STORE.iterdir())
ok("ticked: Playlist Flow's files deleted, others left", after == ["notes.txt", "other.json"], str(after))
ok("ticked: the folder itself stays", STORE.is_dir())
ok("ticked: the sign-in is gone too", Prefs().refresh_token == "")
mw.DisconnectDialog.exec = real_exec
from playlistflow.settings import SettingsDialog
real_s = SettingsDialog.exec
SettingsDialog.exec = lambda self: (self.btn_disconnect.click(), self.result())[1]
called = []
win.disconnect_spotify = lambda: called.append(1)
win.open_settings()
ok("Settings > Disconnect Spotify starts it", called == [1])
SettingsDialog.exec = real_s

win._dirty = False
win.close()
shutil.rmtree(TMP, ignore_errors=True)
bad = [n for n, g in RESULTS if not g]
print(f"\n{len(RESULTS) - len(bad)} of {len(RESULTS)} passed")
print("FAILED: " + ", ".join(bad) if bad else "AGREEMENT TESTS PASSED")
sys.stdout.flush()
os._exit(1 if bad else 0)
