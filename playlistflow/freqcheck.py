"""The FreqBlog key check and the monthly usage line.

Both come from one GET /me/stats call, which FreqBlog confirmed does not count
against the free monthly allowance. Used by the setup wizard, Settings' Test button
and the key-rejected popup's way back to the wizard. It is only ever called because
the user is looking at one of those screens: nothing polls it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .providers import FreqBlog, KeyRejected, ProviderError, Usage

WARN_PCT = 90.0           # at or above this the usage line turns the warning colour
UNAVAILABLE = "Usage unavailable"


@dataclass
class KeyCheck:
    status: str           # "ok" | "rejected" | "offline"
    message: str          # plain text for the user ("rejected": FreqBlog's own words)
    usage: Usage | None = None


def check_key(key: str, client=None) -> KeyCheck:
    """One /me/stats call. Never raises."""
    fb = client or FreqBlog(key)
    if client is not None:
        fb.api_key = key
    try:
        usage = fb.stats()
    except KeyRejected as e:
        detail = str(e).split("rejected the key.", 1)[-1].strip()
        return KeyCheck("rejected", detail or "FreqBlog rejected the key.")
    except ProviderError as e:
        return KeyCheck("offline", f"Couldn't check the key with FreqBlog right now ({e}).")
    except Exception as e:                      # anything at all: said, never raised
        return KeyCheck("offline", f"Couldn't check the key with FreqBlog right now "
                                   f"({type(e).__name__}).")
    return KeyCheck("ok", "FreqBlog accepted the key.", usage)


def reset_text(raw: str) -> str:
    """quota_reset_date, plainly, in local time: "November 1, 2026". A bare date
    stays that date; a timestamp is converted to this PC's time zone first."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        if len(raw) <= 10:
            d = datetime.strptime(raw[:10], "%Y-%m-%d")
        else:
            d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            d = d.astimezone()
    except ValueError:
        return raw
    return f"{d:%B} {d.day}, {d.year}"


def usage_text(u: Usage | None) -> tuple[str, bool]:
    """("X of Y requests used this month, resets <date>", warn). Y is FreqBlog's
    monthly_quota, never a number of our own. warn is True at WARN_PCT or more."""
    if u is None or u.quota <= 0:
        return UNAVAILABLE, False
    pct = u.pct if u.pct else (100.0 * u.used / u.quota)
    text = f"{u.used:,} of {u.quota:,} requests used this month"
    when = reset_text(u.reset)
    if when:
        text += f", resets {when}"
    return text, pct >= WARN_PCT
