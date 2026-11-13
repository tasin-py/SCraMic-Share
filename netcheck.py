"""Is something on this PC likely to stop the phone from connecting?

Checks the two things that usually do: Windows Firewall without a rule letting this app in, and an antivirus
firewall (Avast, Norton, ...) that blocks other devices on networks it calls Public. Reading these needs no admin
rights. Windows Firewall can be fixed from here, with the user's approval. An antivirus firewall can't be changed by
other apps, so the app shows the user where to change it.
"""
import json
import os
import subprocess
import sys

NO_WINDOW = 0x08000000
RULE = "SCraMic Share"

# Gets the IP and the exe through the environment, so nothing needs quoting.
_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$out = @{ category = ''; network = ''; firewalls = @(); windowsBlocks = $false }
$a = Get-NetIPAddress -IPAddress $env:SCS_IP | Select-Object -First 1
if ($a) {
  $p = Get-NetConnectionProfile -InterfaceIndex $a.InterfaceIndex | Select-Object -First 1
  if ($p) { $out.category = [string]$p.NetworkCategory; $out.network = [string]$p.Name }
}
$out.firewalls = @(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName FirewallProduct |
  Where-Object { (($_.productState -shr 8) -band 0x10) -and $_.displayName -notlike 'Windows*' } |
  ForEach-Object { [string]$_.displayName })
$fw = switch ($out.category) { 'Private' { 'Private' } 'DomainAuthenticated' { 'Domain' } default { 'Public' } }
if ((Get-NetFirewallProfile -Name $fw).Enabled -eq 'True') {
  $rules = @(Get-NetFirewallApplicationFilter -Program $env:SCS_EXE | Get-NetFirewallRule |
    Where-Object { $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' -and
                   ($_.Profile.ToString() -eq 'Any' -or $_.Profile.ToString() -match $fw) })
  $out.windowsBlocks = [bool](($rules | Where-Object Action -eq 'Block') -or -not ($rules | Where-Object Action -eq 'Allow'))
}
$out | ConvertTo-Json -Compress
"""


def check(ip):
    """{"category": "Public" | "Private" | "DomainAuthenticated" | "", "network": its name,
    "firewalls": [antivirus firewalls that are on], "windowsBlocks": bool, "exe": this app}"""
    out = {"category": "", "network": "", "firewalls": [], "windowsBlocks": False, "exe": sys.executable}
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", _SCRIPT],
                           capture_output=True, text=True, timeout=25, creationflags=NO_WINDOW,
                           env={**os.environ, "SCS_IP": ip, "SCS_EXE": sys.executable})
        found = json.loads(r.stdout.strip() or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return out   # can't tell: say nothing rather than warn about nothing
    out.update({k: found[k] for k in ("category", "network", "windowsBlocks") if k in found})
    fws = found.get("firewalls") or []
    out["firewalls"] = [fws] if isinstance(fws, str) else [f for f in fws if isinstance(f, str)]
    return out


def allow_in_windows_firewall(run_elevated):
    """Lets this app through Windows Firewall on every network. Windows asks for approval first.
    Clears this app's old inbound rules too: clicking Cancel on Windows' own question leaves a Block rule,
    and a Block rule beats any Allow."""
    exe = sys.executable
    return run_elevated("cmd.exe",
                        f'/c netsh advfirewall firewall delete rule name=all dir=in program="{exe}" & '
                        f'netsh advfirewall firewall add rule name="{RULE}" dir=in action=allow '
                        f'program="{exe}" enable=yes profile=any')
