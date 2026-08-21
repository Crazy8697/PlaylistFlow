"""Build, package and publish a release the in-app updater can find.

    .venv\\Scripts\\python.exe release.py            build + zip + gh release
    .venv\\Scripts\\python.exe release.py --zip-only  build + zip, no publish

The zip holds the CONTENTS of dist/PlaylistFlow (no wrapper folder) — the
updater extracts it straight into a staging dir and robocopies over the
install, and a recipient unzips it into any folder and runs the exe.

Refuses to package if anything resembling a secret is in the tree: this zip
goes to other people.
"""

import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from playlistflow import __version__          # noqa: E402

ROOT = Path(__file__).parent
DIST = ROOT / "dist" / "PlaylistFlow"
ISCC = Path.home() / "AppData/Local/Programs/Inno Setup 6/ISCC.exe"


def run(*cmd):
    print("$", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True)


def main():
    zip_only = "--zip-only" in sys.argv
    tag = f"v{__version__}"

    run(sys.executable, "-m", "PyInstaller", "PlaylistFlow.spec", "--noconfirm")
    (DIST / "icon_v3.ico").write_bytes((ROOT / "assets" / "icon_v3.ico").read_bytes())

    # Nothing personal leaves this machine.
    leaks = [p for p in DIST.rglob("*")
             if p.name in (".env", ".env.example") or p.suffix == ".log"]
    if leaks:
        sys.exit(f"REFUSING to package — found: {leaks}")

    out = ROOT / f"PlaylistFlow-{tag}-win64.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(DIST.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(DIST))
    print(f"wrote {out.name}  ({out.stat().st_size // 1048576} MB)")

    setup = ROOT / f"PlaylistFlow-Setup-{tag}-win64.exe"
    if ISCC.exists():
        run(ISCC, f"/DAppVersion={__version__}", "/Qp", "_installer.iss")
        built = ROOT / f"PlaylistFlow-Setup-{tag}.exe"
        if built.exists():
            built.replace(setup)
        print(f"wrote {setup.name}  ({setup.stat().st_size // 1048576} MB)")
    else:
        setup = None
        print("Inno Setup not found - shipping zip only")

    if zip_only:
        return
    notes = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"], capture_output=True, text=True,
        cwd=ROOT).stdout.strip()
    assets = [str(out)] + ([str(setup)] if setup else [])
    run("gh", "release", "create", tag, *assets,
        "--title", f"Playlist Flow {tag}",
        "--notes", notes or f"Playlist Flow {tag}")
    print(f"published {tag}")


if __name__ == "__main__":
    main()
