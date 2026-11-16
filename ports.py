"""The app's ports: claimed so no other program can share them, and moved to free ones when they're taken.

Windows lets a second program listen on the same port on one of the PC's addresses (the WiFi one, say), and
phones then reach that program instead of this app. Programs for servers and virtual machines (VMware, Hyper-V,
Docker, port forwarding) do this. Claiming a port exclusively stops it, and shows the clash when the other program
was first: then the app takes another port. The QR code and links carry the port, so phones follow.
The ports that worked are kept, so the addresses stay the same from one start to the next.
"""
import csv
import io
import json
import os
import random
import re
import socket
import subprocess
from pathlib import Path

from applog import log

DATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "SCraMicShare"
KEPT = DATA / "ports.json"
NO_WINDOW = 0x08000000
SPARE = range(47810, 47900)   # tried when the usual port is taken, before any port Windows picks


def _kept():
    try:
        return json.loads(KEPT.read_text())
    except (OSError, ValueError):
        return {}


def keep(name, port):
    k = _kept()
    if k.get(name) != port:
        k[name] = port
        try:
            KEPT.write_text(json.dumps(k))
        except OSError:
            pass


def listen(name, host, usual, avoid=()):
    """A listening socket for this app alone, on the usual port if it can be had. Returns (socket, port)."""
    kept = _kept().get(name)
    spare = [p for p in SPARE if p != usual]
    random.shuffle(spare)
    tries = [p for p in dict.fromkeys([kept, usual] + spare + [0]) if p is not None and p not in avoid]
    for port in tries:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind((host, port))
            s.listen(128)
        except OSError as e:
            s.close()
            if port:
                why = (" (Windows keeps it for itself: Hyper-V, WSL or Docker)" if reserved(port)
                       else owner_text(port))
                log.warning("Port %s (%s site on %s) can't be used: %s%s", port, name, host, e, why)
            continue
        s.setblocking(False)
        got = s.getsockname()[1]
        if got != usual:
            log.warning("The %s site uses port %s instead of the usual %s", name, got, usual)
        keep(name, got)
        return s, got
    raise OSError(f"no free port for the {name} site")


def owner(port):
    """The program listening on this port, as "Name (service)", or "" if none or unknown."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10,
                             creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    pids = {line.split()[-1] for line in out.splitlines()
            if "LISTEN" in line and re.search(rf":{port}\s", line)}
    pids.discard(str(os.getpid()))
    names = []
    for pid in pids:
        try:
            r = subprocess.run(["tasklist", "/svc", "/fi", f"PID eq {pid}", "/fo", "csv", "/nh"],
                               capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW).stdout
            row = next(csv.reader(io.StringIO(r.strip())), [])
        except (OSError, subprocess.SubprocessError, StopIteration):
            row = []
        if len(row) >= 3 and row[1] == pid:
            svc = row[2] if row[2] not in ("N/A", "") else ""
            names.append(f"{row[0]} ({svc})" if svc else row[0])
        elif pid != "0":
            names.append(f"process {pid}")
    return ", ".join(sorted(set(names)))


def owner_text(port):
    o = owner(port)
    return f" (used by {o})" if o else ""


def reserved(port):
    """Is this port in a range Windows keeps for itself (Hyper-V, WSL and Docker reserve ranges)?"""
    try:
        out = subprocess.run(["netsh", "interface", "ipv4", "show", "excludedportrange", "protocol=tcp"],
                             capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    for a, b in re.findall(r"^\s*(\d+)\s+(\d+)", out, re.M):
        if int(a) <= port <= int(b):
            return True
    return False
