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


# Where the felt-BPM fold sits. A fixed fold always has a cliff, so it is a
# Display setting now (default 165 -- the top of the range a listener can
# track as a pulse). Display/sort only; classification is on raw BPM.
FELT_FOLD = 165

# Half-width of the clean windows, multiplicative. A Display setting:
# tight 0.03 for blended sets, normal 0.06, loose 0.08 for cut sets.
TEMPO_TOL = 0.06

# Whether both-axes-off is computed and shown at all. A Display setting.
WARN_BOTH = True


def set_display(felt_fold: int = None, tolerance: float = None,
                warn_both: bool = None) -> None:
    """Apply Display settings. Module-level on purpose: every classification
    site reads the same values, and the caller re-runs seams() after."""
    global FELT_FOLD, TEMPO_TOL, WARN_BOTH
    if felt_fold is not None:
        FELT_FOLD = felt_fold
    if tolerance is not None:
        TEMPO_TOL = tolerance
    if warn_both is not None:
        WARN_BOTH = warn_both


def felt_bpm(bpm: float) -> float:
    """Half-time detection.

    In trap-influenced music the snare lands on beat 3 rather than 2 and 4,
    so a fast-count track feels like half its reported tempo.
    """
    return bpm / 2 if bpm >= FELT_FOLD else bpm


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


TEMPO_COLORS = {
    "holds":   "#4ADE80",   # green
    "doubles": "#4ADE80",   # green
    "halves":  "#4ADE80",   # green
    "shifts":  "#2DD4BF",   # teal — valid relationship, just not seamless
    "drifts":  "#FBBF24",   # amber
    "jumps":   "#F87171",   # red
}

# What the header's "clean" counter counts on the tempo axis.
CLEAN_TEMPO = frozenset({"holds", "doubles", "halves", "shifts"})


def classify_tempo(current_bpm: float, next_bpm: float, same_key: bool = False) -> str:
    """
    Classify the tempo relationship between two adjacent tracks.

    Returns one of: holds, doubles, halves, shifts, drifts, jumps

    Clean states:  holds, doubles, halves, shifts
    Warnings:      drifts, jumps

    If same_key is True, a jumps result is downgraded to drifts.
    One axis off is survivable; both axes off breaks the seam.
    """
    if not current_bpm or not next_bpm:
        return "jumps"

    ratio = next_bpm / current_bpm

    # Clean windows, nearest-first. All derived from one tolerance so the
    # presets scale them together; every window is v/(1+t) .. v*(1+t), which
    # makes A->B and B->A agree by construction, holds included.
    t = 1 + TEMPO_TOL
    if (1 / t) <= ratio <= t:
        return "holds"
    if (2 / t) <= ratio <= (2 * t):
        return "doubles"
    if (1 / (2 * t)) <= ratio <= (t / 2):
        return "halves"
    if (1.5 / t) <= ratio <= (1.5 * t):
        return "shifts"
    if (1 / (1.5 * t)) <= ratio <= (t / 1.5):
        return "shifts"

    # Not clean — measure distance to the nearest valid ratio
    valid_ratios = [1.0, 2.0, 0.5, 1.5, 0.667]
    distance = min(abs(ratio - v) / v for v in valid_ratios)

    if distance <= 0.08:
        return "drifts"

    return "drifts" if same_key else "jumps"


def tempo_rel(a: Track, b: Track) -> Rel:
    """Classified on RAW BPM, not felt: doubles/halves detect the octave
    relationship explicitly, and felt-halving would erase the direction the
    labels exist to show. Felt stays a display/sort concern.

    same_key downgrades jumps to drifts — a stretched double in the same key
    holds by ear; the same stretch across a key change does not.
    """
    if a.bpm <= 0 or b.bpm <= 0:
        return Rel("—", "#5C636D", False)
    same_key = a.n > 0 and a.n == b.n and a.letter == b.letter
    label = classify_tempo(a.bpm, b.bpm, same_key=same_key)
    return Rel(label, TEMPO_COLORS[label], label == "jumps")


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
        g = key_gap(a, b)
        k = key_label(g)
        t = tempo_rel(a, b)
        # Both-axes-off: tempo jumps AND the key is worse than two steps.
        # The diagonal (1.5) is a preferred transition, not a degraded one.
        both = WARN_BOTH and t.txt == "jumps" and g > 2
        out.append(Seam(k, t, both, known=True, checked=ok))
    return out


def summary(tracks: list[Track], approved=None) -> str:
    sm = seams(tracks, approved)
    # A seam nobody can judge yet is not a clean seam.
    judged = [s for s in sm if s.known]
    clean = sum(1 for s in judged
                if not s.key.bad and s.tempo.txt in CLEAN_TEMPO)
    both = sum(1 for s in judged if s.both)
    unresolved = sum(1 for t in tracks if not t.resolved)
    # The track count lives with the playlist name in the bottom strip now.
    bits = []
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
