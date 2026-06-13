; Inno Setup script for Leike.
; Build with Build-installer.bat (which populates the staging\ folder first).

#define MyAppName "Leike"
#define MyAppVersion "1.12"
#define MyAppPublisher "Ville Mattila"
#define MyAppURL "https://github.com/Ville-Mattila/Leike"
#define MyAppExeName "Leike.exe"

[Setup]
; A unique, stable AppId so upgrades/uninstall are tracked correctly.
AppId={{8F3C5D2A-1B47-4E96-AE10-7C2F9B6D4A85}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\Leike
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install: no admin/UAC prompt needed.
PrivilegesRequired=lowest
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=Leike-Setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=..\leike.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "staging\Leike.exe";                 DestDir: "{app}"; Flags: ignoreversion
Source: "staging\ffmpeg.exe";                DestDir: "{app}"; Flags: ignoreversion
Source: "staging\LICENSE.txt";               DestDir: "{app}"; Flags: ignoreversion
Source: "staging\THIRD_PARTY_NOTICES.txt";   DestDir: "{app}"; Flags: ignoreversion
Source: "staging\licenses\*";                DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\{#MyAppName}";   Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
