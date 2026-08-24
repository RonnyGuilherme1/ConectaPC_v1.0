#define MyAppName "ConectaPC"
#define MyAppVersion "2.1.0"
#define MyAppPublisher "ConectaPC"
#define MyAppExeName "ConectaPC.exe"

[Setup]
AppId={{3EA53E81-92F7-4DCC-B346-9A2F2BA3C0F1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ConectaPC
DefaultGroupName=ConectaPC
DisableProgramGroupPage=yes
OutputDir=dist_installer
OutputBaseFilename=ConectaPC_Setup_v2.1.0
SetupIconFile=assets\conectapc.ico
UninstallDisplayIcon={app}\ConectaPC.exe
WizardStyle=modern
WizardImageFile=assets\wizard.bmp
WizardSmallImageFile=assets\wizard-small.bmp
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"; Flags: checkedonce

[Files]
Source: "dist\ConectaPC\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ConectaPC"; Filename: "{app}\ConectaPC.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\ConectaPC"; Filename: "{app}\ConectaPC.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""ConectaPC TCP LAN"""; Flags: runhidden waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""ConectaPC UDP LAN"""; Flags: runhidden waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""ConectaPC TCP LAN"" dir=in action=allow program=""{app}\ConectaPC.exe"" protocol=TCP localport=45888 profile=private"; Flags: runhidden waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""ConectaPC UDP LAN"" dir=in action=allow program=""{app}\ConectaPC.exe"" protocol=UDP localport=45889 profile=private"; Flags: runhidden waituntilterminated
Filename: "{app}\ConectaPC.exe"; Description: "Abrir o ConectaPC"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""ConectaPC TCP LAN"""; Flags: runhidden waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""ConectaPC UDP LAN"""; Flags: runhidden waituntilterminated

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  UpdateDir: String;
begin
  if CurStep = ssPostInstall then
  begin
    UpdateDir := ExpandConstant('{localappdata}\ConectaPC\updates');
    ForceDirectories(UpdateDir);
    FileCopy(ExpandConstant('{srcexe}'), UpdateDir + '\current_setup.exe', False);
  end;
end;
