; Installeur Windows du planning des perms (spec V3, V3-14). Compilation : python construire.py
; Paramètres de ligne de commande : /DVersion=0.3.0  /DDist=<dossier dist>  /DSortie=<dossier de sortie>
#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Dist
  #define Dist SourcePath + "build\dist"
#endif
#ifndef Sortie
  #define Sortie SourcePath + "build"
#endif

[Setup]
AppId={{D124E6B4-1B4F-4D5A-AAF0-36B78A1D49D6}
AppName=Planning des perms
AppVersion={#Version}
AppVerName=Planning des perms {#Version}
AppPublisher=Crèche Balustrade
DefaultDirName={autopf}\Planning des perms
DisableDirPage=yes
DisableProgramGroupPage=yes
DefaultGroupName=Planning des perms
PrivilegesRequired=lowest
WizardStyle=modern
SetupIconFile=icone.ico
UninstallDisplayIcon={app}\icone.ico
UninstallDisplayName=Planning des perms
CloseApplications=yes
RestartApplications=no
OutputDir={#Sortie}
; Nom fixe : le bouton « Télécharger » du README pointe sur releases/latest/download/<ce nom>.
OutputBaseFilename=Installer-Planning-des-perms
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoVersion={#Version}
VersionInfoDescription=Installeur du planning des perms

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Messages]
french.FinishedLabel=L'installation de [name] est terminée. Une icône a été ajoutée sur le Bureau et dans le menu Démarrer.%n%nVos plannings (dossier balustrade-planning) et vos réglages ne sont pas supprimés si vous désinstallez l'application.

[CustomMessages]
french.LancerApp=Lancer le planning des perms

[Files]
Source: "{#Dist}\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Dist}\planning-perms\*"; DestDir: "{app}\planning-perms"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "icone.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\Planning des perms"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\planning-perms\app\demarrer.py"""; WorkingDir: "{app}\planning-perms"; IconFilename: "{app}\icone.ico"; Comment: "Planning mensuel des permanences"
Name: "{userprograms}\Planning des perms"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\planning-perms\app\demarrer.py"""; WorkingDir: "{app}\planning-perms"; IconFilename: "{app}\icone.ico"; Comment: "Planning mensuel des permanences"

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\planning-perms\app\demarrer.py"""; WorkingDir: "{app}\planning-perms"; Description: "{cm:LancerApp}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Caches Python créés après l'installation, puis tout le dossier d'installation.
; Les données utilisateur (~\balustrade-planning, %APPDATA%\balustrade-planning) sont ailleurs et restent.
Type: filesandordirs; Name: "{app}"

[Code]
// Arrête les processus dont l'exécutable est sous {app} (pythonw.exe, python.exe) : leurs fichiers
// sont verrouillés et bloqueraient la mise à jour ou la désinstallation. Les autres processus sont épargnés.
procedure ArreterProcessusDeLApplication();
var
  Dossier, Commande: String;
  Code: Integer;
begin
  Dossier := RemoveBackslash(ExpandConstant('{app}'));
  StringChangeEx(Dossier, '''', '''''', True);
  Commande := '-NoProfile -NonInteractive -Command "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith(''' + Dossier + '\'', ''OrdinalIgnoreCase'') -and $_.Name -notlike ''unins*'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"';
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Commande, '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(800);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  ArreterProcessusDeLApplication();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  ArreterProcessusDeLApplication();
  Result := True;
end;
