; Builds SCraMicShare-Setup-x.x.x.exe with Inno Setup, from what PyInstaller made in dist/SCraMicShare.
;   iscc /DAppVersion=1.0.0 installer/scramicshare.iss

[Setup]
AppId={{8F2D6C1E-4B7A-4E93-9A51-2C7E1D0B6A34}
AppName=SCraMic Share
AppVersion={#AppVersion}
AppPublisher=Tasin's problem
AppPublisherURL=https://github.com/tasin-py/SCraMic-Share
DefaultDirName={localappdata}\Programs\SCraMic Share
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=SCraMicShare-Setup-{#AppVersion}
SetupIconFile=..\build\scramicshare.ico
UninstallDisplayIcon={app}\SCraMicShare.exe
UninstallDisplayName=SCraMic Share
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Add a desktop shortcut"

[Files]
Source: "..\dist\SCraMicShare\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\SCraMic Share"; Filename: "{app}\SCraMicShare.exe"
Name: "{autodesktop}\SCraMic Share"; Filename: "{app}\SCraMicShare.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SCraMicShare.exe"; Description: "Open SCraMic Share"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM SCraMicShare.exe /F"; Flags: runhidden; RunOnceId: "StopApp"

[Code]
procedure RunAsAdmin(const Exe, Params: String);
var
  Code: Integer;
begin
  ShellExec('runas', Exe, Params, '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

procedure CurUninstallStepChanged(Step: TUninstallStep);
var
  Data, Dll, Mic: String;
begin
  if (Step <> usUninstall) or UninstallSilent then
    Exit;
  Data := ExpandConstant('{userappdata}\SCraMicShare');
  Dll := Data + '\tools\ucam\UnityCaptureFilter64.dll';
  Mic := Data + '\tools\vbcable\VBCABLE_Setup_x64.exe';
  if (FileExists(Dll) or FileExists(Mic)) and
     (MsgBox('Also remove ScramicShare Cam and ScramicShare Mic? Windows will ask for permission.', mbConfirmation, MB_YESNO) = IDYES) then
  begin
    if FileExists(Dll) then
      RunAsAdmin('regsvr32.exe', '/s /u "' + Dll + '"');
    if FileExists(Mic) then
      RunAsAdmin(Mic, '-u -h');
  end;
  if DirExists(Data) and
     (MsgBox('Also delete settings and downloaded tools?', mbConfirmation, MB_YESNO) = IDYES) then
    DelTree(Data, True, True, True);
end;
