"""Which devices reached the phone site, and whether their secure (HTTPS) connection worked.

asyncio sets up HTTPS connections itself and keeps quiet when one fails, so the app would never know that a phone
got this far. This listens in on asyncio's TLS layer, for this app's server side only, and notes each device's
outcome: a phone that reached this PC but couldn't connect is something the Wireless screen can explain.
If a Python update changes asyncio's insides, this just notes nothing; the app works the same.
"""
import threading
import time

from applog import log

seen = {}             # ip -> {"ok": time, "fail": time, "kind": ..., "error": ..., "fails": n}
_lock = threading.Lock()
_logged = {}          # (ip, kind) -> time, so a phone retrying doesn't fill the log
ignore = set()        # this PC's own addresses: the app's self-check connects from them

# Chrome and Safari close the connection this way when they show their "Not private" page. That's expected.
CERT_WARNING = ("CERTIFICATE_UNKNOWN", "UNKNOWN_CA", "BAD_CERTIFICATE", "CERTIFICATE_UNSUPPORTED")


def kind_of(error):
    e = str(error).upper()
    if not e:
        return "dropped"
    if any(c in e for c in CERT_WARNING):
        return "cert"
    if "HTTP_REQUEST" in e:
        return "http"          # the phone opened http:// instead of https://
    if isinstance(error, (ConnectionError, TimeoutError)) or "EOF" in e:
        return "dropped"
    return "tls"


def note(ip, ok, error=None):
    if not ip or ip in ignore or ip.startswith("127."):
        return
    now = time.time()
    with _lock:
        s = seen.setdefault(ip, {"ok": 0, "fail": 0, "kind": "", "error": "", "fails": 0})
        if ok:
            if not s["ok"]:
                log.info("Phone at %s made a secure connection", ip)
            s["ok"] = now
            return
        kind = kind_of(error)
        s.update(fail=now, kind=kind, error=str(error)[:200] or "connection closed before it was secure")
        s["fails"] += 1
    if now - _logged.get((ip, kind), 0) > 60:
        _logged[(ip, kind)] = now
        log.info("Phone at %s reached this PC but its secure connection failed (%s): %s",
                 ip, kind, str(error)[:200] or "closed early")


def report():
    """What the Wireless screen shows: each device seen in the last 10 minutes."""
    now = time.time()
    with _lock:
        return [{"ip": ip, "ok": bool(s["ok"]), "working": s["ok"] >= s["fail"], "okAgo": round(now - s["ok"]) if s["ok"] else None,
                 "failAgo": round(now - s["fail"]) if s["fail"] else None,
                 "kind": s["kind"], "error": s["error"], "fails": s["fails"]}
                for ip, s in seen.items() if now - max(s["ok"], s["fail"]) < 600]


def install():
    try:
        from asyncio import sslproto
        P = sslproto.SSLProtocol
        made, done, lost = P.connection_made, P._on_handshake_complete, P.connection_lost
    except (ImportError, AttributeError):
        log.info("TLS watch not available on this Python")
        return

    def connection_made(self, transport):
        if getattr(self, "_server_side", False):
            try:
                self._scs_peer = (transport.get_extra_info("peername") or ("",))[0]
            except Exception:
                self._scs_peer = ""
        return made(self, transport)

    def on_handshake_complete(self, exc):
        peer = getattr(self, "_scs_peer", None)
        if peer is not None and not getattr(self, "_scs_done", False):
            self._scs_done = True
            try:
                note(peer, exc is None, exc)
            except Exception:
                pass
        return done(self, exc)

    def connection_lost(self, exc):
        peer = getattr(self, "_scs_peer", None)
        if peer is not None and not getattr(self, "_scs_done", False):
            self._scs_done = True
            try:
                if exc is not None:   # a clean close before any handshake is a browser's spare connection
                    note(peer, False, exc)
            except Exception:
                pass
        return lost(self, exc)

    P.connection_made, P._on_handshake_complete, P.connection_lost = \
        connection_made, on_handshake_complete, connection_lost
