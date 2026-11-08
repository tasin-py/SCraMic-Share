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
; the folder page shows on a first install; updates keep the folder already chosen
DisableDirPage=auto
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
Name: "{autoprograms}\Uninstall SCraMic Share"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\SCraMicShare.exe"; Description: "Open SCraMic Share"; Flags: nowait postinstall skipifsilent
Filename: "{app}\SCraMicShare.exe"; Flags: nowait; Check: UpdatingFromApp

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM SCraMicShare.exe /F"; Flags: runhidden; RunOnceId: "StopApp"

[Code]
{ The app's Update button runs this installer with /update=1: no questions, and reopen the app at the end. }
function UpdatingFromApp: Boolean;
begin
  Result := ExpandConstant('{param:update|0}') = '1';
end;

{ This installs without administrator rights, so it can only use a folder the user can write to.
  Tries it, then removes any folders it made just for the test. }
function CanWriteTo(Dir: String): Boolean;
var
  Top, Test: String;
  Made: Boolean;
begin
  Dir := RemoveBackslashUnlessRoot(Dir);
  Top := Dir;
  while (not DirExists(ExtractFileDir(Top))) and (ExtractFileDir(Top) <> Top) do
    Top := ExtractFileDir(Top);
  Made := not DirExists(Dir);
  Test := AddBackslash(Dir) + 'scramicshare-write-test.tmp';
  Result := ForceDirectories(Dir) and SaveStringToFile(Test, 'x', False);
  DeleteFile(Test);
  if Made then
    DelTree(Top, True, True, True);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and not CanWriteTo(WizardDirValue) then
  begin
    MsgBox('SCraMic Share can''t install in this folder, because Windows only lets administrators change it.' + #13#10#13#10 +
           'Pick a folder of your own, for example D:\SCraMic Share.', mbError, MB_OK);
    Result := False;
  end;
end;

procedure RunAsAdmin(const Exe, Params: String);
var
  Code: Integer;
begin
  ShellExec('runas', Exe, Params, '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

{ ScramicShare Cam is registered by name, under the camera filter's id. The app finds it the same way. }
function CamInstalled: Boolean;
var
  Name: String;
begin
  Result := RegQueryStringValue(HKCR, 'CLSID\{860BB310-5D01-11d0-BD3B-00A0C911CE86}\Instance\{5C2CD55C-92AD-4999-8666-912BD3E70010}',
                                'FriendlyName', Name) and (Name = 'ScramicShare Cam');
end;

{ Deletes Dir, except its subfolder Keep (and what's in it). }
procedure DelTreeExcept(const Dir, Keep: String);
var
  F: TFindRec;
begin
  if FindFirst(Dir + '\*', F) then
  try
    repeat
      if (F.Name <> '.') and (F.Name <> '..') and (CompareText(F.Name, Keep) <> 0) then
        DelTree(Dir + '\' + F.Name, F.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0, True, True);
    until not FindNext(F);
  finally
    FindClose(F);
  end;
end;

procedure CurUninstallStepChanged(Step: TUninstallStep);
var
  Data, Mic: String;
  Cam, KeepCam: Boolean;
begin
  if (Step <> usUninstall) or UninstallSilent then
    Exit;
  Data := ExpandConstant('{userappdata}\SCraMicShare');
  Mic := Data + '\tools\vbcable\VBCABLE_Setup_x64.exe';
  Cam := CamInstalled;
  KeepCam := False;
  if (Cam or FileExists(Mic)) and
     (MsgBox('Also remove ScramicShare Cam and ScramicShare Mic? Windows will ask for permission.', mbConfirmation, MB_YESNO) = IDYES) then
  begin
    { The app removes the camera itself, so it also works when the camera's file was already deleted. }
    if Cam then
      RunAsAdmin(ExpandConstant('{app}\SCraMicShare.exe'), '--remove-cam');
    if FileExists(Mic) then
      RunAsAdmin(Mic, '-u -h');
  end
  else
    KeepCam := Cam;   { the camera still runs from its file in the tools folder, so that file must stay }
  if DirExists(Data) and
     (MsgBox('Also delete settings and downloaded tools?', mbConfirmation, MB_YESNO) = IDYES) then
  begin
    if KeepCam then
    begin
      DelTreeExcept(Data, 'tools');
      DelTreeExcept(Data + '\tools', 'ucam');
    end
    else
      DelTree(Data, True, True, True);
  end;
  if CamInstalled then
    MsgBox('ScramicShare Cam is still installed. To remove it later, see "Removing ScramicShare Cam and Mic" on the SCraMic Share GitHub page.',
           mbInformation, MB_OK);
end;
