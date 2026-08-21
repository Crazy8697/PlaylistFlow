"""Self-updating from GitHub Releases.

The release channel is the public repo's Releases feed — recipients need no
account and no key, just the zip this app shipped in. The flow:

    check_update()   compare the latest release tag against __version__
    UpdateWorker     download the asset, verify the zip, extract to staging
    apply_update()   write a batch script that waits for this process to exit,
                     swaps the install directory, and relaunches

The swap cannot happen in-process on Windows — a running exe cannot replace
itself — hence the script. User data is safe by construction: keys live in
%APPDATA%\\PlaylistFlow, playlists in Documents, the Spotify token in
QSettings. Nothing in the install directory is user state.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal

from . import __version__
from .config import app_dir

REPO = "Crazy8697/PlaylistFlow"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_SUFFIX = "-win64.zip"
UA = {"User-Agent": f"PlaylistFlow/{__version__}"}


def _ver_tuple(v: str) -> tuple:
    """'v1.2.0' -> (1, 2, 0). Non-numeric parts compare as zero."""
    out = []
    for part in v.strip().lstrip("vV").split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def check_update(timeout: int = 10) -> dict | None:
    """The newest release, or None when current (or unreachable).

    Raises nothing: an updater must never be the reason the app fails to
    start, so every failure collapses to 'no update'.
    """
    try:
        r = requests.get(API_LATEST, headers=UA, timeout=timeout)
        if r.status_code != 200:
            return None
        j = r.json()
        latest = j.get("tag_name", "")
        if _ver_tuple(latest) <= _ver_tuple(__version__):
            return None
        asset = next((a for a in j.get("assets", [])
                      if a.get("name", "").endswith(ASSET_SUFFIX)), None)
        if not asset:
            return None
        return {
            "version": latest.lstrip("vV"),
            "notes": (j.get("body") or "").strip(),
            "url": asset["browser_download_url"],
            "size": asset.get("size", 0),
        }
    except Exception:
        return None


class UpdateWorker(QThread):
    """Download and stage. The swap itself happens after the app exits."""

    progress = Signal(int, int)      # bytes done, total
    ready = Signal(str)              # staging dir
    failed = Signal(str)

    def __init__(self, url: str, size: int, parent=None):
        super().__init__(parent)
        self.url = url
        self.size = size

    def run(self):
        try:
            staging = app_dir() / "update-staging"
            if staging.exists():
                import shutil
                shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)

            zpath = Path(tempfile.gettempdir()) / "playlistflow-update.zip"
            done = 0
            with requests.get(self.url, headers=UA, stream=True,
                              timeout=60) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or self.size or 0)
                with open(zpath, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        fh.write(chunk)
                        done += len(chunk)
                        self.progress.emit(done, total)

            with zipfile.ZipFile(zpath) as z:
                # A truncated download fails here rather than mid-swap.
                if z.testzip() is not None:
                    raise RuntimeError("downloaded archive is corrupt")
                z.extractall(staging)
            zpath.unlink(missing_ok=True)

            if not (staging / "PlaylistFlow.exe").exists():
                raise RuntimeError("archive does not look like a PlaylistFlow build")
            self.ready.emit(str(staging))
        except Exception as e:
            self.failed.emit(str(e))


def apply_update(staging: str) -> None:
    """Hand off to a batch script and let the caller close the app.

    robocopy /E overwrites into place; _internal is deleted first so files
    dropped between versions cannot linger and shadow-import. robocopy's
    success exit codes are 0-7, hence the errorlevel dance.
    """
    install = app_dir()
    exe = Path(sys.executable if getattr(sys, "frozen", False)
               else install / "PlaylistFlow.exe")
    pid = os.getpid()
    bat = Path(tempfile.gettempdir()) / "playlistflow-apply-update.bat"
    bat.write_text(
        "@echo off\r\n"
        ":wait\r\n"
        f"tasklist /FI \"PID eq {pid}\" 2>nul | find \"{pid}\" >nul\r\n"
        "if not errorlevel 1 (timeout /t 1 /nobreak >nul & goto wait)\r\n"
        f"rd /s /q \"{install}\\_internal\" 2>nul\r\n"
        f"robocopy \"{staging}\" \"{install}\" /E /NFL /NDL /NJH /NJS >nul\r\n"
        "if errorlevel 8 (\r\n"
        "  echo Update failed - files are in update-staging. & pause & exit /b 1\r\n"
        ")\r\n"
        f"rd /s /q \"{staging}\" 2>nul\r\n"
        f"start \"\" \"{exe}\"\r\n"
        "del \"%~f0\"\r\n",
        encoding="ascii")
    subprocess.Popen(["cmd", "/c", str(bat)],
                     creationflags=subprocess.CREATE_NO_WINDOW,
                     close_fds=True)


def can_self_update() -> bool:
    """Source checkouts update with git, not by overwriting themselves."""
    return bool(getattr(sys, "frozen", False))
