import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""What playback options exist: preview clips, or remote-controlling Spotify?"""

import requests

from PySide6.QtCore import QCoreApplication

from playlistflow.config import load_env, Prefs
from playlistflow.auth import SpotifyAuth

app = QCoreApplication([])
app.setOrganizationName("darkrelay")
app.setApplicationName("PlaylistFlow")

auth = SpotifyAuth(load_env().get("SPOTIFY_CLIENT_ID", ""), Prefs())
H = {"Authorization": f"Bearer {auth.access_token()}"}
API = "https://api.spotify.com/v1"

IDS = ["0FJKAzOCba9AX4cVfAudd1",   # LET ME IN
       "2MtieCU5vMqxt6F2GcVPB7",   # Curiosity
       "5TxzZAJPGD1oDMLeyWPKG3"]   # Don't You Dare Look Away

print("=== preview_url (30s clip) ===")
for tid in IDS:
    r = requests.get(f"{API}/tracks/{tid}", headers=H, timeout=25)
    if r.status_code != 200:
        print(f"  [{r.status_code}] {tid}")
        continue
    j = r.json()
    pv = j.get("preview_url")
    print(f"  {j.get('name','?')[:28]:<28} preview_url={'YES ' + pv[:48] if pv else 'None'}")

print("\n=== playback control (needs extra scopes) ===")
for label, path in (("devices", "/me/player/devices"),
                    ("player state", "/me/player"),
                    ("profile", "/me")):
    r = requests.get(f"{API}{path}", headers=H, timeout=25)
    print(f"  [{r.status_code}] {label}: {r.text[:180]}")
