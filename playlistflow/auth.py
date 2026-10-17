"""Spotify user authorisation, PKCE.

Spotify killed Client Credentials for playlist items: GET /playlists/{id}/items
answers 401 "Valid user authentication required". Development Mode grants
playlist access only to the playlist's creator or a collaborator, and Client
Credentials carries no identity to check, so no amount of permission fixes it.

The redirect goes to http://127.0.0.1:<port>/callback. While the wizard's sign-in
step waits, callback.py listens there (127.0.0.1 only) and hands the address over;
when that port can't be bound, the user copies the address out of the browser and
pastes it instead. Either way the address goes through complete(), which checks the
state parameter against the one this sign-in sent.

PKCE rather than the client secret: a secret shipped inside a distributed binary
is not a secret, and PKCE is the documented desktop path.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import urllib.parse

import requests

from .providers import ProviderError

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# Registered on the user's Spotify app. Must be 127.0.0.1, Spotify rejects the
# "localhost" form. The port is chosen by the setup wizard (8888 for older setups).
DEFAULT_PORT = 8888


def redirect_uri(port: int = DEFAULT_PORT) -> str:
    return f"http://127.0.0.1:{int(port)}/callback"


REDIRECT_URI = redirect_uri(DEFAULT_PORT)     # kept for older callers

SCOPES = ("playlist-read-private playlist-read-collaborative "
          "playlist-modify-private playlist-modify-public "
          "user-read-playback-state user-modify-playback-state")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class AuthError(RuntimeError):
    pass


class SpotifyAuth:
    def __init__(self, client_id: str, prefs, port: int = DEFAULT_PORT):
        self.client_id = client_id
        self.prefs = prefs
        self.port = port
        self._access = ""
        self._expires = 0.0
        self._verifier = ""
        self._state = ""
        # Called (no arguments) when Spotify rejects the stored sign-in, so the
        # window can say so once and offer to sign in again. Never raises.
        self.on_dead = None

    @property
    def redirect_uri(self) -> str:
        return redirect_uri(self.port)

    def _dead(self):
        cb = self.on_dead
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def check(self, timeout: float = 8.0) -> str:
        """Is the stored sign-in alive? "ok", "dead" (Spotify rejected it, or the
        client ID), "none" (nothing stored) or "offline" (could not ask).
        A refresh is the cheapest real test; a fresh token is kept on success."""
        if not self.client_id or not self.refresh_token:
            return "none"
        try:
            r = requests.post(TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
            }, timeout=timeout)
        except requests.RequestException:
            return "offline"
        if r.status_code in (400, 401):
            return "dead"
        if r.status_code != 200:
            return "offline"
        try:
            j = r.json()
        except ValueError:
            return "offline"
        if not j.get("access_token"):
            return "dead"
        self._access = j["access_token"]
        self._expires = time.time() + j.get("expires_in", 3600)
        if j.get("refresh_token"):
            self.refresh_token = j["refresh_token"]
        return "ok"

    # ---------------- state ----------------

    @property
    def refresh_token(self) -> str:
        return self.prefs.refresh_token

    @refresh_token.setter
    def refresh_token(self, v: str):
        self.prefs.refresh_token = v

    @property
    def authorised(self) -> bool:
        return bool(self.refresh_token)

    def forget(self):
        self.refresh_token = ""
        self._access = ""
        self._expires = 0.0

    # ---------------- step 1 ----------------

    def begin(self) -> str:
        """Return the URL to open in the user's browser."""
        if not self.client_id:
            raise AuthError("No Spotify client ID, check your .env")
        self._verifier = _b64url(os.urandom(64))
        self._state = _b64url(os.urandom(16))
        challenge = _b64url(hashlib.sha256(self._verifier.encode("ascii")).digest())
        q = urllib.parse.urlencode({
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "scope": SCOPES,
            "state": self._state,
        })
        return f"{AUTH_URL}?{q}"

    # ---------------- step 2 ----------------

    def complete(self, pasted: str) -> None:
        """Take the redirect address (caught by the listener or pasted) and get tokens.

        The address must carry the state this sign-in sent: a missing or different
        one means it belongs to another sign-in (or was forged), so it is refused
        before any code is exchanged."""
        pasted = (pasted or "").strip()
        if not pasted:
            raise AuthError("Nothing pasted.")
        if not self._verifier or not self._state:
            raise AuthError("Start the sign-in again, the session was lost.")
        if "code=" not in pasted and "error=" not in pasted:
            raise AuthError("Couldn't find a code in that. Paste the whole URL.")

        params = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
        got_state = (params.get("state") or [""])[0]
        if not got_state:
            raise AuthError("State missing, start the sign-in again.")
        if not hmac.compare_digest(got_state, self._state):
            raise AuthError("State mismatch, start the sign-in again.")
        if "error" in params:
            raise AuthError(f"Spotify refused: {params['error'][0]}")
        code = (params.get("code") or [""])[0]
        if not code:
            raise AuthError("Couldn't find a code in that. Paste the whole URL.")

        try:
            r = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "client_id": self.client_id,
                    "code_verifier": self._verifier,
                },
                timeout=25,
            )
        except requests.RequestException:
            raise AuthError("Couldn't reach Spotify to finish the sign-in. Check your "
                            "connection and try again.") from None
        if r.status_code != 200:
            raise AuthError(f"Token exchange failed ({r.status_code}): {r.text[:200]}")
        try:
            j = r.json()
        except ValueError:
            raise AuthError("Spotify's sign-in reply couldn't be read. Try again.") from None
        # one address, one sign-in: the same state can't be used twice
        self._state = ""
        self._access = j.get("access_token", "")
        self._expires = time.time() + j.get("expires_in", 3600)
        if j.get("refresh_token"):
            self.refresh_token = j["refresh_token"]
        if not self._access:
            raise AuthError("Spotify returned no access token.")

    # ---------------- use ----------------

    def access_token(self) -> str:
        if self._access and time.time() < self._expires - 30:
            return self._access
        if not self.refresh_token:
            raise AuthError("Not signed in to Spotify yet.")
        try:
            r = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                },
                timeout=25,
            )
        except requests.RequestException:
            # offline is not a dead sign-in: keep it, and say so plainly
            raise ProviderError("Couldn't reach Spotify. Check your connection and "
                                "try again.") from None
        if r.status_code >= 500 or r.status_code == 429:
            raise ProviderError(f"Spotify is having trouble ({r.status_code}). Try again "
                                "in a moment.")
        if r.status_code != 200:
            # Refresh tokens can be revoked out from under us; make the caller
            # re-authorise rather than dying.
            self.forget()
            self._dead()
            raise AuthError("Spotify sign-in expired, sign in again.")
        try:
            j = r.json()
        except ValueError:
            raise ProviderError("Spotify's reply couldn't be read. Try again in a moment.") from None
        self._access = j.get("access_token", "")
        self._expires = time.time() + j.get("expires_in", 3600)
        if j.get("refresh_token"):
            self.refresh_token = j["refresh_token"]
        if not self._access:
            self.forget()
            self._dead()
            raise AuthError("Spotify sign-in expired, sign in again.")
        return self._access
