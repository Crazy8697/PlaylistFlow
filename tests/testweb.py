import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""Measure Brave lookup against the 35 tracks FreqBlog gave up on.

Precision matters more than recall here: a wrong value is worse than no value.
The first block are controls with values we already know from FreqBlog.
"""

import json
import sys
from pathlib import Path

from playlistflow.config import load_env
from playlistflow.websearch import BraveLookup
from playlistflow.domain import Track

bl = BraveLookup(load_env().get("BRAVE_API_KEY", ""))
if not bl.api_key:
    raise SystemExit("Set BRAVE_API_KEY in .env first.")

print("=== controls (we know the answer) ===")
CONTROLS = [
    ("Devil in Her Eyes", "Bryce Savage", "110 / 12B"),
    ("Headstrong", "Dracu", "92 / 9A  (Trapt's 185 would be a false match)"),
    ("Pretty Lady Heart Out", "Sir Silly", "122 / 10A"),
    ("Believe It", "Jared Benjamin", "172 / 12A"),
]
for title, artist, known in CONTROLS:
    h = bl.lookup(title, artist)
    print(f"  {artist} — {title}")
    print(f"     known {known}")
    print(f"     brave bpm={h.bpm or '-'} key={h.camelot or '-'} "
          f"agreed={h.agreed} sources={h.sources}")

store = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if not store:
    raise SystemExit(0)

data = json.loads((store / "Ruin-auto.json").read_text(encoding="utf-8"))
tracks = [Track.from_dict(d) for d in data["tracks"]]
missing = [t for t in tracks if not t.resolved]

print(f"\n=== {len(missing)} tracks FreqBlog could not resolve ===")
got = both = 0
for t in missing:
    h = bl.lookup(t.title, t.artist)
    if h.bpm or h.camelot:
        got += 1
        if h.bpm and h.camelot:
            both += 1
        flag = "AGREED" if h.agreed else "single"
        print(f"  HIT  {t.artist[:18]:<18} {t.title[:28]:<28} "
              f"bpm={h.bpm or '-':<6} key={h.camelot or '-':<4} {flag:<7} {h.sources}")
    else:
        print(f"  --   {t.artist[:18]:<18} {t.title[:28]:<28}")

print(f"\nfound something for {got} of {len(missing)}   (both bpm+key: {both})")
