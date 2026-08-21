import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""Sanity check of the domain port against the prototype's behaviour."""

from playlistflow.domain import Track, key_gap, key_label, tempo_rel, felt_bpm, seams


def T(k, b=100.0):
    return Track(title="x", bpm=b, key=k)


ok = True

print("key_gap:")
cases = [
    ("12B", "12B", 0),    # same key
    ("12B", "1B", 1),     # one step, wraps 12 -> 1
    ("12A", "11A", 1),
    ("12B", "12A", 0),    # letter flip, same position
    ("12B", "1A", 1.5),   # diagonal
    ("12B", "11A", 1.5),  # diagonal the other way
    ("1A", "3A", 2),      # two steps
    ("1A", "7A", 6),      # far apart
    ("1A", "4B", 9),      # 3 steps + flip -> 3 + 6
]
for a, b, exp in cases:
    g = key_gap(T(a), T(b))
    good = g == exp
    ok &= good
    print(f"  {a:>4} -> {b:<4} gap={g:<4} expected={exp:<4} "
          f"{'ok' if good else 'MISMATCH'}  ({key_label(g).txt})")

print("\nfelt_bpm:")
for b, exp in ((140, 70), (130, 65), (129.9, 129.9), (100, 100), (60, 60)):
    got = felt_bpm(b)
    good = abs(got - exp) < 1e-9
    ok &= good
    print(f"  felt({b}) = {got}  {'ok' if good else 'MISMATCH'}")

print("\ntempo_rel (on felt bpm):")
for x, y, exp in (
    (100, 105, "locked"),
    (140, 70, "locked"),       # both felt to 70
    (100, 115, "drifts"),
    (100, 140, "jumps"),       # 140 felts to 70 -> ratio 1.43
    (172, 86, "locked"),       # 172 felts to 86
    # The Addict case. 129.43 sits just under the felt cutoff so it is not
    # halved, but the ratio against a 65 track is 1.99 — the half-time branch
    # catches it and the seam reads clean.
    (129.43, 65, "half-time"),
):
    got = tempo_rel(T("1A", x), T("1A", y)).txt
    good = got == exp
    ok &= good
    print(f"  {x} vs {y}: {got:<10} expected={exp:<10} {'ok' if good else 'MISMATCH'}")

print("\nseam 'both off' only when key AND tempo are both bad:")
pairs = [
    ("1A", 100, "3A", 100, False),   # two steps (bad key), locked tempo
    ("1A", 100, "1A", 140, False),   # same key, jumping tempo
    ("1A", 100, "7A", 140, True),    # far apart + jumps
    ("12B", 100, "1A", 140, False),  # diagonal is never a problem
]
for ka, ba, kb, bb, exp in pairs:
    s = seams([T(ka, ba), T(kb, bb)])[0]
    good = s.both == exp
    ok &= good
    print(f"  {ka}@{ba} -> {kb}@{bb}: key={s.key.txt:<10} tempo={s.tempo.txt:<10} "
          f"both={s.both} expected={exp} {'ok' if good else 'MISMATCH'}")

print("\nunresolved rows never produce a seam warning:")
s = seams([Track(title="a"), T("1A", 100)])[0]
good = not s.both
ok &= good
print(f"  both={s.both} {'ok' if good else 'MISMATCH'}")

print("\n" + ("ALL DOMAIN TESTS PASSED" if ok else "DOMAIN TESTS FAILED"))
raise SystemExit(0 if ok else 1)
