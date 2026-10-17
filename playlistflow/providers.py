"""Network clients.

Spotify, playlist/track reads only. Client Credentials, no user login.
           audio_features is dead (403 since 2024-11-27); we never call it.
FreqBlog, BPM and musical key. Returns Camelot directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import html
import threading
import time

import requests

SPOTIFY_API = "https://api.spotify.com/v1"
FREQBLOG_API = "https://api.freqblog.com"

from . import __version__

# FreqBlog asked for this shape so they can spot the program's traffic and help its
# users; built from the real version so it follows releases.
UA = f"PlaylistFlow/{__version__} (+https://darkrelay.net)"


class KeyRejected(RuntimeError):
    """A provider refused the key itself (wrong, revoked or suspended), as opposed
    to a missing track. The window says so once per session, with a way to fix it."""

    def __init__(self, provider: str, detail: str = ""):
        super().__init__(f"{provider} rejected the key. {detail}".strip())
        self.provider = provider


RATE_LIMIT_TRIES = 3
RATE_LIMIT_MAX_WAIT = 10.0           # GetSongBPM only (it sends no Retry-After of note)
FREQBLOG_429_TRIES = 6               # concurrency 429s waited out, each for its full Retry-After
FREQBLOG_MAX_WAIT = 120.0            # a longer Retry-After isn't waited out inside a fetch


def retry_after(r, attempt: int) -> float:
    """Seconds to wait on a 429: the server's Retry-After when it gives one."""
    try:
        return min(RATE_LIMIT_MAX_WAIT, float(r.headers.get("Retry-After") or 0) or 2.0 * (attempt + 1))
    except (TypeError, ValueError):
        return min(RATE_LIMIT_MAX_WAIT, 2.0 * (attempt + 1))


