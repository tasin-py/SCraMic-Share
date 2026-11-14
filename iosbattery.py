"""An iPhone's battery, read through Apple Mobile Device Service (installed with iTunes or Apple Devices).

iPhone browsers can't tell a website the battery level, so the phone's page can't send it like Android does.
Windows can, though: the same service iTunes uses lists iPhones on a USB cable (and on WiFi, if WiFi sync is on)
and lets a PC the iPhone trusts ask it questions. This asks just one: the battery.

The protocol: usbmuxd on 127.0.0.1:27015 lists devices and opens a connection to the iPhone's lockdownd
(port 62078). lockdownd answers plain questions in plists, after a TLS session made with this PC's pair record.
Nothing here needs admin rights.

Over WiFi: once the iPhone has "WiFi connections" on, its lockdownd also listens on its WiFi address. The
iPhone is connected to the app, so its address is known: this asks it there directly, with the same pair
record (Apple's own list of WiFi iPhones can lag behind, or hold an old pair record). "WiFi connections" is
the "Show this iPhone when on Wi-Fi" box in iTunes / Apple Devices. Whenever the battery is read over the
cable, this turns it on too (the one thing changed on the phone), so after plugging in once, the battery
keeps showing over WiFi.

Trust: an iPhone only answers a PC it trusts. setup() asks for that itself, the way iTunes does: it makes this
PC's keys, sends lockdownd a Pair request (the iPhone shows "Trust This Computer?"), and keeps the record that
comes back, with Apple's service and in the app's own folder.
"""
import os
import plistlib
import socket
import ssl
import warnings
import struct
import sys
import tempfile
import time

USBMUXD = ("127.0.0.1", 27015)
LOCKDOWN_PORT = 62078
LABEL = "SCraMicShare"
OWN_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "SCraMicShare", "iphone")   # records made here
LOCKDOWN_DIR = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Apple", "Lockdown")


class Unavailable(Exception):
    """No service, no iPhone, or the iPhone hasn't trusted this PC. .why says which, for the app's note:
    "driver" (no Apple service), "none" (no iPhone found), "trust" (found, but it won't answer this PC)."""
    def __init__(self, text, why="trust"):
        super().__init__(text)
        self.why = why


# ---------------------------------------------------------------- usbmuxd
def _mux_socket():
    try:
        return socket.create_connection(USBMUXD, timeout=4)
    except OSError as e:
        raise Unavailable("Apple Mobile Device Service isn't running", "driver") from e


def _mux_send(sock, msg, tag=1):
    body = plistlib.dumps({"ClientVersionString": LABEL, "ProgName": LABEL, **msg})
    sock.sendall(struct.pack("<IIII", 16 + len(body), 1, 8, tag) + body)   # version 1, plist message


def _recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise Unavailable("the connection closed", "trust")
        data += chunk
    return data


def _mux_recv(sock):
    length, _, _, _ = struct.unpack("<IIII", _recv_exact(sock, 16))
    return plistlib.loads(_recv_exact(sock, length - 16))


def _mux_ask(msg):
    with _mux_socket() as s:
        _mux_send(s, msg)
        return _mux_recv(s)


def devices():
    """[(device id, udid, "USB" | "Network")], cable first."""
    out = []
    for d in _mux_ask({"MessageType": "ListDevices"}).get("DeviceList", []):
        p = d.get("Properties", {})
        if p.get("SerialNumber"):
            out.append((d.get("DeviceID"), p["SerialNumber"], p.get("ConnectionType", "")))
    return sorted(out, key=lambda d: d[2] != "USB")


_good = {}   # udid -> the pair record the iPhone accepted last


