"""Write the app icon out at every size Windows asks for.

The drawing itself lives in playlistflow/artwork.py, because the About dialog
paints the same wave as a background and the two must not drift apart.

The .ico filename carries a version. Windows caches shell icons by path, so
overwriting the same filename leaves stale icons on existing shortcuts — a new
name sidesteps the cache entirely.
"""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from playlistflow.artwork import wave_pixmap

ICON_VERSION = 2


def main():
    QApplication(sys.argv)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    out.mkdir(parents=True, exist_ok=True)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    for s in sizes:
        wave_pixmap(s).save(str(out / f"icon_{s}.png"))
    wave_pixmap(256).save(str(out / "icon.png"))

    ico = out / f"icon_v{ICON_VERSION}.ico"
    wave_pixmap(256).save(str(ico))
    wave_pixmap(256).save(str(out / "icon.ico"))   # kept for the exe resource

    print("sizes:", sizes)
    print("wrote:", ico)


if __name__ == "__main__":
    main()
