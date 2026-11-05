# SCraMic Share setup
# Installs for the current user (no admin needed), into %LOCALAPPDATA%\Programs\SCraMic Share.
# Optional: ScramicShare Cam / Mic, which ask Windows for admin permission once.

$ErrorActionPreference = 'Stop'
$AppName = 'SCraMic Share'
$Src     = Split-Path -Parent $PSScriptRoot
$Dest    = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SCraMicShare'

function Say($text, $color = 'Gray') { Write-Host $text -ForegroundColor $color }
function Fail($text) { Say ''; Say $text 'Red'; Say ''; Read-Host 'Press Enter to close'; exit 1 }

Say ''
Say "  $AppName setup" 'White'
Say '  ---------------------------'

# ---- 1. Python 3.10 or newer
$py = $null
foreach ($cand in @('python', 'py')) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) {
        $ver = & $cmd.Source -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($ver -and ([version]$ver -ge [version]'3.10')) { $py = $cmd.Source; break }
    }
}
if (-not $py) {
    Say 'Python 3.10 or newer is needed. Opening the download page...' 'Yellow'
    Start-Process 'https://www.python.org/downloads/'
    Fail 'Install Python (tick "Add python.exe to PATH" on the first screen), then run this setup again.'
}
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }
Say "  Python: $py"

# ---- 2. copy the app
Say '  Copying the app...'
$running = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$Dest*scramicshare.py*" }
foreach ($p in $running) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force $Dest | Out-Null
$items = @('scramicshare.py', 'server.py', 'teacher.py', 'control.py', 'wired.py', 'tools.py', 'receivers.py',
           'rotateview.py', 'unitycam.py', 'updates.py', 'vdevices.py', 'requirements.txt', 'NOTICE', 'LICENSE', 'LICENSE-InkCast', 'web', 'installer')
foreach ($i in $items) {
    $from = Join-Path $Src $i
    if (Test-Path $from) { Copy-Item $from -Destination $Dest -Recurse -Force }
}

# ---- 3. libraries
Say '  Installing what it needs (this can take a minute)...'
& $py -m pip install --user --disable-pip-version-check -q -r (Join-Path $Dest 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail "Couldn't install the Python libraries. Check the internet connection and try again." }

# ---- 4. icon + shortcuts
$ico = Join-Path $Dest 'scramicshare.ico'
& $py (Join-Path $Dest 'installer\make_icon.py') $ico | Out-Null
$shell = New-Object -ComObject WScript.Shell
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) "$AppName.lnk"
$desktop   = Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk"
foreach ($lnkPath in @($startMenu, $desktop)) {
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $pyw
    $lnk.Arguments = '"' + (Join-Path $Dest 'scramicshare.py') + '"'
    $lnk.WorkingDirectory = $Dest
    $lnk.IconLocation = "$ico,0"
    $lnk.Description = 'Use your phone camera, mic and screen on this PC'
    $lnk.Save()
}
Say '  Shortcuts added to the Start menu and Desktop.'

# ---- 5. "Installed apps" entry (uninstall)
New-Item -Path $UninstallKey -Force | Out-Null
$un = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Dest 'installer\uninstall.ps1') + '"'
Set-ItemProperty $UninstallKey -Name DisplayName -Value $AppName
$version = & $py -c "import sys; sys.path.insert(0, r'$Dest'); import updates; print(updates.VERSION)"
Set-ItemProperty $UninstallKey -Name DisplayVersion -Value $version
Set-ItemProperty $UninstallKey -Name Publisher -Value "Tasin's problem"
Set-ItemProperty $UninstallKey -Name DisplayIcon -Value $ico
Set-ItemProperty $UninstallKey -Name InstallLocation -Value $Dest
Set-ItemProperty $UninstallKey -Name UninstallString -Value $un
Set-ItemProperty $UninstallKey -Name NoModify -Value 1 -Type DWord
Set-ItemProperty $UninstallKey -Name NoRepair -Value 1 -Type DWord

# ---- 6. optional: the phone as a camera and microphone in other apps
Say ''
$ans = Read-Host '  Also add "ScramicShare Cam" and "ScramicShare Mic" for Zoom, Meet, Discord, OBS? (Y/n)'
if ($ans -notmatch '^[nN]') {
    Say '  Windows will ask for permission. Click Yes.' 'Yellow'
    $code = @"
import sys, time
sys.path.insert(0, r'$Dest')
import server, tools, vdevices
t = tools.Tools(server.DATA)
msgs = []
h = vdevices.setup(t, msgs.append)
h({'a': 'install-cam'}); h({'a': 'install-mic'})
end = time.time() + 240
while time.time() < end and len(msgs) < 2:
    time.sleep(1)
print('camera:', 'ready' if vdevices.cam_installed() else 'not installed', '| mic:', vdevices.mic_state())
"@
    & $py -c $code
}

Say ''
Say "  Done! $AppName is installed." 'Green'
Start-Process $pyw -ArgumentList ('"' + (Join-Path $Dest 'scramicshare.py') + '"') -WorkingDirectory $Dest
Start-Sleep 2
