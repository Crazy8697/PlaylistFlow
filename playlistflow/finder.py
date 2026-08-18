"""Bulk track resolver — plain-text song list to Spotify track URIs.

Resolving titles to URIs by hand is the bottleneck this removes. A web search
returns four or five track IDs for the same song (original master, re-release,
regional variant, live cut, "Revisited") with nothing to tell them apart. The
Search API returns album, release year and duration alongside each candidate,
which is what makes the choice decidable.

Lines arrive as "Title Artist" with no delimiter, multi-word artists, and titles
like "5 to 9" and "23". There is no reliable way to split that, so we do not try:
the whole line goes out as a free-text query and Spotify's own relevance ranking
does the work. Field filters are a fallback for the zero-result case only.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QThread, Signal

from .providers import Spotify, ProviderError, RateLimited

# Pacing. Spotify's limit is a rolling window and the numbers are undocumented,
# so this is deliberately gentle rather than tuned — 40 lines still finishes in
# well under ten seconds.
GAP_S = 0.10

# A track name carrying any of these is never auto-accepted, however confident
# the match looks. "feat." is here on purpose: a featured-artist credit is often
# a different release from the album cut.
VERSION_MARKERS = (
    "live", "acoustic", "remix", "remaster", "remastered", "revisited",
    "demo", "version", "edit", "stripped", "sped up", "slowed", "radio",
    "single version", "re-record", "taylor's version", "instrumental",
    "session", "sessions", "feat.",
)

# NOTE: Spotify's search response carries no "popularity" field for this app —
# the key is absent from the track objects, not zero. The handoff's planned
# auto-accept test (top popularity clearing the runner-up by a margin) can never
# fire, so decisiveness is measured on fields that are actually returned:
# the track name and the credited artists.


# --------------------------------------------------------------------------
# Normalising
# --------------------------------------------------------------------------

def norm(s: str) -> str:
    """Fold a string down to comparable tokens.

    Strips accents, unifies smart quotes with straight ones (a pasted list and
    Spotify's metadata disagree about "Ragin'"), spells out "&", and drops the
    rest of the punctuation. Both sides of every comparison go through this.
    """
    s = (s or "").lower()
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("&", " and ")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def has_version_marker(name: str) -> bool:
    n = norm(name)
    for m in VERSION_MARKERS:
        # norm() strips the dot from "feat." and the hyphen from "re-record",
        # so the needle has to be folded the same way as the haystack.
        needle = norm(m)
        if needle and needle in n:
            return True
    return False


def fmt_duration(ms: int) -> str:
    if not ms:
        return "—"
    total = int(round(ms / 1000.0))
    return f"{total // 60}:{total % 60:02d}"


# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------

@dataclass
class Line:
    """One input line, plus whatever structure we could get out of it."""
    raw: str
    title: str = ""          # only set when a delimiter made it unambiguous
    artist: str = ""
    explicit: bool = False   # a tab or " - " told us where the split is
    dup_of: Optional[int] = None   # index of the earlier identical line


def parse_lines(text: str) -> list[Line]:
    """Blank lines vanish; exact repeats are flagged, not resolved twice."""
    out: list[Line] = []
    seen: dict[str, int] = {}
    for raw in (text or "").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        line = Line(raw=raw)
        if "\t" in raw:
            a, _, b = raw.partition("\t")
            line.title, line.artist, line.explicit = a.strip(), b.strip(), True
        elif " - " in raw:
            a, _, b = raw.partition(" - ")
            line.title, line.artist, line.explicit = a.strip(), b.strip(), True
        key = norm(raw)
        if key in seen:
            line.dup_of = seen[key]
        else:
            seen[key] = len(out)
        out.append(line)
    return out


# --------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------

@dataclass
class Candidate:
    uri: str
    name: str
    artists: str
    album: str
    year: str
    duration_ms: int
    popularity: int = 0   # absent from search results; kept for display only
    isrc: str = ""

    @property
    def duration(self) -> str:
        return fmt_duration(self.duration_ms)

    @staticmethod
    def from_json(t: dict) -> "Candidate":
        album = t.get("album") or {}
        return Candidate(
            uri=t.get("uri", ""),
            name=t.get("name", ""),
            artists=", ".join(a.get("name", "") for a in (t.get("artists") or [])),
            album=album.get("name", ""),
            year=(album.get("release_date") or "")[:4],
            duration_ms=t.get("duration_ms") or 0,
            popularity=t.get("popularity") or 0,
            isrc=((t.get("external_ids") or {}).get("isrc") or ""),
        )


AUTO, REVIEW, NOTFOUND, DUP = "auto", "review", "notfound", "dup"


@dataclass
class Result:
    line: Line
    status: str = REVIEW
    candidates: list = field(default_factory=list)
    chosen: int = -1          # index into candidates; -1 means nothing picked
    skip: bool = False
    note: str = ""

    @property
    def pick(self) -> Optional[Candidate]:
        if self.skip or self.chosen < 0 or self.chosen >= len(self.candidates):
            return None
        return self.candidates[self.chosen]


def leads_line(line_norm: str, name: str) -> bool:
    """Does `name` start the line, ending on a word boundary?

    A bare startswith() matches mid-token: the track "zzz" would "lead" the line
    "zzzz nonexistent track", which is how a nonsense line acquired a confident
    match. The trailing space is the whole point.
    """
    n = norm(name)
    if not n:
        return False
    return line_norm == n or line_norm.startswith(n + " ")


def artist_named(line_norm: str, cand) -> bool:
    """Is any credited artist actually mentioned in the line the user typed?

    This is the outlier check. A genre-consensus test was the obvious idea, but
    Spotify returns no genres at all for this app (the artist object's `genres`
    is empty even for Zach Bryan and Eric Church), so there is nothing to take a
    majority of. Artist agreement catches the same mistakes more directly:
    "Linger Royel Otis" resolving to The Cranberries fails this instantly.
    """
    for a in (cand.artists or "").split(","):
        a = norm(a)
        if a and a in line_norm:
            return True
    return False


def rank(line_norm: str, cands: list) -> list:
    """Float candidates whose artist the user actually named to the top.

    Stable, so Spotify's own relevance ordering survives within each group.
    Without this the default selection on a review row can be a cover by an
    unrelated artist that merely ranked well.
    """
    named = [c for c in cands if artist_named(line_norm, c)]
    rest = [c for c in cands if c not in named]
    return named + rest


def consumes_line(line_norm: str, cand) -> bool:
    """True when name + credited artist account for the WHOLE line.

    This is the replacement for the popularity test. "Kate McCannon Colter Wall"
    is consumed exactly by name "Kate McCannon" + artist "Colter Wall", while the
    same-titled track by Dexter and The Moonrocks leaves "colter wall" unmatched.
    That is the distinction popularity was supposed to draw, done on fields that
    are actually present in the response.
    """
    n = norm(cand.name)
    if not leads_line(line_norm, cand.name):
        return False
    rest = line_norm[len(n):].strip()
    if not rest:
        return False        # nothing left to identify an artist with
    if norm(cand.artists) == rest:
        return True
    # A line naming only the lead artist still counts.
    return any(norm(a) == rest for a in cand.artists.split(","))


def classify(line: Line, cands: list) -> Result:
    """Decide whether the top hit can be taken silently.

    Auto-accept needs all three: the top result is the only one that accounts
    for the whole line, the title leads the line, and the name carries no
    version marker. Anything else goes to review — a wrong silent pick is far
    more expensive than a row the user glances at.
    """
    if not cands:
        return Result(line=line, status=NOTFOUND, note="no results")

    q = norm(line.title if line.explicit else line.raw)
    cands = rank(q, cands)
    top = cands[0]
    leads = leads_line(q, top.name)
    marker = has_version_marker(top.name)

    if line.explicit:
        # The user drew the boundary, so there is no whole-line to consume.
        matches = [c for c in cands
                   if norm(c.name) == norm(line.title)
                   and norm(line.artist) in norm(c.artists)]
    else:
        matches = [c for c in cands if consumes_line(q, c)]

    decisive = len(cands) == 1 or (len(matches) == 1 and matches[0] is top)

    # Most "ambiguity" is one recording listed on several albums — the original,
    # a compilation, a re-release. Measured on the real list, 7 of 8 ambiguous
    # lines were a single ISRC across every plausible hit, at identical
    # duration. Those are the same audio, so there is nothing to choose between
    # and asking the user to choose is noise. Take the earliest release, which
    # is the original album rather than whatever compilation ranked well.
    same_recording = False
    if not decisive and len(matches) > 1:
        isrcs = {c.isrc for c in matches}
        if len(isrcs) == 1 and "" not in isrcs:
            same_recording = True
            matches = sorted(matches, key=lambda c: (c.year or "9999"))
            top = matches[0]
            cands = [top] + [c for c in cands if c is not top]
            decisive = True

    named = artist_named(q, top)

    if leads and decisive and not marker and named:
        return Result(line=line, status=AUTO, candidates=cands, chosen=0)

    why = []
    if not named:
        why.append("ARTIST MISMATCH — you didn't name %s" % (top.artists or "them"))
    if not leads:
        why.append("title doesn't lead the line")
    if not decisive:
        why.append("more than one plausible match" if len(matches) > 1
                   else "no clean artist match")
    if marker:
        why.append("version marker")

    # Search answers a nonsense line with a fuzzy match rather than nothing, so
    # a zero-result NOTFOUND is rare. When neither the title nor the artist ties
    # the top hit to the line there is no evidence at all, and pre-selecting it
    # would slide a junk URI into the block unnoticed. Select nothing instead
    # and make the user choose.
    evidence = leads or named
    if not evidence:
        why.insert(0, "nothing here matches your line — pick one or skip")

    return Result(line=line, status=REVIEW, candidates=cands,
                  chosen=0 if evidence else -1, note=", ".join(why))


# --------------------------------------------------------------------------
# Query building
# --------------------------------------------------------------------------

def primary_query(line: Line) -> str:
    if line.explicit:
        return 'track:"%s" artist:"%s"' % (line.title, line.artist)
    return line.raw


def fallback_queries(line: Line) -> list:
    """Only reached when the free-text pass found nothing.

    Peel 1, 2 then 3 trailing tokens off as the artist. Stop at the first split
    that returns anything — no scoring, the review table sorts it out.
    """
    if line.explicit:
        return []
    toks = line.raw.split()
    out = []
    for n in (1, 2, 3):
        if len(toks) <= n:
            break
        title = " ".join(toks[:-n])
        artist = " ".join(toks[-n:])
        out.append('track:"%s" artist:"%s"' % (title, artist))
    return out


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------

class SearchWorker(QThread):
    """Sequential, paced, cancellable.

    Not a thread pool: parallel searches are the fastest way to earn a 429, and
    the whole batch is under ten seconds anyway.
    """

    resolved = Signal(int, object)      # line index, Result
    progress = Signal(int, int, str)    # done, total, current line
    message = Signal(str)
    done = Signal()

    def __init__(self, sp: Spotify, lines: list, parent=None):
        super().__init__(parent)
        self.sp = sp
        self.lines = lines
        self._stop = False

    def stop(self):
        self._stop = True

    def _wait(self, seconds: float) -> bool:
        """Sleep in slices so cancelling stays responsive during a 429 hold."""
        end = time.time() + seconds
        while time.time() < end:
            if self._stop:
                return False
            time.sleep(min(0.1, max(0.0, end - time.time())))
        return not self._stop

    def _search(self, q: str) -> list:
        """One query, retrying through rate limits rather than dropping a line."""
        while not self._stop:
            try:
                items = self.sp.search_tracks(q)
            except RateLimited as e:
                self.message.emit("Rate limited — waiting %.0fs" % e.retry_after)
                if not self._wait(e.retry_after):
                    return []
                continue
            except ProviderError as e:
                self.message.emit(str(e))
                return []
            return [Candidate.from_json(t) for t in items if t]
        return []

    def run(self):
        total = len(self.lines)

        for i, line in enumerate(self.lines):
            if self._stop:
                break
            self.progress.emit(i, total, line.raw)

            # A repeat reuses the earlier answer instead of burning a request.
            if line.dup_of is not None:
                self.resolved.emit(i, Result(line=line, status=DUP,
                                             note="same as line %d" % (line.dup_of + 1)))
                continue

            cands = self._search(primary_query(line))
            if not cands:
                for q in fallback_queries(line):
                    if self._stop:
                        break
                    if not self._wait(GAP_S):
                        break
                    cands = self._search(q)
                    if cands:
                        break

            self.resolved.emit(i, classify(line, cands))

            if not self._wait(GAP_S):
                break

        self.progress.emit(total, total, "")
        self.done.emit()
