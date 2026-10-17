# PyInstaller spec for Playlist Flow (onedir, windowed).
# Build: .\build.ps1   ->  dist\PlaylistFlow\PlaylistFlow.exe   (-Setup packages it as an installer)
#
# The Windows version resource (Properties > Details) is generated here from
# playlistflow.__version__, so the version is set in one place only.
import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
    VarStruct, VSVersionInfo)

HERE = Path(SPECPATH)
VERSION = re.search(r'__version__ = "([^"]+)"',
                    (HERE / "playlistflow" / "__init__.py").read_text(encoding="utf-8")).group(1)
nums = tuple(int(p) for p in (VERSION.split(".") + ["0", "0", "0"])[:4])

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0,
                      OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "darkrelay.net"),
            StringStruct("FileDescription", "Playlist Flow"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "PlaylistFlow"),
            StringStruct("OriginalFilename", "PlaylistFlow.exe"),
            StringStruct("ProductName", "Playlist Flow"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 0x04B0])]),
    ])
version_file = Path(workpath) / "version_info.txt"
version_file.parent.mkdir(parents=True, exist_ok=True)
version_file.write_text(str(version_info), encoding="utf-8")
print(f"PlaylistFlow spec: version resource {VERSION} -> {version_file}")

# Qt modules Playlist Flow never uses (it needs QtCore, QtGui and QtWidgets only).
QT_EXCLUDE = ["PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSql",
              "PySide6.QtTest", "PySide6.QtDBus", "PySide6.QtOpenGL",
              "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtWebEngineCore",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts"]

from PyInstaller.utils.hooks import collect_data_files

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=[("assets", "assets")]
          # only the one icon font the toolbars use (Material Design Icons 6); the other
          # fonts QtAwesome bundles are left out (see THIRD-PARTY-NOTICES.md)
          + collect_data_files("qtawesome", includes=["fonts/materialdesignicons6-webfont-6.9.96.ttf",
                                                       "fonts/materialdesignicons6-webfont-charmap-6.9.96.json"]),
    hiddenimports=[],
    excludes=QT_EXCLUDE + ["tkinter", "matplotlib", "numpy", "IPython", "pytest"],
    noarchive=False,
)

# PyInstaller's own QtAwesome hook collects every font QtAwesome bundles, whatever the datas above
# ask for. Only Material Design Icons 6 is used and licensed in THIRD-PARTY-NOTICES.md, so the
# rest are dropped here (build.ps1 refuses a build that ships any other font).
KEEP_FONT = "materialdesignicons6-webfont"
a.datas = [d for d in a.datas
           if not d[0].replace("\\", "/").startswith("qtawesome/fonts/") or KEEP_FONT in d[0]]
print("PlaylistFlow spec: QtAwesome fonts kept:",
      ", ".join(sorted(Path(d[0]).name for d in a.datas
                       if d[0].replace("\\", "/").startswith("qtawesome/fonts/"))))

# Binaries pulled in by Qt plugins that nothing in Playlist Flow loads.
DROP = ("opengl32sw", "qt6quick", "qt6qml", "qt6pdf", "qt6opengl", "qt6network",
        "qt6virtualkeyboard", "qt6dbus", "qpdf.dll", "qtvirtualkeyboardplugin")
dropped = [b for b in a.binaries
           if any(k in b[0].lower().replace("\\", "/").split("/")[-1] for k in DROP)]
a.binaries = [b for b in a.binaries if b not in dropped]
print("PlaylistFlow spec: dropped binaries:",
      ", ".join(sorted({Path(b[0]).name for b in dropped})) or "none")

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PlaylistFlow",
    icon="assets/icon.ico",
    console=False,
    upx=False,
    version=str(version_file),
)
coll = COLLECT(exe, a.binaries, a.datas, name="PlaylistFlow", upx=False)

# --- license files next to PlaylistFlow.exe (Help > Licenses reads them from there) ---
import shutil
app = Path(DISTPATH) / "PlaylistFlow"
shutil.rmtree(app / "licenses", ignore_errors=True)
shutil.copytree(HERE / "licenses", app / "licenses")
shutil.copy2(HERE / "LICENSE", app / "LICENSE.txt")
shutil.copy2(HERE / "NOTICE", app / "NOTICE.txt")
shutil.copy2(HERE / "THIRD-PARTY-NOTICES.md", app / "THIRD-PARTY-NOTICES.md")
for doc in ("PRIVACY.md", "TERMS.md"):
    if (HERE / doc).exists():
        shutil.copy2(HERE / doc, app / doc)
print(f"PlaylistFlow spec: {len(list((app / 'licenses').iterdir()))} license files + LICENSE.txt, "
      "NOTICE.txt, THIRD-PARTY-NOTICES.md (and PRIVACY.md, TERMS.md) -> " + str(app))
