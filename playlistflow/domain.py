"""Core domain logic — ported verbatim from playlist-flow.html.

The thresholds in this module were tuned by ear. Do not adjust them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional

# 12 hues, one per Camelot wheel position. Matches Mixed In Key / Serato.
HUE = [
    "#E8544F", "#E87A3E", "#E8A93E", "#D9CE45",
    "#A8C94A", "#5FBF6B", "#3FBFA8", "#3FA8D9",
    "#4A7FD9", "#6B5FD9", "#9B54D9", "#D94FA8",
]

KEY_RE = re.compile(r"^([1-9]|1[0-2])[AB]$")

# Seam relationship colours
C_OK = "#5FBF6B"
C_WARN = "#E8A93E"
C_BAD = "#E8544F"

# Confidence floors. The two fields are on different scales:
#   key_confidence  0..1        (Essentia key extractor)
#   bpm_confidence  0..~5.3     (Essentia rhythm extractor; <1.5 is shaky)
KEY_CONF_FLOOR = 0.70
BPM_CONF_FLOOR = 1.50


def valid_key(key: str) -> bool:
    return bool(KEY_RE.match((key or "").strip().upper()))


@dataclass
class Track:
    title: str = ""
    artist: str = ""
    bpm: float = 0.0
    key: str = ""
    uri: str = ""
    # provenance
    source: str = ""            # "freqblog" | "manual" | "spotify" | ""
    bpm_conf: Optional[float] = None
    key_conf: Optional[float] = None
    manual: bool = False        # a manual value always wins over a later fetch
    isrc: str = ""
    duration_ms: int = 0        # needed to cue the last N seconds of a track

    @property
    def n(self) -> int:
        """Wheel position 1-12. Zero when the key is unset/invalid."""
        m = KEY_RE.match((self.key or "").strip().upper())
        return int(m.group(1)) if m else 0

    @property
    def letter(self) -> str:
        k = (self.key or "").strip().upper()
        return k[-1] if KEY_RE.match(k) else ""

    @property
    def resolved(self) -> bool:
        """True when this row has usable BPM and key."""
        return self.bpm > 0 and self.n > 0

    @property
    def low_confidence(self) -> bool:
        """Worth a second look. A manual value is the user's own call, never flagged."""
        if self.manual:
            return False
        if self.key_conf is not None and self.key_conf < KEY_CONF_FLOOR:
            return True
        if self.bpm_conf is not None and self.bpm_conf < BPM_CONF_FLOOR:
            return True
        return False

    @property
    def unverified(self) -> bool:
        """Came from a web search rather than an analysis API. Measured against
        known-good values these keys were right roughly 4 times in 10, so they
        are shown as provisional rather than blended in with the rest."""
        return self.source.startswith("web") and not self.manual

    def colour(self) -> str:
        return HUE[self.n - 1] if self.n else "#3D444F"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Track":
        known = {f for f in Track.__dataclass_fields__}
        return Track(**{k: v for k, v in d.items() if k in known})


def felt_bpm(bpm: float) -> float:
    """Half-time detection.

    In trap-influenced music the snare lands on beat 3 rather than 2 and 4,
    so a track reported at 140 feels like 70.
    """
    return bpm / 2 if bpm >= 130 else bpm


def key_gap(a: Track, b: Track) -> float:
    """Distance between two keys on the Camelot wheel.

    0    same key
    1    one step
    1.5  diagonal  — one step plus a letter flip. Not on the standard
         compatibility list, but a deliberate favourite. Its own category.
    2    two steps
    >2   far apart
    """
    d = min((a.n - b.n) % 12, (b.n - a.n) % 12)
    if a.letter == b.letter:
        return d
    return 0 if d == 0 else (1.5 if d == 1 else d + 6)


@dataclass
class Rel:
    txt: str
    colour: str
    bad: bool


def key_label(g: float) -> Rel:
    if g == 0:
        return Rel("same key", C_OK, False)
    if g == 1:
        return Rel("one step", C_OK, False)
    if g == 1.5:
        return Rel("diagonal", C_WARN, False)
    if g == 2:
        return Rel("two steps", C_WARN, True)
    return Rel("far apart", C_BAD, True)


def tempo_rel(a: Track, b: Track) -> Rel:
    """Always computed on felt BPM, whichever view is displayed."""
    x, y = felt_bpm(a.bpm), felt_bpm(b.bpm)
    if x <= 0 or y <= 0:
        return Rel("—", "#5C636D", False)
    r = max(x, y) / min(x, y)
    if r <= 1.07:
        return Rel("locked", C_OK, False)
    if abs(r - 2) / 2 <= 0.07:
        return Rel("half-time", C_OK, False)
    if r <= 1.20:
        return Rel("drifts", C_WARN, False)
    return Rel("jumps", C_BAD, True)


def seam_key(a: Track, b: Track) -> str:
    """Stable identity for the transition a -> b.

    Keyed on the tracks, not the row number, so an ear-check survives
    reordering elsewhere in the list and correctly disappears the moment a
    different track is dragged in between.
    """
    def one(t: Track) -> str:
        return t.uri or f"{t.artist.strip().lower()}|{t.title.strip().lower()}"
    return one(a) + " >> " + one(b)


@dataclass
class Seam:
    key: Rel
    tempo: Rel
    both: bool
    known: bool = True   # False when either side has no BPM/key yet
    checked: bool = False   # the user listened to this transition and approved it


def seams(tracks: list[Track], approved=None) -> list[Seam]:
    """One seam per adjacent pair. Key and tempo are evaluated independently;
    only 'both off' is a hard warning — one axis off is survivable.

    `approved` is the set of seam_key() ids the user has ear-checked. An
    ear-check is allowed on an unresolved seam too — listening outranks
    numbers that have not arrived yet.
    """
    approved = approved or frozenset()
    out: list[Seam] = []
    for i in range(len(tracks) - 1):
        a, b = tracks[i], tracks[i + 1]
        ok = seam_key(a, b) in approved
        if not (a.resolved and b.resolved):
            out.append(Seam(Rel("—", "#5C636D", False),
                            Rel("—", "#5C636D", False), False, known=False,
                            checked=ok))
            continue
        k = key_label(key_gap(a, b))
        t = tempo_rel(a, b)
        out.append(Seam(k, t, k.bad and t.bad, known=True, checked=ok))
    return out


def summary(tracks: list[Track], approved=None) -> str:
    sm = seams(tracks, approved)
    # A seam nobody can judge yet is not a clean seam.
    judged = [s for s in sm if s.known]
    clean = sum(1 for s in judged if not s.key.bad and not s.tempo.bad)
    both = sum(1 for s in judged if s.both)
    unresolved = sum(1 for t in tracks if not t.resolved)
    bits = [f"{len(tracks)} tracks"]
    # Lead with what is still missing — that is the number being watched while
    # a fetch runs.
    if unresolved:
        bits.append(f"{unresolved} need BPM/key")
    if judged:
        bits += [f"{clean} clean", f"{both} off on both"]
    checked = sum(1 for s in sm if s.checked)
    if checked:
        bits.append(f"{checked} ear-checked")
    return "  ·  ".join(bits)
