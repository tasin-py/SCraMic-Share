'use strict';
hydrateIcons();

const $ = id => document.getElementById(id);
const screens = ['home', 'wireless', 'wired', 'live'];
let current = 'home';
function show(name) {
  current = name;
  screens.forEach(s => $(s).classList.toggle('hidden', s !== name));
  if (name === 'wireless') loadPairing();   // the QR code is always ready on this screen
  if (name === 'wired') send({ t: 'wired-watch', on: true });
}

let toastT;
function toast(text) {
  const t = $('toast');
  t.textContent = text; t.classList.add('show');
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('show'), 2400);
}

// ---------------------------------------------------------------- navigation
$('goWireless').onclick = () => show('wireless');
$('goWired').onclick = () => show('wired');
document.querySelectorAll('.back').forEach(b => b.onclick = () => show('home'));

// settings + donation
function openModal(id) { $(id).classList.remove('hidden'); }
function closeModal(el) { el.closest('.modal').classList.add('hidden'); }
$('openSettings').onclick = () => { openModal('settings'); send({ t: 'dev', a: 'state' }); };
document.querySelectorAll('.openSettings2').forEach(b => b.onclick = () => { openModal('settings'); send({ t: 'dev', a: 'state' }); });
$('openCoffee').onclick = () => openModal('coffee');
$('copyBinance').onclick = async () => {
  const id = $('binanceId').textContent;
  try {
    await navigator.clipboard.writeText(id);
  } catch (e) {                       // the app's window may not allow the newer way
    const box = document.createElement('textarea');
    box.value = id;
    document.body.appendChild(box);
    box.select();
    document.execCommand('copy');
    box.remove();
  }
  $('copyBinance').textContent = 'Copied';
  setTimeout(() => { $('copyBinance').textContent = 'Copy'; }, 1500);
};
document.querySelectorAll('[data-close]').forEach(b => b.onclick = () => closeModal(b));
document.querySelectorAll('.modal').forEach(m => m.onclick = e => { if (e.target === m) m.classList.add('hidden'); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.querySelectorAll('.modal:not(.hidden)').forEach(m => m.classList.add('hidden'));
});
document.querySelectorAll('[data-link]').forEach(b => b.onclick = () => send({ t: 'open-link', url: b.dataset.link }));

// ---------------------------------------------------------------- check for updates
fetch('/api/version').then(r => r.json()).then(v => { $('appVer').textContent = `Version ${v.version}`; }).catch(() => {});
const UPDATE_TEXT = {
  current: "You're on the latest version.",
  none: 'No updates have been published yet.',
  error: "Couldn't check. Check your internet connection and try again.",
};
async function askForUpdate() {
  try { return await (await fetch('/api/update')).json(); } catch (e) { return { state: 'error' }; }
}
function showUpdate(r) {
  const newer = r.state === 'update';
  $('updateMsg').textContent = newer ? `Version ${r.version} is available.` : (UPDATE_TEXT[r.state] || UPDATE_TEXT.error);
  $('updateMsg').classList.remove('hidden');
  $('getUpdate').textContent = `Download version ${r.version}`;
  $('getUpdate').classList.toggle('hidden', !newer);
  document.querySelectorAll('#openSettings, .openSettings2').forEach(b => b.classList.toggle('has-update', newer));
}
$('checkUpdate').onclick = async () => {
  const btn = $('checkUpdate');
  btn.disabled = true;
  btn.textContent = 'Checking…';
  $('getUpdate').classList.add('hidden');
  showUpdate(await askForUpdate());
  btn.disabled = false;
  btn.textContent = 'Check for updates';
  $('appVer').scrollIntoView({ block: 'nearest' });   // Settings scrolls: the answer must not land out of sight
};
// Every time the app starts. It only speaks up for a real update: no internet is nobody's problem here.
askForUpdate().then(r => {
  if (r.state !== 'update') return;
  showUpdate(r);
  toast(`Version ${r.version} is available. Open Settings to download it.`);
});

// ---------------------------------------------------------------- pairing info
let pairingLoaded = false;
async function loadPairing() {
  if (pairingLoaded) return;
  try {
    const info = await (await fetch('/api/info')).json();
    $('qr').innerHTML = await (await fetch('/api/qr.svg')).text();
    $('url').textContent = info.url.replace(/\/$/, '');
    if (info.others.length) {
      $('others').innerHTML = info.others.map(u => u.replace(/\/$/, '')).join('<br>');
      $('othersWrap').classList.remove('hidden');
    }
    pairingLoaded = true;
  } catch (e) { setTimeout(loadPairing, 1000); }
}

