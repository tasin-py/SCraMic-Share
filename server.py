"""SCraMic Share - local server.

Two sites run from one asyncio loop in a background thread:
  * http://127.0.0.1:<PC_PORT>   the PC app's own UI (loaded in the Qt window)
  * https://<lan-ip>:<PHONE_PORT> the phone website (HTTPS so the phone browser
                                   is allowed to use its camera and microphone)

Both sides connect to /ws. The server only relays messages between the one PC
page and the one phone; the audio/video itself goes phone -> PC over WebRTC.
"""
import asyncio
import datetime
import ipaddress
import json
import os
import secrets
import socket
import ssl
import threading
import webbrowser
from pathlib import Path

import qrcode
import qrcode.image.svg
from aiohttp import WSMsgType, web

import updates

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "SCraMicShare"
PC_PORT = 47800
PHONE_PORT = 47801
PHONE_LOCAL_PORT = 47802

ALLOWED_LINKS = (
    updates.RELEASES_PAGE,
    "https://fb.com/tasin.py",
    "https://instagram.com/tasin.py/",
    "https://github.com/tasin-py",
)


# ---------------------------------------------------------------- pairing key
def pairing_token():
    """Random key carried by the QR code. Only phones that scanned it can connect."""
    DATA.mkdir(parents=True, exist_ok=True)
    f = DATA / "pairing.key"
    try:
        t = f.read_text().strip()
        if len(t) >= 12:
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(12)
    f.write_text(t)
    return t


TOKEN = pairing_token()


def token_ok(request):
    return secrets.compare_digest(request.query.get("k", ""), TOKEN)


# ---------------------------------------------------------------- networking
def primary_ip():
    """IP of the adapter that holds the default route (normally the WiFi/LAN one)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # nothing is sent; just picks the route
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def all_ips():
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    p = primary_ip()
    if p in ips:
        ips.remove(p)
    if not p.startswith("127."):
        ips.insert(0, p)
    return ips


# ---------------------------------------------------------------- certificate
def ensure_cert(ips):
    """Self-signed certificate for the phone site, remade when the PC's IPs change."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    DATA.mkdir(parents=True, exist_ok=True)
    crt, key, meta = DATA / "cert.pem", DATA / "key.pem", DATA / "cert-ips.json"
    want = sorted(set(ips) | {"127.0.0.1"})
    if crt.exists() and key.exists() and meta.exists():
        try:
            if json.loads(meta.read_text()) == want:
                return crt, key
        except ValueError:
            pass

    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SCraMic Share")])
    now = datetime.datetime.now(datetime.timezone.utc)
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in want]
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(k.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(k, hashes.SHA256())
    )
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption()))
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    meta.write_text(json.dumps(want))
    return crt, key


def qr_svg(text):
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, border=1, box_size=10)
    return img.to_string(encoding="unicode")


# ---------------------------------------------------------------- relay
class Hub:
    """Holds the single PC page socket and the single phone socket and relays between them."""

    def __init__(self):
        self.pc = None
        self.phone = None
        self.phone_info = {}
        self.on_win = None      # set by the app: minimize / restore its window
        self.on_view = None     # set by the app: show the turned phone screen
        self.wired = None       # Wired manager (USB phones)
        self.media_pc = None    # PC page's media socket (wired camera/mic stream)
        self.rx = None          # screen share receivers
        self.dev = None         # ScramicShare Cam / Mic install actions
        self.vcam = None        # frames -> ScramicShare Cam
        self.update = None      # the Update button in Settings

    async def send(self, ws, msg):
        if ws is not None and not ws.closed:
            try:
                await ws.send_str(json.dumps(msg))
            except ConnectionError:
                pass

    async def status(self):
        await self.send(self.pc, {"t": "peer", "connected": self.phone is not None, "info": self.phone_info})
        await self.send(self.phone, {"t": "peer", "connected": self.pc is not None})


def videos_folder():
    """Where recordings go: "SCraMic Share" in the user's Videos folder, wherever Windows keeps that."""
    base = Path.home() / "Videos"
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            base = Path(os.path.expandvars(winreg.QueryValueEx(k, "My Video")[0]))
    except OSError:
        pass
    return base / "SCraMic Share"


def own_address(request):
    """The address the PC page is loaded from: this port, on 127.0.0.1."""
    return f"127.0.0.1:{request.transport.get_extra_info('sockname')[1]}"


