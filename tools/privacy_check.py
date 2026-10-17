"""Refuse to publish if Playlist Flow carries something private: a personal Windows user path, a
home-network address or hostname, an e-mail address, a token or key, a filled-in .env line, or an
em dash. build.ps1 -Release runs it before anything goes public; run it by hand any time:

    python tools/privacy_check.py                 the tracked (and new, unignored) files
    python tools/privacy_check.py --dist          also the frozen build in dist\\PlaylistFlow (its
                                                  PyInstaller archive is unpacked and scanned too)
    python tools/privacy_check.py --root <dir>    check another copy of the tree (tests)

Exit 1 and a list of file:line (or file: for the build) if anything is found. Findings name the
file, line and kind of match only, never the matched text.

The patterns are generic, so nothing private is written here. Exact values that no generic
pattern catches (a real name, a family member, a playlist name) go one per line in
tools/privacy-local.txt, which is gitignored and never leaves this PC. Real API keys are caught
two ways, and neither stores a key in a tracked file:
  - every secret in the real .env files on this PC (%APPDATA%\\PlaylistFlow\\.env, written by the
    setup wizard, and a .env next to this repo if there is one) is searched for verbatim;
  - "sha256:<hex>" lines in privacy-local.txt are fingerprints of real keys: every key-shaped
    token in a file is hashed and compared, so a key is caught even when no .env is on this PC
    (between setups, or on a clean machine). Add fingerprints from a .env with
        python tools/privacy_check.py --remember <path to .env> [...]
    which appends the SHA-256 of each secret in it and prints only how many it added. Binary files in the tree are skipped; license texts quote their
authors' addresses, so those are skipped too.

Allowed on purpose: Crazy8697, darkrelay.net itself (not its subdomains), the GitHub noreply
address, 127.0.0.1."""
import hashlib
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOCAL = HERE / "privacy-local.txt"
ENV_KEYS = ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "FREQBLOG_API_KEY", "GETSONGBPM_API_KEY",
            "BRAVE_API_KEY")

USER_PATH = ("a personal user path",
             re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|Default\b|<|%|\$|\{)[A-Za-z0-9_.-]+", re.I))
PRIVATE_IP = ("a private network address",
              re.compile(r"(?<!Version: )(?<![\d.])(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))"
                         r"\.\d{1,3}\.\d{1,3}(?![\d.])"))
TAILNET = ("a tailnet name", re.compile(r"\btailscale\b|\.ts\.net\b|\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b", re.I))
HOMELAB = ("a home-lab hostname",
           re.compile(r"\bnexus(?:-config|-wire|\.)|\bhal9000\b|\bhal69000\b|[a-z0-9-]+\.darkrelay\.net", re.I))
TOKEN = ("a token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|\beyJ[A-Za-z0-9_-]{20,}\.eyJ"
                               r"|\bfb_(?:live|test)_[A-Za-z0-9]{8,}"))
KEY = ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"))
EMAIL = ("an e-mail address",
         re.compile(r"\b[A-Za-z0-9._%+-]+@(?!example\.|users\.noreply\.github\.com\b|github\.com\b)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"))
# a key name followed by a value, the shape of a filled-in .env line (placeholders stay empty)
ENV_LINE = ("a filled-in .env line",
            re.compile(r"^\s*(?:" + "|".join(ENV_KEYS) + r")\s*=\s*[^\s#]+", re.M))
EMDASH = ("an em dash", re.compile(chr(0x2014)))

TREE_PATTERNS = [USER_PATH, PRIVATE_IP, TAILNET, HOMELAB, TOKEN, KEY, EMAIL, ENV_LINE, EMDASH]
# the frozen build is mostly third-party binaries (Qt, Python) whose strings carry their own
# authors' addresses and sample IPs; there, look only for what could only be ours
# (Qt's and other vendors' DLLs carry PDB paths from their CI machines' user folders: the "qt"
# user and the usual CI accounts are not ours)
DIST_USER_PATH = ("a personal user path",
                  re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|Default\b|qt\b|runneradmin\b|"
                             r"VssAdministrator\b|appveyor\b|<|%|\$|\{)[A-Za-z0-9_.-]+", re.I))
DIST_PATTERNS = [DIST_USER_PATH, HOMELAB, TOKEN, KEY]
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".ico", ".ttf", ".pdf"}
SKIP_PREFIX = ("licenses/", "LICENSE")   # verbatim official license texts
SKIP_FILES = {"tools/privacy-local.txt"}


