# SCraMic Share uninstall (current user). Also offers to remove ScramicShare Cam / Mic.
$AppName = 'SCraMic Share'
$Dest    = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$Data    = Join-Path $env:APPDATA 'SCraMicShare'

Write-Host ''
Write-Host "  Uninstalling $AppName..." -ForegroundColor White

# stop the app
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*scramicshare.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# virtual camera / mic (need admin, Windows asks)
$ans = Read-Host '  Also remove "ScramicShare Cam" and "ScramicShare Mic"? (y/N)'
if ($ans -match '^[yY]') {
    $dll = Get-ChildItem (Join-Path $Data 'tools\ucam') -Filter 'UnityCaptureFilter64.dll' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($dll) { Start-Process regsvr32.exe -ArgumentList '/s', '/u', ('"' + $dll.FullName + '"') -Verb RunAs -Wait }
    $vb = Get-ChildItem (Join-Path $Data 'tools\vbcable') -Filter 'VBCABLE_Setup_x64.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($vb) { Start-Process $vb.FullName -ArgumentList '-u', '-h' -Verb RunAs -Wait }
}

# shortcuts, files, "Installed apps" entry
Remove-Item (Join-Path ([Environment]::GetFolderPath('Programs')) "$AppName.lnk") -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk") -ErrorAction SilentlyContinue
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SCraMicShare' -Recurse -ErrorAction SilentlyContinue
$ans = Read-Host '  Also delete settings and downloaded tools (pairing key, Android tools, receivers)? (y/N)'
if ($ans -match '^[yY]') { Remove-Item $Data -Recurse -Force -ErrorAction SilentlyContinue }

# the folder this script lives in goes last (after this window closes)
Start-Process cmd.exe -ArgumentList '/c', 'timeout /t 2 >nul & rmdir /s /q "' + $Dest + '"' -WindowStyle Hidden
Write-Host "  $AppName was removed." -ForegroundColor Green
Start-Sleep 2
