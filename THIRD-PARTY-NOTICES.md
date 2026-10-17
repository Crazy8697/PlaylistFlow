# Playlist Flow: third-party notices

Playlist Flow is free software under the Apache License, Version 2.0 (see LICENSE and NOTICE).
Copyright 2026 DarkRelay (Crazy8697). Source code: https://github.com/Crazy8697/PlaylistFlow

The Windows build of Playlist Flow (the installer and the program folder it creates) includes the
components below, each under its own license. Their full license texts are in the `licenses`
folder next to PlaylistFlow.exe (Help > Licenses opens it). All of them allow distribution
together with an Apache-2.0 program.

## LGPL components: source and replacing them

Qt 6, PySide6 and Shiboken6 (LGPL-3.0) are shipped unmodified, as separate DLLs and Python
extension modules that Playlist Flow loads dynamically:

- `_internal\PySide6\Qt6Core.dll`, `Qt6Gui.dll`, `Qt6Widgets.dll`, `Qt6Svg.dll`,
  `Qt6DataVisualization.dll`, `pyside6.abi3.dll`, the `*.pyd` modules and the `plugins` folder
- `_internal\shiboken6\`

You may replace any of them with your own modified build of the same version (or a compatible
one): put your build in place of the shipped file in the program folder. The corresponding
source code for the exact versions shipped (Qt 6.11.1, PySide6 6.11.1, Shiboken6 6.11.1) is
available from https://download.qt.io/official_releases/qt/6.11/6.11.1/ and
https://download.qt.io/official_releases/QtForPython/ . On request the Playlist Flow maintainer
will provide it too, for at least three years after a release: open an issue at
https://github.com/Crazy8697/PlaylistFlow. Playlist Flow places no restriction on reverse
engineering these libraries for debugging such modifications.

## Components

| Component | Version | License | License file | Upstream |
|---|---|---|---|---|
| Qt 6 (Core, Gui, Widgets, Svg, DataVisualization, plugins) | 6.11.1 | LGPL-3.0-only (also GPL-2.0 / GPL-3.0) | `qt-pyside6-lgpl-3.0.txt`, `gpl-3.0.txt` | https://download.qt.io/official_releases/qt/ |
| PySide6 (Qt for Python) | 6.11.1 | LGPL-3.0-only (also GPL-2.0 / GPL-3.0) | `qt-pyside6-lgpl-3.0.txt`, `gpl-3.0.txt` | https://download.qt.io/official_releases/QtForPython/ |
| Shiboken6 | 6.11.1 | LGPL-3.0-only (also GPL-2.0 / GPL-3.0) | `qt-pyside6-lgpl-3.0.txt`, `gpl-3.0.txt` | https://download.qt.io/official_releases/QtForPython/ |
| requests | 2.34.2 | Apache-2.0 | `requests.txt` (LICENSE and NOTICE) | https://github.com/psf/requests |
| urllib3 (used by requests) | 2.7.0 | MIT | `urllib3.txt` | https://github.com/urllib3/urllib3 |
| certifi (used by requests; Mozilla's CA bundle) | 2026.7.22 | MPL-2.0 | `certifi.txt` (notice and full MPL-2.0 text) | https://github.com/certifi/python-certifi |
| idna (used by requests) | 3.18 | BSD-3-Clause | `idna.txt` | https://github.com/kjd/idna |
| charset-normalizer (used by requests) | 3.5.1 | MIT | `charset-normalizer.txt` | https://github.com/jawah/charset_normalizer |
| QtAwesome | 1.4.2 | MIT | `qtawesome.txt` | https://github.com/spyder-ide/qtawesome |
| QtPy (used by QtAwesome) | 2.4.3 | MIT | `qtpy.txt` | https://github.com/spyder-ide/qtpy |
| Material Design Icons webfont (the only icon font shipped) | 6.9.96 | Pictogrammers Free License: the font and icons under Apache-2.0 | `materialdesignicons.txt` | https://github.com/Templarian/MaterialDesign-Webfont |
| Python runtime and standard library | 3.11.9 | PSF-2.0, plus the licenses of code built into it (bzip2, libffi, zlib, libmpdec, expat and others), listed in the file | `python.txt` | https://www.python.org |
| OpenSSL (libssl-3, libcrypto-3, used by Python) | 3.0.13 | Apache-2.0 | `openssl-apache-2.0.txt` | https://www.openssl.org |
| PyInstaller bootloader (PlaylistFlow.exe's launcher) | 6.22.1 | GPL-2.0-or-later with the PyInstaller bootloader exception | `pyinstaller.txt` | https://pyinstaller.org |
| Microsoft Visual C++ runtime (VCRUNTIME140, MSVCP140, api-ms-win-*) | 14.x / 10.0 | Microsoft Visual C++ Redistributable license (redistributable files) | none (Microsoft terms) | https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist |

## Trademarks and brand assets (not covered by the Apache License)

- **Spotify logo** (`assets\spotify\Spotify_Full_Logo_RGB_White.png`,
  `Spotify_Primary_Logo_RGB_White.png`): trademarks of Spotify AB, taken unmodified from
  https://developer.spotify.com/documentation/design and used under Spotify's Design & Branding
  Guidelines and Developer Terms, only to attribute content from Spotify. Playlist Flow is not
  made, endorsed or supported by Spotify.
- **DarkRelay banner and the Playlist Flow artwork** (`assets\brand`, `assets\icon*`,
  `assets\about_source.png`): DarkRelay's own artwork, part of Playlist Flow.
- FreqBlog and GetSongBPM are named as the services that supply BPM and key estimates; each user
  uses them with their own key under each service's terms.

## Notes

- The PyInstaller bootloader exception allows distributing the bootloader with programs under
  any license.
- QtAwesome normally bundles several icon fonts; Playlist Flow ships only the Material Design
  Icons font it uses, and loads it privately: nothing is installed into the Windows fonts
  folders.
- The Visual C++ runtime files are distributed under Microsoft's redistribution terms for them.