// ---------------------------------------------------------------- socket
let ws, phoneConnected = false;
function send(msg) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg)); }

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws?role=pc`);
  ws.onmessage = e => handle(JSON.parse(e.data));
  ws.onclose = () => setTimeout(connect, 800);
}
connect();

function phoneName(ua) {
  if (!ua) return 'Phone';
  if (/iPhone/.test(ua)) return 'iPhone';
  if (/iPad|Macintosh.*Mobile/.test(ua)) return 'iPad';
  const m = ua.match(/Android [\d.]+; ([^;)]+)/);
  if (m && m[1] && m[1] !== 'K') return m[1].trim();
  if (/Android/.test(ua)) return 'Android phone';
  return 'Phone';
}

function setPhone(connected, info) {
  phoneConnected = connected;
  const st = $('pairStatus');
  st.innerHTML = connected
    ? '<span class="dot live"></span><span>Phone connected</span>'
    : '<span class="dot wait"></span><span>Waiting for your phone…</span>';
  $('steps').classList.toggle('hidden', connected);
  $('connected').classList.toggle('hidden', !connected);
  $('wConnected').classList.toggle('hidden', !connected);
  if (connected) $('phoneName').textContent = $('wPhoneName').textContent = phoneName(info && info.ua);
  // Screen share doesn't use the phone's page: mirroring carries on while the page is in the background.
  if (feature === 'screen') {
    if (connected) {
      send({ t: 'screen-resume', wired: wiredFeature, audio: screenAudio });
      if (rx) renderRx(rx);
    }
    return;
  }
  if (!connected && current === 'live') { endFeature(); show(backTo); toast('Phone disconnected'); }
}

function handle(m) {
  switch (m.t) {
    case 'peer': setPhone(m.connected, m.info); break;
    case 'feature': startFeature(m.f, m.wired, m); break;
    case 'wired': renderWired(m); break;
    case 'rx-state': renderRx(m); break;
    case 'devices': renderDevices(m); break;
    case 'screen-audio':
      if (feature === 'screen') { screenAudio = !!m.on; send({ t: 'rx', a: 'start', kind: RX_KIND(), audio: screenAudio }); }
      break;
    case 'rx-rotate': if (feature === 'screen') send({ t: 'rx', a: 'rotate', by: m.by }); break;
    case 'rx-auto': if (feature === 'screen') rotateAuto(!!m.on); break;
    case 'rx-control': if (feature === 'screen') rxControl(!!m.on); break;
    case 'offer': onOffer(m); break;
    case 'ice': onIce(m); break;
    case 'rot': rot = m.deg || 0; layout(); break;
    case 'micstate': setChip('chipMic', m.on && !m.muted); setChip('chipMuted', m.on && m.muted); if (bubble) bubble.setMuted(m.muted); break;
    case 'dark': setChip('chipDark', m.on); break;
    case 'videostate': setChip('chipVideoOff', m.off); break;
    case 'stream-state': renderStream(m); break;
    case 'control-state':
      if (feature === 'control') $('remoteText').textContent = m.on ? REMOTE.control[2] : "Your phone can only watch this PC. It can't control it.";
      break;
  }
}

$('kickPhone').onclick = $('kickPhone2').onclick = $('kickPhone3').onclick = () => openModal('discAsk');
$('discYes').onclick = () => {
  closeModal($('discYes'));
  send({ t: 'disconnect' });
  endFeature();
  show(backTo);
  toast('Phone disconnected');
};
$('stopFeature').onclick = $('liveBack').onclick = () => {
  send({ t: 'stop-feature' });
  endFeature();
  show(backTo);
};

// ---------------------------------------------------------------- features
let feature = null, pc = null, pendingIce = [], stream = null, rot = 0;
let audioCtx = null, bubble = null;
const video = $('video');
const TITLES = {
  camera: ['Camera', 'Stop camera'],
  streamer: ['Streamer mode', 'Stop stream'],
  mic: ['Microphone', 'Stop microphone'],
  teacher: ['Teacher mode', 'Stop Teacher mode'],
  screen: ['Screen share', 'Stop screen share'],
  control: ['PC Control', 'Stop PC Control'],
};
const REMOTE = {
  teacher: ['teacher', 'Teacher mode is on', 'Draw on your phone. The ink appears on top of your screen.'],
  control: ['pcControl', 'PC Control is on', 'Your phone is controlling this PC.'],
  screen: ['screen', 'Screen share', ''],
};
$('minimize').onclick = () => send({ t: 'win', a: 'min' });

function setChip(id, on) { $(id).classList.toggle('hidden', !on); }

const isCam = f => f === 'camera' || f === 'streamer';
let backTo = 'wireless', wiredFeature = false;
function startFeature(f, wired, msg) {
  if (!f) { if (feature) { endFeature(); show(backTo); } return; }
  if (!TITLES[f]) return;   // later phases
  if (current === 'wired' || current === 'wireless') backTo = current;
  endFeature();
  feature = f;
  wiredFeature = !!wired;
  rot = 0;
  $('liveTitle').textContent = TITLES[f][0];
  $('stopLabel').textContent = TITLES[f][1];
  ['chipMic', 'chipMuted', 'chipDark', 'chipVideoOff'].forEach(c => setChip(c, false));
  video.classList.toggle('hidden', !isCam(f) || wiredFeature);
  $('wcv').classList.toggle('hidden', !isCam(f) || !wiredFeature);
  $('live').classList.toggle('mic-mode', f === 'mic');
  $('liveBack').classList.toggle('hidden', isCam(f));   // the video's own screen: Stop and Disconnect are in the bar
  $('recBtn').classList.toggle('hidden', !isCam(f));
  $('popBtn').classList.toggle('hidden', !isCam(f));
  $('obsBtn').classList.toggle('hidden', !isCam(f));
  $('quality').classList.toggle('hidden', f !== 'streamer');
  $('qNow').textContent = '';
  $('bubble').classList.toggle('hidden', f !== 'mic');
  $('remote').classList.toggle('hidden', !REMOTE[f]);
  $('rxRotate').classList.add('hidden');
  $('rxControlRow').classList.add('hidden');
  $('stageMsg').textContent = 'Connecting…';
  $('stageMsg').classList.toggle('hidden', !!REMOTE[f]);
  if (REMOTE[f]) {
    const [ic, title, text] = REMOTE[f];
    $('remoteIc').innerHTML = icon(ic);
    $('remoteTitle').textContent = title;
    $('remoteText').textContent = text;
    $('remoteBody').innerHTML = '';
    $('minimize').classList.remove('hidden');
    if (f === 'screen') startScreenShare(msg && msg.os, msg && msg.audio);
    else send({ t: 'win', a: 'min' });   // get out of the way so the phone sees the desktop
  }
  if (f === 'mic') {
    bubble = makeBubble($('bubble'), null);
    setChip('chipMic', true);
  }
  renderMicRoute();
  show('live');
}

function endFeature() {
  recStop();
  popClose();
  if (feature === 'screen') send({ t: 'rx', a: 'stop' });
  else if (REMOTE[feature]) send({ t: 'win', a: 'restore' });
  feature = null;
  if (pc) { pc.close(); pc = null; }
  pendingIce = [];
  stream = null;
  setVcamMode(1280, 720, 30);
  video.srcObject = null;
  if (bubble) { bubble.stop(); bubble = null; }
  if (audioCtx) { audioCtx.close(); audioCtx = null; }
  stopWiredAudio();
  wiredFeature = false;
  renderMicRoute();
}

async function onOffer(m) {
  if (pc) { pc.close(); pc = null; }
  pendingIce = [];
  pc = new RTCPeerConnection({ iceServers: [] });
  pc.onicecandidate = e => { if (e.candidate) send({ t: 'ice', c: e.candidate }); };
  pc.ontrack = e => {
    stream = e.streams[0] || new MediaStream([e.track]);
    if (video.srcObject !== stream) { video.muted = true; video.srcObject = stream; }   // routeAudio unmutes it
    video.play().catch(() => {});
    popFeed();
    if (e.track.kind === 'audio' && feature === 'mic') attachAnalyser(stream);
    if (e.track.kind === 'video' || feature === 'mic') $('stageMsg').classList.add('hidden');
  };
  pc.onconnectionstatechange = () => {
    if (!pc) return;
    if (pc.connectionState === 'failed') {
      $('stageMsg').textContent = "Couldn't connect to the phone. Check that both are on the same WiFi.";
      $('stageMsg').classList.remove('hidden');
    }
  };
  await pc.setRemoteDescription({ type: 'offer', sdp: m.sdp });
  for (const c of pendingIce) await pc.addIceCandidate(c).catch(() => {});
  pendingIce = [];
  const answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);
  send({ t: 'answer', sdp: pc.localDescription.sdp });
}

function onIce(m) {
  if (!m.c) return;
  if (pc && pc.remoteDescription) pc.addIceCandidate(m.c).catch(() => {});
  else pendingIce.push(m.c);
}

function attachAnalyser(s) {
  if (audioCtx) audioCtx.close();
  audioCtx = new AudioContext();
  const an = audioCtx.createAnalyser();
  an.fftSize = 1024;
  audioCtx.createMediaStreamSource(s).connect(an);
  audioCtx.resume();
  if (bubble) bubble.setAnalyser(an);
}

// Fit the video in the stage, honoring the 0/90/180/270° rotation chosen on the phone.
function layout() {
  const el = wiredFeature ? $('wcv') : video;
  const vw = wiredFeature ? el.width : video.videoWidth, vh = wiredFeature ? el.height : video.videoHeight;
  if (!vw || !vh) return;
  const st = $('stage');
  const W = st.clientWidth - 24, H = st.clientHeight - 24;
  const side = rot % 180 !== 0;
  const s = Math.min(W / (side ? vh : vw), H / (side ? vw : vh));
  el.style.width = vw * s + 'px';
  el.style.height = vh * s + 'px';
  el.style.transform = `translate(-50%, -50%) rotate(${rot}deg)`;
  popLayout();
}
video.addEventListener('resize', layout);          // phone turned sideways -> new frame size
video.addEventListener('loadedmetadata', layout);
window.addEventListener('resize', layout);

// ---------------------------------------------------------------- wired: status of phones on the USB cable
let wiredUrls = { android: '', iphone: [] };
const qrImg = url => `<div class="wqr"><img src="/api/qr.svg?text=${encodeURIComponent(url)}" alt=""></div>`;
const status = (el, cls, text) => { $(el).innerHTML = `<span class="dot ${cls}"></span><span>${text}</span>`; };
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

async function renderWired(m) {
  try { wiredUrls = await (await fetch('/api/wired')).json(); } catch (e) {}
  // ---- Android
  const a = $('aBody');
  const dev = (m.android || []).find(d => d.state === 'device') || (m.android || [])[0];
  if (m.adb === 'missing') {
    status('aStatus', '', 'Needs the Android USB tools');
    a.innerHTML = `<p class="wtext">SCraMic Share uses Google's free Android USB tools (adb, about 7 MB) to talk to your phone over the cable. They're saved in SCraMic Share's own folder.</p>
      <button class="btn primary" id="adbGet">Download Android tools</button>`;
    $('adbGet').onclick = () => { send({ t: 'wired-download' }); status('aStatus', 'wait', 'Starting download…'); };
  } else if (m.adb === 'downloading') {
    const d = m.download || {}, pct = d.total ? Math.round(d.done / d.total * 100) : 0;
    status('aStatus', 'wait', `Downloading Android tools… ${pct}%`);
    a.innerHTML = `<div class="bar"><i style="width:${pct}%"></i></div>`;
  } else if (m.adb === 'error') {
    status('aStatus', '', "Couldn't download the Android tools");
    a.innerHTML = `<p class="wtext">${esc((m.download && m.download.error) || '')}<br>Check the internet connection and try again.</p>
      <button class="btn primary" id="adbGet">Try again</button>`;
    $('adbGet').onclick = () => send({ t: 'wired-download' });
  } else if (!dev) {
    status('aStatus', 'wait', 'Waiting for an Android phone on the cable…');
    a.innerHTML = `<ol class="steps small">
      <li>On the phone: <b>Settings → About phone</b>, tap <b>Build number</b> 7 times.</li>
      <li><b>Settings → Developer options</b>: turn on <b>USB debugging</b>.</li>
      <li>Plug the phone into this PC with a USB cable.</li>
      <li>Tap <b>Allow</b> on the phone when it asks.</li></ol>`;
  } else if (dev.state === 'unauthorized') {
    status('aStatus', 'wait', 'Tap Allow on your phone');
    a.innerHTML = `<p class="wtext">Your phone is asking <b>"Allow USB debugging?"</b>. Tick <b>Always allow from this computer</b>, then tap <b>Allow</b>.</p>`;
  } else if (dev.state !== 'device') {
    status('aStatus', '', 'Phone not responding');
    a.innerHTML = `<p class="wtext">Unplug the cable and plug it back in. If that doesn't help, turn USB debugging off and on again.</p>`;
  } else {
    status('aStatus', 'live', `${esc(dev.model || 'Android phone')} connected by cable`);
    a.innerHTML = `<p class="wtext">SCraMic Share opened on your phone. If it didn't, click <b>Open on phone</b> or scan this with that phone.</p>
      <div class="wrow">${qrImg(wiredUrls.android)}<button class="btn" id="adbOpen">Open on phone</button></div>`;
    $('adbOpen').onclick = () => send({ t: 'wired-open', serial: dev.serial });
  }
  // ---- iPhone
  const i = $('iBody');
  if ((m.iphone || []).length && wiredUrls.iphone.length) {
    status('iStatus', 'live', 'iPhone connected through Personal Hotspot');
    i.innerHTML = `<p class="wtext">Scan this with the iPhone's camera. If Safari says <b>"Not private"</b>, tap <b>Show Details → visit this website</b>.</p>
      <div class="wrow">${qrImg(wiredUrls.iphone[0])}</div>`;
  } else if (m.iphoneUsb) {
    status('iStatus', 'wait', "iPhone found, but its hotspot isn’t shared over the cable");
    i.innerHTML = `<ol class="steps small">
      <li>Unlock the iPhone. Open <b>Settings → Personal Hotspot</b> and turn on <b>Allow Others to Join</b>.</li>
      <li>Keep that screen open, then <b>unplug the cable and plug it back in</b>. The iPhone only offers the hotspot to a cable plugged in after it's turned on.</li>
      <li>Tap <b>Trust</b> if the iPhone asks. When it works, the iPhone shows a <b>connection</b> bubble at the top and a QR code appears here.</li></ol>
      <p class="wnote">Personal Hotspot only works with <b>Cellular Data turned on</b>, even though SCraMic Share uses no data over the cable. If it's missing, greyed out, or your carrier blocks it, use <b>Wireless</b> mode instead.</p>
      <p class="wnote"><b>Still nothing?</b> Connect this PC's WiFi to the iPhone's hotspot instead (it shows up in the Windows WiFi list). That links them directly with no router, and the QR code appears here. A real cable link needs Apple's desktop <b>iTunes</b> driver; the Microsoft Store "Apple Devices" app driver doesn't share the hotspot over USB.</p>`;
  } else {
    status('iStatus', 'wait', 'Waiting for an iPhone on the cable…');
    i.innerHTML = `<ol class="steps small">
      <li>On the iPhone: <b>Settings → Personal Hotspot</b>, turn on <b>Allow Others to Join</b>.</li>
      <li>Plug the iPhone into this PC. Tap <b>Trust</b> if it asks.</li>
      <li>A QR code appears here. Scan it with the iPhone.</li></ol>
      <p class="wnote">Needs Apple's <b>Apple Devices</b> app (or iTunes) on this PC for the cable connection. While the hotspot is on, this PC may use the iPhone's mobile data for internet.</p>`;
  }
}

