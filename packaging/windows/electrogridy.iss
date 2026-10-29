; Inno Setup script of the Windows installer. The release workflow calls
;   iscc /DAppVersion=1.3.0 /DNumericVersion=1.3.0 packaging\windows\electrogridy.iss
; after PyInstaller has put the program into dist\ElectroGridy.

#ifndef AppVersion
  #define AppVersion "0"
#endif
#ifndef NumericVersion
  #define NumericVersion "0.0.0"
#endif

[Setup]
AppId={{950F70FD-B0FA-4FBD-A796-6B6326D1CD58}
AppName=ElectroGridy
AppVersion={#AppVersion}
AppVerName=ElectroGridy {#AppVersion}
AppPublisher=ElectroGridy
AppPublisherURL=https://github.com/Glenn-Dandy/ElectroGridy
AppSupportURL=https://github.com/Glenn-Dandy/ElectroGridy/issues
VersionInfoVersion={#NumericVersion}
DefaultDirName={autopf}\ElectroGridy
; The same AppId as SLDGridy (the name until 1.3.2) replaces it, but in the new folder.
UsePreviousAppDir=no
DefaultGroupName=ElectroGridy
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=ElectroGridy-{#AppVersion}-setup
SetupIconFile=..\..\build\electrogridy.ico
UninstallDisplayIcon={app}\ElectroGridy.exe
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
Source: "..\..\dist\ElectroGridy\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; An update must not keep files of the previous version (old Qt libraries).
Type: filesandordirs; Name: "{app}\_internal"
; SLDGridy, the name until 1.3.2.
Type: filesandordirs; Name: "{autopf}\SLDGridy"
Type: files; Name: "{autoprograms}\SLDGridy.lnk"
Type: files; Name: "{autodesktop}\SLDGridy.lnk"

[Icons]
Name: "{autoprograms}\ElectroGridy"; Filename: "{app}\ElectroGridy.exe"
Name: "{autodesktop}\ElectroGridy"; Filename: "{app}\ElectroGridy.exe"; Tasks: desktopicon

[Registry]
; .grdy files and the old .sldg files open with ElectroGridy.
Root: HKA; Subkey: "Software\Classes\.grdy\OpenWithProgids"; ValueType: string; ValueName: "ElectroGridy.Drawing"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.sldg\OpenWithProgids"; ValueType: string; ValueName: "ElectroGridy.Drawing"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\ElectroGridy.Drawing"; ValueType: string; ValueName: ""; ValueData: "ElectroGridy"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\ElectroGridy.Drawing\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\ElectroGridy.exe,0"
Root: HKA; Subkey: "Software\Classes\ElectroGridy.Drawing\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\ElectroGridy.exe"" ""%1"""
; Registration of SLDGridy, the name until 1.3.2.
Root: HKA; Subkey: "Software\Classes\.sldg\OpenWithProgids"; ValueType: none; ValueName: "SLDGridy.Drawing"; Flags: deletevalue
Root: HKA; Subkey: "Software\Classes\SLDGridy.Drawing"; Flags: deletekey

[Run]
Filename: "{app}\ElectroGridy.exe"; Description: "{cm:LaunchProgram,ElectroGridy}"; Flags: nowait postinstall skipifsilent
