"""Wheel compatibility must agree with the seam scoring in domain.py.

Two independent statements of the same rules would eventually disagree, so this
checks the wheel's "safe" and "diagonal" sets against key_gap directly.
"""

import sys

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from playlistflow.wheel import safe_moves, diagonals
from playlistflow.domain import Track, key_gap, key_label

ok = True


def T(k):
    return Track(title="x", bpm=100, key=k)


print("safe moves must score as gap 0 or 1 (never a problem):")
bad = 0
for n in range(1, 13):
    for letter in "AB":
        src = f"{n}{letter}"
        for dst in safe_moves(n, letter):
            g = key_gap(T(src), T(dst))
            lab = key_label(g)
            if g not in (0, 1) or lab.bad:
                print(f"  {src} -> {dst}: gap={g} ({lab.txt}) UNEXPECTED")
                bad += 1
ok &= bad == 0
print(f"  {24 * 3 - bad}/{24 * 3} safe moves check out")

print("\ndiagonals must all score exactly 1.5:")
bad = 0
for n in range(1, 13):
    for letter in "AB":
        src = f"{n}{letter}"
        for dst in diagonals(n, letter):
            g = key_gap(T(src), T(dst))
            if g != 1.5:
                print(f"  {src} -> {dst}: gap={g} EXPECTED 1.5")
                bad += 1
ok &= bad == 0
print(f"  {24 * 2 - bad}/{24 * 2} diagonals check out")

print("\nsafe and diagonal sets must not overlap:")
overlap = 0
for n in range(1, 13):
    for letter in "AB":
        both = set(safe_moves(n, letter)) & set(diagonals(n, letter))
        if both:
            print(f"  {n}{letter}: {both}")
            overlap += 1
ok &= overlap == 0
print(f"  {'none' if not overlap else f'{overlap} overlapping'}")

print("\nwrapping around 12 -> 1:")
cases = [("12A", "1A", True), ("1A", "12A", True), ("12B", "1A", False),
         ("12A", "11A", True)]
for src, dst, expect_safe in cases:
    n, letter = int(src[:-1]), src[-1]
    is_safe = dst in safe_moves(n, letter)
    good = is_safe == expect_safe
    ok &= good
    print(f"  {src} -> {dst}: safe={is_safe} expected={expect_safe} "
          f"{'ok' if good else 'MISMATCH'}")

print("\n" + ("WHEEL TESTS PASSED" if ok else "WHEEL TESTS FAILED"))
raise SystemExit(0 if ok else 1)
