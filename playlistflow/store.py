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
# Inside cache.json: when a track FreqBlog queued (202) or could not find may be asked
# about again. Keyed like the cache; never sent anywhere.
WAIT_KEY = "_lookup_wait"
# Re-check delays for a queued track, by how many checks it has had. Every check is a
# request (a queued track sent again by name within 30 days is collected free).
# FreqBlog: analysis is usually ready within a minute, so the first re-check comes
# after 45 seconds; later ones keep the longer waits.
QUEUED_DELAYS = (45, 600, 3600, 6 * 3600, 86400)
MISSING_DAYS = 7          # a track found nowhere is asked about again after this


class StoreError(RuntimeError):
    """A playlist file or the folder could not be read or written. The message is
    plain enough to show as is."""


def safe_name(name: str) -> str:
    n = re.sub(r'[<>:"/\\|?*]', "_", (name or "").strip())
    n = re.sub(r"\s+", " ", n).strip(" .")
    return n[:120] or "untitled"


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise StoreError(f"Can't use the playlist folder {self.root}: "
                             f"{e.strerror or e}. Pick another one in Settings.") from None
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
        try:
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(target)
        except OSError as e:
            raise StoreError(f"Couldn't save '{name}' to {self.root}: {e.strerror or e}.") from None
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
        try:
            data = json.loads(pick.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("tracks", []), list):
                raise ValueError("not a playlist file")
            tracks = [Track.from_dict(d) for d in data.get("tracks", []) if isinstance(d, dict)]
        except (OSError, ValueError, TypeError) as e:
            raise StoreError(f"Couldn't read {pick.name}: it is damaged or not a Playlist Flow "
                             f"file ({e}). The other save of this playlist, if there is one, "
                             "is untouched.") from None
        self._last_pid = data.get("spotify_id", "") or ""
        self._last_desc = data.get("description", "") or ""
        self._last_checked = data.get("ear_checked", []) or []
        return tracks

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

    def meta(self, name: str) -> dict:
        """Description and ear-checks of a saved playlist, without loading it.

        Same file preference as load(). Used when a playlist is re-fetched from
        Spotify: the track list comes from the API, but the ear-checks only
        exist locally, and being pair-keyed they apply cleanly to the fresh
        list -- pairs that no longer exist simply match nothing.
        """
        manual_p, auto_p = self._paths(name)
        pick = None
        if auto_p.exists() and manual_p.exists():
            pick = auto_p if auto_p.stat().st_mtime > manual_p.stat().st_mtime else manual_p
        else:
            pick = auto_p if auto_p.exists() else manual_p
        if not pick.exists():
            return {}
        try:
            data = json.loads(pick.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {
            "description": data.get("description", "") or "",
            "ear_checked": data.get("ear_checked", []) or [],
        }

    def refresh_metadata(self, name: str, meta: dict) -> int:
        """Bring the stored titles and artists of a saved playlist up to date with
        Spotify (Developer Terms IV.3.1: stored Spotify content kept current).

        `meta` is uri -> (title, artist). Both the save and the auto-save are updated
        in place; only those two fields of matching tracks change, never the order,
        BPM/key, ear-checks or anything else, and a track missing from `meta` is left
        exactly as stored. Each file keeps its modified time, so which of the two is
        newer (and so which one opens) doesn't change. Returns how many track entries
        changed across both files."""
        import os
        changed = 0
        for path in self._paths(name):
            if not path.exists():
                continue
            try:
                st = path.stat()
                data = json.loads(path.read_text(encoding="utf-8"))
                tracks = data.get("tracks") if isinstance(data, dict) else None
                if not isinstance(tracks, list):
                    continue
                n = 0
                for d in tracks:
                    if not isinstance(d, dict):
                        continue
                    got = meta.get(d.get("uri") or "")
                    if not got:
                        continue
                    title, artist = got
                    if title and (d.get("title") != title or d.get("artist") != artist):
                        d["title"], d["artist"] = title, artist
                        n += 1
                if not n:
                    continue
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
                tmp.replace(path)
                os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
                changed += n
            except (OSError, ValueError, TypeError):
                continue                 # best effort: the playlist stays as stored
        return changed

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

    def delete_program_files(self) -> list[str]:
        """Delete everything Playlist Flow wrote into this folder and nothing else:
        saved playlists (manual and auto), cache.json and leftover .tmp files of
        those. Other files that happen to be in the folder are left alone, and so is
        the folder itself. Returns the names deleted."""
        gone = []
        for p in sorted(self.root.glob("*")):
            if not p.is_file():
                continue
            ours = False
            if p.name in (CACHE_FILE, CACHE_FILE.replace(".json", ".tmp")):
                ours = True
            elif p.suffix in (".json", ".tmp"):
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    ours = isinstance(d, dict) and "tracks" in d and "saved" in d
                except (OSError, ValueError):
                    ours = False
            if ours:
                try:
                    p.unlink()
                    gone.append(p.name)
                except OSError:
                    pass
        self._cache = {}
        return gone

    # ---------------- track cache ----------------

    def _load_cache(self) -> dict:
        if self._cache is None:
            p = self.root / CACHE_FILE
            try:
                self._cache = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            except (OSError, ValueError):
                self._cache = {}
            if not isinstance(self._cache, dict):
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
        hit = self._load_cache().get(self.cache_key(track))
        return hit if isinstance(hit, dict) else None

    def cache_put(self, track: Track) -> None:
        if not track.resolved:
            return
        c = self._load_cache()
        self._waits().pop(self.cache_key(track), None)
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

    # ---------------- when to ask FreqBlog again ----------------

    def _waits(self) -> dict:
        c = self._load_cache()
        w = c.get(WAIT_KEY)
        if not isinstance(w, dict):
            w = c[WAIT_KEY] = {}
        return w

    def lookup_due(self, track: Track, now: float | None = None) -> bool:
        """False while a queued or missing track is still inside its wait."""
        w = self._waits().get(self.cache_key(track))
        if not isinstance(w, dict):
            return True
        return (time.time() if now is None else now) >= float(w.get("next") or 0)

    def waiting(self, track: Track) -> dict | None:
        w = self._waits().get(self.cache_key(track))
        return w if isinstance(w, dict) else None

    def mark_waiting(self, track: Track, kind: str, retry_after_days: float | None = None,
                     now: float | None = None) -> float:
        """Record that FreqBlog queued ("queued") or could not find ("missing") the
        track, and when it may be asked again: retry_after_days when FreqBlog gave
        one, else a growing delay for queued tracks and MISSING_DAYS for missing
        ones. Returns that time."""
        now = time.time() if now is None else now
        waits = self._waits()
        key = self.cache_key(track)
        prev = waits.get(key) if isinstance(waits.get(key), dict) else {}
        checks = int(prev.get("checks", 0)) + 1 if prev.get("kind") == kind else 1
        if retry_after_days:
            delay = float(retry_after_days) * 86400
        elif kind == "queued":
            delay = QUEUED_DELAYS[min(checks - 1, len(QUEUED_DELAYS) - 1)]
        else:
            delay = MISSING_DAYS * 86400
        waits[key] = {"kind": kind, "checks": checks, "next": now + delay}
        self.flush_cache()
        return now + delay

    def clear_waiting(self, track: Track) -> None:
        if self._waits().pop(self.cache_key(track), None) is not None:
            self.flush_cache()
