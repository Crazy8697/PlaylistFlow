<div align="center">

<img src="assets/icon_128.png" width="96" alt="Playlist Flow">

# Playlist Flow

**Plan playlists by harmonic key and tempo. Works with Spotify.**

Loads a Spotify playlist, fills in BPM and Camelot key, shows you where the
seams between tracks will fight you, and pushes the reordered playlist back.

A native Windows program. No browser, no webview, no server of its own.

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
| **Spotify Premium** | yes | no | Your own developer app only works with Premium, and so does playback control |
| **Your own Spotify developer app** | yes | yes | The client ID the program signs in with |
| **Your own FreqBlog key** | yes | yes | BPM and musical key |
| **Your own GetSongBPM key** | optional | yes | Fallback BPM source |
| **Python 3.11+** | to build | yes | Only if running from source |

Everyone who uses Playlist Flow registers their own Spotify developer app and
their own keys. Nothing is shared and nothing is bundled. Spotify keeps every
new app in **Development Mode**, which needs the app owner to have Premium and
allows up to 5 Spotify accounts that you add to the app's allowlist yourself.

**Your keys are yours alone.** Never share them, paste them into an issue, or
commit them anywhere. FreqBlog allows one free key per person.

Playlist Flow is not made, endorsed or supported by Spotify, FreqBlog or
GetSongBPM.

---

## Accounts, one at a time

### 1. Spotify developer app (required)

1. Go to **https://developer.spotify.com/dashboard** and log in with your normal
   Spotify account
2. **Create app**. Name and description can be anything, but don't put
   "Spotify" in the name: Spotify's rules forbid it
3. Set **Redirect URI** to exactly:
   ```
   http://127.0.0.1:8888/callback
   ```
   Use `127.0.0.1`, not `localhost`. Spotify rejects the hostname form
4. Tick **Web API**, then save
5. Copy the **Client ID** from the app's settings
6. **Do not skip this step.** Open the app's **User Management** and add your own
   name and the email on your Spotify account

Step 6 catches people out. Development Mode serves playlists only to accounts on
that list, your own included. Without it, loading a playlist fails with a `403`
that looks like a bug.

There is no client secret to copy. The program signs in with PKCE.

### 2. FreqBlog (required)

1. Go to **https://freqblog.com**
2. Request your own free key. No card needed
3. The key arrives by email

The free tier has a monthly allowance of requests (setup and Settings show how
much of it is used). Playlist Flow sends playlists through FreqBlog's bulk
lookup, 50 tracks a call. A value that resolves is cached, so a track that has
been looked up costs nothing the next time you load the playlist. A track FreqBlog
is still analysing is checked again a few minutes later, not polled, and one it
doesn't know is asked about again after a week.

### 3. GetSongBPM (optional)

1. Go to **https://getsongbpm.com/api**
2. Fill in the form. It asks for a **backlink URL**, a page that links to
   `getsongbpm.com`. Their crawler checks for the link **before** issuing the
   key. If you have no site of your own, this project's GitHub page carries
   the link
3. The key is issued once the link is found

Coverage of independent artists is thin. Worth having, not worth waiting for.

> The About dialog carries a visible link back to getsongbpm.com, which their
> terms require. Leave it in place if you use this key.

---

## Install

### Option A: the installer (recommended)