def retry_after_seconds(r, default: float = 5.0) -> float:
    """The Retry-After header in seconds, exactly as sent (seconds or an HTTP date),
    never shortened. `default` only when the header is missing or unreadable."""
    v = (r.headers.get("Retry-After") or "").strip() if getattr(r, "headers", None) else ""
    if not v:
        return default
    try:
        return max(0.0, float(v))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        import datetime as _dt
        when = parsedate_to_datetime(v)
        return max(0.0, (when - _dt.datetime.now(_dt.timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return default


class AllowanceUsed(RuntimeError):
    """FreqBlog's monthly allowance for this key is used up (a 429 that isn't the
    concurrency limit). `usage` is the /me/stats answer when it was already asked."""

    def __init__(self, usage=None, detail: str = ""):
        super().__init__("FreqBlog allowance used." + (f" {detail}" if detail else ""))
        self.usage = usage


class ProviderError(RuntimeError):
    pass


def read_json(r, who: str = "The server", want=dict):
    """r.json(), but a reply that is not JSON (or not the expected shape) raises
    ProviderError with a plain message instead of a parser traceback."""
    try:
        j = r.json()
    except ValueError:
        raise ProviderError(f"{who} sent a reply Playlist Flow could not read "
                            f"(HTTP {r.status_code}). Try again in a moment.") from None
    if want is not None and not isinstance(j, want):
        raise ProviderError(f"{who} sent an unexpected reply (HTTP {r.status_code}).")
    return j


class RateLimited(ProviderError):
    """429. Carries Spotify's Retry-After so the caller can pace itself.

    Raised rather than slept on here: the search worker owns the pacing so the
    wait stays cancellable.
    """

    def __init__(self, retry_after: float):
        super().__init__(f"Spotify rate limit, waiting {retry_after:.0f}s")
        self.retry_after = retry_after


# --------------------------------------------------------------------------
# Spotify
# --------------------------------------------------------------------------

@dataclass
class SpotifyTrack:
    title: str
    artist: str
    uri: str
    isrc: str
    duration_ms: int


@dataclass
class SpotifyPlaylist:
    id: str
    name: str
    count: int
    owner: str
    mine: bool


class _SpotifySession(requests.Session):
    """A connection failure (offline, DNS, timeout) becomes a ProviderError with a
    plain message, which every caller already shows, instead of an unhandled
    requests exception."""

    def request(self, *a, **kw):
        try:
            return super().request(*a, **kw)
        except requests.RequestException as e:
            raise ProviderError(f"Couldn't reach Spotify ({type(e).__name__}). Check your "
                                "connection and try again.") from None


class Spotify:
    """Playlist reads with a user token.

    Client Credentials is not an option: GET /playlists/{id}/items answers
    401 "Valid user authentication required", because Development Mode grants
    playlist access only to the creator or a collaborator and Client Credentials
    carries no identity to check against.

    The item endpoint was renamed in the February 2026 migration:
        /playlists/{id}/tracks  ->  /playlists/{id}/items   (403 on the old one)
        items[].track           ->  items[].item
    """

    def __init__(self, auth):
        self.auth = auth
        self._s = _SpotifySession()
        self._s.headers["User-Agent"] = UA

    def _auth(self) -> str:
        return self.auth.access_token()

    @staticmethod
    def playlist_id(text: str) -> str:
        """Accept a URL, a spotify:playlist: URI, or a bare ID."""
        t = (text or "").strip()
        if not t:
            raise ProviderError("Enter a playlist URL or ID.")
        if "open.spotify.com" in t:
            part = t.split("playlist/")[-1]
            return part.split("?")[0].split("/")[0]
        if t.startswith("spotify:playlist:"):
            return t.split(":")[-1]
        return t

    def playlist_name(self, pid: str) -> str:
        r = self._s.get(
            f"{SPOTIFY_API}/playlists/{pid}",
            headers={"Authorization": f"Bearer {self._auth()}"},
            params={"fields": "name"},
            timeout=20,
        )
        if r.status_code == 401:
            raise ProviderError("Spotify sign-in expired, sign in again.")
        if r.status_code == 404:
            raise ProviderError("Playlist not found.")
        if r.status_code != 200:
            raise ProviderError(f"Spotify returned {r.status_code} for that playlist.")
        return read_json(r, "Spotify").get("name") or ""

    def me(self) -> str:
        r = self._s.get(f"{SPOTIFY_API}/me",
                        headers={"Authorization": f"Bearer {self._auth()}"},
                        timeout=20)
        return read_json(r, "Spotify").get("id") or "" if r.status_code == 200 else ""

    def my_playlists(self) -> list[SpotifyPlaylist]:
        """Everything on the signed-in account, own and followed."""
        mine = self.me()
        out: list[SpotifyPlaylist] = []
        url = f"{SPOTIFY_API}/me/playlists"
        params = {"limit": 50}
        while url:
            r = self._s.get(url, headers={"Authorization": f"Bearer {self._auth()}"},
                            params=params, timeout=25)
            if r.status_code == 401:
                raise ProviderError("Spotify sign-in expired, sign in again.")
            if r.status_code != 200:
                raise ProviderError(f"Spotify returned {r.status_code} listing playlists.")
            j = read_json(r, "Spotify")
            for it in j.get("items") or []:
                if not it:
                    continue
                # "tracks" was renamed "items" on the playlist object too.
                counts = it.get("items") or it.get("tracks") or {}
                owner = (it.get("owner") or {}).get("id", "")
                out.append(SpotifyPlaylist(
                    id=it.get("id", ""),
                    name=it.get("name", "") or "(untitled)",
                    count=counts.get("total") or 0,
                    owner=owner,
                    mine=bool(mine) and owner == mine,
                ))
            url = j.get("next")
            params = None
        return out

    # ---------------- details ----------------

    def playlist_details(self, pid: str) -> dict:
        """Name, description and cover for a playlist.

        Spotify returns the description HTML-escaped (&amp;, &#x27;), so it is
        unescaped here, what goes back on a PUT is the plain text.
        """
        r = self._s.get(
            f"{SPOTIFY_API}/playlists/{pid}",
            headers={"Authorization": f"Bearer {self._auth()}"},
            params={"fields": "name,description,public,images"},
            timeout=20,
        )
        if r.status_code == 401:
            raise ProviderError("Spotify sign-in expired - sign in again.")
        if r.status_code != 200:
            raise ProviderError(f"Spotify returned {r.status_code} for that playlist.")
        j = read_json(r, "Spotify")
        images = j.get("images") or []
        return {
            "name": j.get("name", "") or "",
            "description": html.unescape(j.get("description") or ""),
            "public": bool(j.get("public")),
            # Largest first in Spotify's ordering; the smallest is 60px, too
            # coarse for anything but a list icon.
            "image": (images[0].get("url") if images else "") or "",
        }

    def set_playlist_details(self, pid: str, name: str = None,
                             description: str = None) -> None:
        """PUT /playlists/{id}. Only the fields given are sent."""
        body = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if not body:
            return
        r = self._s.put(
            f"{SPOTIFY_API}/playlists/{pid}",
            headers={"Authorization": f"Bearer {self._auth()}"},
            json=body,
            timeout=25,
        )
        if r.status_code == 401:
            raise ProviderError("Spotify sign-in expired - sign in again.")
        if r.status_code not in (200, 201, 204):
            raise ProviderError(
                f"Spotify refused the change ({r.status_code}): {r.text[:120]}")

    # ---------------- search ----------------

    def search_tracks(self, q: str, limit: int = 5, market: str = "US") -> list[dict]:
        """Track search. Works on the user token the app already holds.

        Unlike audio_features and playlist items, search has no identity
        requirement, so nothing extra had to be arranged for it.

        Params go through requests' encoder rather than an f-string: queries
        carry ampersands, apostrophes and quotes ("Rock & Roll", "Rockin'",
        'track:"..."') that must not land raw in the URL.
        """
        r = self._s.get(
            f"{SPOTIFY_API}/search",
            headers={"Authorization": f"Bearer {self._auth()}"},
            params={"q": q, "type": "track", "limit": limit, "market": market},
            timeout=20,
        )
        if r.status_code == 429:
            try:
                wait = float(r.headers.get("Retry-After", "2"))
            except ValueError:
                wait = 2.0
            raise RateLimited(wait)
        if r.status_code == 401:
            raise ProviderError("Spotify sign-in expired, sign in again.")
        if r.status_code != 200:
            raise ProviderError(f"Spotify returned {r.status_code} for that search.")
        return (read_json(r, "Spotify").get("tracks") or {}).get("items") or []

    # ---------------- playback ----------------
    #
    # Nothing is streamed here. These drive the user's own Spotify client,
    # which is the only playback Spotify permits from outside their SDK.
    # Everything needs Premium and an active device, i.e. Spotify running.

    def devices(self) -> list[dict]:
        r = self._s.get(f"{SPOTIFY_API}/me/player/devices",
                        headers={"Authorization": f"Bearer {self._auth()}"},
                        timeout=15)
        if r.status_code != 200:
            return []
        try:
            return read_json(r, "Spotify").get("devices") or []
        except ProviderError:
            return []

    def player_state(self) -> dict | None:
        """None when nothing is playing anywhere (Spotify answers 204)."""
        r = self._s.get(f"{SPOTIFY_API}/me/player",
                        headers={"Authorization": f"Bearer {self._auth()}"},
                        timeout=15)
        if r.status_code == 204 or not r.content:
            return None
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    def _player_call(self, method: str, path: str, **kw):
        r = self._s.request(
            method, f"{SPOTIFY_API}/me/player/{path}",
            headers={"Authorization": f"Bearer {self._auth()}"},
            timeout=20, **kw)
        if r.status_code == 404:
            raise ProviderError(
                "No active Spotify device. Open Spotify and play something for "
                "a second, then try again.")
        if r.status_code == 403:
            raise ProviderError(
                "Spotify refused playback control. This needs Spotify Premium.")
        if r.status_code == 429:
            raise ProviderError("Spotify rate limit, wait a moment.")
        if r.status_code not in (200, 202, 204):
            raise ProviderError(f"Spotify returned {r.status_code}.")
        return r

    def play(self, uris: list[str] | None = None, position_ms: int = 0,
             device_id: str = ""):
        """Start playback. Passing a list of URIs replaces the queue, so the
        app's working order can be auditioned before it is pushed."""
        body: dict = {}
        if uris:
            body["uris"] = uris[:200]
            body["position_ms"] = max(0, int(position_ms))
        params = {"device_id": device_id} if device_id else None
        self._player_call("PUT", "play", json=body or None, params=params)

    def resume(self, device_id: str = ""):
        params = {"device_id": device_id} if device_id else None
        self._player_call("PUT", "play", params=params)

    def pause(self):
        self._player_call("PUT", "pause")

    def next_track(self):
        self._player_call("POST", "next")

    def previous_track(self):
        self._player_call("POST", "previous")

    def seek(self, position_ms: int):
        self._player_call("PUT", "seek",
                          params={"position_ms": max(0, int(position_ms))})

    def playlist_uris(self, pid: str) -> list[str]:
        return [t.uri for t in self.playlist_tracks(pid)]

    def add_items(self, pid: str, uris: list, progress=None) -> int:
        """Append tracks to a playlist. Returns how many were added.

        POST /playlists/{id}/items, the same February 2026 rename that hit the
        GET path; POST /tracks answers 403. Spotify caps a request at 100 uris.

        Appends only. Placing them correctly is the reorder step's job, which
        keeps every existing track's "date added" intact.
        """
        added = 0
        for start in range(0, len(uris), 100):
            chunk = uris[start:start + 100]
            r = self._s.post(
                f"{SPOTIFY_API}/playlists/{pid}/items",
                headers={"Authorization": f"Bearer {self._auth()}"},
                json={"uris": chunk},
                timeout=30,
            )
            if r.status_code == 429:
                raise ProviderError(
                    f"Spotify rate limit after adding {added} track(s). "
                    "Wait a minute and try again."
                )
            if r.status_code not in (200, 201):
                raise ProviderError(
                    f"Spotify refused to add tracks ({r.status_code}) after "
                    f"{added} successful one(s): {r.text[:120]}"
                )
            added += len(chunk)
            if progress:
                progress(added, len(uris))
        return added

    def track_meta(self, uris: list) -> dict:
        """uri -> (title, artist) as Spotify has them now, 50 ids a request.

        Matched by position in the reply, not by the uri in it: a relinked track comes
        back under another id, and must still update the track that was asked about.
        A track Spotify no longer knows (null in the reply) or a request that fails is
        simply missing from the result. Best effort, never raises."""
        out = {}
        wanted = [u for u in uris if (u or "").startswith("spotify:track:")]
        for start in range(0, len(wanted), 50):
            chunk = wanted[start:start + 50]
            try:
                r = self._s.get(
                    f"{SPOTIFY_API}/tracks",
                    headers={"Authorization": f"Bearer {self._auth()}"},
                    params={"ids": ",".join(u.split(":")[-1] for u in chunk), "market": "from_token"},
                    timeout=20,
                )
                if r.status_code != 200:
                    continue
                rows = r.json().get("tracks") or []
                for uri, t in zip(chunk, rows):
                    if not isinstance(t, dict) or not t.get("name"):
                        continue
                    artists = ", ".join(n for n in ((a or {}).get("name") for a in (t.get("artists") or [])) if n)
                    out[uri] = (t.get("name") or "", artists)
            except Exception:
                continue
        return out

    def track_names(self, uris: list) -> dict:
        """uri -> "Artist - Title" for tracks this app has no local copy of.

        Used to name what a destructive confirmation is about to delete, rather
        than showing the user a base-62 id. Best effort: on any failure the
        caller falls back to the id.
        """
        return {u: (f"{a} - {t}" if a else t) for u, (t, a) in self.track_meta(uris).items()}

    def remove_items(self, pid: str, uris: list, progress=None) -> int:
        """Remove tracks from a playlist. Returns how many were removed.

        DELETE /playlists/{id}/items, body {"items": [{"uri": ...}]}.

        The February 2026 rename hit the body as well as the path: the parameter
        went from "tracks" to "items". It still takes OBJECTS with a "uri" key,
        not bare strings -- a list of strings answers "Invalid base62 id".
        Everything else ("tracks", "uris", query parameters) answers 400
        "No uris provided", which is emitted for any unrecognised body and so
        says nothing about whether the endpoint or the shape is at fault.
        100 per request; DELETE /tracks is 403.

        Removes every occurrence of each uri. Destructive, so the caller is
        expected to have confirmed it explicitly.
        """
        removed = 0
        for start in range(0, len(uris), 100):
            chunk = uris[start:start + 100]
            r = self._s.request(
                "DELETE",
                f"{SPOTIFY_API}/playlists/{pid}/items",
                headers={"Authorization": f"Bearer {self._auth()}"},
                json={"items": [{"uri": u} for u in chunk]},
                timeout=30,
            )
            if r.status_code == 429:
                raise ProviderError(
                    f"Spotify rate limit after removing {removed} track(s). "
                    "Wait a minute and try again."
                )
            if r.status_code not in (200, 201):
                raise ProviderError(
                    f"Spotify refused to remove tracks ({r.status_code}) after "
                    f"{removed} successful one(s): {r.text[:120]}"
                )
            removed += len(chunk)
            if progress:
                progress(removed, len(uris))
        return removed

    def reorder_playlist(self, pid: str, target: list[str], progress=None) -> int:
        """Permute the playlist into `target` order using move operations.

        Deliberately not the replace-everything endpoint: replacing rewrites
        every item and resets each track's "date added". Moves preserve that,
        at the cost of up to one request per track.

        Refuses unless the playlist holds exactly the same set of tracks, so a
        stale window can never delete anything.
        """
        current = self.playlist_uris(pid)
        if sorted(current) != sorted(target):
            missing = len(set(current) - set(target))
            extra = len(set(target) - set(current))
            raise ProviderError(
                "The playlist on Spotify no longer matches this window "
                f"({missing} track(s) not here, {extra} not there). "
                "Reload the playlist, redo your order, then push."
            )

        moves = 0
        for i, uri in enumerate(target):
            if current[i] == uri:
                continue
            j = current.index(uri, i)
            r = self._s.put(
                f"{SPOTIFY_API}/playlists/{pid}/items",
                headers={"Authorization": f"Bearer {self._auth()}"},
                json={"range_start": j, "insert_before": i, "range_length": 1},
                timeout=25,
            )
            if r.status_code == 429:
                raise ProviderError(
                    f"Spotify rate limit after {moves} move(s). The order is "
                    f"partly applied, wait a minute and push again."
                )
            if r.status_code not in (200, 201):
                raise ProviderError(
                    f"Spotify refused a move ({r.status_code}) after {moves} "
                    f"successful one(s)."
                )
            current.insert(i, current.pop(j))
            moves += 1
            if progress:
                progress(moves, i + 1, len(target))
        return moves

    def playlist_tracks(self, pid: str, progress=None) -> list[SpotifyTrack]:
        """Paginated, Spotify caps a page at 100."""
        out: list[SpotifyTrack] = []
        url = f"{SPOTIFY_API}/playlists/{pid}/items"
        params = {
            "limit": 100,
            "fields": "next,items(item(name,uri,duration_ms,artists(name),external_ids(isrc)))",
        }
        while url:
            r = self._s.get(
                url,
                headers={"Authorization": f"Bearer {self._auth()}"},
                params=params,
                timeout=25,
            )
            if r.status_code == 401:
                raise ProviderError("Spotify sign-in expired, sign in again.")
            if r.status_code == 403:
                raise ProviderError(
                    "Spotify refused the track list. In Development Mode only the "
                    "playlist's creator or a collaborator can read its items, and "
                    "your account must be listed under Users and Access in the "
                    "Spotify developer dashboard."
                )
            if r.status_code == 404:
                raise ProviderError("Playlist not found.")
            if r.status_code != 200:
                raise ProviderError(f"Spotify returned {r.status_code} reading tracks.")
            j = read_json(r, "Spotify")
            for entry in j.get("items") or []:
                # A removed or unavailable track comes back as null (the entry, or its
                # item); skip it rather than fail the whole playlist.
                if not isinstance(entry, dict):
                    continue
                # Renamed from "track" to "item" in the February 2026 migration.
                t = entry.get("item") or entry.get("track")
                if not isinstance(t, dict):
                    continue
                uri = t.get("uri") or ""
                if not uri or uri.startswith("spotify:local"):
                    continue
                out.append(
                    SpotifyTrack(
                        title=t.get("name") or "",
                        artist=", ".join(n for n in ((a or {}).get("name") for a in (t.get("artists") or [])) if n),
                        uri=uri,
                        isrc=(t.get("external_ids") or {}).get("isrc") or "",
                        duration_ms=t.get("duration_ms") or 0,
                    )
                )
            if progress:
                progress(len(out))
            url = j.get("next")
            params = None  # `next` already carries the query string
        return out


# --------------------------------------------------------------------------
# FreqBlog
# --------------------------------------------------------------------------

@dataclass
class Features:
    bpm: float = 0.0
    camelot: str = ""
    bpm_conf: Optional[float] = None
    key_conf: Optional[float] = None
    isrc: str = ""
    pending: bool = False      # queued for on-demand analysis, re-check later
    terminal: bool = False     # definitively not analysable, stop asking
    source: str = ""           # which pass resolved it
    retry_after_days: Optional[float] = None   # FreqBlog's own "ask again in" hint


def _retry_days(*dicts) -> Optional[float]:
    """retry_after_days from the first of these replies that carries a usable one."""
    for d in dicts:
        if isinstance(d, dict) and d.get("retry_after_days") is not None:
            try:
                v = float(d["retry_after_days"])
            except (TypeError, ValueError):
                continue
            if v >= 0:
                return v
    return None


@dataclass
class Usage:
    """GET /me/stats, the key's monthly usage. Free: it doesn't count as a request."""
    used: int
    quota: int
    pct: float
    reset: str            # quota_reset_date as FreqBlog sent it


class FreqBlog:
    """BPM + Camelot key. A track FreqBlog doesn't have yet is queued for analysis
    (202, usually ready within a minute), so a miss is a 'pending', not a failure.

    Every lookup counts against the key's monthly allowance, a 202 too and on /bulk
    too, so nothing here polls: the caller records queued tracks and asks again later
    (see Store.mark_waiting). GET /me/stats is free and checks the key."""

    # One FreqBlog request in flight per program, whatever thread asks: a free key
    # allows 2 /bulk requests at once and answers a third with 429.
    _inflight = threading.Lock()

    # words in a 429's body that mean the month's allowance, not the concurrency limit
    ALLOWANCE_WORDS = ("quota", "allowance", "monthly", "per month", "this month")

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._s = requests.Session()
        self._s.headers["User-Agent"] = UA
        self._sleep = time.sleep          # swapped out by tests
        self.last_hint = ""               # /bulk's plain-English "hint", when it sent one

    def _headers(self) -> dict:
        if not self.api_key:
            raise ProviderError("No FreqBlog API key, add it in setup (Settings > Run setup again).")
        return {"x-api-key": self.api_key}

    def _allowance_429(self, r, wait: float):
        """Is this 429 the monthly allowance? The body says so; or the body doesn't say
        either way, the Retry-After is long (the concurrency limit asks for seconds) and
        /me/stats, asked once, shows the month used up. Returns the Usage when stats
        were asked, True when the body alone said so, else None."""
        body = ""
        try:
            j = r.json()
            if isinstance(j, dict):
                body = " ".join(str(j.get(k) or "") for k in ("detail", "error_code", "error", "message"))
        except ValueError:
            body = getattr(r, "text", "") or ""
        b = body.lower()
        if any(w in b for w in self.ALLOWANCE_WORDS):
            return True
        if "concurren" in b or "in flight" in b or "at once" in b or wait <= 60:
            return None
        try:
            u = self.stats()
        except Exception:
            return None
        return u if (u.quota and u.used >= u.quota) or u.pct >= 100 else None

    def _send(self, method: str, url: str, **kw):
        """One request with FreqBlog's error shapes sorted out: a rejected or suspended
        key raises KeyRejected; the monthly allowance raises AllowanceUsed; a concurrency
        429 is waited out for its full Retry-After, every time, then retried. Requests go
        out strictly one at a time."""
        for attempt in range(FREQBLOG_429_TRIES):
            with FreqBlog._inflight:
                try:
                    r = self._s.request(method, url, headers=self._headers(), **kw)
                except requests.RequestException as e:
                    raise ProviderError(f"FreqBlog unreachable: {type(e).__name__}") from e
            if r.status_code in (401, 403):
                raise KeyRejected("FreqBlog", "It may be mistyped, revoked or suspended.")
            if r.status_code == 429:
                wait = retry_after_seconds(r)
                used = self._allowance_429(r, wait)
                if used is not None:
                    raise AllowanceUsed(used if used is not True else None)
                if wait > FREQBLOG_MAX_WAIT or attempt + 1 >= FREQBLOG_429_TRIES:
                    raise ProviderError("FreqBlog is busy (rate limit), try again in a moment.")
                self._sleep(wait)          # the full Retry-After, never less
                continue
            return r
        raise ProviderError("FreqBlog is busy (rate limit), try again in a moment.")

    @staticmethod
    def _parse(d: dict) -> Features:
        return Features(
            bpm=float(d.get("bpm_snapped") or d.get("bpm") or 0.0),
            camelot=(d.get("camelot") or "").upper(),
            bpm_conf=d.get("bpm_confidence"),
            key_conf=d.get("key_confidence"),
            isrc=d.get("isrc") or "",
        )

    def lookup(self, title: str, artist: str = "", isrc: str = "", wait: int = 0) -> Features:
        """One track. The name and artist always go with it when there are any: FreqBlog
        charges a queued track once and collects it free when it is sent again BY NAME,
        while an ISRC-only request is charged again. The ISRC rides along when known, as
        the exact key."""
        params: dict = {"wait": wait}
        if title:
            params["track"] = title
        if artist:
            params["artist"] = artist
        if isrc:
            params["isrc"] = isrc
        r = self._send("GET", f"{FREQBLOG_API}/lookup", params=params, timeout=40)

        if r.status_code == 200:
            return self._parse(read_json(r, "FreqBlog"))
        body = {}
        if r.status_code in (202, 404):
            try:
                body = r.json()
            except ValueError:
                pass
            body = body if isinstance(body, dict) else {}
        if r.status_code == 202:
            return Features(pending=True, retry_after_days=_retry_days(body))
        if r.status_code == 404:
            return Features(terminal=bool(body.get("terminal", True)),
                            retry_after_days=_retry_days(body))
        raise ProviderError(f"FreqBlog returned {r.status_code}.")

    def stats(self, timeout: float = 15) -> Usage:
        """GET /me/stats: is the key good, and how much of the month is used.
        Raises KeyRejected with FreqBlog's own "detail" text on a 401, ProviderError
        when FreqBlog can't be reached or answers oddly."""
        if not self.api_key:
            raise ProviderError("No FreqBlog key.")
        try:
            r = self._s.get(f"{FREQBLOG_API}/me/stats",
                            headers={"X-API-Key": self.api_key}, timeout=timeout)
        except requests.RequestException as e:
            raise ProviderError(f"Couldn't reach FreqBlog ({type(e).__name__}).") from None
        if r.status_code in (401, 403):
            detail = ""
            try:
                j = r.json()
                if isinstance(j, dict):
                    detail = str(j.get("detail") or "").strip()
            except ValueError:
                pass
            raise KeyRejected("FreqBlog", detail or f"FreqBlog answered {r.status_code}.")
        if r.status_code != 200:
            raise ProviderError(f"FreqBlog answered {r.status_code}.")
        j = read_json(r, "FreqBlog")
        try:
            return Usage(used=int(j.get("requests_this_month") or 0),
                         quota=int(j.get("monthly_quota") or 0),
                         pct=float(j.get("quota_used_pct") or 0.0),
                         reset=str(j.get("quota_reset_date") or ""))
        except (TypeError, ValueError):
            raise ProviderError("FreqBlog sent usage figures Playlist Flow couldn't read.") from None

    def bulk(self, items: Iterable[dict]) -> list[dict]:
        """Up to 50 per call. Each item: {track, artist?, isrc?}.
        Returns the raw result rows so callers can match them back by index."""
        # The REST endpoint takes a bare array, unlike the MCP tool, which
        # wraps the same items in {"tracks": [...]}.
        payload = list(items)[:50]
        self.last_hint = ""
        r = self._send("POST", f"{FREQBLOG_API}/bulk", json=payload, timeout=90)
        if r.status_code not in (200, 202):
            raise ProviderError(f"FreqBlog bulk returned {r.status_code}.")
        j = read_json(r, "FreqBlog", want=(dict, list))
        if isinstance(j, dict) and isinstance(j.get("hint"), str):
            self.last_hint = j["hint"].strip()
        rows = j if isinstance(j, list) else j.get("results")
        return rows if isinstance(rows, list) else []

    @staticmethod
    def features_from_row(row: dict) -> Features:
        if not isinstance(row, dict):
            return Features(terminal=True)
        if row.get("found") and isinstance(row.get("result"), dict):
            return FreqBlog._parse(row["result"])
        days = _retry_days(row, row.get("result"))
        status = (row.get("backfill_status") or "").lower()
        if status in ("queued", "running", "pending", "processing"):
            return Features(pending=True, retry_after_days=days)
        return Features(terminal=True, retry_after_days=days)


# --------------------------------------------------------------------------
# GetSongBPM, last-resort fallback
# --------------------------------------------------------------------------

GETSONGBPM_API = "https://api.getsong.co"


class GetSongBPM:
    """Coverage on independent artists is near zero, but it is free and the key
    is already registered, so it is worth one shot on whatever else missed.

    Only exact artist+title matches are accepted. A loose search here returns
    confidently wrong recordings: a singular title can resolve to its plural
    namesake by a completely different artist.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._s = requests.Session()
        self._s.headers["User-Agent"] = UA
        self._sleep = time.sleep          # swapped out by tests

    # Words in a GetSongBPM error that mean the key itself is the problem (their
    # API has no documented error codes); anything else, like "no result", is a miss.
    KEY_ERROR_WORDS = ("api key", "api_key", "apikey", "invalid key", "key is", "suspend",
                       "banned", "blocked", "denied", "not authori", "unauthori")

    @classmethod
    def _key_problem(cls, text: str) -> bool:
        t = (text or "").lower()
        return any(w in t for w in cls.KEY_ERROR_WORDS)

    @staticmethod
    def _norm(s: str) -> str:
        return "".join(ch for ch in (s or "").lower() if ch.isalnum())

    def lookup(self, title: str, artist: str) -> Features:
        from .keys import to_camelot

        if not self.api_key or not title:
            return Features(terminal=True)
        params = {
            "api_key": self.api_key,
            "type": "both",
            "lookup": f"song:{title} artist:{artist}" if artist else f"song:{title}",
        }
        r = None
        for attempt in range(RATE_LIMIT_TRIES):
            try:
                r = self._s.get(f"{GETSONGBPM_API}/search/", params=params, timeout=25)
            except requests.RequestException:
                return Features(terminal=True)
            if r.status_code != 429:
                break
            if attempt + 1 < RATE_LIMIT_TRIES:
                self._sleep(retry_after(r, attempt))      # quiet: a rate limit is not a fault
        if r.status_code in (401, 403):
            raise KeyRejected("GetSongBPM", "It may be mistyped, not active yet, or suspended.")
        if r.status_code != 200:
            return Features(terminal=True)
        try:
            j = r.json()
        except ValueError:
            return Features(terminal=True)
        if not isinstance(j, dict):
            return Features(terminal=True)
        top_err = j.get("error")
        if isinstance(top_err, str) and self._key_problem(top_err):
            raise KeyRejected("GetSongBPM", "It may be mistyped, not active yet, or suspended.")

        found = j.get("search")
        if isinstance(found, dict) and found.get("error"):
            if self._key_problem(str(found.get("error"))):
                raise KeyRejected("GetSongBPM", "It may be mistyped, not active yet, or suspended.")
            return Features(terminal=True)
        if not found:
            return Features(terminal=True)
        rows = found if isinstance(found, list) else [found]

        for row in rows:
            got_title = row.get("title") or row.get("song_title") or ""
            got_artist = ((row.get("artist") or {}).get("name")
                          if isinstance(row.get("artist"), dict)
                          else row.get("artist")) or ""
            # Exact match only. Anything looser silently injects wrong data.
            if self._norm(got_title) != self._norm(title):
                continue
            if artist and self._norm(got_artist) != self._norm(artist):
                continue
            try:
                bpm = float(row.get("tempo") or 0)
            except (TypeError, ValueError):
                bpm = 0.0
            cam = to_camelot(row.get("key_of") or "")
            if bpm > 0 or cam:
                return Features(bpm=bpm, camelot=cam)
        return Features(terminal=True)
