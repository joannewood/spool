; SPOOL Windows Installer — Inno Setup script (https://jrsoftware.org/isinfo.php,
; free, produces a real wizard-style Setup.exe). Wraps setup.ps1 the same way
; the Mac installer wraps setup.sh via Platypus (scripts/build-mac-installer.sh).
;
; Unsigned for v1 (a deliberate cost/tradeoff decision, not an oversight —
; see README's "Known limitations"): testers will see a one-time Windows
; SmartScreen "Windows protected your PC" warning on first run and need to
; click "More info" -> "Run anyway". A code-signing certificate would reduce
; or remove this but costs real money annually and, for anything short of an
; EV certificate, doesn't guarantee it disappears immediately either.
;
; Built via .github/workflows/build-windows-installer.yml on a GitHub-hosted
; windows-latest runner — there's no Windows machine in this project's normal
; dev loop to build/test this locally, unlike scripts/build-mac-installer.sh.
; Install ISCC.exe yourself (via `choco install innosetup` or
; https://jrsoftware.org/isdl.php) if you ever need to build this by hand.

#define MyAppName "SPOOL"
#define MyAppVersion "1.0"
#define MyAppPublisher "SPOOL"
#define MyAppURL "https://github.com/joannewood/spool"

[Setup]
AppId={{B6C1F2B0-6E1F-4E9F-9A9B-1B7B6C9F1A11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
; Per-user, no admin required — the same "runs as the normal logged-in
; user, no privilege boundary" execution model the Mac installer uses
; (Platypus .app, no .pkg), and avoids a UAC prompt entirely. AppData\Local
; (not Documents) specifically to sidestep a Windows equivalent of the
; iCloud "Optimize Mac Storage" eviction/deadlock issue already hit and
; documented for this project — Documents can be OneDrive-redirected
; (Known Folder Move) on a lot of real Windows installs, AppData\Local
; normally isn't.
DefaultDirName={localappdata}\SPOOL
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=SPOOL-Installer
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
; Everything from the tracked repo — this .iss lives in scripts\, so ..\*
; is the repo root, matching how scripts\build-mac-installer.sh's git
; archive HEAD also exports exactly the tracked tree. Excludes covers
; things that would either bloat the installer or make no sense on a
; fresh Windows machine (Mac-only build tooling, git internals).
Source: "..\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: ".git,.github,.platypus-tools,dist,__pycache__,*.pyc"

[Run]
; Hands off to setup.ps1 exactly the way the Mac installer's wrapper
; script execs ./setup.sh — same script, same behavior, whether run from
; a PowerShell window directly or from inside this wrapped installer.
; runasoriginaluser matters if someone manually "Run as administrator"s
; this installer despite PrivilegesRequired=lowest — keeps setup.ps1
; running as the normal user either way, same reasoning as avoiding a
; .pkg's root-context scripts on the Mac side.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup.ps1"""; WorkingDir: "{app}"; Flags: postinstall runasoriginaluser skipifsilent; Description: "Run SPOOL setup now"