Download **`PlaylistFlow-Setup-X.Y.Z.exe`** from the
[latest release](https://github.com/Crazy8697/PlaylistFlow/releases/latest)
and run it. Windows asks for admin once (UAC): it installs for all users into
`C:\Program Files\PlaylistFlow` (64-bit) with a Start menu entry, an optional
desktop shortcut, and a normal uninstall entry in Apps. Each release also
carries `PlaylistFlow-Setup-X.Y.Z.exe.sha256` to check the download against.

Nothing you create lives in the install folder. Keys and display settings are
in `%APPDATA%\PlaylistFlow\.env`, saved playlists in the storage folder you
pick, window layout and the Spotify sign-in in your user registry. Installing
a new version over an old one keeps all of it.

> Windows SmartScreen will warn on first run because the exe is unsigned:
> **More info → Run anyway.**

Uninstalling never touches your keys or saved playlists.

### Updates

A few seconds after startup the program asks GitHub, in the background, whether
a newer release is out. That is the only thing it sends, and you can turn it off
under **Settings → Display → Check for updates at startup**; **Help → Check for
updates…** works either way.

When there is one, a bar appears at the bottom of the window (never a popup):
**Release notes**, **Download and install**, **Skip this version** (that
version is never offered again; a newer one still is), or **Later** (until the
next launch). Download and install fetches the release's installer, checks it
against the SHA-256 published with it and refuses anything that doesn't match,
then closes the program and runs the installer silently. Windows asks for admin
once, and Playlist Flow starts again by itself when it's done.

### Option B: from source

Needs **Python 3.11 or newer** from [python.org](https://www.python.org/downloads/)
(tick *Add Python to PATH* during install).

```bat
git clone https://github.com/Crazy8697/PlaylistFlow.git
cd PlaylistFlow

py -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt

.venv\Scripts\python main.py
```

### Building the exe

```powershell
.\build.ps1                # build only: dist\PlaylistFlow\PlaylistFlow.exe
.\build.ps1 -Setup         # build, then the installer + .sha256 in dist\installer,
                           # versioned and as PlaylistFlow-Setup.exe for the updater
.\build.ps1 -PrivacyCheck  # scan the tree (and the build, if there is one) for anything private
.\build.ps1 -Release -Version X.Y.Z   # privacy gate, build, public source sync, GitHub release
```

Releases are published only by `build.ps1 -Release`: it refuses unless the tree is clean, the
version matches, `release-notes/vX.Y.Z.md` exists and `tools/privacy_check.py` finds nothing in the
tree, the build, and the public copy of the source. The public repository gets exactly the
committed files (minus what `.gitattributes` marks `export-ignore`), one commit per release.

`-Setup` needs Inno Setup 6. The version comes from `playlistflow/__init__.py`
and lands in the exe's Properties > Details and in the installer name.
Regenerate the icon PNGs first with `.venv\Scripts\python makeicon.py assets`
if the artwork changed.

`tools/privacy_check.py` looks for personal paths, home-network addresses and
hostnames, e-mail addresses, tokens, filled-in `.env` lines and em dashes. Exact
personal values it should also catch go one per line in
`tools/privacy-local.txt`, which is gitignored.

A release carries `PlaylistFlow-Setup-X.Y.Z.exe`, `PlaylistFlow-Setup.exe` and
a `.sha256` for each. The updater only acts on a release that has
`PlaylistFlow-Setup.exe` and its `.sha256`.

`--onedir`, not `--onefile`. Onefile unpacks ~150 MB to a temp directory on
every single launch, which costs several seconds each time. Onedir starts
immediately and still gives you one exe to make a shortcut to.

---

## First run

The first launch opens a setup wizard, one step at a time:

1. **Welcome**, and what you'll need
2. **Spotify app**: the redirect URI to add (on a free port it picks for you)
   and the box for your client ID. A paste with extra text around it, such as
   a "Client ID:" label or line breaks, is cleaned up
3. **Privacy and terms**: read and accept both
4. **Sign in**: click **Open Spotify sign-in** and approve in your browser. While
   it waits, the program listens on 127.0.0.1 (this PC only) for Spotify's answer,
   the browser says you can close the tab, and the step finishes by itself. The
   listener stops right after. If the port can't be used, paste the address the
   browser lands on instead
5. **FreqBlog key**: **Check key** asks FreqBlog about the key (free, it doesn't
   count against the allowance) and shows how much of this month's allowance is used
6. **GetSongBPM key**, optional
7. **Storage folder** for saved playlists
8. **Done**, then **Finish**

Run it again any time from **File → Settings… → Run setup again**.

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

Right-click a track for play / preview / ear-check / copy / remove.

**Reading the table.** A solid coloured key chip came from an audio analysis. A
**hollow, dashed chip** is a value an older version scraped off the web, kept
so nothing you had is lost; treat it as a guess. A red-tinted row has no BPM or
key yet. Anything you type in yourself is permanent and is never overwritten
by a later fetch.

BPM and key values are estimates from automated analysis, not authoritative
data. Trust your ears over the numbers.

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

Keys are stored outside the program folder on purpose: that folder is replaced
on every install and update.

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

`1.5` is **the diagonal**: one step around the wheel plus a letter flip. It is
not on the standard harmonic-mixing compatibility list. It gets its own
category anyway, because it works.

Tempo is classified on **raw** BPM (felt is display-only, and the fold point is
a Display setting, default 165). Every window derives from one tolerance
(Settings → Display: tight ±3% / normal ±6% / loose ±8%), reciprocal by
construction so A→B and B→A always agree:

| ratio near | reads as | a problem? |
|---|---|---|
| 1 | holds | no |
| 2 | doubles | no |
| ½ | halves | no |
| 3:2 or 2:3 | shifts | no, valid, just not seamless |
| within 8% of any of those | drifts | soft warning |
| anything else | jumps | yes (downgraded to drifts in the same key) |

Key and tempo are judged independently. **One axis off is survivable. Both off
is where it breaks**, and only that gets a hard warning.

---

## Where the BPM and key come from

Spotify removed its `audio_features` endpoint in November 2024 and never
replaced it, so the numbers come from elsewhere, in this order:

1. **FreqBlog**, by name, artist and ISRC. It analyses tracks it has never
   seen on demand, so a miss can resolve a few minutes later; the program
   re-polls those for a while before giving up
2. **ISRC retry**, an exact recording identifier that cannot mismatch
3. **Cleaned titles**, which strips `(feat. …)`, `- Remastered` and similar
4. **GetSongBPM**, if you set a key. Exact title and artist matches only

Whatever is still missing is listed as "not found anywhere, type those in".
Type those in once; typed values are cached and never overwritten.

---

## Spotify API notes

Written down because they cost real time to work out:

- `audio_features` is **403 forever** for any app registered after 2024-11-27.
  There is no application process to get it back
- The playlist items endpoint was **renamed in February 2026**:
  `/playlists/{id}/tracks` → `/playlists/{id}/items`, and `items[].track` →
  `items[].item`. The old path returns 403
- **Client Credentials cannot read playlist items at all.** `/items` answers
  `401 Valid user authentication required`. Development Mode serves playlist
  items only to the creator or a collaborator, and Client Credentials carries no
  identity to check against. User auth is mandatory, even for a public playlist
  you own
- Playlist **writes do work** in Development Mode
- Track **preview URLs are gone**, so there is no audio to analyse locally
- Extended Quota Mode (more than 5 users on one app) is only open to registered
  organisations with a large user base, which is why every user brings their
  own app

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
.venv\Scripts\python tests\testupdater.py     REM updater against a fake local GitHub
```

Keep the drag tests. Qt's `InternalMove` deletes the dragged row *after*
`dropEvent` returns, which corrupts a table rebuilt inside the handler, and
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
The program couldn't listen on the redirect port (or the wait timed out). Copy the
URL out of the address bar and paste it into the sign-in step.

**"No active Spotify device"**
Open Spotify and play something for a second, so it registers as a device.
Playback is a remote control: the audio always comes from your Spotify.

**Player says "This needs Spotify Premium"**
It does.

**A track's BPM looks wrong**
Click the cell and type in whatever's right. Typed values are permanent.

**Everything comes back "not found"**
Check the FreqBlog key under **File → Settings** and hit **Test**. The usage line
next to the key shows how much of this month's allowance is used, and when it resets.

---

## Privacy and terms

Playlist Flow has no server and collects nothing. What it keeps on your PC, which services it
talks to and how to delete everything is in [PRIVACY.md](PRIVACY.md). Using it with Spotify means
accepting the [end user agreement](TERMS.md), which setup shows before you sign in.
**Settings > Disconnect Spotify** removes the sign-in at any time.

---

## License

Playlist Flow is free software under the [Apache License 2.0](LICENSE), copyright 2026 DarkRelay
(Crazy8697). The Windows build includes third-party components, each under its own license; they
are listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md), and their full texts are in
[licenses](licenses) (and next to the installed program, under Help > Licenses). The Spotify logo
is a trademark of Spotify AB, used under Spotify's brand guidelines and not covered by the Apache
License.

---

## Credits

Audio analysis by [FreqBlog](https://freqblog.com). Optional fallback BPM data from
[GetSongBPM](https://getsongbpm.com). Playlist and track metadata from Spotify. BPM and key values
are estimates. Playlist Flow is not made, endorsed or supported by Spotify, FreqBlog or GetSongBPM.

Built by [darkrelay.net](https://darkrelay.net).
