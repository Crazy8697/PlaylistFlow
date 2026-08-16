"""End-to-end check of the network layer through the real app code.

Usage:  python inttest.py [<spotify playlist url or id>]
Keeps FreqBlog calls to a handful so it barely touches the monthly quota.
"""

import sys

from PySide6.QtCore import QCoreApplication  # QSettings needs an app identity

from playlistflow.config import load_env, Prefs
from playlistflow.providers import Spotify, FreqBlog, ProviderError
from playlistflow.auth import SpotifyAuth, AuthError
from playlistflow.domain import Track, valid_key

_app = QCoreApplication([])
_app.setOrganizationName("darkrelay")
_app.setApplicationName("PlaylistFlow")

env = load_env()
print("env loaded:",
      {k: (v[:8] + "…" if v else "MISSING") for k, v in env.items()})

auth = SpotifyAuth(env.get("SPOTIFY_CLIENT_ID", ""), Prefs())
print("spotify signed in:", auth.authorised)
sp = Spotify(auth)
fb = FreqBlog(env.get("FREQBLOG_API_KEY", ""))

target = sys.argv[1] if len(sys.argv) > 1 else None

print("\n--- Spotify ---")
if target:
    try:
        pid = Spotify.playlist_id(target)
        name = sp.playlist_name(pid)
        rows = sp.playlist_tracks(pid)
        print(f"  playlist '{name}' -> {len(rows)} tracks")
        for r in rows[:5]:
            print(f"    {r.artist} — {r.title}  isrc={r.isrc or '-'}  {r.uri}")
        sample = [Track(title=r.title, artist=r.artist, uri=r.uri, isrc=r.isrc)
                  for r in rows[:6]]
    except (ProviderError, AuthError) as e:
        print("  FAILED:", e)
        sample = []
else:
    print("  no playlist given — skipping (pass a URL to test this path)")
    sample = [
        Track(title="Devil in Her Eyes", artist="Bryce Savage"),
        Track(title="OUTLAW", artist="Ryan Jesse"),
        Track(title="Headstrong", artist="Dracu"),
    ]

print("\n--- FreqBlog bulk ---")
if sample:
    payload = []
    for t in sample:
        item = {"track": t.title}
        if t.artist:
            item["artist"] = t.artist
        if t.isrc:
            item["isrc"] = t.isrc
        payload.append(item)
    try:
        rows = fb.bulk(payload)
        print(f"  {len(rows)} rows back")
        for t, row in zip(sample, rows):
            f = FreqBlog.features_from_row(row)
            if f.pending:
                state = "PENDING (queued for analysis)"
            elif f.terminal:
                state = "MISS (terminal)"
            else:
                ok = "ok" if valid_key(f.camelot) else "BAD KEY"
                state = (f"bpm={f.bpm} camelot={f.camelot} [{ok}] "
                         f"conf={f.bpm_conf}/{f.key_conf}")
            print(f"    {t.artist} — {t.title}: {state}")
    except ProviderError as e:
        print("  FAILED:", e)

print("\ndone")
