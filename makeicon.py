"""Write the app icon out at every size Windows asks for.

The artwork is assets/icon.svg (Funnel A) and, for 16 and 24 px, the thicker
assets/icon-small.svg; playlistflow/artwork.py renders them, so the window,
About and the .ico can't drift apart.

Writes assets/icon.ico (the one the .spec embeds in the exe and the installer
uses), assets/icon.png (256 px, main.py's fallback) and icon_<size>.png for a
look (gitignored).

Qt's image writer only ever puts ONE image in an .ico. Windows then downscales
that single 256px frame for the 16px tray and list views, which looks mushy, so
the .ico is assembled by hand here with a frame per size.
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray
from PySide6.QtWidgets import QApplication

from playlistflow.artwork import icon_pixmap

SIZES = [16, 24, 32, 48, 64, 128, 256]


def png_bytes(size: int) -> bytes:
    pm = icon_pixmap(size)
    # The QByteArray must outlive the QBuffer: passing a temporary lets Python
    # collect it while Qt still holds the pointer, which segfaults.
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.WriteOnly)
    pm.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def write_ico(path: Path, frames: dict) -> None:
    """ICONDIR + one ICONDIRENTRY per size, then the PNG payloads.

    PNG-compressed frames are what modern tooling emits and what Windows has
    read since Vista; storing 256px as BMP would balloon the file for nothing.
    """
    sizes = sorted(frames)
    header = struct.pack("<HHH", 0, 1, len(sizes))     # reserved, type=icon, count
    offset = len(header) + 16 * len(sizes)
    entries, payload = b"", b""
    for s in sizes:
        data = frames[s]
        entries += struct.pack(
            "<BBBBHHII",
            0 if s >= 256 else s,   # width  (0 means 256)
            0 if s >= 256 else s,   # height
            0,                      # palette size, 0 for truecolour
            0,                      # reserved
            1,                      # colour planes
            32,                     # bits per pixel
            len(data),
            offset,
        )
        payload += data
        offset += len(data)
    path.write_bytes(header + entries + payload)


def main():
    QApplication(sys.argv)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("assets")
    out.mkdir(parents=True, exist_ok=True)

    frames = {}
    for s in SIZES:
        icon_pixmap(s).save(str(out / f"icon_{s}.png"))
        frames[s] = png_bytes(s)
    icon_pixmap(256).save(str(out / "icon.png"))

    ico = out / "icon.ico"
    write_ico(ico, frames)                  # the name the .spec embeds

    print("sizes:", SIZES)
    print("wrote:", ico, f"({ico.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