// ---------------------------------------------------------------- wired: camera frames + audio from the cable
let mws = null;
function mconnect() {
  mws = new WebSocket(`ws://${location.host}/media?role=pc`);
  mws.binaryType = 'arraybuffer';
  mws.onmessage = e => {
    const type = new Uint8Array(e.data, 0, 1)[0];
    if (type === 1 && wiredFeature && isCam(feature)) { nextFrame = e.data; if (!decoding) drawFrame(); }
    else if (type === 2 && wiredFeature) playPcm(e.data);
  };
  mws.onclose = () => setTimeout(mconnect, 1000);
}
mconnect();

let decoding = false, nextFrame = null, wiredFrames = 0;
async function drawFrame() {     // always shows the newest frame; older ones are skipped
  const d = nextFrame; nextFrame = null;
  if (!d) return;
  decoding = true;
  try {
    const bmp = await createImageBitmap(new Blob([new Uint8Array(d, 1)], { type: 'image/jpeg' }));
    const c = $('wcv');
    if (c.width !== bmp.width || c.height !== bmp.height) { c.width = bmp.width; c.height = bmp.height; layout(); }
    c.getContext('2d').drawImage(bmp, 0, 0);
    vcamWired(bmp);
    wiredFrames++;
    $('stageMsg').classList.add('hidden');
  } catch (e) {}
  decoding = false;
  if (nextFrame) drawFrame();
}

