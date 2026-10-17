; Playlist Flow Windows installer. Built by build.ps1 -Setup with Inno Setup 6 (ISCC):
;   ISCC /DAppVersion=<playlistflow.__version__> /DDistDir=<dist\PlaylistFlow> /O<output folder> _installer.iss
; The PyInstaller onedir build (dist\PlaylistFlow) goes to Program Files (64-bit), admin
; install, one UAC prompt. Inno Setup is a build tool only: nothing of it ships.
;
; Uninstall keeps every piece of user data: keys and display settings
; (%APPDATA%\PlaylistFlow\.env), saved playlists, autosave and cache.json (the storage
; folder the user picked), window state and the Spotify token (HKCU\Software\darkrelay).
;
; Updates: the same AppId upgrades the installed copy in place. CloseApplications closes a
; running Playlist Flow first. The program's own updater runs Setup with
; /SILENT /SP- /SUPPRESSMSGBOXES /NORESTART /RELAUNCH=1; /RELAUNCH=1 starts the program again
; afterwards as the original, unelevated user (the Lazarus PDF / PhoneDeck pattern).

#ifndef AppVersion
  #error AppVersion must be given: ISCC /DAppVersion=x.y.z
#endif
#ifndef DistDir
  #define DistDir "dist\PlaylistFlow"
#endif
#define ExeName "PlaylistFlow.exe"
; AppId is the identity Windows tracks the install by. NEVER change it,
; or upgrades stop finding the old install and uninstall entries orphan.
#define AppGuid "{D3D56ED7-1039-478C-BA35-2F3D863CBE6F}"
#define ProductName "Playlist Flow"
#define SetupBase "PlaylistFlow-Setup-"

[Setup]
AppId={{#AppGuid}
AppName={#ProductName}
AppVersion={#AppVersion}
AppVerName={#ProductName} {#AppVersion}
AppPublisher=darkrelay.net
AppPublisherURL=https://darkrelay.net
AppSupportURL=https://github.com/Crazy8697/PlaylistFlow/issues
AppUpdatesURL=https://github.com/Crazy8697/PlaylistFlow/releases
AppComments=Order playlists so they flow, by key and tempo
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#ProductName} Setup
VersionInfoProductName={#ProductName}
DefaultDirName={autopf}\PlaylistFlow
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#ExeName}
UninstallDisplayName={#ProductName}
OutputBaseFilename={#SetupBase}{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#ProductName}"; Filename: "{app}\{#ExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#ExeName}"; Comment: "Order playlists so they flow, by key and tempo"
Name: "{autodesktop}\{#ProductName}"; Filename: "{app}\{#ExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#ExeName}"; Comment: "Order playlists so they flow, by key and tempo"; Tasks: desktopicon

[Run]
; offered on the last page; postinstall entries run as the original (unelevated) user
Filename: "{app}\{#ExeName}"; Description: "Launch Playlist Flow"; Flags: postinstall nowait skipifsilent
; an update from inside the program (/RELAUNCH=1): start it again when done, unelevated
Filename: "{app}\{#ExeName}"; Check: ShouldRelaunch; Flags: nowait runasoriginaluser

[Code]
function ShouldRelaunch(): Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;
