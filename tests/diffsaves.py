import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""Compare the manual save against the auto-save, in order."""

import json
import sys
from pathlib import Path

d = Path(sys.argv[1])
name = sys.argv[2] if len(sys.argv) > 2 else "Ruin"


def load(p):
    j = json.loads(p.read_text(encoding="utf-8"))
    return [f"{t.get('artist','')} — {t.get('title','')}" for t in j["tracks"]], j


man_p, auto_p = d / f"{name}.json", d / f"{name}-auto.json"
man, mj = load(man_p)
auto, aj = load(auto_p)

print(f"manual save : {man_p.name}  {len(man)} tracks")
print(f"auto save   : {auto_p.name}  {len(auto)} tracks")
print(f"same set    : {sorted(man) == sorted(auto)}")
print(f"same order  : {man == auto}")

if man != auto:
    print("\nposition changes (manual -> auto):")
    idx = {t: i for i, t in enumerate(man)}
    moved = 0
    for new_i, t in enumerate(auto):
        old_i = idx.get(t)
        if old_i is None:
            print(f"  {new_i+1:>3}  NEW           {t}")
            moved += 1
        elif old_i != new_i:
            print(f"  {new_i+1:>3}  was {old_i+1:>3}      {t}")
            moved += 1
    print(f"\n{moved} of {len(auto)} tracks sit in a different place")

print("\nfirst 12 of the auto save (what loads):")
for i, t in enumerate(auto[:12], 1):
    print(f"  {i:>2}. {t}")