def build_app(hub, role_default, info, live=None):
    def from_pc_page(request):
        """Being on this PC isn't enough: websites open in a browser here connect from this PC too.
        Browsers always say which site a socket comes from, and websites can't change that."""
        return (role_default == "pc" and request.remote in ("127.0.0.1", "::1")
                and request.headers.get("Origin") == f"http://{own_address(request)}")

    async def ws_handler(request):
        role = request.query.get("role", role_default)
        if role == "pc" and not from_pc_page(request):
            raise web.HTTPForbidden()
        if role == "phone" and not token_ok(request):
            raise web.HTTPForbidden(text="Scan the QR code in SCraMic Share again.")
        ws = web.WebSocketResponse(heartbeat=10, max_msg_size=8 * 1024 * 1024)
        await ws.prepare(request)

        if role == "pc":
            hub.pc = ws           # newest PC page wins; an older one just goes quiet
        else:
            old, hub.phone = hub.phone, ws
            hub.phone_info = {"ua": request.headers.get("User-Agent", ""), "ip": request.remote}
            if old is not None:   # a newer phone tab takes over
                await hub.send(old, {"t": "replaced"})
                if not old.closed:
                    await old.close()
        await hub.status()

        try:
            async for m in ws:
                if m.type != WSMsgType.TEXT:
                    continue
                try:
                    msg = json.loads(m.data)
                except ValueError:
                    continue
                if role == "pc" and msg.get("t") == "open-link":
                    if msg.get("url") in ALLOWED_LINKS:
                        webbrowser.open(msg["url"])
                    continue
                if role == "pc" and msg.get("t") == "update-install":
                    if hub.update:
                        hub.update()
                    continue
                if role == "pc" and str(msg.get("t", "")).startswith("wired"):
                    if hub.wired:
                        hub.wired.handle(msg)
                    continue
                if role == "pc" and msg.get("t") == "rx":
                    if hub.rx:
                        if msg.get("kind") == "scrcpy-wifi":   # this phone's address on the network
                            msg["serial"] = hub.phone_info.get("ip")
                        hub.rx.handle(msg)
                    continue
                if role == "pc" and msg.get("t") == "dev":
                    if hub.dev:
                        hub.dev(msg)
                    continue
                if role == "pc" and msg.get("t") == "vcam-mode":
                    if hub.vcam:
                        hub.vcam.configure(msg.get("w"), msg.get("h"), msg.get("fps"))
                    continue
                if role == "pc" and msg.get("t") == "win":
                    if hub.on_win:
                        hub.on_win(msg.get("a"))
                    continue
                target = hub.phone if role == "pc" else hub.pc
                await hub.send(target, msg)
        finally:
            if role == "pc" and hub.pc is ws:
                hub.pc = None
            elif role == "phone" and hub.phone is ws:
                hub.phone = None
                hub.phone_info = {}
            await hub.status()
        return ws

    async def page(request):
        return web.FileResponse(WEB / role_default / "index.html",
                                headers={"Cache-Control": "no-store"})

    async def api_info(request):
        return web.json_response(info)

    async def api_qr(request):
        text = request.query.get("text", "")[:300] or info["url"]
        return web.Response(text=qr_svg(text), content_type="image/svg+xml")

    async def api_wired(request):
        w = hub.wired
        return web.json_response({"android": w.phone_url() if w else "",
                                  "iphone": [f"https://{ip}:{PHONE_PORT}/?k={TOKEN}&wired=1"
                                             for ip in (w.iphone_ips() if w else [])]})

    # Wired camera / mic: the phone streams JPEG frames + PCM audio over this
    # socket (plain TCP works through a USB cable); the server hands each
    # message to the PC page untouched.
    async def media_handler(request):
        role = request.query.get("role", role_default)
        if role == "pc":
            if not from_pc_page(request):
                raise web.HTTPForbidden()
        elif not token_ok(request):
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(max_msg_size=16 * 1024 * 1024, compress=False)
        await ws.prepare(request)
        if role == "pc":
            hub.media_pc = ws
        try:
            async for m in ws:
                if role == "phone" and m.type == WSMsgType.BINARY:
                    pc = hub.media_pc
                    if pc is not None and not pc.closed:
                        try:
                            await pc.send_bytes(m.data)
                        except ConnectionError:
                            pass
        finally:
            if role == "pc" and hub.media_pc is ws:
                hub.media_pc = None
        return ws

    @web.middleware
    async def no_cache(request, handler):
        resp = await handler(request)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @web.middleware
    async def pc_address_only(request, handler):
        """A website can point its own name at 127.0.0.1 and then read this site as if it were its own, key included.
        Its name still shows in the request, so anything but the real address is refused."""
        if role_default == "pc" and request.host != own_address(request):
            raise web.HTTPForbidden()
        return await handler(request)

    app = web.Application(middlewares=[pc_address_only, no_cache])
    app.router.add_get("/", page)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/media", media_handler)

    # PC page -> ScramicShare Cam: JPEG frames of whatever camera is live, while an app has the camera open
    async def vcam_handler(request):
        if not from_pc_page(request):
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(max_msg_size=16 * 1024 * 1024, compress=False)
        await ws.prepare(request)

        async def tell_page():
            told = None
            while not ws.closed:
                on = bool(hub.vcam and hub.vcam.active)
                if on != told:
                    await ws.send_str("on" if on else "off")
                    told = on
                await asyncio.sleep(0.25)

        telling = asyncio.ensure_future(tell_page())
        try:
            async for m in ws:
                if m.type == WSMsgType.BINARY and hub.vcam:
                    hub.vcam.push_jpeg(m.data)
        finally:
            telling.cancel()
        return ws
    app.router.add_get("/vcam", vcam_handler)

    # PC page -> a video file on this PC. The first message names the format, then pieces of the file follow.
    async def record_handler(request):
        if not from_pc_page(request):
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(max_msg_size=256 * 1024 * 1024, compress=False)
        await ws.prepare(request)
        loop = asyncio.get_running_loop()
        out = None
        try:
            async for m in ws:
                if m.type == WSMsgType.TEXT and out is None:
                    ext = "mp4" if m.data == "mp4" else "webm"
                    folder = videos_folder()
                    folder.mkdir(parents=True, exist_ok=True)
                    path = folder / f"SCraMic Share {datetime.datetime.now():%Y-%m-%d %H-%M-%S}.{ext}"
                    out = open(path, "wb")
                    await ws.send_str(str(path))
                elif m.type == WSMsgType.BINARY and out:
                    await loop.run_in_executor(None, out.write, m.data)
        except OSError as e:
            await ws.send_str("error:" + str(e))
        finally:
            if out:
                out.close()
        return ws
    app.router.add_get("/record", record_handler)
    async def api_update(request):
        result = await asyncio.get_running_loop().run_in_executor(None, updates.check)
        return web.json_response(result)

    async def api_version(request):
        return web.json_response({"version": updates.VERSION})

    if role_default == "pc":   # these hold the pairing key: never on the phone site, which anyone on the WiFi can reach
        app.router.add_get("/api/info", api_info)
        app.router.add_get("/api/qr.svg", api_qr)
        app.router.add_get("/api/wired", api_wired)
        app.router.add_get("/api/update", api_update)
        app.router.add_get("/api/version", api_version)
    app.router.add_static("/static/", WEB / role_default)
    app.router.add_static("/assets/", WEB / "assets")
    if live is not None:
        live.routes(app)
    return app


