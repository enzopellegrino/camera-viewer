[Setup]
AppName=Camera Viewer
AppVersion=1.0.0
AppPublisher=Enzo Pellegrino
AppPublisherURL=mailto:enzo@n1computer.it
AppSupportURL=mailto:enzo@n1computer.it
DefaultDirName={autopf}\Camera Viewer
DefaultGroupName=Camera Viewer
OutputDir=dist
OutputBaseFilename=Camera Viewer Setup
SetupIconFile=icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\Camera Viewer.exe
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "Crea un'icona sul {cm:DesktopName}"; GroupDescription: "Icone aggiuntive:"; Flags: checked

[Files]
Source: "dist\Camera Viewer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Camera Viewer"; Filename: "{app}\Camera Viewer.exe"
Name: "{group}\Disinstalla Camera Viewer"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Camera Viewer"; Filename: "{app}\Camera Viewer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Camera Viewer.exe"; Description: "Avvia Camera Viewer"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
