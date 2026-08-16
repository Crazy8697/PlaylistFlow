"""Can we reorder a playlist through the API?

Moves track 1 to position 2 on 'Ruin', verifies, then puts it back and verifies
again. Aborts before touching anything if the order does not read back cleanly.
"""

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
PID = "1yVtQ4qDn6bMPd2PPr7Tmd"


def first_names(n=4):
    r = requests.get(f"{API}/playlists/{PID}/items",
                     headers=H, params={"limit": n}, timeout=25)
    if r.status_code != 200:
        print(f"  read failed [{r.status_code}] {r.text[:160]}")
        return None
    out = []
    for e in r.json().get("items", []):
        t = e.get("item") or e.get("track") or {}
        out.append(t.get("name", "?"))
    return out


def snapshot():
    r = requests.get(f"{API}/playlists/{PID}", headers=H,
                     params={"fields": "snapshot_id"}, timeout=25)
    return r.json().get("snapshot_id", "") if r.status_code == 200 else ""


def reorder(start, insert_before, path):
    body = {"range_start": start, "insert_before": insert_before,
            "range_length": 1}
    r = requests.put(f"{API}/playlists/{PID}/{path}", headers=H,
                     json=body, timeout=25)
    return r


before = first_names()
print("before      :", before)
if not before:
    raise SystemExit("cannot read the playlist — aborting without writing")
print("snapshot    :", snapshot()[:24], "\n")

# Which path does the write live on after the February 2026 rename?
for path in ("items", "tracks"):
    r = reorder(0, 2, path)
    print(f"PUT /{path:<7} -> [{r.status_code}] {r.text[:200]}")
    if r.status_code in (200, 201):
        print("\nafter move  :", first_names())
        back = reorder(1, 0, path)
        print(f"move back   -> [{back.status_code}] {back.text[:120]}")
        print("restored    :", first_names())
        final = first_names()
        print("\nmatches original:", final == before)
        break
else:
    print("\nno write path worked — playlist untouched")