class Server:
    def __init__(self, live=None):
        self.live = live
        self.hub = Hub()
        self.loop = asyncio.new_event_loop()
        self.ips = all_ips()
        ip = self.ips[0] if self.ips else "127.0.0.1"
        self.info = {
            "url": f"https://{ip}:{PHONE_PORT}/?k={TOKEN}",
            "ip": ip,
            "others": [f"https://{i}:{PHONE_PORT}/?k={TOKEN}" for i in self.ips[1:]],
        }
        self.ready = threading.Event()
        self.error = None

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="server").start()
        self.ready.wait(15)
        if self.error:
            raise self.error

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._serve())
        except Exception as e:   # surface startup errors to the main thread
            self.error = e
            self.ready.set()
            return
        self.ready.set()
        self.loop.run_forever()

    async def _serve(self):
        crt, key = ensure_cert(self.ips)
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(crt, key)

        pc_runner = web.AppRunner(build_app(self.hub, "pc", self.info), access_log=None)
        phone_runner = web.AppRunner(build_app(self.hub, "phone", self.info, self.live), access_log=None)
        await pc_runner.setup()
        await phone_runner.setup()
        await web.TCPSite(pc_runner, "127.0.0.1", PC_PORT).start()
        await web.TCPSite(phone_runner, "0.0.0.0", PHONE_PORT, ssl_context=ctx).start()
        # Plain-HTTP phone site on this PC only. Phones reach it through USB port
        # forwarding (wired mode), where "localhost" already counts as secure.
        await web.TCPSite(phone_runner, "127.0.0.1", PHONE_LOCAL_PORT).start()

        from wired import Wired
        def notify(msg):   # called from the wired thread
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.hub.send(self.hub.pc, msg)))
        self.hub.wired = Wired(DATA, PHONE_LOCAL_PORT, TOKEN, notify, all_ips)

        from tools import Tools
        from receivers import Receivers
        import vdevices
        tools = Tools(DATA)
        self.hub.rx = Receivers(tools, self.hub.wired, notify)
        self.hub.rx.on_view = lambda value: self.hub.on_view and self.hub.on_view(value)
        tools.on_change = self.hub.rx.tool_changed
        self.hub.dev = vdevices.setup(tools, notify)
        self.hub.vcam = vdevices.VirtualCam()

        updates.clean()   # the installer from the last update, if there was one
        def close_app():
            if self.hub.on_win:
                self.hub.on_win("quit")
        self.hub.update = lambda: threading.Thread(target=updates.install_update, args=(notify, close_app),
                                                   daemon=True, name="update").start()

    @property
    def pc_url(self):
        return f"http://127.0.0.1:{PC_PORT}/"
