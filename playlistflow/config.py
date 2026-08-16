"""Secrets and persisted preferences.

Secrets live in a .env next to the program, never in the source.
The storage-folder choice is persisted per-user via QSettings.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings

ORG = "darkrelay"
APP = "PlaylistFlow"


def app_dir() -> Path:
    """Folder the program lives in — works frozen and from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def load_env() -> dict:
    """Minimal .env reader. KEY=value, # comments, no quoting rules."""
    env: dict[str, str] = {}
    path = app_dir() / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    # Real environment variables win, so you can override without editing the file.
    for k in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "FREQBLOG_API_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


class Prefs:
    def __init__(self):
        self._s = QSettings(ORG, APP)

    @property
    def storage_dir(self) -> str:
        return self._s.value("storage_dir", "", type=str)

    @storage_dir.setter
    def storage_dir(self, v: str):
        self._s.setValue("storage_dir", v)

    @property
    def felt(self) -> bool:
        return self._s.value("felt", False, type=bool)

    @felt.setter
    def felt(self, v: bool):
        self._s.setValue("felt", bool(v))

    @property
    def refresh_token(self) -> str:
        return self._s.value("spotify_refresh_token", "", type=str)

    @refresh_token.setter
    def refresh_token(self, v: str):
        self._s.setValue("spotify_refresh_token", v or "")

    @property
    def geometry(self):
        return self._s.value("geometry")

    @geometry.setter
    def geometry(self, v):
        self._s.setValue("geometry", v)

    # Splitter layouts, saved as QSplitter.saveState() blobs.
    def splitter(self, name: str):
        return self._s.value(f"splitter_{name}")

    def set_splitter(self, name: str, state):
        self._s.setValue(f"splitter_{name}", state)
