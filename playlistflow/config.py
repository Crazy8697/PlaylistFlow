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


KEYS = (
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "FREQBLOG_API_KEY",
    "GETSONGBPM_API_KEY",
    "BRAVE_API_KEY",
    # Display settings. Same file as the keys on purpose: one place to look,
    # and they are catalog preferences, not per-playlist state.
    "GRAPH_MAX_BPM",
    "TIMELINE_ON",
    "FELT_FOLD",
    "TEMPO_TOLERANCE",
    "WARN_BOTH_OFF",
    "PREVIEW_SECONDS",
    "AUTOSAVE_ON",
    "AUTOSAVE_SECONDS",
)

# name -> (default, lo, hi) for the numeric display settings
DISPLAY_DEFAULTS = {
    "GRAPH_MAX_BPM": (200, 60, 300),
    "FELT_FOLD": (165, 100, 200),
    "PREVIEW_SECONDS": (20, 5, 60),
    "AUTOSAVE_SECONDS": (2, 1, 300),
}
TOLERANCES = {"tight": 0.03, "normal": 0.06, "loose": 0.08}


def display_settings(env: dict | None = None) -> dict:
    """Typed display settings out of the .env strings, defaults applied."""
    env = env if env is not None else load_env()

    def num(key):
        default, lo, hi = DISPLAY_DEFAULTS[key]
        try:
            return min(hi, max(lo, int(float(env.get(key, "")))))
        except (TypeError, ValueError):
            return default

    def flag(key, default=True):
        v = str(env.get(key, "")).strip().lower()
        if v in ("1", "true", "on", "yes"):
            return True
        if v in ("0", "false", "off", "no"):
            return False
        return default

    tol = str(env.get("TEMPO_TOLERANCE", "")).strip().lower()
    if tol not in TOLERANCES:
        tol = "normal"

    return {
        "graph_max": num("GRAPH_MAX_BPM"),
        "timeline": flag("TIMELINE_ON", default=False),
        "felt_fold": num("FELT_FOLD"),
        "tolerance": tol,
        "warn_both": flag("WARN_BOTH_OFF"),
        "preview_s": num("PREVIEW_SECONDS"),
        "autosave_on": flag("AUTOSAVE_ON"),
        "autosave_s": num("AUTOSAVE_SECONDS"),
    }

# Keys without which the app cannot do its job.
REQUIRED = ("SPOTIFY_CLIENT_ID", "FREQBLOG_API_KEY")


def user_config_dir() -> Path:
    """Where settings entered in the app are written.

    Not next to the exe: that folder is replaced wholesale on every rebuild,
    so anything saved there would be lost.
    """
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP


def env_path() -> Path:
    return user_config_dir() / ".env"


def _read_env_file(path: Path) -> dict:
    """Minimal .env reader. KEY=value, # comments, no quoting rules."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_env() -> dict:
    """Later sources win: bundled file, then the user's own, then the real
    environment (so a key can be overridden without editing anything)."""
    env = _read_env_file(app_dir() / ".env")
    env.update(_read_env_file(env_path()))
    for k in KEYS:
        if os.environ.get(k):
            env[k] = os.environ[k]
    return {k: v for k, v in env.items() if v}


def save_env(values: dict) -> Path:
    """Write the user's own .env. Blank entries are dropped rather than stored
    as empty strings, so 'not set' and 'set to nothing' stay the same thing."""
    path = env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Playlist Flow settings. Written by the app — safe to edit by hand.",
        "# Never commit this file.",
        "",
    ]
    for k in KEYS:
        v = (values.get(k) or "").strip()
        if v:
            lines.append(f"{k}={v}")
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def missing_required(env: dict | None = None) -> list[str]:
    env = env if env is not None else load_env()
    return [k for k in REQUIRED if not env.get(k)]


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
