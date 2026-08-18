"""Network clients.

Spotify  — playlist/track reads only. Client Credentials, no user login.
           audio_features is dead (403 since 2024-11-27); we never call it.
FreqBlog — BPM and musical key. Returns Camelot directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import requests

SPOTIFY_API = "https://api.spotify.com/v1"
FREQBLOG_API = "https://api.freqblog.com"

UA = "PlaylistFlow/1.0"


class ProviderError(RuntimeError):
    pass


class RateLimited(ProviderError):
    """429. Carries Spotify's Retry-After so the caller can pace itself.

    Raised rather than slept on here: the search worker owns the pacing so the
    wait stays cancellable.
    """

    def __init__(self, retry_after: float):
        super().__init__(f"Spotify rate limit — waiting {retry_after:.0f}s")
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
        self._s = requests.Session()
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
            raise ProviderError("Spotify sign-in expired — sign in again.")
        if r.status_code == 404:
            raise ProviderError("Playlist not found.")
        if r.status_code != 200:
            raise ProviderError(f"Spotify returned {r.status_code} for that playlist.")
        return r.json().get("name", "")

    def me(self) -> str:
        r = self._s.get(f"{SPOTIFY_API}/me",
                        headers={"Authorization": f"Bearer {self._auth()}"},
                        timeout=20)
        return r.json().get("id", "") if r.status_code == 200 else ""

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
                raise ProviderError("Spotify sign-in expired — sign in again.")
            if r.status_code != 200:
                raise ProviderError(f"Spotify returned {r.status_code} listing playlists.")
            j = r.json()
            for it in j.get("items", []):
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

    # ---------------- search ----------------

    def search_tracks(self, q: str, limit: int = 5, market: str = "US") -> list[dict]:
        """Track search. Works on the user token the app already holds.

        Unlike audio_features and playlist items, search has no identity
        requirement, so nothing extra had to be arranged for it.

        Params go through requests' encoder rather than an f-string: queries
        carry ampersands, apostrophes and quotes ("Stop & Stare", "Still
        Ragin'", 'track:"..."') that must not land raw in the URL.
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
            raise ProviderError("Spotify sign-in expired — sign in again.")
        if r.status_code != 200:
            raise ProviderError(f"Spotify returned {r.status_code} for that search.")
        return (r.json().get("tracks") or {}).get("items") or []

    # ---------------- playback ----------------
    #
    # Nothing is streamed here. These drive the user's own Spotify client,
    # which is the only playback Spotify permits from outside their SDK.
    # Everything needs Premium and an active device — i.e. Spotify running.

    def devices(self) -> list[dict]:
        r = self._s.get(f"{SPOTIFY_API}/me/player/devices",
                        headers={"Authorization": f"Bearer {self._auth()}"},
                        timeout=15)
        if r.status_code != 200:
            return []
        return r.json().get("devices", [])

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
            raise ProviderError("Spotify rate limit — wait a moment.")
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
                    f"partly applied — wait a minute and push again."
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
        """Paginated — Spotify caps a page at 100."""
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
                raise ProviderError("Spotify sign-in expired — sign in again.")
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
            j = r.json()
            for entry in j.get("items", []):
                # Renamed from "track" to "item" in the February 2026 migration.
                t = entry.get("item") or entry.get("track") or {}
                uri = t.get("uri", "")
                if not uri or uri.startswith("spotify:local"):
                    continue
                out.append(
                    SpotifyTrack(
                        title=t.get("name", ""),
                        artist=", ".join(a.get("name", "") for a in t.get("artists", [])),
                        uri=uri,
                        isrc=(t.get("external_ids") or {}).get("isrc", ""),
                        duration_ms=t.get("duration_ms", 0),
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
    pending: bool = False      # queued for on-demand analysis, re-poll later
    terminal: bool = False     # definitively not analysable — stop asking
    source: str = ""           # which pass resolved it


class FreqBlog:
    """BPM + Camelot key. Misses are queued for analysis and resolve in ~15s,
    so a miss is a 'pending', not a failure."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._s = requests.Session()
        self._s.headers["User-Agent"] = UA

    def _headers(self) -> dict:
        if not self.api_key:
            raise ProviderError("No FreqBlog API key — add FREQBLOG_API_KEY to your .env")
        return {"x-api-key": self.api_key}

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
        """One track. ISRC is preferred — it cannot mismatch. Falls back to
        name+artist, which is fuzzy and can return the wrong recording."""
        params: dict = {"wait": wait}
        if isrc:
            params["isrc"] = isrc
        else:
            params["track"] = title
            if artist:
                params["artist"] = artist
        try:
            r = self._s.get(f"{FREQBLOG_API}/lookup", headers=self._headers(),
                            params=params, timeout=40)
        except requests.RequestException as e:
            raise ProviderError(f"FreqBlog unreachable: {e}") from e

        if r.status_code == 200:
            return self._parse(r.json())
        if r.status_code == 202:
            return Features(pending=True)
        if r.status_code == 404:
            body = {}
            try:
                body = r.json()
            except Exception:
                pass
            return Features(terminal=bool(body.get("terminal", True)))
        if r.status_code == 401:
            raise ProviderError("FreqBlog rejected the API key.")
        if r.status_code == 429:
            raise ProviderError("FreqBlog rate limit hit — wait a moment and retry.")
        raise ProviderError(f"FreqBlog returned {r.status_code}.")

    def bulk(self, items: Iterable[dict]) -> list[dict]:
        """Up to 50 per call. Each item: {track, artist?, isrc?}.
        Returns the raw result rows so callers can match them back by index."""
        # The REST endpoint takes a bare array — unlike the MCP tool, which
        # wraps the same items in {"tracks": [...]}.
        payload = list(items)[:50]
        try:
            r = self._s.post(f"{FREQBLOG_API}/bulk", headers=self._headers(),
                             json=payload, timeout=90)
        except requests.RequestException as e:
            raise ProviderError(f"FreqBlog unreachable: {e}") from e
        if r.status_code == 401:
            raise ProviderError("FreqBlog rejected the API key.")
        if r.status_code == 429:
            raise ProviderError("FreqBlog rate limit hit — wait a moment and retry.")
        if r.status_code not in (200, 202):
            raise ProviderError(f"FreqBlog bulk returned {r.status_code}.")
        j = r.json()
        return j.get("results", j if isinstance(j, list) else [])

    def lookup_isrc(self, isrc: str, wait: int = 0) -> Features:
        """ISRC-only. Used as a second pass when a name match missed — ISRC is
        an exact key and cannot return the wrong recording."""
        return self.lookup("", "", isrc=isrc, wait=wait)

    @staticmethod
    def features_from_row(row: dict) -> Features:
        if row.get("found") and row.get("result"):
            return FreqBlog._parse(row["result"])
        status = (row.get("backfill_status") or "").lower()
        if status in ("queued", "running", "pending"):
            return Features(pending=True)
        return Features(terminal=True)


# --------------------------------------------------------------------------
# GetSongBPM — last-resort fallback
# --------------------------------------------------------------------------

GETSONGBPM_API = "https://api.getsong.co"


class GetSongBPM:
    """Coverage on independent artists is near zero, but it is free and the key
    is already registered, so it is worth one shot on whatever else missed.

    Only exact artist+title matches are accepted. A loose search here returns
    confidently wrong recordings — 'Pretty Distraction' resolves to
    'Pretty Distractions' by a completely different artist.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._s = requests.Session()
        self._s.headers["User-Agent"] = UA

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
        try:
            r = self._s.get(f"{GETSONGBPM_API}/search/", params=params, timeout=25)
        except requests.RequestException:
            return Features(terminal=True)
        if r.status_code != 200:
            return Features(terminal=True)
        try:
            j = r.json()
        except ValueError:
            return Features(terminal=True)

        found = j.get("search")
        if not found or isinstance(found, dict) and found.get("error"):
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
