"""The documents that ship next to the program: the privacy policy, the end user
agreement, the license and the third-party notices.

AGREEMENT_VERSION is the version printed at the top of PRIVACY.md and TERMS.md. The
version a user accepted is kept in HKCU (Prefs.agreement_version); when this changes,
the wizard shows both documents again before the next Spotify sign-in.
"""

from __future__ import annotations

import sys
from pathlib import Path

AGREEMENT_VERSION = "2026-10-17.2"

# file name in the repo -> file name next to the installed exe
SHIPPED = {"PRIVACY.md": "PRIVACY.md", "TERMS.md": "TERMS.md", "LICENSE": "LICENSE.txt",
           "NOTICE": "NOTICE.txt", "THIRD-PARTY-NOTICES.md": "THIRD-PARTY-NOTICES.md"}


def base_dir() -> Path:
    """Next to PlaylistFlow.exe when installed, the repo root when run from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def doc_path(name: str) -> Path:
    b = base_dir()
    p = b / SHIPPED.get(name, name)
    return p if p.exists() else b / name


def read_doc(name: str) -> str:
    try:
        return doc_path(name).read_text(encoding="utf-8")
    except OSError:
        return (f"{name} is missing from this copy of Playlist Flow. It is also at "
                f"https://github.com/Crazy8697/PlaylistFlow/blob/main/{name}")


def licenses_dir() -> Path:
    return base_dir() / "licenses"
