import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
"""Render the window with the prototype's Ruin dataset and save a screenshot.

Verification harness — not part of the shipped program.
"""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QTimer

from main import QSS
from playlistflow.mainwindow import MainWindow
from playlistflow.domain import Track

RUIN = """Curiosity, Bryce Savage, 144, 12B
Don't You Dare Look Away, XxCaveinxX, 142, 12A
Devil in Her Eyes, Bryce Savage, 110, 12B
LET ME IN, Jared Benjamin, 160, 12A
Believe It, Jared Benjamin, 84, 12A
Pretty Lady Heart Out, Sir Silly, 122, 10A
Good Girl (Praise), Nation Haven, 89, 10A
Addict, Don Louis, 65, 12A
Straitjackets & Roses, Diggy Graves, 105, 12A
Pretty Distraction, SkyDxddy, 172, 11A
Talk About It, Lundy, 140, 10A
Beggin', Kowshik Saha, 60, 10A
The Devil Wears Lace, Steven Rodriguez, 65, 9A
Killer Looks, Golgotha, 127, 9A
Porcelain & Pain, Steven Rodriguez, 72, 9A
Headstrong, Dracu, 185, 9A
Three Steps Ahead, Jared Benjamin, 71, 9A
OUTLAW, Ryan Jesse, 153, 8A
Bad Thing, Steven Rodriguez, 85, 8B
TN HONEY, Ryan Jesse, 80, 8A
Pretty When You Beg, Henri Werner, 116, 7A
Psycho Baby, Shadow Beloved, 80, 7A
SOOEY, Coey Redd, 85, 7A
Type Shit, Jay Webb, 160, 7A
Darkside, SkyDxddy, 80, 7A
Control, Bryce Savage, 100, 7A
MAN OF THE HOUSE, Ryan Jesse, 128, 6A
No Mercy, Austin Giorgio, 60, 6A
150, Ryan Jesse, 135, 6A
Like You Mean It, Steven Rodriguez, 110, 6A
D!E FOR ME, Ekoh, 156, 5B
roses red, Jeris Johnson, 74, 5B
Don't Slow Down, Ryan Jesse, 140, 5A
When I Drink, Coey Redd, 123, 4A
Slayer, Bryce Savage, 67, 4A
Do It Like That, Nevv, 103, 4A
Cute Girl, Diggy Graves, 150, 3A
Wrangler, Austin Martin, 110, 3A
No Return, fwc, 69, 3A
mine tonight, EXXCLUSIVE, 65, 3A
I WISH, Ryan Oakes, 180, 3B
Mommy Don't Know, ANTH, 66, 3B
Chokehold, Austin Giorgio, 98, 2A
Ruined After Me, Klosure, 140, 2A
Beg For Me, Braeker, 60, 2A
Broken Heart Collector, Ekoh, 145, 2A
Nasty Lil Freak, Sir Silly, 117, 1A
Shakedown, Clejan, 117, 1A
Going to Hell, Bryce Savage, 140, 1A"""


def parse(txt):
    out = []
    for ln in txt.splitlines():
        if not ln.strip():
            continue
        p = [x.strip() for x in ln.split(",")]
        key, bpm, artist = p[-1], float(p[-2]), p[-3]
        title = ",".join(p[:-3])
        out.append(Track(title=title, artist=artist, bpm=bpm, key=key,
                         source="manual", manual=True,
                         uri=f"spotify:track:demo{len(out):04d}"))
    return out


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(QSS)

    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    felt = "--felt" in sys.argv

    w = MainWindow()
    w.prefs.storage_dir = str(out_dir / "store")
    w._ensure_storage()
    w.tracks = parse(RUIN)
    w.current_name = "Ruin"
    if felt:
        w.set_felt(True)
    w.refresh()
    w.resize(1280, 900)
    w.show()

    def grab():
        name = "shot_felt.png" if felt else "shot_reported.png"
        w.grab().save(str(out_dir / name))
        print("saved", out_dir / name)
        print("summary:", w.stat.text())
        app.quit()

    QTimer.singleShot(1200, grab)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
