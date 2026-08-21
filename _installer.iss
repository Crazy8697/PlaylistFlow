; Playlist Flow installer — Inno Setup 6.
;
; Per-user on purpose: no UAC, and the install lands in a user-writable
; folder ({autopf} resolves to %LOCALAPPDATA%\Programs under lowest
; privileges), which is exactly what the in-app self-updater needs to swap
; files without elevation.
;
; Version comes from the build script:  ISCC /DAppVersion=1.2.0 installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId is the identity Windows tracks the install by. NEVER change it,
; or upgrades stop finding the old install and uninstall entries orphan.
AppId={{D3D56ED7-1039-478C-BA35-2F3D863CBE6F}
AppName=Playlist Flow
AppVersion={#AppVersion}
AppPublisher=darkrelay.net
AppPublisherURL=https://github.com/Crazy8697/PlaylistFlow
DefaultDirName={autopf}\PlaylistFlow
DefaultGroupName=Playlist Flow
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=.
OutputBaseFilename=PlaylistFlow-Setup-v{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\PlaylistFlow.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\PlaylistFlow\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Playlist Flow"; Filename: "{app}\PlaylistFlow.exe"; IconFilename: "{app}\icon_v3.ico"
Name: "{autodesktop}\Playlist Flow"; Filename: "{app}\PlaylistFlow.exe"; IconFilename: "{app}\icon_v3.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\PlaylistFlow.exe"; Description: "Start Playlist Flow"; Flags: nowait postinstall skipifsilent

; User data (keys in %APPDATA%\PlaylistFlow, playlists in Documents) is
; deliberately NOT touched by the uninstaller.
