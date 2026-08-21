<div align="center">

<img src="assets/icon_128.png" width="96" alt="Playlist Flow">

# Playlist Flow

**Plan playlists by harmonic key and tempo.**

Loads a Spotify playlist, fills in BPM and Camelot key, shows you where the
seams between tracks will fight you, and pushes the reordered playlist back.

Native Qt. No browser, no webview, no local web server.

</div>

---

## Contents

- [What you need](#what-you-need)
- [Accounts, one at a time](#accounts-one-at-a-time)
- [Install](#install)
- [First run](#first-run)
- [Using it](#using-it)
- [Where your files live](#where-your-files-live)
- [The rules it uses](#the-rules-it-uses)
- [Where the BPM and key come from](#where-the-bpm-and-key-come-from)
- [Spotify API notes](#spotify-api-notes)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)

---

## What you need

| | Required? | Free? | What it's for |
|---|---|---|---|
| **Spotify Premium** | yes | no | Reading your playlists, and playback control |
| **Spotify developer app** | yes | yes | The client ID the app signs in with |
| **FreqBlog account** | yes | yes | BPM and musical key |
| **GetSongBPM account** | optional | yes | Fallback BPM source |
| **Brave Search API** | optional | yes | Last resort for obscure tracks |
| **Python 3.11+** | to build | yes | Only if running from source |

Premium is not optional. Spotify requires it for Web API access, and playback
control stops working if it lapses.

---

## Accounts, one at a time

### 1. Spotify developer app — required

1. Go to **https://developer.spotify.com/dashboard** and log in with your normal
   Spotify account
2. **Create app**. Name and description can be anything
3. Set **Redirect URI** to exactly:
   ```
   http://127.0.0.1:8888/callback
   ```
   Use `127.0.0.1`, not `localhost` — Spotify rejects the hostname form
4. Tick **Web API**, then save
5. Copy the **Client ID** from the app's settings
6. **Do not skip this step.** Open the app's **User Management** and add your own
   name and the email on your Spotify account

Step 6 catches people out. Spotify apps start in Development Mode, which serves
your playlists only to accounts on that list — your own included. Without it,
loading a playlist fails with a `403` that looks like a bug.

You do **not** need the client secret. The app signs in with PKCE.

### 2. FreqBlog — required

1. Go to **https://freqblog.com**
2. Request a free key. No card needed
3. The key arrives by email

Free tier is 1000 lookups a month. Results are cached permanently, so a track
only ever costs one lookup no matter how many times you load the playlist.

### 3. GetSongBPM — optional

1. Go to **https://getsongbpm.com/api**
2. Fill in the form. It asks for a **backlink URL** — a page you control that
   links to `getsongbpm.com`. Their crawler checks for the link **before**
   issuing the key, so put the link up first or the form rejects you
3. The key is issued immediately once the link is found

Coverage of independent artists is thin. Worth having, not worth waiting for.

> The About dialog carries a visible link back to getsongbpm.com, which their
> terms require. Leave it in place if you use this key.

### 4. Brave Search — optional

1. Go to **https://brave.com/search/api/**
2. Sign up and take the free tier

Used only for tracks nothing else can resolve. Its BPM is usually right; its
**key often is not**, so anything it supplies is marked as a guess.

---

## Install

### Option A — the installer (recommended)

Download **`PlaylistFlow-Setup-vX.Y.Z-win64.exe`** from the
[latest release](https://github.com/Crazy8697/PlaylistFlow/releases/latest)
and run it. No admin prompt — it installs per-user into
`%LOCALAPPDATA%\Programs\PlaylistFlow` with a Start menu entry, an optional
desktop shortcut, and a normal uninstall entry in Apps.

> Windows SmartScreen will warn on first run because the exe is unsigned:
> **More info → Run anyway.**

The app checks for updates a few seconds after startup and offers them —
downloads, swaps itself, and restarts. **Help → Check for updates…** does the
same on demand. Uninstalling never touches your keys or saved playlists.

### Option B — portable zip

Grab **`PlaylistFlow-vX.Y.Z-win64.zip`** from the same release, unzip it
anywhere writable, run `PlaylistFlow.exe`. The self-updater works here too.

### Option C — from source

Needs **Python 3.11 or newer** from [python.org](https://www.python.org/downloads/)
(tick *Add Python to PATH* during install).

```bat
git clone https://github.com/Crazy8697/PlaylistFlow.git
cd PlaylistFlow

py -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install PySide6 requests pyinstaller

.venv\Scripts\python main.py
```

### Building the exe

```bat
.venv\Scripts\python makeicon.py assets
.venv\Scripts\python -m PyInstaller PlaylistFlow.spec --noconfirm
```

Result lands in `dist\PlaylistFlow\`.

### Cutting a release

Bump `__version__` in `playlistflow/__init__.py`, then:

```bat
.venv\Scripts\python release.py
```

Builds, zips, compiles the installer from `_installer.iss` (needs Inno Setup 6),
and publishes both to GitHub Releases via `gh`. It refuses to package if a
`.env` is anywhere in the build. Everyone on an older build gets offered the
update on next launch.

`--onedir`, not `--onefile`. Onefile unpacks ~150 MB to a temp directory on
every single launch, which costs several seconds each time. Onedir starts
immediately and still gives you one exe to make a shortcut to.

---

## First run

The app asks for your keys the first time it starts, and won't nag again.

1. Paste the **Spotify client ID** and the **FreqBlog key**. Optional ones can
   be left blank
2. Hit **Test** next to each — it checks the key against the real service, so a
   typo surfaces now rather than as a confusing error mid-fetch
3. Pick a folder for saved playlists
4. **Finish setup**

Then sign in: paste a playlist URL and hit **Load playlist**, or use **File →
Sign in to Spotify…**

Signing in is a one-time, slightly odd dance, because the app deliberately
opens no network ports:

1. Click **Open Spotify** — your browser opens Spotify's login
2. Approve
3. The browser lands on a page that **fails to load**. That is expected and
   correct — nothing is listening on that address
4. Copy the whole URL out of the address bar and paste it back into the app

Change any of this later under **File → Settings…**

---

## Using it

| Do this | To get this |
|---|---|
| Pick a playlist in the sidebar | Loads it, with anything previously looked up already filled in |
| **Fetch BPM/key** | Fills the gaps, trying each source in turn |
| Drag a row, or drag a bar on the chart | Reorder |
| **Sort: key** / **Sort: BPM** | Straight sort; click again to reverse |
| Double-click a track | Plays it and everything after it, in the order shown here |
| **Preview transition** | Plays the tail of the selected track into the next one |
| Settings → Display → **Timeline mode** | Bar width becomes track length; Ctrl+wheel zooms |
| **Push to Spotify** | Adds what's missing, offers removals, reorders to match |

| Key | |
|---|---|
| `Space` | play / pause |
| `Ctrl+↑` `Ctrl+↓` | move the selected track |
| `Ctrl+B` | jump to the next missing BPM or key and start typing |
| `Ctrl+P` | preview the transition |
| `Ctrl+M` | mark the selected transition as ear-checked |
| `Ctrl+Shift+F` | bulk track finder |
| `Ctrl+E` | export the URI block |
| `Ctrl+F` | fetch |
| `Ctrl+Z` | undo |

Right-click a track for play / preview / cross-check / remove.

**Reading the table.** A solid coloured key chip came from an audio analysis and
can be trusted. A **hollow, dashed chip** was scraped off the web and is a
guess worth checking. A red-tinted row has no BPM or key yet. Anything you type
in yourself is permanent and is never overwritten by a later fetch.

---

## Where your files live

| What | Where |
|---|---|
| Your API keys | `%APPDATA%\PlaylistFlow\.env` |
| Saved playlists and the BPM/key cache | the folder you chose during setup |
| Window size, sign-in token, preferences | Windows registry, under `darkrelay\PlaylistFlow` |

Each playlist is saved twice: `<name>.json` when you hit **Save**, and
`<name>-auto.json` written continuously as you work. The auto file never
overwrites the manual one, so a deliberate save is always recoverable.

Keys are stored outside the program folder on purpose — that folder gets
replaced wholesale every time the exe is rebuilt.

---

## The rules it uses

Tuned by ear against a real library. Don't "improve" them.

```python
def felt_bpm(bpm):                                # trap snare lands on 3, so a
    return bpm / 2 if bpm >= FELT_FOLD else bpm   # fast count feels half-time

def key_gap(a, b):
    d = min((a.n - b.n) % 12, (b.n - a.n) % 12)
    if a.letter == b.letter:
        return d
    return 0 if d == 0 else (1.5 if d == 1 else d + 6)
```

`1.5` is **the diagonal** — one step around the wheel plus a letter flip. It is
not on the standard harmonic-mixing compatibility list. It gets its own
category anyway, because it works.

Tempo is classified on **raw** BPM (felt is display-only — the fold point is a
Display setting, default 165). Every window derives from one tolerance
(Settings → Display: tight ±3% / normal ±6% / loose ±8%), reciprocal by
construction so A→B and B→A always agree:

| ratio near | reads as | a problem? |
|---|---|---|
| 1 | holds | no |
| 2 | doubles | no |
| ½ | halves | no |
| 3:2 or 2:3 | shifts | no — valid, just not seamless |
| within 8% of any of those | drifts | soft warning |
| anything else | jumps | yes (downgraded to drifts in the same key) |

Key and tempo are judged independently. **One axis off is survivable. Both off
is where it breaks** — and only that gets a hard warning.

---

## Where the BPM and key come from

Spotify removed its `audio_features` endpoint in November 2024 and never
replaced it, so the numbers come from elsewhere, in this order:

1. **FreqBlog** — analyses tracks it has never seen on demand, so a miss can
   resolve a few minutes later. Re-fetch before assuming a track is unavailable
2. **ISRC retry** — an exact recording identifier that cannot mismatch
3. **Cleaned titles** — strips `(feat. …)`, `- Remastered` and similar
4. **GetSongBPM**
5. **Brave Search** over songbpm / chordify snippets

Expect gaps on genuinely obscure tracks. Type those in once; they're cached
forever.

---

## Spotify API notes

Written down because they cost real time to work out:

- `audio_features` is **403 forever** for any app registered after 2024-11-27.
  There is no application process to get it back
- The playlist items endpoint was **renamed in February 2026**:
  `/playlists/{id}/tracks` → `/playlists/{id}/items`, and `items[].track` →
  `items[].item`. The old path returns 403
- **Client Credentials cannot read playlist items at all.** `/items` answers
  `401 Valid user authentication required` — Development Mode serves playlist
  items only to the creator or a collaborator, and Client Credentials carries no
  identity to check against. User auth is mandatory, even for a public playlist
  you own
- Playlist **writes do work** in Development Mode
- Track **preview URLs are gone** — there is no audio to analyse locally

---

## Tests

All ad hoc scripts live in `tests/` and run from anywhere:

```bat
.venv\Scripts\python tests\selftest.py        REM key gaps, felt BPM, tempo, seams
.venv\Scripts\python tests\testdrag.py        REM reorder integrity
.venv\Scripts\python tests\testkeys.py        REM key names to Camelot
.venv\Scripts\python tests\testearcheck.py    REM ear-checked seams
.venv\Scripts\python tests\testdisplay.py     REM Display settings + exit prompt
.venv\Scripts\python tests\testchartdrag.py   REM chart drag targets
```

Keep the drag tests. Qt's `InternalMove` deletes the dragged row *after*
`dropEvent` returns, which corrupts a table rebuilt inside the handler — and
answering `CopyAction` does not prevent it, because `QTableWidget`'s model
doesn't advertise `CopyAction` and Qt coerces the action back. The fix is to
re-sync the view from the track list once the drag has fully finished. A test
that calls `dropEvent` directly passes while the real thing is broken.

---

## Troubleshooting

**"Spotify refused the track list" / 403 when loading a playlist**
Your account isn't on the app's allowlist. Dashboard → your app → **User
Management** → add your name and the email on your Spotify account.

**Sign-in page fails to load after approving**
That's correct. Copy the URL out of the address bar and paste it into the app.

**"No active Spotify device"**
Open Spotify and play something for a second, so it registers as a device.
Playback is a remote control — the audio always comes from your Spotify.

**Player says "This needs Spotify Premium"**
It does.

**A track's BPM looks wrong**
Cross-check it: right-click → **Cross-check BPM & key on the web**, compare, and
type in whatever's right. Typed values are permanent.

**Everything comes back "not found"**
Check the FreqBlog key under **File → Settings** and hit **Test**. If it says
rate limited, you're out of monthly quota.

---

## Credits

BPM and key data by [FreqBlog](https://freqblog.com) and
[GetSongBPM](https://getsongbpm.com). Playlist and track metadata from Spotify.

Built by [darkrelay.net](https://darkrelay.net).