def _pair_records(udid):
    """This PC's pair records for the iPhone, the likeliest first. After a new Trust, Apple's service can keep
    handing out the old record while the new one waits in a .plist.tmp file, so all of them are tried."""
    out = [_good[udid]] if udid in _good else []
    try:
        r = _mux_ask({"MessageType": "ReadPairRecord", "PairRecordID": udid})
        if r.get("PairRecordData"):
            out.append(plistlib.loads(r["PairRecordData"]))
    except (Unavailable, OSError, ValueError, plistlib.InvalidFileException):
        pass
    files = []
    for folder in (OWN_DIR, LOCKDOWN_DIR):
        try:
            files += [os.path.join(folder, f) for f in os.listdir(folder) if f.startswith(udid + ".plist")]
        except OSError:
            pass
    for path in sorted(files, key=lambda f: -os.path.getmtime(f)):   # newest first
        try:
            with open(path, "rb") as f:
                out.append(plistlib.load(f))
        except (OSError, ValueError, plistlib.InvalidFileException):
            pass
    seen, records = set(), []
    for r in out:
        if isinstance(r, dict) and r.get("HostID") and r["HostID"] not in seen and "HostCertificate" in r:
            seen.add(r["HostID"])
            records.append(r)
    if not records:
        raise Unavailable("this iPhone hasn't trusted this PC", "none")
    return records


# ---------------------------------------------------------------- lockdownd
def _ld_send(sock, msg):
    body = plistlib.dumps({"Label": LABEL, **msg})
    sock.sendall(struct.pack(">I", len(body)) + body)


def _ld_recv(sock):
    (length,) = struct.unpack(">I", _recv_exact(sock, 4))
    return plistlib.loads(_recv_exact(sock, length))


def _ld_ask(sock, msg):
    _ld_send(sock, msg)
    r = _ld_recv(sock)
    if "Error" in r:
        raise Unavailable(f"the iPhone said {r['Error']}")
    return r


