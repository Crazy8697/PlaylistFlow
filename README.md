# Playlist Flow

Native Windows app for planning playlists by harmonic key and tempo. Loads a
Spotify playlist, fills in BPM and Camelot key, and shows where the seams
between tracks will fight you.

PySide6 (Qt) — no browser, no webview, no local server.

![the window](assets/icon_128.png)

## What it does

- **Load** a playlist straight from your Spotify account, or by URL
- **Fetch** BPM and key, trying several sources in order and caching forever
- **Order** by dragging rows or bars, or sort down the wheel / by tempo
- **See** the seams: key relationship and tempo relationship for every pair,
  with a hard warning only when both are off
- **Hear** a transition before committing — plays the tail of one track into
  the next through your own Spotify
- **Push** the finished order back to Spotify

## The domain rules

These were tuned by ear against a real library. Don't "improve" them.

```python
def felt_bpm(bpm):            # trap snare lands on 3, not 2 and 4,
    return bpm / 2 if bpm >= 130 else bpm    # so 140 feels like 70

def key_gap(a, b):
    d = min((a.n - b.n) % 12, (b.n - a.n) % 12)
    if a.letter == b.letter:
        return d
    return 0 if d == 0 else (1.5 if d == 1 else d + 6)
```

`1.5` is the diagonal — one step around the wheel plus a letter flip. It is not
on the standard compatibility list and it gets its own category anyway.

Tempo, always computed on felt BPM:

| ratio | reads as | problem |
|---|---|---|
| ≤ 1.07 | locked | no |
| ≈ 2 (±7%) | half-time | no |
| ≤ 1.20 | drifts | no |
| else | jumps | yes |

One axis off is survivable. Both off is where it breaks.

## Where the data comes from

Spotify killed `audio_features` in November 2024 and there is no replacement,
so BPM and key come from elsewhere, in this order:

1. **FreqBlog** — analyses unknown tracks on demand; misses can resolve minutes
   later, so re-fetch before concluding anything
2. **ISRC retry**, then **cleaned titles** — for name-match failures
3. **GetSongBPM** — near-zero coverage on independent artists, but free
4. **Brave Search** over songbpm/chordify snippets — fills real gaps, but
   matched a known-good reference on key only about 4 times in 10. These land
   with a hollow dashed key chip and are meant to be checked, not trusted

Anything you type in yourself wins permanently and is never overwritten.

## Spotify API notes

Worth knowing, because these cost a day to work out:

- `audio_features` is **403 forever** for apps registered after 2024-11-27
- The playlist items endpoint was renamed in February 2026:
  `/playlists/{id}/tracks` → `/items`, and `items[].track` → `items[].item`
- **Client Credentials cannot read playlist items at all** — `/items` answers
  `401 Valid user authentication required`. Development Mode serves playlist
  items only to the creator or a collaborator, and Client Credentials carries
  no identity to check. User auth is mandatory
- Auth is **PKCE with the redirect pasted back by hand**, so nothing listens on
  a port
- Playlist **writes work** in Development Mode

## Running it

```
py -m venv .venv
.venv\Scripts\python -m pip install PySide6 requests pyinstaller
copy .env.example .env        # then fill it in
.venv\Scripts\python main.py
```

Build the exe and icon:

```
.venv\Scripts\python makeicon.py assets
.venv\Scripts\python -m PyInstaller --noconfirm --windowed --onedir ^
  --name PlaylistFlow --icon assets\icon.ico --add-data "assets;assets" main.py
```

`--onedir`, not `--onefile`: onefile unpacks ~150MB to a temp directory on every
launch, which costs several seconds of startup every time.

## Tests

```
.venv\Scripts\python selftest.py        # key gaps, felt BPM, tempo, seams
.venv\Scripts\python testdrag.py        # reorder integrity
.venv\Scripts\python testsort.py        # sort order
.venv\Scripts\python testkeys.py        # key-name to Camelot
.venv\Scripts\python testblank.py       # walking the missing values
.venv\Scripts\python testgaps.py        # timeline strip spacing
.venv\Scripts\python testchartdrag.py   # chart drag targets
```

The drag tests are worth keeping. Qt's `InternalMove` deletes the dragged row
*after* `dropEvent` returns, which corrupts a table rebuilt in the handler, and
answering `CopyAction` does not prevent it — `QTableWidget`'s model doesn't
advertise `CopyAction`, so Qt coerces it back. The fix is to re-sync the view
from the track list once the drag has fully finished. A test that calls
`dropEvent` directly will not catch any of this.

## Keys

| | |
|---|---|
| `Space` | play / pause |
| `Ctrl+↑` `Ctrl+↓` | move the selected track |
| `Ctrl+B` | jump to the next missing BPM or key |
| `Ctrl+P` | preview the transition |
| `Ctrl+F` | fetch |
| `Ctrl+Z` | undo |

## Attribution

BPM and key data by [FreqBlog](https://freqblog.com) and
[GetSongBPM](https://getsongbpm.com). Playlist and track metadata from Spotify.
The About dialog carries these links, which GetSongBPM require.
