import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""Current state of the saved playlist: what resolved, from where, what's left."""

import json
import sys
from pathlib import Path

from playlistflow.domain import Track

store = Path(sys.argv[1])
name = sys.argv[2] if len(sys.argv) > 2 else "Ruin"
path = store / f"{name}-auto.json"
if not path.exists():
    path = store / f"{name}.json"
data = json.loads(path.read_text(encoding="utf-8"))
tracks = [Track.from_dict(d) for d in data["tracks"]]

resolved = [t for t in tracks if t.resolved]
missing = [t for t in tracks if not t.resolved]

print(f"file      : {path.name}")
print(f"total     : {len(tracks)}")
print(f"resolved  : {len(resolved)}")
print(f"missing   : {len(missing)}")

buckets = {}
for t in resolved:
    src = t.source or "?"
    head = src.split(":")[0]
    buckets[head] = buckets.get(head, 0) + 1
print(f"by source : {buckets}")

unver = [t for t in resolved if t.unverified]
print(f"unverified (web, dashed chip): {len(unver)}")

if missing:
    print("\n--- still need typing ---")
    for t in missing:
        print(f"  {t.artist[:24]:<24} {t.title}")

if unver:
    print("\n--- web-sourced, worth checking ---")
    for t in unver:
        print(f"  {t.artist[:22]:<22} {t.title[:30]:<30} "
              f"{t.bpm:g} / {t.key}   ({t.source})")
