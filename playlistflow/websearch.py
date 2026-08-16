"""Brave Search as a last-resort source for BPM and key.

Sites like songbpm.com and chordify.net put the numbers straight into their
page description, so the search index carries them even when the site itself
is unreachable programmatically. TuneBat does not — its values render
client-side, so its snippets are generic boilerplate and never usable.

The danger here is false matches, not missing data. A loose search for
"Headstrong by Dracu" cheerfully returns Trapt's Headstrong at 185 BPM, and
nothing downstream would ever flag it. So every candidate must name BOTH the
exact track and the exact artist before its numbers are accepted, and a value
only one source vouches for is marked low-confidence.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import requests

from .keys import to_camelot

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"

# Sites whose descriptions actually carry the values.
USEFUL = ("songbpm.com", "chordify.net", "gemtracks.com", "musicstax.com",
          "songdata.io", "findsongtempo.com", "tunebat.com")

_BPM_PATTERNS = [
    re.compile(r"tempo of\s*(\d{2,3}(?:\.\d+)?)\s*BPM", re.I),
    re.compile(r"\bbpm\s*[·:\-]?\s*(\d{2,3}(?:\.\d+)?)", re.I),
    re.compile(r"(\d{2,3}(?:\.\d+)?)\s*BPM\b", re.I),
]
_KEY_PATTERNS = [
    re.compile(r"\bkey\s*(?:is\s*in\s*)?[·:\-]?\s*([A-G][#b♯♭]?)\s*"
               r"(major|minor|maj|min|m|ₘ)?\b", re.I),
    re.compile(r"\bkey\s*(?:of|is)\s*([A-G][#b♯♭]?)\s*"
               r"(major|minor|maj|min|m|ₘ)?\b", re.I),
]


def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


@dataclass
class WebHit:
    bpm: float = 0.0
    camelot: str = ""
    sources: list = field(default_factory=list)
    agreed: bool = False        # two or more independent sites matched


class BraveLookup:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._s = requests.Session()
        self._last = 0.0

    def _search(self, q: str, count: int = 8) -> list[dict]:
        if not self.api_key:
            return []
        # Free tier allows one query per second.
        wait = 1.1 - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            r = self._s.get(
                BRAVE_URL,
                headers={"Accept": "application/json",
                         "X-Subscription-Token": self.api_key},
                params={"q": q, "count": count},
                timeout=25,
            )
        except requests.RequestException:
            return []
        finally:
            self._last = time.time()
        if r.status_code != 200:
            return []
        try:
            return (r.json().get("web") or {}).get("results") or []
        except ValueError:
            return []

    @staticmethod
    def _extract(blob: str) -> tuple[float, str]:
        bpm = 0.0
        for pat in _BPM_PATTERNS:
            m = pat.search(blob)
            if m:
                try:
                    v = float(m.group(1))
                except ValueError:
                    continue
                if 40 <= v <= 260:
                    bpm = v
                    break
        cam = ""
        for pat in _KEY_PATTERNS:
            m = pat.search(blob)
            if m:
                root, mode = m.group(1), (m.group(2) or "")
                mode = "minor" if mode.lower() in ("m", "ₘ", "min", "minor") else "major"
                cam = to_camelot(f"{root} {mode}")
                if cam:
                    break
        return bpm, cam

    def lookup(self, title: str, artist: str) -> WebHit:
        """Only accepts results naming this exact track AND this exact artist."""
        hit = WebHit()
        if not self.api_key or not title:
            return hit

        nt, na = _norm(title), _norm(artist)
        if not nt:
            return hit

        found: dict[str, tuple[float, str]] = {}
        for q in (f'"{title}" "{artist}" bpm key' if artist else f'"{title}" bpm key',
                  f'{artist} {title} songbpm bpm key' if artist else f"{title} songbpm"):
            for res in self._search(q):
                url = res.get("url", "")
                host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
                if not any(host.endswith(u) for u in USEFUL):
                    continue
                blob = re.sub(r"<[^>]+>", " ",
                              f"{res.get('title','')} {res.get('description','')}")
                nb = _norm(blob)
                # Both names must be present, or it is a different recording.
                if nt not in nb:
                    continue
                if na and na not in nb:
                    continue
                bpm, cam = self._extract(blob)
                if bpm or cam:
                    prev = found.get(host, (0.0, ""))
                    found[host] = (bpm or prev[0], cam or prev[1])
            if len(found) >= 2:
                break

        if not found:
            return hit

        bpms = [b for b, _ in found.values() if b]
        cams = [c for _, c in found.values() if c]
        if bpms:
            # Prefer a value two sites agree on; otherwise take the first.
            counts = {}
            for b in bpms:
                counts[round(b)] = counts.get(round(b), 0) + 1
            best = max(counts.items(), key=lambda kv: (kv[1], -abs(kv[0] - bpms[0])))
            hit.bpm = float(best[0])
            hit.agreed = best[1] >= 2
        if cams:
            counts = {}
            for c in cams:
                counts[c] = counts.get(c, 0) + 1
            best = max(counts.items(), key=lambda kv: kv[1])
            hit.camelot = best[0]
            hit.agreed = hit.agreed or best[1] >= 2
        hit.sources = sorted(found)
        return hit