// audio: a small jitter buffer (40 ms to start, never more than 200 ms behind)
const PLAYER = `
class P extends AudioWorkletProcessor {
  constructor() {
    super(); this.q = []; this.cur = null; this.i = 0; this.n = 0; this.go = false;
    this.port.onmessage = e => {
      this.q.push(e.data); this.n += e.data.length;
      while (this.n > sampleRate * 0.2 && this.q.length > 1) this.n -= this.q.shift().length;
    };
  }
  process(_, outs) {
    const out = outs[0][0];
    if (!this.go) { if (this.n < sampleRate * 0.04) { out.fill(0); return true; } this.go = true; }
    for (let k = 0; k < out.length; k++) {
      if (!this.cur || this.i >= this.cur.length) {
        this.cur = this.q.shift(); this.i = 0;
        if (!this.cur) { out.fill(0, k); this.go = false; return true; }
        this.n -= this.cur.length;
      }
      out[k] = this.cur[this.i++];
    }
    return true;
  }
}
registerProcessor('scramic-play', P);`;
let wctx = null, wnode = null, wgain = null, wrate = 0;
function ensureAudio(sr) {
  stopWiredAudio();
  wrate = sr;
  const ctx = wctx = new AudioContext({ sampleRate: sr });
  (async () => {
    await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([PLAYER], { type: 'application/javascript' })));
    if (ctx !== wctx) return;
    wnode = new AudioWorkletNode(ctx, 'scramic-play', { outputChannelCount: [1] });
    const an = ctx.createAnalyser(); an.fftSize = 1024;
    wgain = ctx.createGain(); wgain.gain.value = 0;   // silent until routeAudio picks where it goes
    wnode.connect(an); an.connect(wgain); wgain.connect(ctx.destination);
    ctx.resume();
    if (bubble) bubble.setAnalyser(an);
    $('stageMsg').classList.add('hidden');
    routeAudio();
  })().catch(() => {});
}
function playPcm(buf) {
  const sr = new DataView(buf).getUint32(1, true);
  if (!wctx || wrate !== sr) ensureAudio(sr);
  if (!wnode) return;
  const i16 = new Int16Array(buf.slice(5));
  const f = new Float32Array(i16.length);
  for (let k = 0; k < i16.length; k++) f[k] = i16[k] / 32768;
  monitorPcm(f, sr);
  wnode.port.postMessage(f, [f.buffer]);
}
function stopWiredAudio() {
  if (wctx) wctx.close().catch(() => {});
  wctx = wnode = wgain = null; wrate = 0;
}

// ================================================================ phase 4
// ---------------------------------------------------------------- screen share: PC is the receiver
let rx = null, screenOS = 'android', screenAudio = true;
let androidWifi = 'scrcpy-wifi';   // or 'miracast', when the user picks Wireless Display instead
const RX_KIND = () => screenOS === 'ios' ? 'airplay' : (wiredFeature ? 'scrcpy' : androidWifi);
const usesScrcpy = k => k === 'scrcpy' || k === 'scrcpy-wifi';
function useWirelessDisplay() {
  androidWifi = 'miracast';
  send({ t: 'rx', a: 'start', kind: 'miracast', audio: screenAudio });
}

function startScreenShare(os, audio) {
  screenOS = os === 'ios' ? 'ios' : 'android';
  screenAudio = audio !== false;
  androidWifi = 'scrcpy-wifi';
  $('remoteIc').innerHTML = icon('screen');
  $('remoteTitle').textContent = 'Screen share';
  $('remoteText').textContent = 'Getting the receiver ready…';
  $('remoteBody').innerHTML = '';
  $('minimize').classList.add('hidden');
  send({ t: 'rx', a: 'auto-rotate', on: savedRotateAuto() });
  send({ t: 'rx', a: 'control', on: savedRxControl() });
  send({ t: 'rx', a: 'start', kind: RX_KIND(), audio: screenAudio });
}

function tellPhone(text, ready) { send({ t: 'screen-state', text, ready: !!ready, pcName: rx && rx.pcName, rotate: rx && rx.rotate, control: rx && rx.control, kind: RX_KIND(), pairing: !!rx && rx.error === 'needs-pairing' }); }

// Android over USB: with this off, the PC only shows the phone's screen.
const rxControl = on => {
  try { localStorage.rxControl = on ? '1' : '0'; } catch (e) {}
  send({ t: 'rx', a: 'control', on });
};
const savedRxControl = () => { try { return localStorage.rxControl !== '0'; } catch (e) { return true; } };
$('rxControl').onchange = () => rxControl($('rxControl').checked);

// iPhone only: Android's receivers follow the phone's rotation by themselves.
const rotateAuto = on => {
  try { localStorage.rxAuto = on ? '1' : '0'; } catch (e) {}
  send({ t: 'rx', a: 'auto-rotate', on });
};
const savedRotateAuto = () => { try { return localStorage.rxAuto !== '0'; } catch (e) { return true; } };
$('rotAuto').onchange = () => rotateAuto($('rotAuto').checked);
$('rotLeft').onclick = () => send({ t: 'rx', a: 'rotate', by: -1 });
$('rotRight').onclick = () => send({ t: 'rx', a: 'rotate', by: 1 });

function renderRotate(m) {
  const r = m.rotate || {};
  $('rxRotate').classList.toggle('hidden', RX_KIND() !== 'airplay');
  $('rotAuto').checked = !!r.auto;
  $('rotNow').textContent = `${r.deg || 0}°`;
  $('rxControlRow').classList.toggle('hidden', !usesScrcpy(RX_KIND()));
  $('rxControl').checked = m.control !== false;
}

function renderRx(m) {
  rx = m;
  if (feature !== 'screen') return;
  renderRotate(m);
  const body = $('remoteBody'), tl = m.tools || {};
  const kind = RX_KIND();
  const tool = kind === 'airplay' ? 'uxplay' : 'scrcpy';
  const t = tl[tool] || {};
  const p = t.progress;
  if (m.error && m.error.startsWith('needs-tool')) {
    if (p && !p.error) {
      const pct = p.total ? Math.round(p.done / p.total * 100) : 0;
      $('remoteText').textContent = `Downloading ${t.label}… ${pct}%`;
      body.innerHTML = `<div class="bar wide"><i style="width:${pct}%"></i></div>`;
      tellPhone(`Your PC is getting ready (${pct}%)…`);
    } else {
      $('remoteText').textContent = kind === 'airplay'
        ? 'iPhone screen mirroring needs a free AirPlay receiver (UxPlay, open source).'
        : 'Android mirroring needs scrcpy (free, open source).';
      body.innerHTML = `${p && p.error ? `<p class="wtext">Download failed: ${esc(p.error)}</p>` : ''}
        <button class="btn primary" id="rxGet">Download (${t.size}, one time)</button>`;
      $('rxGet').onclick = () => send({ t: 'rx', a: 'fetch', name: tool });
      tellPhone('Your PC needs a one-time download. Click Download on the PC.');
    }
    return;
  }
  if (m.error === 'needs-wireless-display') {
    $('remoteText').textContent = "Android casting uses Windows' free Wireless Display feature. It isn't installed yet.";
    body.innerHTML = `<ol class="steps small left">
        <li>Click <b>Open Optional features</b>, then <b>View features</b> (or <b>Add a feature</b>).</li>
        <li>Search <b>Wireless Display</b>, tick it, and install it.</li>
        <li>Come back and click <b>Check again</b>.</li></ol>
      <div class="wrow"><button class="btn primary" id="rxInstall">Open Optional features</button><button class="btn" id="rxRetry">Check again</button></div>`;
    $('rxInstall').onclick = () => send({ t: 'rx', a: 'install-wireless-display' });
    $('rxRetry').onclick = () => send({ t: 'rx', a: 'start', kind, audio: screenAudio });
    tellPhone("Your PC needs Windows' Wireless Display feature. Follow the steps on the PC.");
    return;
  }
  const fallback = kind === 'scrcpy-wifi' ? '<button class="btn" id="rxFallback">Use Wireless Display instead</button>' : '';
  if (m.error === 'needs-pairing') {
    renderPairing(m, body, fallback);
    return;
  }
  if (m.error) {
    $('remoteText').textContent = m.error;
    body.innerHTML = `<div class="wrow"><button class="btn" id="rxRetry">Try again</button>${fallback}</div>`;
    $('rxRetry').onclick = () => send({ t: 'rx', a: 'start', kind, audio: screenAudio });
    if (fallback) $('rxFallback').onclick = useWirelessDisplay;
    tellPhone(m.error);
    return;
  }
  if (kind === 'airplay') {
    renderAirplay(m, body);
  } else if (usesScrcpy(kind)) {
    const link = kind === 'scrcpy' ? 'the cable' : 'WiFi';
    $('remoteText').textContent = !m.running ? `Connecting to your phone over ${link}…`
      : m.control === false ? "Your phone screen is open in its own window. This PC can only watch, it can't control the phone."
      : `Your phone screen is open in its own window, over ${link}.`;
    body.innerHTML = '';
    tellPhone(m.running ? `Your screen is showing on the PC over ${link}. Tap Allow if the phone asks.` : 'Connecting to your PC…', m.running);
  } else {
    $('remoteText').textContent = `Wireless Display is open. On the phone: Cast / Smart View / Screen mirroring → "${m.pcName}".`;
    body.innerHTML = `<p class="wnote">If the phone can't find this PC: open <b>Projecting to this PC</b> and set it to <b>Available everywhere</b>. Google Pixel phones can't cast to Windows; use Wired mode instead.</p>
      <button class="btn" id="rxProj">Open Projecting to this PC</button>`;
    $('rxProj').onclick = () => send({ t: 'rx', a: 'project-settings' });
    tellPhone(`Ready. Open Cast / Smart View / Screen mirroring and choose "${m.pcName}".`, true);
  }
}

