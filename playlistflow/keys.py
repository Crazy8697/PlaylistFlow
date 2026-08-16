"""Musical key names to Camelot notation, and title cleaning for lookups."""

from __future__ import annotations

import re

# Camelot wheel. Minor keys are the A ring, major keys the B ring.
_MINOR = {
    "G#": "1A", "AB": "1A",
    "D#": "2A", "EB": "2A",
    "A#": "3A", "BB": "3A",
    "F": "4A",
    "C": "5A",
    "G": "6A",
    "D": "7A",
    "A": "8A",
    "E": "9A",
    "B": "10A",
    "F#": "11A", "GB": "11A",
    "C#": "12A", "DB": "12A",
}
_MAJOR = {
    "B": "1B",
    "F#": "2B", "GB": "2B",
    "C#": "3B", "DB": "3B",
    "G#": "4B", "AB": "4B",
    "D#": "5B", "EB": "5B",
    "A#": "6B", "BB": "6B",
    "F": "7B",
    "C": "8B",
    "G": "9B",
    "D": "10B",
    "A": "11B",
    "E": "12B",
}


def to_camelot(text: str) -> str:
    """Accept 'C#m', 'C#-Minor', 'Db major', 'F', '12A' — return Camelot or ''."""
    if not text:
        return ""
    s = str(text).strip()

    # Already Camelot.
    m = re.fullmatch(r"([1-9]|1[0-2])\s*([ABab])", s)
    if m:
        return f"{m.group(1)}{m.group(2).upper()}"

    s = s.replace("♯", "#").replace("♭", "b")
    norm = re.sub(r"[\s\-_]+", " ", s).strip()

    minor = False
    mm = re.search(r"(minor|min|m)$", norm, re.IGNORECASE)
    if re.search(r"\bminor\b|\bmin\b", norm, re.IGNORECASE):
        minor = True
        norm = re.sub(r"\b(minor|min)\b", "", norm, flags=re.IGNORECASE)
    elif re.search(r"\bmajor\b|\bmaj\b", norm, re.IGNORECASE):
        norm = re.sub(r"\b(major|maj)\b", "", norm, flags=re.IGNORECASE)
    elif mm and re.fullmatch(r"[A-Ga-g][#b]?m", norm):
        # Trailing bare 'm' means minor: 'C#m'. A bare letter means major.
        minor = True
        norm = norm[:-1]

    root = norm.strip().upper()
    # Normalise the accidental: 'DB' -> 'Db' handled by the lookup tables' keys.
    m = re.fullmatch(r"([A-G])([#B]?)", root)
    if not m:
        return ""
    root = m.group(1) + m.group(2)
    table = _MINOR if minor else _MAJOR
    return table.get(root, "")


_STRIP_PATTERNS = [
    r"\s*\(feat\.?[^)]*\)",
    r"\s*\[feat\.?[^\]]*\]",
    r"\s*\(with[^)]*\)",
    r"\s*-\s*(remaster(ed)?|radio edit|single version|album version)\b.*$",
    r"\s*\((remaster(ed)?|radio edit|single version|album version)[^)]*\)",
    r"\s*\(\s*explicit\s*\)",
]


def clean_title(title: str) -> str:
    """Strip the decorations that break a name match. Returns '' if unchanged."""
    out = title or ""
    for pat in _STRIP_PATTERNS:
        out = re.sub(pat, "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out).strip(" -–—")
    return out if out and out.lower() != (title or "").strip().lower() else ""


def primary_artist(artist: str) -> str:
    """First credited artist only — multi-artist strings often fail lookups."""
    if not artist:
        return ""
    first = re.split(r"\s*(?:,|&|\bfeat\.?\b|\bft\.?\b|\bx\b|\bwith\b)\s*",
                     artist, maxsplit=1, flags=re.IGNORECASE)[0]
    return first.strip()
