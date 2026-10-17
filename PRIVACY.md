# Playlist Flow privacy policy

Version 2026-10-17. Applies to the Playlist Flow program for Windows, published by DarkRelay
(Crazy8697). By installing or signing up through Playlist Flow you agree that its handling of your
data is described by, and subject to, this policy.

## The short version

Playlist Flow has no server. DarkRelay collects nothing: no account, no analytics, no telemetry, no
cookies, no crash reports. Everything the program keeps stays on your PC, and it only talks to the
services listed below, directly from your PC, using your own keys and your own Spotify sign-in.

## What is stored on your PC, and where

| What | Where |
|---|---|
| Your Spotify developer app's client ID, the redirect port, your FreqBlog key and your GetSongBPM key (if you added one), and your display settings | `%APPDATA%\PlaylistFlow\.env` |
| Your Spotify sign-in (a refresh token), window layout, the playlists folder you chose, whether you accepted these documents, and update choices | The Windows registry, `HKEY_CURRENT_USER\Software\darkrelay\PlaylistFlow` |
| Your saved playlists (track names, artists, Spotify track links, BPM and key values, your notes) and the remembered BPM/key values (`cache.json`) | The playlists folder you chose (by default `Documents\PlaylistFlow`) |
| A downloaded update installer, only while an update is being installed | `%APPDATA%\PlaylistFlow\update-staging` |

None of this is sent to DarkRelay. Nobody but you has it.

## Which services it talks to, and why

- **Spotify** (accounts.spotify.com, api.spotify.com): to sign you in, read your playlists and
  their tracks, show your Spotify display name once during setup, find tracks you search for,
  control playback on your own Spotify devices, and save the order and description you choose
  back to your playlists. It uses your own Spotify developer app and your own sign-in. What Spotify
  does with your data is covered by Spotify's own privacy policy.
- **FreqBlog** (api.freqblog.com): to look up BPM and musical key estimates. It sends track names,
  artist names and track identifiers (such as ISRC codes), with your own FreqBlog key. Nothing
  about you personally is sent.
- **GetSongBPM** (api.getsong.co), only if you added a GetSongBPM key: the same kind of lookup for
  tracks FreqBlog did not find, with your own key.
- **GitHub** (api.github.com, github.com): to check whether a newer version of Playlist Flow is
  published, and to download it if you choose to update. This check sends nothing but the request
  itself, and you can turn it off (Settings > Display > Check for updates at startup).

Each request identifies the program by name and version (for example
`PlaylistFlow/0.7.0 (+https://darkrelay.net)`) and carries no information about you. Playlist Flow does not sell, share or transfer any data obtained from Spotify or anyone else,
does not use it for advertising, and does not use it to train any machine learning or AI model.

## Cookies

Playlist Flow does not use cookies, and does not let any third party place cookies. Signing in to
Spotify happens in your own web browser, on Spotify's own pages, under Spotify's own cookie policy.

## Disconnecting Spotify and deleting everything

- **Disconnect Spotify**: Settings > Disconnect Spotify. This removes the Spotify sign-in from your
  PC at once, and the program stops reading your Spotify data. You can also choose, in the same
  step, to delete your saved playlists and the remembered BPM/key values. To also remove the
  program's access on Spotify's side, open https://www.spotify.com/account/apps/ .
- **Delete everything**: uninstall Playlist Flow from Windows Settings > Apps, then delete the
  `%APPDATA%\PlaylistFlow` folder, the registry key
  `HKEY_CURRENT_USER\Software\darkrelay\PlaylistFlow`, and your playlists folder.

## Contact

Questions about your data or this policy: open an issue at
https://github.com/Crazy8697/PlaylistFlow/issues . Please never post your keys there.

## Spotify

Spotify is a third party beneficiary of this privacy policy and of the Playlist Flow end user
agreement (TERMS.md), and is entitled to enforce them directly.

## Changes

If this policy changes, its version above changes, and Playlist Flow asks you to read and accept
it again before you next sign in to Spotify.
