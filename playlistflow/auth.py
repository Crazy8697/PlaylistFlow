"""Spotify user authorisation — PKCE, with the redirect pasted back by hand.

Spotify killed Client Credentials for playlist items: GET /playlists/{id}/items
answers 401 "Valid user authentication required". Development Mode grants
playlist access only to the playlist's creator or a collaborator, and Client
Credentials carries no identity to check, so no amount of permission fixes it.

The redirect lands on a dead 127.0.0.1 URL that the browser fails to load. The
user copies that URL out of the address bar and pastes it in. Nothing listens on
a port — the "no local web server" constraint stays intact.

PKCE rather than the client secret: a secret shipped inside a distributed binary
is not a secret, and PKCE is the documented desktop path.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import time
import urllib.parse

import requests

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# Registered on the app. Must be 127.0.0.1 — Spotify rejects the "localhost" form.
REDIRECT_URI = "http://127.0.0.1:8888/callback"

SCOPES = ("playlist-read-private playlist-read-collaborative "
          "playlist-modify-private playlist-modify-public "
          "user-read-playback-state user-modify-playback-state")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class AuthError(RuntimeError):
    pass


class SpotifyAuth:
    def __init__(self, client_id: str, prefs):
        self.client_id = client_id
        self.prefs = prefs
        self._access = ""
        self._expires = 0.0
        self._verifier = ""
        self._state = ""

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
            raise AuthError("No Spotify client ID — check your .env")
        self._verifier = _b64url(os.urandom(64))
        self._state = _b64url(os.urandom(16))
        challenge = _b64url(hashlib.sha256(self._verifier.encode("ascii")).digest())
        q = urllib.parse.urlencode({
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "scope": SCOPES,
            "state": self._state,
        })
        return f"{AUTH_URL}?{q}"

    # ---------------- step 2 ----------------

    def complete(self, pasted: str) -> None:
        """Take the pasted redirect URL (or a bare code) and get tokens."""
        pasted = (pasted or "").strip()
        if not pasted:
            raise AuthError("Nothing pasted.")
        if not self._verifier:
            raise AuthError("Start the sign-in again — the session was lost.")

        code = ""
        if "code=" in pasted:
            parsed = urllib.parse.urlparse(pasted)
            params = urllib.parse.parse_qs(parsed.query)
            if "error" in params:
                raise AuthError(f"Spotify refused: {params['error'][0]}")
            code = (params.get("code") or [""])[0]
            got_state = (params.get("state") or [""])[0]
            if got_state and self._state and got_state != self._state:
                raise AuthError("State mismatch — start the sign-in again.")
        elif re.fullmatch(r"[A-Za-z0-9_\-]+", pasted):
            code = pasted
        if not code:
            raise AuthError("Couldn't find a code in that. Paste the whole URL.")

        r = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": self.client_id,
                "code_verifier": self._verifier,
            },
            timeout=25,
        )
        if r.status_code != 200:
            raise AuthError(f"Token exchange failed ({r.status_code}): {r.text[:200]}")
        j = r.json()
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
        r = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
            },
            timeout=25,
        )
        if r.status_code != 200:
            # Refresh tokens can be revoked out from under us; make the caller
            # re-authorise rather than dying.
            self.forget()
            raise AuthError("Spotify sign-in expired — sign in again.")
        j = r.json()
        self._access = j.get("access_token", "")
        self._expires = time.time() + j.get("expires_in", 3600)
        if j.get("refresh_token"):
            self.refresh_token = j["refresh_token"]
        if not self._access:
            self.forget()
            raise AuthError("Spotify sign-in expired — sign in again.")
        return self._access