// Android over WiFi, first time: Wireless debugging's pairing code. It's typed here because
// the code disappears from the phone as soon as it leaves that Settings screen.
let pairShown = null;
function renderPairing(m, body, fallback) {
  tellPhone('Pair this phone with your PC: follow the steps below, then type the numbers into the PC.');
  const note = m.pairNote || '';
  if ($('pairGo') && pairShown === note) {    // keep what has been typed
    $('pairGo').disabled = false;
    $('pairGo').textContent = 'Pair';
    return;
  }
  pairShown = note;
  $('remoteText').textContent = note === 'paired'
    ? "Paired. Now type the port from your phone's Wireless debugging screen."
    : 'Pair your phone once over WiFi. No cable needed.';
  const steps = note === 'paired'
    ? `<p class="wnote">On the phone's <b>Wireless debugging</b> screen, find <b>IP address &amp; Port</b> and type the number after the colon.</p>`
    : `<ol class="steps small left">
        <li>On the phone, open <b>Developer options → Wireless debugging</b> and turn it on.</li>
        <li>Tap <b>Pair device with pairing code</b>, and stay on that screen.</li>
        <li>Type the code and the port from the phone here. The port is the number after the colon.</li></ol>
      ${note === 'failed' ? `<p class="wnote pair-err">That didn't pair. Check the numbers on the phone and try again.</p>` : ''}
      <div class="pair-form">
        <label>Pairing code <input id="pairCode" inputmode="numeric" maxlength="6" autocomplete="off"></label>
        <label>Port <input id="pairPort" inputmode="numeric" maxlength="5" autocomplete="off"></label>
        <button class="btn primary" id="pairGo">Pair</button>
      </div>`;
  body.innerHTML = `${steps}
    <details class="pair-more" ${note === 'paired' ? 'open' : ''}>
      <summary>Already paired? Type the connection port</summary>
      <div class="pair-form">
        <label>Port <input id="wifiPort" inputmode="numeric" maxlength="5" autocomplete="off"></label>
        <button class="btn" id="wifiGo">Connect</button>
      </div>
    </details>
    <div class="wrow pair-alt">${fallback}</div>`;
  if ($('pairGo')) $('pairGo').onclick = () => {
    $('pairGo').disabled = true;
    $('pairGo').textContent = 'Pairing…';
    send({ t: 'rx', a: 'pair', port: $('pairPort').value.trim(), code: $('pairCode').value.trim() });
  };
  $('wifiGo').onclick = () => send({ t: 'rx', a: 'wifi-port', port: $('wifiPort').value.trim() });
  $('rxFallback').onclick = useWirelessDisplay;
}

function renderAirplay(m, body) {
  const a = m.airplay || {};
  if (!a.listening) {
    if (a.failed) {
      $('remoteText').textContent = "The AirPlay receiver didn't start on this PC, so your iPhone can't see it.";
      body.innerHTML = `<p class="wnote">${esc(a.failed)}</p>
        ${a.failed.includes('It said:') ? '' : '<p class="wnote">Check whether your antivirus (Avast, Windows Security) blocked or quarantined uxplay-windows.exe, then try again.</p>'}
        <button class="btn" id="rxRetry">Try again</button>`;
      $('rxRetry').onclick = () => send({ t: 'rx', a: 'start', kind: 'airplay', audio: screenAudio });
      tellPhone("The receiver didn't start on your PC. Check the PC.");
    } else {
      $('remoteText').textContent = 'Starting the AirPlay receiver…';
      body.innerHTML = '';
      tellPhone('Your PC is getting ready…');
    }
    return;
  }
  $('remoteText').textContent = `Ready. On the iPhone: Control Center → Screen Mirroring → "${m.airplayName}". The receiver waits in the background, and its window opens after you pick it on the iPhone.`;
  const notes = [`The iPhone must be on the same network as this PC (${esc(a.ip || 'unknown address')}).`];
  if (a.hotspot) notes.push("This PC is on the iPhone's own hotspot. If the name doesn't appear there, connect both to the same WiFi router.");
  if (!a.bonjour) notes.push('The Bonjour service is not running, and the iPhone needs it to find this PC. Start it from Windows Services.');
  body.innerHTML = notes.map(n => `<p class="wnote">${n}</p>`).join('') +
    (a.firewallOk ? '' : '<button class="btn" id="rxFirewall">Allow through Firewall</button>');
  if (!a.firewallOk) $('rxFirewall').onclick = () => {
    $('rxFirewall').textContent = 'Approve in Windows…';
    $('rxFirewall').disabled = true;
    send({ t: 'rx', a: 'allow-firewall' });
  };
  tellPhone(`Ready. Open Control Center → Screen Mirroring → "${m.airplayName}". Your iPhone must be on the same WiFi as the PC.`, true);
}

// ---------------------------------------------------------------- ScramicShare Cam / Mic
let devState = { cam: 'missing', mic: 'missing' };
let monitorOn = (() => { try { return localStorage.monitor === '1'; } catch (e) { return false; } })();

function renderDevices(m) {
  devState = m;
  const row = (id, ready, busyText) => {
    const b = $(id);
    b.disabled = ready === 'ready';
    b.textContent = ready === 'ready' ? 'Installed ✓' : (busyText || 'Install');
  };
  row('devCam', m.cam);
  row('devMic', m.mic, m.mic === 'needs-rename' ? 'Finish setup' : 'Install');
  if (m.mic !== 'missing') findFeed();
  renderMicRoute();
}

// On the Microphone screen: say where the voice is going, and offer the install if it has nowhere to go.
function renderMicRoute() {
  const el = $('micRoute');
  el.classList.toggle('hidden', feature !== 'mic');
  if (feature !== 'mic') return;
  if (feedSink && devState.mic === 'ready') {
    el.textContent = 'Your voice is going to "ScramicShare Mic". Pick it as the microphone in your other app.';
  } else if (devState.mic === 'ready') {
    el.textContent = 'Looking for ScramicShare Mic…';
  } else {
    el.innerHTML = `<span>${devState.mic === 'needs-rename'
        ? 'The virtual mic works, but Windows still shows its old VB-Cable name.'
        : "ScramicShare Mic isn't set up yet, so your voice isn't going to other apps."}</span>
      <button class="btn small" id="micInstall">${devState.mic === 'needs-rename' ? 'Finish setup' : 'Install'}</button>`;
    $('micInstall').onclick = () => {
      $('micInstall').textContent = 'Approve in Windows…';
      $('micInstall').disabled = true;
      send({ t: 'dev', a: 'install-mic' });
    };
  }
}
$('devCam').onclick = () => { $('devCam').textContent = 'Approve in Windows…'; $('devCam').disabled = true; send({ t: 'dev', a: 'install-cam' }); };
$('devMic').onclick = () => { $('devMic').textContent = 'Approve in Windows…'; $('devMic').disabled = true; send({ t: 'dev', a: 'install-mic' }); };
$('monitor').checked = monitorOn;
$('monitor').onchange = () => {
  monitorOn = $('monitor').checked;
  try { localStorage.monitor = monitorOn ? '1' : '0'; } catch (e) {}
  routeAudio();
};

// where phone sound goes: into ScramicShare Mic (if installed), plus this PC's speakers if wanted
let feedSink = null;
async function findFeed() {
  if (feedSink) return;
  try {   // device names are only visible after a mic permission; stop it right away
    const s = await navigator.mediaDevices.getUserMedia({ audio: true });
    s.getTracks().forEach(t => t.stop());
  } catch (e) {}
  try {
    const d = await navigator.mediaDevices.enumerateDevices();
    const o = d.find(x => x.kind === 'audiooutput' && /ScramicShare Mic Feed|CABLE Input/i.test(x.label));
    feedSink = o ? o.deviceId : null;
    routeAudio();
    renderMicRoute();
  } catch (e) {}
}
const monitorEl = new Audio();
// The phone's sound goes into ScramicShare Mic. It only reaches this PC's speakers when
// "Also play the phone's sound on this PC" is ticked, otherwise the speaker feeds back into the phone mic.
async function routeAudio() {
  const toFeed = !!feedSink;
  let videoInFeed = false;
  try { await video.setSinkId(toFeed ? feedSink : ''); videoInFeed = toFeed; } catch (e) {}
  video.muted = !(videoInFeed || monitorOn);
  monitorEl.srcObject = videoInFeed && monitorOn && !wiredFeature ? (video.srcObject || null) : null;
  if (monitorEl.srcObject) monitorEl.play().catch(() => {});
  if (wctx) {
    let wiredInFeed = false;
    if (wctx.setSinkId) { try { await wctx.setSinkId(toFeed ? feedSink : ''); wiredInFeed = toFeed; } catch (e) {} }
    if (wgain) wgain.gain.value = wiredInFeed || monitorOn ? 1 : 0;
  }
}
video.addEventListener('loadedmetadata', routeAudio);

// wired audio: a second player on the speakers when "hear on this PC" is on
let monCtx = null, monNode = null;
function monitorPcm(f32, sr) {
  if (!(feedSink && monitorOn && wiredFeature)) { if (monCtx) { monCtx.close().catch(() => {}); monCtx = monNode = null; } return; }
  if (!monCtx || monCtx.sampleRate !== sr) {
    if (monCtx) monCtx.close().catch(() => {});
    const ctx = monCtx = new AudioContext({ sampleRate: sr }); monNode = null;
    ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([PLAYER], { type: 'application/javascript' })))
      .then(() => { if (ctx === monCtx) { monNode = new AudioWorkletNode(ctx, 'scramic-play', { outputChannelCount: [1] }); monNode.connect(ctx.destination); } })
      .catch(() => {});
  }
  if (monNode) monNode.port.postMessage(f32.slice(0));
}

// ---------------------------------------------------------------- Streamer mode selector
function renderStream(m) {
  if (feature !== 'streamer') return;
  const o = m.opts || {};
  const fill = (el, list, cur, maxLabel, label) => {
    el.innerHTML = [`<option value="max">${esc(maxLabel)}</option>`]
      .concat((list || []).map(v => `<option value="${esc(v)}">${esc(label(v))}</option>`)).join('');
    el.value = String(cur);
  };
  fill($('qRes'), o.res, m.res, o.maxShort ? `Max (${o.maxShort}p)` : 'Max', v => v + 'p');
  fill($('qFps'), o.fps, m.fps, o.maxFps ? `Max (${o.maxFps})` : 'Max', v => String(v));
  // ScramicShare Cam follows the stream, up to 1080p60
  const short = Math.min(1080, Math.min(m.w || 1080, m.h || 1080));
  setVcamMode(Math.round(short * 16 / 9 / 2) * 2, short, Math.min(60, m.f || 30));
}
$('qRes').onchange = $('qFps').onchange = () => {
  const num = v => v === 'max' ? v : +v;
  send({ t: 'stream-set', res: $('qRes').value, fps: num($('qFps').value) });
};

// what the PC is really receiving, shown on both sides
let lastFrames = 0;
setInterval(async () => {
  if (feature !== 'streamer') return;
  let w = 0, h = 0, fps = 0;
  if (wiredFeature) {
    w = $('wcv').width; h = $('wcv').height;
    fps = wiredFrames - lastFrames; lastFrames = wiredFrames;
  } else if (pc) {
    (await pc.getStats()).forEach(r => {
      if (r.type === 'inbound-rtp' && r.kind === 'video') { w = r.frameWidth || 0; h = r.frameHeight || 0; fps = r.framesPerSecond || 0; }
    });
  }
  if (!w || !h || feature !== 'streamer') return;
  const text = `${w}×${h} at ${Math.round(fps)} fps`;
  $('qNow').textContent = 'Receiving ' + text;
  send({ t: 'stream-stats', text });
}, 1000);

// ---------------------------------------------------------------- pop-out video window
// Plays the same stream as the app, with nothing around it, so OBS can capture it cleanly.
let popWin = null, popVid = null, popCanvasStream = null;
function popFeed() {
  if (!popVid) return;
  if (wiredFeature) popVid.srcObject = popCanvasStream || (popCanvasStream = $('wcv').captureStream());
  else if (popVid.srcObject !== video.srcObject) popVid.srcObject = video.srcObject;
  popVid.play().catch(() => {});
}
function popLayout() {
  if (!popVid || !popWin || popWin.closed) return;
  const vw = popVid.videoWidth, vh = popVid.videoHeight;
  if (!vw || !vh) return;
  const side = rot % 180 !== 0, s = Math.min(popWin.innerWidth / (side ? vh : vw), popWin.innerHeight / (side ? vw : vh));
  popVid.style.width = vw * s + 'px';
  popVid.style.height = vh * s + 'px';
  popVid.style.transform = `translate(-50%, -50%) rotate(${rot}deg)`;
}
function popOpen() {
  const el = wiredFeature ? $('wcv') : video;
  const vw = (wiredFeature ? el.width : video.videoWidth) || 16, vh = (wiredFeature ? el.height : video.videoHeight) || 9;
  const side = rot % 180 !== 0, tall = (side ? vw : vh) > (side ? vh : vw);
  const h = tall ? 800 : 540, w = Math.round(h * (side ? vh : vw) / (side ? vw : vh));
  popWin = window.open('', 'ScramicShareVideo', `popup,width=${w},height=${h}`);
  if (!popWin) { toast("Couldn't open the video window"); return; }
  const d = popWin.document;
  d.title = 'ScramicShare Video';
  d.body.style.cssText = 'margin:0;background:#000;overflow:hidden';
  popVid = d.createElement('video');
  popVid.autoplay = popVid.muted = popVid.playsInline = true;
  popVid.style.cssText = 'position:absolute;left:50%;top:50%;transform-origin:center';
  d.body.appendChild(popVid);
  popVid.addEventListener('resize', popLayout);
  popVid.addEventListener('loadedmetadata', popLayout);
  popWin.addEventListener('resize', popLayout);
  popFeed();
  $('popLabel').textContent = 'Close pop out';
}
function popClose() {
  if (popWin && !popWin.closed) popWin.close();
  popWin = popVid = popCanvasStream = null;
  $('popLabel').textContent = 'Pop out';
}
$('popBtn').onclick = () => { if (popWin && !popWin.closed) popClose(); else popOpen(); };
$('obsBtn').onclick = () => openModal('obsGuide');
setInterval(() => { if (popWin && popWin.closed) popClose(); }, 500);

// ---------------------------------------------------------------- recording: the video from the phone, saved on this PC
// The stream is passed through here so the phone's Rotate choice is in the file, and it keeps going while minimized.
// With a graphics card that can make H.264, it does the work: smooth at any frame rate, and every player opens the file.
// Otherwise MediaRecorder makes it on the processor, which can't keep up with detailed 60 fps video.
const REC_TYPES = ['video/mp4', 'video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm'];
const H264_CONFIG = (w, h) => ({ codec: w * h > 1920 * 1088 ? 'avc1.640033' : 'avc1.64002A', width: w, height: h, bitrate: Math.min(20e6, w * h * 7.2), framerate: 60, hardwareAcceleration: 'prefer-hardware', latencyMode: 'realtime', avc: { format: 'avc' } });
const AAC_CONFIG = (sampleRate, numberOfChannels) => ({ codec: 'mp4a.40.2', sampleRate, numberOfChannels, bitrate: 160000 });
let rec = null, recHardware = false;
Promise.all([VideoEncoder.isConfigSupported(H264_CONFIG(1920, 1080)), AudioEncoder.isConfigSupported(AAC_CONFIG(48000, 2))])
  .then(([v, a]) => { recHardware = v.supported && a.supported; }).catch(() => {});
function recTrack() {
  const s = wiredFeature ? (rec && rec.canvasStream) : video.srcObject;
  return s && s.getVideoTracks()[0] || null;
}
async function recFeed(track) {
  const r = rec, mine = ++r.feed;
  r.track = track;
  const reader = new MediaStreamTrackProcessor({ track }).readable.getReader();
  let cv = null, cx = null;
  try {
    while (rec === r && r.feed === mine) {
      const { value: f, done } = await reader.read();
      if (done) break;
      if (rec !== r || r.feed !== mine) { f.close(); break; }
      const w = f.displayWidth, h = f.displayHeight, side = rot % 180 !== 0;
      if (!r.W) { r.W = (side ? h : w) & ~1; r.H = (side ? w : h) & ~1; }    // one recording keeps one size, so every player copes
      if (!rot && w === r.W && h === r.H) { await r.put(f); continue; }      // put() closes the frame
      if (!cv) { cv = new OffscreenCanvas(r.W, r.H); cx = cv.getContext('2d', { alpha: false }); }
      const s = Math.min(r.W / (side ? h : w), r.H / (side ? w : h));
      cx.fillStyle = '#000'; cx.fillRect(0, 0, r.W, r.H);
      cx.save(); cx.translate(r.W / 2, r.H / 2); cx.rotate(rot * Math.PI / 180);
      cx.drawImage(f, -w * s / 2, -h * s / 2, w * s, h * s);
      cx.restore();
      const out = new VideoFrame(cv, { timestamp: f.timestamp });
      f.close();
      await r.put(out);
    }
  } catch (e) {}
  reader.cancel().catch(() => {});
}
function recTick() {
  const r = rec;
  if (!r) return;
  const t = Math.floor((performance.now() - r.start) / 1000);
  $('recLabel').textContent = `Stop ${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
  const track = recTrack();
  if (track && track !== r.track) recFeed(track);              // the phone restarted its video
  if (wiredFeature) {
    if (wnode && wnode !== r.wnode) {
      r.wnode = wnode;
      const d = wctx.createMediaStreamDestination();
      wnode.connect(d);
      r.ctx.createMediaStreamSource(d.stream).connect(r.dest);
    }
  } else if (video.srcObject) {
    video.srcObject.getAudioTracks().forEach(a => {
      if (r.audio.has(a)) return;
      r.audio.add(a);
      r.ctx.createMediaStreamSource(new MediaStream([a])).connect(r.dest);
    });
  }
}
// The graphics card's H.264, and AAC sound, put into an MP4 by mp4mux.js.
function recHardwareRoute(r) {
  const fail = () => { if (r.failed) return; r.failed = true; toast("Couldn't keep recording, so it was saved up to here"); if (rec === r) recStop(); };
  const channels = 2;
  r.dest.channelCount = channels;
  const venc = new VideoEncoder({ error: fail, output: (chunk, meta) => r.mux.addVideo(chunk, meta, chunk.timestamp) });
  const aenc = new AudioEncoder({
    error: () => {},                                     // the video still matters without its sound
    output: (chunk, meta) => {
      if (r.wall === undefined) return;                  // sound starts with the first picture
      if (r.soundAt === undefined) r.soundAt = (performance.now() - r.wall) * 1000 - chunk.timestamp;
      r.mux.addAudio(chunk, meta, chunk.timestamp + r.soundAt);
    },
  });
  aenc.configure(AAC_CONFIG(r.ctx.sampleRate, channels));
  let last = -1, lastKey = -1e9;
  r.put = f => {
    if (!r.mux) {
      venc.configure(H264_CONFIG(r.W, r.H));
      r.mux = new Mp4Mux(b => { if (r.ws.readyState === 1) r.ws.send(b); }, r.W, r.H, r.ctx.sampleRate, channels);
    }
    if (venc.encodeQueueSize > 3) { f.close(); return; }           // the card is busy: skip one, don't fall behind
    if (r.wall === undefined) { r.wall = performance.now(); r.base = f.timestamp; }
    let time = f.timestamp - r.base;
    if (time <= last || time - last > 2e6) {             // the phone restarted its video: its clock starts over
      time = Math.max(last + 1000, (performance.now() - r.wall) * 1000);
      r.base = f.timestamp - time;
    }
    last = time;
    const out = new VideoFrame(f, { timestamp: time });
    f.close();
    const keyFrame = time - lastKey >= 2e6;
    if (keyFrame) lastKey = time;
    venc.encode(out, { keyFrame });
    out.close();
  };
  const sound = new MediaStreamTrackProcessor({ track: r.dest.stream.getAudioTracks()[0] }).readable.getReader();
  (async () => {
    try {
      while (rec === r) {
        const { value, done } = await sound.read();
        if (done) break;
        if (rec === r && aenc.state === 'configured') aenc.encode(value);
        value.close();
      }
    } catch (e) {}
    sound.cancel().catch(() => {});
  })();
  r.finish = async () => {
    try { if (venc.state === 'configured') await venc.flush(); } catch (e) {}
    try { if (aenc.state === 'configured') await aenc.flush(); } catch (e) {}
    if (r.mux) r.mux.flush();
    if (venc.state !== 'closed') venc.close();
    if (aenc.state !== 'closed') aenc.close();
    r.ctx.close().catch(() => {});
    r.ws.close();
  };
}
// The processor's fallback.
function recMediaRecorderRoute(r, type) {
  const gen = new MediaStreamTrackGenerator({ kind: 'video' });
  const mr = new MediaRecorder(new MediaStream([gen, r.dest.stream.getAudioTracks()[0]]), { mimeType: type, videoBitsPerSecond: 12e6, audioBitsPerSecond: 160e3 });
  const writer = gen.writable.getWriter();
  let chain = Promise.resolve();
  r.put = f => writer.write(f);
  r.begin = () => mr.start(1000);
  mr.ondataavailable = e => {
    if (!e.data.size) return;
    chain = chain.then(async () => { const b = await e.data.arrayBuffer(); if (r.ws.readyState === 1) r.ws.send(b); });
  };
  mr.onstop = () => { chain = chain.then(() => r.ws.close()); r.ctx.close().catch(() => {}); };
  r.finish = () => { if (mr.state !== 'inactive') mr.stop(); else r.ws.close(); };
}
function recStart() {
  const type = recHardware ? 'video/mp4' : REC_TYPES.find(t => MediaRecorder.isTypeSupported(t));
  const canvasStream = wiredFeature ? $('wcv').captureStream() : null;
  const track = canvasStream ? canvasStream.getVideoTracks()[0] : video.srcObject && video.srcObject.getVideoTracks()[0];
  if (!type || !track) { toast('Wait for the video to start, then try again'); return; }
  const ctx = new AudioContext();
  ctx.resume();
  const dest = ctx.createMediaStreamDestination();
  const ws = new WebSocket(`ws://${location.host}/record`);
  const r = rec = { ws, ctx, dest, canvasStream, audio: new Set(), feed: 0, track: null, wnode: null, start: performance.now(), path: '', failed: false };
  if (recHardware) recHardwareRoute(r); else recMediaRecorderRoute(r, type);
  ws.onopen = () => {
    ws.send(type.startsWith('video/mp4') ? 'mp4' : 'webm');
    recFeed(track);
    recTick();
    if (r.begin) r.begin();
    r.start = performance.now();
  };
  ws.onmessage = e => {
    if (e.data.startsWith('error:')) { r.failed = true; toast("Couldn't save the recording: " + e.data.slice(6)); if (rec === r) recStop(); }
    else r.path = e.data;
  };
  ws.onclose = () => {
    if (r.path && !r.failed) toast('Recording saved: ' + r.path);
    else if (!r.failed) toast("Couldn't save the recording");
    if (rec === r) recStop();
  };
  $('recBtn').classList.add('recording');
  $('recLabel').textContent = 'Stop 00:00';
}
function recStop() {
  const r = rec;
  if (!r) return;
  rec = null;
  r.finish();
  $('recBtn').classList.remove('recording');
  $('recLabel').textContent = 'Record';
}
$('recBtn').onclick = () => { if (rec) recStop(); else recStart(); };
setInterval(recTick, 500);

// camera frames -> ScramicShare Cam, as each new one arrives (the phone's rotation applied).
// A worker receives and compresses them, so the preview stays smooth and it keeps working while the app is
// minimized. It only does this while another app has the camera open.
const VCAM_WORKER = `
let ws, cv, cx, on = false, opts = {}, next = null, working = false, reading = 0;
function connect(url) {
  ws = new WebSocket(url);
  ws.onmessage = e => { on = e.data === 'on'; };
  ws.onclose = () => { on = false; setTimeout(() => connect(url), 1500); };
}
function give(frame) {                                 // only the newest frame waits
  if (next) next.close();
  next = frame;
  if (!working) work();
}
async function work() {
  working = true;
  while (next) {
    const f = next; next = null;
    try {
      if (on && opts.live && ws.readyState === 1 && ws.bufferedAmount < 2e6) {
        if (!cv || cv.width !== opts.W || cv.height !== opts.H) { cv = new OffscreenCanvas(opts.W, opts.H); cx = cv.getContext('2d', { alpha: false, willReadFrequently: true }); }
        const W = opts.W, H = opts.H, rot = opts.rot, w = f.displayWidth || f.width, h = f.displayHeight || f.height;
        const side = rot % 180 !== 0, s = Math.min(W / (side ? h : w), H / (side ? w : h));
        cx.fillStyle = '#000'; cx.fillRect(0, 0, W, H);
        cx.save(); cx.translate(W / 2, H / 2);
        cx.scale(1, -1);                               // the camera reads the bottom row first
        cx.rotate(rot * Math.PI / 180);
        cx.drawImage(f, -w * s / 2, -h * s / 2, w * s, h * s);
        cx.restore();
        const blob = await cv.convertToBlob({ type: 'image/jpeg', quality: opts.q });
        if (ws.readyState === 1) ws.send(await blob.arrayBuffer());
      }
    } catch (e) {}
    f.close();
  }
  working = false;
}
async function read(readable) {                        // every frame of the phone's video track
  const mine = ++reading, reader = readable.getReader();
  try {
    while (mine === reading) {
      const { value, done } = await reader.read();
      if (done) break;
      if (mine === reading) give(value); else value.close();
    }
  } catch (e) {}
  reader.cancel().catch(() => {});
}
onmessage = e => {
  const m = e.data;
  if (m.url) connect(m.url);
  if (m.opts) opts = m.opts;
  if (m.readable) read(m.readable);
  if (m.frame) give(m.frame);
};`;
const vworker = new Worker(URL.createObjectURL(new Blob([VCAM_WORKER], { type: 'text/javascript' })));
vworker.postMessage({ url: `ws://${location.host}/vcam` });
let vcW = 1280, vcH = 720, vcamTrack = null;
function setVcamMode(w, h, fps) {
  vcW = w; vcH = h;
  send({ t: 'vcam-mode', w, h, fps });
}
// keeps the worker up to date, and gives it the phone's video track whenever that changes
setInterval(() => {
  const live = isCam(feature) && devState.cam === 'ready';
  vworker.postMessage({ opts: { live, rot, W: vcW, H: vcH, q: 0.85 } });
  const track = video.srcObject && video.srcObject.getVideoTracks()[0] || null;
  if (track && track !== vcamTrack) {
    const { readable } = new MediaStreamTrackProcessor({ track });
    vworker.postMessage({ readable }, [readable]);
  }
  vcamTrack = track;
}, 100);
// over the cable there's no track: each decoded frame is handed over
function vcamWired(frame) {
  if (devState.cam === 'ready') vworker.postMessage({ frame }, [frame]);
  else frame.close();
}

send({ t: 'dev', a: 'state' });
setTimeout(() => send({ t: 'dev', a: 'state' }), 1500);
