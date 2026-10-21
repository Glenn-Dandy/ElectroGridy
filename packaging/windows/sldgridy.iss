; Inno Setup script of the Windows installer. The release workflow calls
;   iscc /DAppVersion=1.3.0 /DNumericVersion=1.3.0 packaging\windows\sldgridy.iss
; after PyInstaller has put the program into dist\SLDGridy.

#ifndef AppVersion
  #define AppVersion "0"
#endif
#ifndef NumericVersion
  #define NumericVersion "0.0.0"
#endif

[Setup]
AppId={{950F70FD-B0FA-4FBD-A796-6B6326D1CD58}
AppName=SLDGridy
AppVersion={#AppVersion}
AppVerName=SLDGridy {#AppVersion}
AppPublisher=SLDGridy
AppPublisherURL=https://github.com/Glenn-Dandy/SLDGridy
AppSupportURL=https://github.com/Glenn-Dandy/SLDGridy/issues
VersionInfoVersion={#NumericVersion}
DefaultDirName={autopf}\SLDGridy
DefaultGroupName=SLDGridy
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=SLDGridy-{#AppVersion}-setup
SetupIconFile=..\..\build\sldgridy.ico
UninstallDisplayIcon={app}\SLDGridy.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Installs for all users (asks for administrator rights) or, if chosen, for the
; current user only.
PrivilegesRequiredOverridesAllowed=dialog
ChangesAssociations=yes

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\SLDGridy\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; An update must not keep files of the previous version (old Qt libraries).
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\SLDGridy"; Filename: "{app}\SLDGridy.exe"
Name: "{autodesktop}\SLDGridy"; Filename: "{app}\SLDGridy.exe"; Tasks: desktopicon

[Registry]
; .sldg files open with SLDGridy.
Root: HKA; Subkey: "Software\Classes\.sldg\OpenWithProgids"; ValueType: string; ValueName: "SLDGridy.Drawing"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\SLDGridy.Drawing"; ValueType: string; ValueName: ""; ValueData: "SLDGridy"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SLDGridy.Drawing\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\SLDGridy.exe,0"
Root: HKA; Subkey: "Software\Classes\SLDGridy.Drawing\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SLDGridy.exe"" ""%1"""

[Run]
Filename: "{app}\SLDGridy.exe"; Description: "{cm:LaunchProgram,SLDGridy}"; Flags: nowait postinstall skipifsilent
