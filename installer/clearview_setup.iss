; ============================================================================
; ClearView — Inno Setup Installer Script
; ============================================================================
;
; How to build:
;   1. Install Inno Setup 6  (https://jrsoftware.org/isdl.php)
;   2. Run PyInstaller first:
;        pyinstaller ClearView.spec
;   3. Open this file in Inno Setup Compiler (or run):
;        iscc installer\clearview_setup.iss
;   4. Installer will be created at:  installer\Output\ClearView_Setup.exe
;
; ============================================================================

#define AppName      "ClearView"
#define AppVersion   "2.0"
#define AppPublisher "ClearView"
#define AppURL       "https://github.com/ThatsAli-1/ClearView"
#define AppExeName   "ClearView.exe"
#define AppDescription "AI-powered video content guardian — scan, warn, and blur sensitive scenes in real time"

; Path to the PyInstaller output folder (relative to this script's location)
#define BuildDir     "..\dist\ClearView"

[Setup]
; ── Identity ─────────────────────────────────────────────────────────────────
AppId={{A3F2D9B1-7C4E-4A8F-B6D2-E91C3F5A8B47}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}.0.0
VersionInfoDescription={#AppDescription}

; ── Install location ─────────────────────────────────────────────────────────
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=no
PrivilegesRequired=lowest          ; Install per-user, no admin needed
PrivilegesRequiredOverridesAllowed=dialog

; ── Output ───────────────────────────────────────────────────────────────────
OutputDir=Output
OutputBaseFilename=ClearView_Setup_v{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}

; ── Compression ──────────────────────────────────────────────────────────────
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; ── Appearance ───────────────────────────────────────────────────────────────
WizardStyle=modern
WizardSmallImageFile=..\assets\icon.ico
DisableWelcomePage=no
DisableDirPage=no
DisableProgramGroupPage=no

; ── Behaviour ─────────────────────────────────────────────────────────────────
CloseApplications=yes
CloseApplicationsFilter=*.exe
ChangesAssociations=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";  Description: "Create a &Desktop shortcut";  GroupDescription: "Additional icons:"; Flags: unchecked
Name: "startmenuicon"; Description: "Create a &Start Menu entry"; GroupDescription: "Additional icons:"; Flags: checked

[Files]
; Copy all PyInstaller build output into the install directory
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu
Name: "{group}\{#AppName}";     Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Comment: "{#AppDescription}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

; Desktop shortcut (optional, controlled by Tasks above)
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Offer to launch the app immediately after install
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove the scans folder created by the app (if user leaves it)
Type: filesandordirs; Name: "{app}\scans"

[Code]
// ─── Custom installer pages & logic ────────────────────────────────────────

procedure InitializeWizard();
begin
  // Nothing extra needed — model downloads at runtime.
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
end;
