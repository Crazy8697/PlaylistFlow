"""Disk persistence.

Two files per playlist:
  <name>.json        written only on an explicit save
  <name>-auto.json   written continuously as you edit

The auto file never overwrites the manual save. Loading prefers the auto file
when it is newer, but the manual save is always recoverable.

cache.json holds resolved BPM/key keyed by URI/ISRC so a track is only ever
looked up or typed once.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .domain import Track

CACHE_FILE = "cache.json"


def safe_name(name: str) -> str:
    n = re.sub(r'[<>:"/\\|?*]', "_", (name or "").strip())
    n = re.sub(r"\s+", " ", n).strip(" .")
    return n[:120] or "untitled"


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict] | None = None

    # ---------------- playlists ----------------

    def _paths(self, name: str) -> tuple[Path, Path]:
        base = safe_name(name)
        return self.root / f"{base}.json", self.root / f"{base}-auto.json"

    def list_playlists(self) -> list[str]:
        names = set()
        for p in self.root.glob("*.json"):
            if p.name == CACHE_FILE:
                continue
            stem = p.stem
            if stem.endswith("-auto"):
                stem = stem[: -len("-auto")]
            names.add(stem)
        return sorted(names, key=str.lower)

    def save(self, name: str, tracks: list[Track], auto: bool = False,
             pid: str = "", description: str = "",
             ear_checked: list | None = None) -> Path:
        manual_p, auto_p = self._paths(name)
        target = auto_p if auto else manual_p
        payload = {
            "name": name,
            "saved": time.time(),
            "auto": auto,
            # Remembered so a reopened playlist can still be pushed back.
            "spotify_id": pid,
            # The user's note about what the set is for; shown while working so
            # a track can be judged against the intent, not just the key.
            "description": description,
            # seam_key() ids of transitions the user has listened to and
            # approved -- pair-keyed, so they survive reordering.
            "ear_checked": sorted(ear_checked or []),
            "tracks": [t.to_dict() for t in tracks],
        }
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(target)
        return target

    def load(self, name: str, prefer_auto: bool = True) -> list[Track]:
        manual_p, auto_p = self._paths(name)
        pick = None
        if prefer_auto and auto_p.exists() and manual_p.exists():
            pick = auto_p if auto_p.stat().st_mtime > manual_p.stat().st_mtime else manual_p
        else:
            pick = auto_p if (prefer_auto and auto_p.exists()) else manual_p
            if not pick.exists():
                pick = auto_p if auto_p.exists() else manual_p
        if not pick.exists():
            return []
        data = json.loads(pick.read_text(encoding="utf-8"))
        self._last_pid = data.get("spotify_id", "") or ""
        self._last_desc = data.get("description", "") or ""
        self._last_checked = data.get("ear_checked", []) or []
        return [Track.from_dict(d) for d in data.get("tracks", [])]

    @property
    def last_loaded_checked(self) -> list:
        """Ear-checked seam ids of the most recent load()."""
        return list(getattr(self, "_last_checked", []))

    @property
    def last_loaded_desc(self) -> str:
        """Description of the most recent load()."""
        return getattr(self, "_last_desc", "")

    @property
    def last_loaded_pid(self) -> str:
        """Spotify playlist id of the most recent load(), if it had one."""
        return getattr(self, "_last_pid", "")

    def has_newer_auto(self, name: str) -> bool:
        manual_p, auto_p = self._paths(name)
        if not auto_p.exists():
            return False
        if not manual_p.exists():
            return True
        return auto_p.stat().st_mtime > manual_p.stat().st_mtime

    def rename(self, old: str, new: str) -> None:
        om, oa = self._paths(old)
        nm, na = self._paths(new)
        if om.exists():
            om.replace(nm)
        if oa.exists():
            oa.replace(na)

    def delete(self, name: str) -> None:
        for p in self._paths(name):
            if p.exists():
                p.unlink()

    def delete_all(self) -> None:
        for name in self.list_playlists():
            self.delete(name)

    # ---------------- track cache ----------------

    def _load_cache(self) -> dict:
        if self._cache is None:
            p = self.root / CACHE_FILE
            try:
                self._cache = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            except (OSError, json.JSONDecodeError):
                self._cache = {}
        return self._cache

    @staticmethod
    def cache_key(track: Track) -> str:
        if track.uri:
            return f"uri:{track.uri}"
        if track.isrc:
            return f"isrc:{track.isrc}"
        return f"name:{track.artist.strip().lower()}|{track.title.strip().lower()}"

    def cache_get(self, track: Track) -> dict | None:
        return self._load_cache().get(self.cache_key(track))

    def cache_put(self, track: Track) -> None:
        if not track.resolved:
            return
        c = self._load_cache()
        c[self.cache_key(track)] = {
            "bpm": track.bpm,
            "key": track.key,
            "source": track.source,
            "bpm_conf": track.bpm_conf,
            "key_conf": track.key_conf,
            "manual": track.manual,
            "isrc": track.isrc,
        }
        self.flush_cache()

    def flush_cache(self) -> None:
        if self._cache is None:
            return
        p = self.root / CACHE_FILE
        tmp = p.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass

    def apply_cache(self, track: Track) -> bool:
        """Fill a track from cache. Returns True when it was filled.
        A cached manual value wins over anything a fetch would produce."""
        hit = self.cache_get(track)
        if not hit:
            return False
        track.bpm = hit.get("bpm", 0.0) or 0.0
        track.key = hit.get("key", "") or ""
        track.source = hit.get("source", "") or ""
        track.bpm_conf = hit.get("bpm_conf")
        track.key_conf = hit.get("key_conf")
        track.manual = bool(hit.get("manual"))
        if hit.get("isrc") and not track.isrc:
            track.isrc = hit["isrc"]
        return track.resolved