def local_values(ignore_case=True):
    """Exact private strings from the gitignored tools/privacy-local.txt (# comments allowed).

    Every value matches as a whole word. A line starting with "case:" is matched
    case-sensitively everywhere, for a private value that is also an ordinary word in lower
    case (a playlist named after one, say). In the build every value is matched
    case-sensitively and only against our own files (see check_dist): names are ordinary words
    in other languages and other vendors' strings, and compressed data throws up short letter
    runs at random."""
    if not LOCAL.is_file():
        return []
    out = []
    for ln in LOCAL.read_text(encoding="utf-8-sig").splitlines():
        v = ln.strip()
        if not v or v.startswith("#") or v.startswith("sha256:"):
            continue
        exact = v.startswith("case:")
        if exact:
            v = v[len("case:"):].strip()
        flags = re.I if (ignore_case and not exact) else 0
        out.append(("a private value from privacy-local.txt",
                    re.compile(r"(?<![A-Za-z0-9])" + re.escape(v) + r"(?![A-Za-z0-9])", flags)))
    return out


KEY_TOKEN = re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]{16,128}(?![A-Za-z0-9_\-])")


class _Fingerprints:
    """Duck-types re.Pattern.search: true when a key-shaped token in the text has one of
    the stored SHA-256 fingerprints. The values themselves are never needed or printed."""

    def __init__(self, hashes):
        self.hashes = set(hashes)

    def search(self, text):
        for m in KEY_TOKEN.finditer(text):
            if hashlib.sha256(m.group(0).encode("utf-8", "replace")).hexdigest() in self.hashes:
                return m
        return None


def fingerprints():
    """("a stored key fingerprint", matcher) from the sha256: lines in privacy-local.txt."""
    if not LOCAL.is_file():
        return []
    hs = [ln.strip()[len("sha256:"):].strip().lower()
          for ln in LOCAL.read_text(encoding="utf-8-sig").splitlines()
          if ln.strip().startswith("sha256:")]
    hs = [h for h in hs if re.fullmatch(r"[0-9a-f]{64}", h)]
    return [("a value matching a stored key fingerprint", _Fingerprints(hs))] if hs else []


def env_secrets(path):
    """The secret values in one .env file (the key names in ENV_KEYS), never printed."""
    vals = set()
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return vals
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if k.strip() in ENV_KEYS and len(v) >= 8:
            vals.add(v)
    return vals


def remember(paths):
    """Append the fingerprints of every secret in these .env files to privacy-local.txt."""
    have = set()
    if LOCAL.is_file():
        have = {ln.strip()[len("sha256:"):].strip().lower()
                for ln in LOCAL.read_text(encoding="utf-8-sig").splitlines()
                if ln.strip().startswith("sha256:")}
    new = []
    for p in paths:
        for v in env_secrets(p):
            h = hashlib.sha256(v.encode("utf-8")).hexdigest()
            if h not in have:
                have.add(h)
                new.append(h)
    if new:
        text = LOCAL.read_text(encoding="utf-8-sig") if LOCAL.is_file() else ""
        if text and not text.endswith("\n"):
            text += "\n"
        text += "".join(f"sha256:{h}\n" for h in new)
        LOCAL.write_text(text, encoding="utf-8")
    print(f"privacy check: remembered {len(new)} new key fingerprint(s), {len(have)} stored")
    return 0


def env_values(root):
    """Every value in the real .env files on this PC, as exact strings. Never printed."""
    paths = [root / ".env"]
    if os.environ.get("APPDATA"):
        paths.append(Path(os.environ["APPDATA"]) / "PlaylistFlow" / ".env")
    vals = set()
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            # only secrets: display settings are short numbers and words
            if k.strip() in ENV_KEYS and len(v) >= 8:
                vals.add(v)
    return [("a value from a real .env on this PC", re.compile(re.escape(v))) for v in sorted(vals)]


def tracked(root):
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "."],
                             cwd=root, capture_output=True, check=True).stdout
        return [p for p in out.decode("utf-8").split("\0") if p]
    except (subprocess.CalledProcessError, OSError):
        # not a git checkout (a test copy): every file except build output, venvs and .env
        skip = {".git", ".venv", "build", "dist", "__pycache__"}
        files = []
        for d, dirs, names in os.walk(root):
            dirs[:] = [x for x in dirs if x not in skip]
            files += [os.path.relpath(os.path.join(d, n), root).replace("\\", "/") for n in names
                      if n != ".env"]
        return files


