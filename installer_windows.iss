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
Name: "desktopicon"; Description: "Crea un'icona sul Desktop"; GroupDescription: "Icone aggiuntive:"

[Files]
Source: "dist\Camera Viewer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\Camera Viewer"; Filename: "{app}\Camera Viewer.exe"
Name: "{group}\Disinstalla Camera Viewer"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Camera Viewer"; Filename: "{app}\Camera Viewer.exe"; Tasks: desktopicon

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installazione prerequisiti Visual C++..."; Flags: waituntilterminated
Filename: "{app}\Camera Viewer.exe"; Description: "Avvia Camera Viewer"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