def _tls(sock, record):
    """lockdownd's TLS: this PC proves itself with the certificate from the pair record."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            ctx.minimum_version = ssl.TLSVersion.TLSv1
        ctx.set_ciphers("ALL:@SECLEVEL=0")   # older iPhones only speak old TLS
    except (ValueError, ssl.SSLError):
        pass
    fd, path = tempfile.mkstemp(suffix=".pem")   # Python only loads a certificate from a file
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(record["HostCertificate"] + b"\n" + record["HostPrivateKey"])
        ctx.load_cert_chain(path)
    finally:
        os.remove(path)
    return ctx.wrap_socket(sock)


def battery(ip=None):
    """{"level": 0-100, "charging": bool, "via": "USB" | "WiFi"} of the iPhone. A cable one first, through
    Apple's service; then, given the address the iPhone uses to reach the app, straight over WiFi.
    Raises Unavailable when neither works."""
    last = None
    try:
        found = devices()
    except Unavailable as e:
        found, last = [], e
    for device_id, udid, kind in found:
        try:
            b = _battery_of(udid, lambda: _mux_connect(device_id), kind == "USB")
            b.pop("wifi", None)
            b["via"] = "USB" if kind == "USB" else "WiFi"
            return b
        except (Unavailable, OSError, ssl.SSLError, ValueError, KeyError) as e:
            last = e
    if ip:
        try:
            b = _battery_of(None, lambda: socket.create_connection((ip, LOCKDOWN_PORT), timeout=4), False, key=ip)
            b["via"] = "WiFi"
            return b
        except OSError as e:          # nothing listening: the iPhone's WiFi connections are off
            last = Unavailable(str(e), "none")
        except (Unavailable, ssl.SSLError, ValueError, KeyError) as e:
            last = e
    if last is None:
        raise Unavailable("no iPhone is connected", "none")
    if isinstance(last, Unavailable):
        raise last
    raise Unavailable(str(last), "trust")


def _mux_connect(device_id):
    sock = _mux_socket()
    port = struct.unpack("<H", struct.pack(">H", LOCKDOWN_PORT))[0]   # usbmuxd wants it in network order
    _mux_send(sock, {"MessageType": "Connect", "DeviceID": device_id, "PortNumber": port})
    if _mux_recv(sock).get("Number", 1) != 0:
        sock.close()
        raise Unavailable("couldn't reach the iPhone")
    return sock


def _wifi_on(sock):
    """Let this PC reach the iPhone over WiFi from now on (iTunes' "Show this iPhone when on Wi-Fi")."""
    domain = "com.apple.mobile.wireless_lockdown"
    try:
        r = _ld_ask(sock, {"Request": "GetValue", "Domain": domain, "Key": "EnableWifiConnections"})
        if r.get("Value") is not True:
            _ld_ask(sock, {"Request": "SetValue", "Domain": domain, "Key": "EnableWifiConnections", "Value": True})
        return True
    except (Unavailable, OSError, ssl.SSLError, ValueError):
        return False   # the battery still works over the cable


def _battery_of(udid, connect, cable=False, key=None):
    """Tries this PC's pair records until the iPhone takes one. udid None: the iPhone isn't known yet
    (straight over WiFi), so every iPhone record on this PC is tried, and the one that works is kept."""
    key = key or udid
    if udid:
        records = _pair_records(udid)
    else:
        records = ([_good[key]] if key in _good else []) + list(_good.values()) + _every_record()
    last = Unavailable("this iPhone hasn't trusted this PC", "none")
    for record in records:
        try:
            b = _battery_with(record, connect(), cable)
            _good[key] = record
            return b
        except Unavailable as e:
            if "InvalidHostID" not in str(e):     # anything but "not this record" won't change with another one
                raise
            last = Unavailable("this iPhone doesn't trust this PC anymore", "none")
    raise last


def _every_record():
    """Every iPhone pair record on this PC, newest first (a few at most: one per iPhone ever trusted)."""
    files = []
    for folder in (OWN_DIR, LOCKDOWN_DIR):
        try:
            files += [os.path.join(folder, f) for f in os.listdir(folder) if ".plist" in f and not f.startswith("System")]
        except OSError:
            pass
    out, seen = [], set()
    for path in sorted(files, key=lambda f: -os.path.getmtime(f)):
        try:
            with open(path, "rb") as f:
                r = plistlib.load(f)
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
        if isinstance(r, dict) and r.get("HostID") and "HostCertificate" in r and r["HostID"] not in seen:
            seen.add(r["HostID"])
            out.append(r)
    return out


def _battery_with(record, sock, cable):
    try:
        _ld_ask(sock, {"Request": "QueryType"})
        session = _ld_ask(sock, {"Request": "StartSession", "HostID": record["HostID"],
                                 "SystemBUID": record.get("SystemBUID", "")})
        if session.get("EnableSessionSSL"):
            sock = _tls(sock, record)
        value = _ld_ask(sock, {"Request": "GetValue", "Domain": "com.apple.mobile.battery"}).get("Value", {})
        wifi = _wifi_on(sock) if cable else None
        try:
            _ld_send(sock, {"Request": "StopSession", "SessionID": session.get("SessionID", "")})
        except OSError:
            pass
        level = value.get("BatteryCurrentCapacity")
        if not isinstance(level, int):
            raise Unavailable("the iPhone didn't say its battery level")
        b = {"level": level, "charging": bool(value.get("BatteryIsCharging") or
                                              (value.get("ExternalConnected") and not value.get("FullyCharged")))}
        if wifi is not None:
            b["wifi"] = wifi
        return b
    finally:
        sock.close()


# ---------------------------------------------------------------- Trust (pairing)
def _new_pair_record(device_public_key, wifi_mac):
    """This PC's side of a new pairing: a root certificate, and host and device certificates signed by it."""
    import datetime
    import uuid
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.timezone.utc)

    def cert(signer, public_key, name=None):
        n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)] if name else [])
        return (x509.CertificateBuilder().subject_name(n).issuer_name(x509.Name([])).public_key(public_key)
                .serial_number(1).not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(signer, hashes.SHA256()).public_bytes(serialization.Encoding.PEM))

    def private(key):
        return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                 serialization.NoEncryption())

    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    host_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    try:
        buid = _mux_ask({"MessageType": "ReadBUID"}).get("BUID")
    except Unavailable:
        buid = None
    return {
        "DeviceCertificate": cert(root_key, serialization.load_pem_public_key(device_public_key), "Device"),
        "HostCertificate": cert(root_key, host_key.public_key()),
        "RootCertificate": cert(root_key, root_key.public_key()),
        "HostPrivateKey": private(host_key),
        "RootPrivateKey": private(root_key),
        "HostID": str(uuid.uuid4()).upper(),
        "SystemBUID": buid or str(uuid.uuid4()).upper(),
        "WiFiMACAddress": wifi_mac or "",
    }