def scan_text(label, text, patterns, found, per_line=True):
    if per_line:
        for n, line in enumerate(text.splitlines(), 1):
            for what, rx in patterns:
                if rx.search(line):
                    found.append(f"{label}:{n}: {what}")
    else:
        for what, rx in patterns:
            if rx.search(text):
                found.append(f"{label}: {what}")


def check_tree(root, extra):
    found = []
    files = tracked(root)
    for rel in files:
        if Path(rel).suffix.lower() in SKIP_SUFFIX or rel.startswith(SKIP_PREFIX) or rel in SKIP_FILES:
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scan_text(rel, text, TREE_PATTERNS + extra, found)
    return found, len(files)


def _pyinstaller_members(path):
    """(name, bytes) of every entry inside a PyInstaller exe (its CArchive, and the PYZ of Python
    modules embedded in it), decompressed. Needs PyInstaller (the build venv has it)."""
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except ImportError:
        print("privacy check: PyInstaller not importable, embedded archives not unpacked")
        return
    try:
        arc = CArchiveReader(str(path))
    except Exception:
        return
    for name in arc.toc:
        if name.lower().endswith(".pyz"):
            try:
                pyz = arc.open_embedded_archive(name)
            except Exception:
                continue
            for mod in pyz.toc:
                try:
                    yield f"{name}!{mod}", pyz.extract(mod, raw=True)
                except Exception:
                    pass
            continue
        try:
            yield name, arc.extract(name)
        except Exception:
            pass


def _zip_members(path):
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            yield info.filename, z.read(info)


def _ours(name):
    """A build file or archive member that comes from this repo, not from a vendor."""
    return name.startswith(("playlistflow", "main", "assets/", "PlaylistFlow/_internal/assets/"))


def check_dist(dist, envs, local):
    """envs (key values) are searched everywhere; local (personal names) only in our own files."""
    found = []
    n = 0
    for p in sorted(dist.rglob("*")):
        if not p.is_file():
            continue
        n += 1
        rel = p.relative_to(dist.parent).as_posix()
        data = p.read_bytes()
        pats = DIST_PATTERNS + envs + (local if _ours(rel) else [])
        # ASCII/UTF-8 strings, and UTF-16LE (Windows resources, Qt) folded to ASCII
        scan_text(rel, data.decode("latin-1"), pats, found, per_line=False)
        scan_text(rel + " (utf-16)", data.replace(b"\x00", b"").decode("latin-1"), pats, found,
                  per_line=False)
        members = (_pyinstaller_members(p) if p.name == "PlaylistFlow.exe"
                   else _zip_members(p) if p.suffix.lower() == ".zip" else ())
        for name, blob in members:
            if isinstance(blob, (bytes, bytearray)):
                mpats = DIST_PATTERNS + envs + (local if _ours(name.split("!")[-1]) else [])
                scan_text(f"{rel}!{name}", blob.decode("latin-1"), mpats, found, per_line=False)
    # de-duplicate (the utf-16 fold often repeats the plain hit)
    seen, out = set(), []
    for f in found:
        k = f.replace(" (utf-16)", "")
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out, n


def main(argv):
    root = ROOT
    if "--root" in argv:
        root = Path(argv[argv.index("--root") + 1]).resolve()
    if "--remember" in argv:
        return remember([a for a in argv[argv.index("--remember") + 1:] if not a.startswith("--")])
    local = local_values()
    envs = env_values(ROOT) + fingerprints()
    extra = local + envs
    found, nfiles = check_tree(root, extra)
    for f in found:
        print(f)
    print(f"privacy check: {len(found)} finding(s) in {nfiles} files (tracked + new)"
          f" (+{len(local)} local values, +{len(envs)} .env and fingerprint matchers)")
    bad = bool(found)
    if "--dist" in argv:
        dist = root / "dist" / "PlaylistFlow"
        if not dist.is_dir():
            print(f"privacy check: no build at {dist}")
            return 1
        # fingerprints hash every key-shaped token, so only our own build files get them
        dfound, dn = check_dist(dist, env_values(ROOT), local_values(ignore_case=False) + fingerprints())
        for f in dfound:
            print(f)
        print(f"privacy check: {len(dfound)} finding(s) in {dn} files of the build")
        bad = bad or bool(dfound)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
