; Windows installer for DynaMix. Built by packaging\build_windows.bat after the PyInstaller
; folder build, or by hand from the repository root:
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=0.2.0 packaging\dynamix.iss
; Result: dist\DynaMix-<version>-setup.exe
;
; Installs per user (no administrator rights, no UAC prompt). FFmpeg is NOT shipped: it is GPL
; and DynaMix is MIT, so the Configuration tab downloads it from its own authors on request.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "DynaMix"
#define AppPublisher "timox"
#define AppURL "https://github.com/timox/dynamix"
#define AppExe "DynaMix.exe"

[Setup]
AppId={{9F2C1E64-7C0B-4E5A-9E6F-4B1D3A6D2C57}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}

; per-user install: no administrator rights, and no UAC prompt on an unsigned installer
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}

OutputDir=..\dist
OutputBaseFilename={#AppName}-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; the whole PyInstaller folder build (DynaMix.exe plus its _internal folder)
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; the installer records every file it copies and removes them; this clears what the frozen Python
; writes next to itself while running (__pycache__ and the like), so no empty folder is left behind
Type: filesandordirs; Name: "{app}\_internal"