PAIR_STATES = {"PairingDialogResponsePending": "asking", "PasswordProtected": "locked",
               "UserDeniedPairing": "denied"}


def _pair(device_id, udid, record=None):
    """Asks the iPhone on the cable to trust this PC. Returns (state, record): state "ok" once Trust was
    tapped, else "asking" (the question is on the iPhone), "locked" (unlock it first) or "denied".
    Pass the record back in each time, so the iPhone is asked about the same PC until it answers."""
    sock = _mux_connect(device_id)
    try:
        _ld_ask(sock, {"Request": "QueryType"})
        if record is None:
            key = _ld_ask(sock, {"Request": "GetValue", "Key": "DevicePublicKey"}).get("Value")
            try:
                mac = _ld_ask(sock, {"Request": "GetValue", "Key": "WiFiAddress"}).get("Value", "")
            except Unavailable:
                mac = ""
            record = _new_pair_record(key, mac)
        shared = {k: record[k] for k in ("DeviceCertificate", "HostCertificate", "RootCertificate",
                                         "HostID", "SystemBUID", "WiFiMACAddress")}   # never the private keys
        _ld_send(sock, {"Request": "Pair", "PairRecord": shared, "ProtocolVersion": "2",
                        "PairingOptions": {"ExtendedPairingErrors": True}})
        r = _ld_recv(sock)
    finally:
        sock.close()
    if r.get("Error"):
        return PAIR_STATES.get(r["Error"], "error"), record
    record = dict(record)
    if r.get("EscrowBag"):
        record["EscrowBag"] = r["EscrowBag"]
    _keep(udid, device_id, record)
    return "ok", record


def _keep(udid, device_id, record):
    """Keeps a new pair record in the app's folder, and gives it to Apple's service (iTunes uses it too)."""
    _good[udid] = record
    data = plistlib.dumps(record)
    try:
        os.makedirs(OWN_DIR, exist_ok=True)
        with open(os.path.join(OWN_DIR, udid + ".plist"), "wb") as f:
            f.write(data)
    except OSError:
        pass
    try:
        _mux_ask({"MessageType": "SavePairRecord", "PairRecordID": udid, "PairRecordData": data, "DeviceID": device_id})
    except (Unavailable, OSError):
        pass


def setup(progress, stop, minutes=5):
    """The guide's steps, run until done, stopped (stop: a threading.Event) or out of time. progress(step,
    state, **extra) reports each change: ("service", "missing"), ("cable", "waiting"),
    ("trust", "asking" | "locked" | "denied" | "error"), ("done", "ok", battery=..., wifi=bool), ("end", "timeout")."""
    end = time.time() + minutes * 60
    record, said = None, None

    def say(step, state, **extra):
        nonlocal said
        if (step, state) != said or extra:
            said = (step, state)
            progress(step, state, **extra)

    while not stop.wait(0 if said is None else 1):
        if time.time() > end:
            return say("end", "timeout")
        try:
            usb = [d for d in devices() if d[2] == "USB"]
        except Unavailable:
            say("service", "missing")
            continue
        if not usb:
            say("cable", "waiting")
            continue
        device_id, udid, _ = usb[0]
        try:
            b = _battery_of(udid, lambda: _mux_connect(device_id), True)
            wifi = b.pop("wifi", False)
            return say("done", "ok", battery=b, wifi=wifi)
        except (Unavailable, OSError, ssl.SSLError, ValueError, KeyError):
            pass                       # not trusted yet: ask
        try:
            state, record = _pair(device_id, udid, record)
        except (Unavailable, OSError, ssl.SSLError, ValueError, KeyError):
            state = "error"
        if state != "ok":
            say("trust", state)


if __name__ == "__main__":
    try:
        print("devices:", [(d[0], d[1][:6] + "…", d[2]) for d in devices()])
        print("battery:", battery(sys.argv[1] if len(sys.argv) > 1 else None))
    except Unavailable as e:
        print("unavailable:", e)
