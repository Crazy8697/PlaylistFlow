"""Updates, the Lazarus PDF / PhoneDeck pattern.

The ONLY network requests this module makes:
  1. GET https://api.github.com/repos/Crazy8697/PlaylistFlow/releases/latest (GitHub's "latest
     release" endpoint: drafts and prereleases are never returned), a few seconds after startup
     when Settings > "Check for updates at startup" is on, or from Help > Check for updates;
  2. when the user chooses to update: the release's .sha256 file and its Setup .exe.
Nothing is sent but the request itself (a plain "PlaylistFlow" User-Agent, which GitHub
requires). No key, token or setting ever goes into these URLs.

A release counts only when its tag is a version newer than this one AND it carries the
constant-name installer PlaylistFlow-Setup.exe plus PlaylistFlow-Setup.exe.sha256. Anything
else (an old zip-only release, a release without a checksum) is ignored as if it weren't there.
The download goes to %APPDATA%\\PlaylistFlow\\update-staging (a .part file renamed into place
when complete) and is used only if its SHA-256 matches the published one; a missing or wrong
hash is refused and the file deleted. Setup then runs with Inno Setup's switches
(UPDATE_SETUP_ARGS) so it upgrades the installed copy in place (same AppId), with one UAC
prompt, keeping every setting, and starts Playlist Flow again (unelevated) when done; Playlist
Flow exits itself first.

Dev / test hooks (never set in normal use): PLAYLISTFLOW_UPDATE_URL points the check at another
URL (a local mock server); PLAYLISTFLOW_UPDATE_DRYRUN=<file> writes the Setup command line there
instead of starting it; PLAYLISTFLOW_UPDATE_TIMEOUT overrides the network timeout (seconds).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import __version__
from .config import user_config_dir

REPO = "Crazy8697/PlaylistFlow"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
SETUP_NAME = "PlaylistFlow-Setup.exe"
SHA_NAME = SETUP_NAME + ".sha256"
UPDATE_TIMEOUT = 10.0
UPDATE_CHUNK = 256 * 1024
UPDATE_STARTUP_DELAY_MS = 4000
UPDATE_SETUP_ARGS = ["/SILENT", "/SP-", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1"]


class UpdateError(Exception):
    """Something the user should be told, in plain words."""


class UpdateCancelled(Exception):
    pass


def parse_version(text):
    """'v1.2.3' / '1.2' / '1.2.3-rc1' -> comparable tuple, or None if it isn't a version.
    A suffix (a prerelease) sorts below the same numbers without one."""
    m = re.fullmatch(r"\s*v?(\d+(?:\.\d+){0,3})(?:[-+.]?([0-9A-Za-z.]+))?\s*", str(text or ""))
    if not m:
        return None
    nums = [int(x) for x in m.group(1).split(".")]
    nums += [0] * (4 - len(nums))
    return tuple(nums) + ((0,) if m.group(2) else (1,))


def is_newer(tag, current=__version__):
    a, b = parse_version(tag), parse_version(current)
    return a is not None and b is not None and a > b


def can_install() -> bool:
    """Only an installed (frozen) Playlist Flow updates itself: a source run never installs."""
    return bool(getattr(sys, "frozen", False))


def staging_dir() -> Path:
    """Outside the install folder, which is read-only to the program under Program Files."""
    return user_config_dir() / "update-staging"


def _update_timeout() -> float:
    try:
        return float(os.environ.get("PLAYLISTFLOW_UPDATE_TIMEOUT") or UPDATE_TIMEOUT)
    except ValueError:
        return UPDATE_TIMEOUT


def _http_get(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "PlaylistFlow",
                                               "X-GitHub-Api-Version": "2022-11-28"})
    return urllib.request.urlopen(req, timeout=_update_timeout())


def _net_reason(e) -> str:
    import socket
    if isinstance(e, urllib.error.HTTPError):
        if e.code in (403, 429) and (e.headers.get("X-RateLimit-Remaining") == "0" or e.code == 429):
            return "GitHub's rate limit for checks from this network was reached; try again later."
        return f"GitHub answered with an error ({e.code})."
    if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in str(e).lower():
        return "GitHub didn't answer in time."
    if isinstance(e, urllib.error.URLError):
        return "No connection to GitHub (offline, or blocked)."
    return f"{type(e).__name__}."


def check_release(current=__version__) -> dict:
    """-> dict: status "newer" | "current" | "none" (nothing usable published) | "error";
    version, notes, setup_url, sha_url, page; reason (for "error"). Never raises."""
    url = os.environ.get("PLAYLISTFLOW_UPDATE_URL") or RELEASES_API
    try:
        with _http_get(url) as r:
            body = r.read(2_000_000)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"status": "none"}
        return {"status": "error", "reason": _net_reason(e)}
    except Exception as e:                       # offline, timeout, anything: told, never raised
        return {"status": "error", "reason": _net_reason(e)}
    try:
        rel = json.loads(body.decode("utf-8"))
        if not isinstance(rel, dict):
            raise ValueError("not an object")
    except Exception:
        return {"status": "error", "reason": "GitHub's reply wasn't readable."}
    if rel.get("draft") or rel.get("prerelease"):
        return {"status": "none"}                # (the endpoint never returns these; a mock might)
    tag = str(rel.get("tag_name") or "")
    if parse_version(tag) is None:
        return {"status": "none"}
    assets = {a.get("name", ""): a.get("browser_download_url")
              for a in rel.get("assets") or [] if isinstance(a, dict)}
    if not assets.get(SETUP_NAME) or not assets.get(SHA_NAME):
        # a release this updater can't install safely (an old zip-only one): not there at all
        return {"status": "none"}
    out = {"version": tag.lstrip("vV"), "notes": str(rel.get("body") or "").strip(),
           "page": rel.get("html_url") or RELEASES_URL,
           "setup_url": assets[SETUP_NAME], "sha_url": assets[SHA_NAME]}
    out["status"] = "newer" if is_newer(tag, current) else "current"
    return out


def expected_hash(sha_url) -> str:
    if not sha_url:
        raise UpdateError("The release has no .sha256 checksum, so the download can't be "
                          "verified. Not installing.")
    try:
        with _http_get(sha_url, accept="application/octet-stream") as r:
            text = r.read(4096).decode("ascii", "replace")
    except Exception as e:
        raise UpdateError(f"Couldn't get the release's checksum: {_net_reason(e)}")
    m = re.search(r"\b([0-9a-fA-F]{64})\b", text)
    if not m:
        raise UpdateError("The release's .sha256 file holds no SHA-256 checksum. Not installing.")
    return m.group(1).lower()


def download_update(info, progress=None, stopped=None, folder=None) -> str:
    """The release's Setup into update-staging (or folder), verified. -> its path.
    Raises UpdateError / UpdateCancelled; nothing is left behind then."""
    if not info.get("setup_url"):
        raise UpdateError(f"The release has no installer ({SETUP_NAME}) attached.")
    want = expected_hash(info.get("sha_url"))
    try:
        folder = Path(folder) if folder else staging_dir()
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise UpdateError(f"Couldn't create the download folder ({type(e).__name__}).")
    dest = folder / f"PlaylistFlow-Setup-{info.get('version', 'update')}.exe"
    part = Path(str(dest) + ".part")
    h = hashlib.sha256()
    try:
        with _http_get(info["setup_url"], accept="application/octet-stream") as r, \
                open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if stopped is not None and stopped():
                    raise UpdateCancelled()
                buf = r.read(UPDATE_CHUNK)
                if not buf:
                    break
                f.write(buf)
                h.update(buf)
                done += len(buf)
                if progress is not None:
                    progress(done, total)
        if h.hexdigest() != want:
            raise UpdateError("The download doesn't match the release's SHA-256 checksum. "
                              "It was deleted; nothing is installed.")
        os.replace(part, dest)
        return str(dest)
    except (UpdateError, UpdateCancelled):
        raise
    except Exception as e:
        raise UpdateError(f"The download failed: {_net_reason(e)}")
    finally:
        try:
            if part.exists():
                part.unlink()
        except OSError:
            pass


def setup_command(setup) -> list:
    return [str(setup)] + UPDATE_SETUP_ARGS


def launch_setup(setup) -> bool:
    """Start Setup the way Explorer would (ShellExecute: it asks for elevation itself, one UAC
    prompt). The dry-run hook writes the command line instead. Never raises."""
    cmd = setup_command(setup)
    try:
        dry = os.environ.get("PLAYLISTFLOW_UPDATE_DRYRUN")
        if dry:
            with open(dry, "w", encoding="utf-8") as f:
                json.dump(cmd, f)
            return True
        import ctypes
        r = ctypes.windll.shell32.ShellExecuteW(None, "open", cmd[0],
                                                subprocess.list2cmdline(cmd[1:]), None, 1)
        return r > 32
    except Exception:
        return False


class UpdateChecker(QThread):
    """check_release() off the UI thread."""
    result = Signal(dict)

    def run(self):
        try:
            self.result.emit(check_release())
        except Exception:                        # belt and braces: check_release never raises
            self.result.emit({"status": "error", "reason": "The update check failed."})


class UpdateDownloader(QThread):
    """download_update() off the UI thread, with progress and cancel."""
    progress = Signal(int, int)     # bytes done, total (0 = unknown)
    done = Signal(object, str)      # path or None, error text ("" = ok, "cancelled")

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.cancelled = False

    def run(self):
        try:
            path = download_update(self.info, lambda d, t: self.progress.emit(d, t),
                                   lambda: self.cancelled)
            self.done.emit(path, "")
        except UpdateCancelled:
            self.done.emit(None, "cancelled")
        except UpdateError as e:
            self.done.emit(None, str(e))
        except Exception as e:
            self.done.emit(None, f"The update failed ({type(e).__name__}).")
