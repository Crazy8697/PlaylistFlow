import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""Re-ask FreqBlog for the tracks that missed, now that time has passed."""

import json
import sys
from pathlib import Path

from playlistflow.config import load_env
from playlistflow.providers import FreqBlog, ProviderError
from playlistflow.domain import Track

store = Path(sys.argv[1])
data = json.loads((store / "Ruin-auto.json").read_text(encoding="utf-8"))
tracks = [Track.from_dict(d) for d in data["tracks"]]
missing = [t for t in tracks if not t.resolved]
print(f"retrying {len(missing)} unresolved tracks\n")

fb = FreqBlog(load_env().get("FREQBLOG_API_KEY", ""))

payload = []
for t in missing:
    item = {"track": t.title}
    if t.artist:
        item["artist"] = t.artist
    if t.isrc:
        item["isrc"] = t.isrc
    payload.append(item)

hit = pend = miss = 0
for start in range(0, len(payload), 50):
    try:
        rows = fb.bulk(payload[start:start + 50])
    except ProviderError as e:
        print("FAILED:", e)
        raise SystemExit(1)
    for t, row in zip(missing[start:start + 50], rows):
        f = FreqBlog.features_from_row(row)
        if f.pending:
            pend += 1
            state = "PENDING"
        elif f.bpm or f.camelot:
            hit += 1
            state = f"bpm={f.bpm} {f.camelot}"
        else:
            miss += 1
            state = "MISS"
        print(f"  {t.artist[:20]:<20} {t.title[:30]:<30} {state}")

print(f"\nresolved now: {hit}   still pending: {pend}   terminal miss: {miss}")
