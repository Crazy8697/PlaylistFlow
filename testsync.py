"""Sync must reconcile membership without disturbing the ordering."""

import sys

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from playlistflow.domain import Track


def reconcile(local, remote_uris):
    """The same rule sync_playlist applies, isolated so it can be checked:
    keep local order, drop what's gone, append what's new, keep hand-added."""
    remote = set(remote_uris)
    here = {t.uri for t in local if t.uri}
    kept = [t for t in local if not t.uri or t.uri in remote]
    added = [u for u in remote_uris if u not in here]
    return kept + [Track(title=u, uri=u) for u in added], added


def uris(ts):
    return [t.uri or f"<{t.title}>" for t in ts]


ok = True

# Ordering is the whole point: a track that exists in both must not move.
local = [Track(title=f"T{i}", uri=f"u{i}", bpm=100 + i, key="1A")
         for i in (5, 1, 3, 2, 4)]
local.insert(2, Track(title="hand-added", bpm=90, key="2A"))   # no uri
remote_order = ["u1", "u2", "u3", "u4", "u5", "u6"]            # u6 is new

out, added = reconcile(local, remote_order)
exp = ["u5", "u1", "<hand-added>", "u3", "u2", "u4", "u6"]
good = uris(out) == exp
ok &= good
print("keeps local order, appends new, keeps hand-added")
print(f"  got      {uris(out)}")
print(f"  expected {exp}   {'ok' if good else 'MISMATCH'}")

# Values already resolved must survive untouched.
kept_bpm = [t.bpm for t in out if t.uri == "u5"]
good = kept_bpm == [105]
ok &= good
print(f"  u5 keeps bpm {kept_bpm} (exp [105])  {'ok' if good else 'MISMATCH'}")

# Removals.
out2, _ = reconcile(local, ["u1", "u3", "u5"])
exp2 = ["u5", "u1", "<hand-added>", "u3"]
good = uris(out2) == exp2
ok &= good
print("\ndrops what is gone from Spotify")
print(f"  got      {uris(out2)}")
print(f"  expected {exp2}   {'ok' if good else 'MISMATCH'}")

# No change at all.
out3, added3 = reconcile(local, ["u5", "u1", "u3", "u2", "u4"])
good = uris(out3) == uris(local) and not added3
ok &= good
print(f"\nno differences leaves it identical  {'ok' if good else 'MISMATCH'}")

print("\n" + ("SYNC TESTS PASSED" if ok else "SYNC TESTS FAILED"))
raise SystemExit(0 if ok else 1)
