'use strict';
hydrateIcons();

const $ = id => document.getElementById(id);
const SCREENS = ['sConnect', 'sChoose', 'sWired', 'sMenu', 'sCamera', 'sMic', 'sScreen', 'sGone'];
let screen = 'sConnect';
function show(id) {
  screen = id;
  SCREENS.forEach(s => $(s).classList.toggle('hidden', s !== id));
  const pitch = id === 'sMic';     // the mic screen is pitch black, up to the browser's own bar
  document.body.classList.toggle('pitch', pitch);
  document.querySelector('meta[name=theme-color]').content = pitch ? '#000000' : '#191919';
}
document.querySelectorAll('[data-go]').forEach(b => b.onclick = () => show(b.dataset.go));

let toastT;
function toast(text) {
  const t = $('toast');
  t.textContent = text; t.classList.add('show');
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('show'), 2600);
}

// ---------------------------------------------------------------- pairing key (from the QR code)
const urlKey = new URLSearchParams(location.search).get('k');
if (urlKey) { try { localStorage.k = urlKey; } catch (e) {} history.replaceState(null, '', location.pathname); }
let K = urlKey || (() => { try { return localStorage.k || ''; } catch (e) { return ''; } })();
WiredMedia.setKey(K);

// Wired = this page came over the USB cable: Android "adb reverse" (localhost)
// or an iPhone's USB Personal Hotspot (172.20.10.x).
let WIRED = false;
const onCable = () => { const h = location.hostname; return h === 'localhost' || h === '127.0.0.1' || h.startsWith('172.20.10.'); };

// ---------------------------------------------------------------- socket
let ws = null, pcOnline = false, stopped = false, everConnected = false;
function send(m) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(m)); }

let fails = 0;
function connect() {
  stopped = false;
  if (!K) { goneScreen('Scan the QR code', 'Open SCraMic Share on your PC, pick Wireless and scan the QR code with this phone.'); return; }
  const sock = ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws?role=phone&k=${encodeURIComponent(K)}`);
  let opened = false;
  sock.onopen = () => { opened = true; fails = 0; };
  sock.onmessage = e => { if (sock === ws) handle(JSON.parse(e.data)); };
  sock.onclose = () => {
    if (stopped || sock !== ws) return;   // ignore sockets we already replaced
    if (!opened && ++fails >= 3) {
      goneScreen('Scan the QR code again', "Couldn't connect. Scan the QR code in SCraMic Share on your PC again.");
      return;
    }
    pcOnline = false;
    if (feature) endFeature(false);
    show('sConnect');
    $('connectText').textContent = 'Reconnecting to your PC…';
    setTimeout(connect, 1200);
  };
}
connect();

function handle(m) {
  switch (m.t) {
    case 'peer':
      pcOnline = m.connected;
      if (!pcOnline) {
        if (feature) endFeature(false);
        show('sConnect');
        $('connectText').textContent = 'Waiting for SCraMic Share to open on your PC…';
      } else if (screen === 'sConnect') {
        show(everConnected ? 'sMenu' : 'sChoose');
        everConnected = true;
      }
      break;
    case 'answer': onAnswer(m); break;
    case 'stream-set': if (feature === 'streamer') setStream(m.res, m.fps); break;
    case 'stream-stats': if (feature === 'streamer') { pcSees = m.text || ''; showStreamText(); } break;
    case 'ice': if (rtc && m.c) rtc.addIceCandidate(m.c).catch(() => {}); break;
    case 'stop-feature':
      if (feature) { endFeature(false); show('sMenu'); toast('Stopped from the PC'); }
      break;
    case 'disconnect': goneScreen('Disconnected by PC', 'Your PC disconnected this phone.'); break;
    case 'screen-resume':   // the PC kept mirroring while this page was away
      if (!feature) {
        WIRED = !!m.wired;
        scrAudio = m.audio !== false;
        showScreen();
      }
      break;
    case 'screen-state':
      if (feature === 'screen') {
        $('scrState').textContent = m.text || '';
        $('scrDot').className = 'dot ' + (m.ready ? 'live' : 'wait');
        if (m.pcName) pcName = m.pcName;
        if (m.kind) scrKind = m.kind;
        scrPairing = !!m.pairing;
        screenSteps();
        if (m.rotate) {
          $('scrRotAuto').classList.toggle('on', !!m.rotate.auto);
          $('scrRotNow').textContent = `Turned ${m.rotate.deg || 0}°`;
        }
        $('scrControl').classList.toggle('on', m.control !== false);
      }
      break;
    case 'replaced': goneScreen('Opened somewhere else', 'SCraMic Share was opened on another tab or phone.'); break;
  }
}

function goneScreen(title, text) {
  stopped = true;
  if (feature) endFeature(false);
  if (ws) ws.close();
  $('goneTitle').textContent = title;
  $('goneText').textContent = text;
  show('sGone');
}
$('reconnect').onclick = () => { show('sConnect'); $('connectText').textContent = 'Connecting to your PC…'; connect(); };
$('disconnectAll').onclick = () => goneScreen('Disconnected', 'This phone is no longer connected to your PC.');

// ---------------------------------------------------------------- navigation
function useMode(wired) {
  WIRED = wired;
  $('menuTitle').textContent = wired ? 'Wired' : 'Wireless';
  show('sMenu');
}
$('pickWireless').onclick = () => useMode(false);
$('pickWired').onclick = () => { if (onCable()) useMode(true); else show('sWired'); };
$('wiredToWireless').onclick = () => useMode(false);
// show the steps for this kind of phone first
if (/iPhone|iPad|Macintosh.*Mobile/.test(navigator.userAgent)) {
  $('wiredSteps').prepend($('stepsIphone'));
  $('iosWiredNote').classList.remove('hidden');
}

document.querySelectorAll('.tile').forEach(t => {
  const f = t.dataset.f;
  if (!['camera', 'streamer', 'mic', 'teacher', 'control', 'screen'].includes(f)) t.classList.add('soon');
  t.onclick = () => {
    if (f === 'camera') startCamera(false);
    else if (f === 'streamer') startCamera(true);
    else if (f === 'mic') startMic();
    else if (f === 'teacher' || f === 'control') openPanel(f);
    else if (f === 'screen') startScreen();
    else toast('Coming in the next update');
  };
});

// ---------------------------------------------------------------- Teacher mode / PC Control
// They run as full-screen pages on top, with their own connection to the PC,
// while this page keeps the main connection open underneath.
let panel = null;
function openPanel(f) {
  feature = f;
  send({ t: 'feature', f, wired: WIRED });
  panel = document.createElement('iframe');
  panel.className = 'panel';
  panel.src = `/static/${f === 'teacher' ? 'teacher' : 'control'}.html?k=${encodeURIComponent(K)}`;
  panel.allow = 'clipboard-read; clipboard-write; fullscreen';
  document.body.appendChild(panel);
  if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(() => {});
  holdWake();
}
function closePanel() {
  if (!panel) return;
  panel.remove();
  panel = null;
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
}
addEventListener('message', e => {
  if (e.origin !== location.origin || !panel || e.source !== panel.contentWindow) return;
  if (!e.data) return;
  if (e.data.t === 'exit') { endFeature(); show('sMenu'); }
  else if (e.data.t === 'control-state') send({ t: 'control-state', on: !!e.data.on });
  else if (e.data.t === 'fullscreen') {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(() => {});
  }
});

// ---------------------------------------------------------------- WebRTC (phone sends, PC receives)
let rtc = null, feature = null;
let videoTx = null, audioTx = null, outStream = null;

function hasMedia() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    toast(window.isSecureContext ? "This browser can't use the camera" : 'Open the https:// link from the QR code');
    return false;
  }
  return true;
}

function newRtc() {
  if (rtc) rtc.close();
  rtc = new RTCPeerConnection({ iceServers: [] });
  rtc.onicecandidate = e => { if (e.candidate) send({ t: 'ice', c: e.candidate }); };
  rtc.onconnectionstatechange = () => {
    if (rtc && rtc.connectionState === 'failed') toast("Couldn't reach the PC. Same WiFi?");
  };
  outStream = new MediaStream();
  return rtc;
}

async function negotiate() {
  const offer = await rtc.createOffer();
  await rtc.setLocalDescription(offer);
  send({ t: 'offer', sdp: rtc.localDescription.sdp, f: feature });
}

async function onAnswer(m) {
  if (!rtc) return;
  await rtc.setRemoteDescription({ type: 'answer', sdp: m.sdp });
  applyEncoding();
}

// high quality on a local network
function applyEncoding() {
  if (!videoTx) return;
  const p = videoTx.sender.getParameters();
  if (!p.encodings || !p.encodings.length) p.encodings = [{}];
  if (streaming) {
    const s = camTrack.getSettings(), fps = targetFps();
    p.encodings[0].maxBitrate = Math.round(Math.max(4e6, Math.min(60e6, (s.width || 1920) * (s.height || 1080) * fps * 0.2)));
    p.encodings[0].maxFramerate = fps;
    p.encodings[0].scaleResolutionDownBy = 1;
  } else {
    p.encodings[0].maxBitrate = 8_000_000;
    p.encodings[0].maxFramerate = 30;
  }
  videoTx.sender.setParameters(p).catch(() => {});
}

function endFeature(tellPc = true) {
  if (tellPc) send({ t: 'feature', f: null });
  feature = null;
  streaming = false;
  pcSees = '';
  meterId++;
  $('camQual').classList.add('hidden');
  $('qSheet').classList.add('hidden');
  if (rtc) { rtc.close(); rtc = null; }
  [camTrack, micTrack].forEach(t => t && t.stop());
  camTrack = micTrack = null;
  videoTx = audioTx = null;
  WiredMedia.stop();
  videoOn = true;
  WiredMedia.setBlank(false);
  updateVideo();
  $('camVideo').srcObject = null;
  if (bubble) { bubble.stop(); bubble = null; }
  if (audioCtx) { audioCtx.close(); audioCtx = null; }
  closePanel();
  setDark(false);
  releaseWake();
}

// ---------------------------------------------------------------- keep the phone awake while sharing
let wakeLock = null;
async function holdWake() {
  try { if ('wakeLock' in navigator) wakeLock = await navigator.wakeLock.request('screen'); } catch (e) {}
}
function releaseWake() { if (wakeLock) { wakeLock.release().catch(() => {}); wakeLock = null; } }
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && feature) holdWake();
});

// ---------------------------------------------------------------- camera
let camTrack = null, micTrack = null, facing = localStorage.facing || 'environment', rot = 0, micOn = false;

function camConstraints(face) {
  return { facingMode: { ideal: face }, width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 30 } };
}

// ---------------------------------------------------------------- Streamer mode: resolution + fps
const RES_LIST = [2160, 1440, 1080, 720, 480], FPS_LIST = [60, 30, 24, 15];
let streaming = false, camMax = {}, pcSees = '', streamBusy = false, streamNext = null;
let camList = null, camLabel = '', measuredFps = 0, meterId = 0;
const targetFps = () => streamQ.fps === 'max' ? 60 : +streamQ.fps;
const openVideo = video => navigator.mediaDevices.getUserMedia({ video, audio: false });

// Phones have several cameras (main, wide, tele...) and often only some of them can do 60 fps.
async function probeCameras(face) {
  const first = await openVideo({ facingMode: { ideal: face } });   // labels and ids need permission first
  first.getTracks().forEach(t => t.stop());
  const out = [];
  for (const d of await navigator.mediaDevices.enumerateDevices()) {
    if (d.kind !== 'videoinput') continue;
    let k = d.getCapabilities ? d.getCapabilities() : null, facing = '';
    if (!k || !k.frameRate) {     // this browser can only tell us with the camera open
      try {
        const s = await openVideo({ deviceId: { exact: d.deviceId } }), t = s.getVideoTracks()[0];
        k = t.getCapabilities ? t.getCapabilities() : {};
        facing = t.getSettings().facingMode || '';
        s.getTracks().forEach(x => x.stop());
      } catch (e) { continue; }
    }
    facing = (k.facingMode && k.facingMode[0]) || facing || (/front/i.test(d.label) ? 'user' : /back|rear/i.test(d.label) ? 'environment' : '');
    out.push({
      id: d.deviceId, label: d.label, facing,
      fps: k.frameRate ? Math.round(k.frameRate.max) : 0,
      short: k.width && k.height ? Math.min(k.width.max, k.height.max) : 0,
    });
  }
  return out;
}

// Asks for the exact frame rate first, because "ideal" lets a browser settle for 30.
async function openStreamCamera(face) {
  if (!camList) camList = await probeCameras(face);
  const fps = targetFps();
  const same = camList.filter(c => c.facing === face);
  const cams = (same.length ? same : camList).slice().sort((a, b) => b.fps - a.fps);   // sort keeps the main camera first on ties
  const size = c => {
    const short = streamQ.res === 'max' ? (c.short || 2160) : +streamQ.res;
    return { width: { ideal: Math.round(short * 16 / 9) }, height: { ideal: short } };
  };
  const tries = [];
  if (fps > 30) {
    cams.forEach(c => tries.push([c, { deviceId: { exact: c.id }, ...size(c), frameRate: { exact: fps } }]));
    cams.forEach(c => tries.push([c, { deviceId: { exact: c.id }, frameRate: { exact: fps } }]));   // the frame rate may need a smaller size
  }
  const main = fps > 30 ? cams[0] : (same[0] || cams[0]);
  if (main) tries.push([main, { deviceId: { exact: main.id }, ...size(main), frameRate: { ideal: fps } }]);
  for (const [cam, video] of tries) {
    try {
      const s = await openVideo(video);
      camLabel = cam.label;
      return s;
    } catch (e) {}
  }
  camLabel = '';
  const short = streamQ.res === 'max' ? 2160 : +streamQ.res;
  return openVideo({ facingMode: { ideal: face }, width: { ideal: Math.round(short * 16 / 9) }, height: { ideal: short }, frameRate: { ideal: fps } });
}
const openCamera = face => streaming ? openStreamCamera(face) : openVideo(camConstraints(face));

// What actually arrives from the camera; what a browser reports isn't always true.
function startFpsMeter() {
  const v = $('camVideo'), id = ++meterId;
  measuredFps = 0;
  if (!v.requestVideoFrameCallback) return;
  let n = 0, t0 = performance.now();
  const tick = () => {
    if (id !== meterId || !streaming) return;
    n++;
    const now = performance.now();
    if (now - t0 >= 1000) {
      measuredFps = Math.round(n * 1000 / (now - t0));
      n = 0; t0 = now;
      showStreamText();
    }
    v.requestVideoFrameCallback(tick);
  };
  v.requestVideoFrameCallback(tick);
}
let streamQ = (() => {
  try { return Object.assign({ res: '1080', fps: 60 }, JSON.parse(localStorage.streamQ || '{}')); }
  catch (e) { return { res: '1080', fps: 60 }; }
})();

function readCamMax() {
  const k = camTrack.getCapabilities ? camTrack.getCapabilities() : {};
  camMax = {
    short: k.width && k.height ? Math.min(k.width.max, k.height.max) : 0,
    fps: k.frameRate ? Math.round(k.frameRate.max) : 0,
  };
}

function streamOptions() {
  return {
    res: RES_LIST.filter(r => !camMax.short || r <= camMax.short),
    fps: FPS_LIST,    // phones can under-report, so 60 is always worth trying; the real result is shown
    maxShort: camMax.short, maxFps: 0,
  };
}

// Tells the PC what was chosen and what the camera really gave, then redraws the phone's selector.
function streamChanged() {
  readCamMax();
  // a choice this camera can't reach (saved earlier, or from the other camera) becomes its maximum
  if (camMax.short && streamQ.res !== 'max' && +streamQ.res > camMax.short) streamQ.res = 'max';
  const s = camTrack.getSettings();
  send({ t: 'stream-state', res: streamQ.res, fps: streamQ.fps, w: s.width, h: s.height, f: targetFps(), opts: streamOptions() });
  showStream();
}

function showStreamText() {
  if (!camTrack) return;
  const s = camTrack.getSettings(), short = Math.min(s.width || 0, s.height || 0);
  const fps = measuredFps || Math.round(s.frameRate || 0);
  $('camQual').textContent = `${short}p · ${fps} fps`;
  const low = measuredFps && measuredFps < targetFps() * 0.8;
  $('qNote').textContent = `${camLabel || 'Camera'}: ${s.width || '?'}×${s.height || '?'} at ${fps} fps.`
    + (pcSees ? ` PC is getting ${pcSees}.` : '')
    + (low ? ` This is below the ${targetFps()} fps you picked. The browser may limit the camera, and Low Power Mode or a hot phone can also lower it.` : '');
}

function showStream() {
  const o = streamOptions();
  showStreamText();
  const chips = (el, list, cur, label, pick) => {
    el.innerHTML = '';
    list.concat('max').forEach(v => {
      const b = document.createElement('button');
      b.textContent = label(v);
      b.classList.toggle('on', String(v) === String(cur));
      b.onclick = () => pick(v);
      el.appendChild(b);
    });
  };
  chips($('qRes'), o.res, streamQ.res, v => v === 'max' ? 'Max' : v + 'p', v => setStream(v, streamQ.fps));
  chips($('qFps'), o.fps, streamQ.fps, v => v === 'max' ? 'Max' : String(v), v => setStream(streamQ.res, v));
}
$('camQual').onclick = () => { $('qSheet').classList.toggle('hidden'); showStream(); };

async function setStream(res, fps) {
  const okRes = res === 'max' || RES_LIST.includes(+res), okFps = fps === 'max' || FPS_LIST.includes(+fps);
  if (!streaming || !okRes || !okFps) return;
  if (streamBusy) { streamNext = [res, fps]; return; }    // a new choice while the camera reopens
  streamBusy = true;
  streamQ = { res: String(res), fps };
  try { localStorage.streamQ = JSON.stringify(streamQ); } catch (e) {}
  await reopenCamera(facing);
  streamBusy = false;
  if (streamNext) { const n = streamNext; streamNext = null; setStream(n[0], n[1]); }
}

// Phones only change camera mode reliably by reopening the camera.
async function reopenCamera(face) {
  camTrack.stop();   // iPhones can't hold two cameras open at once
  let ok = true;
  try {
    const s = await openCamera(face);
    camTrack = s.getVideoTracks()[0];
  } catch (e) {
    ok = false;
    const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: facing } }, audio: false });
    camTrack = s.getVideoTracks()[0];
  }
  if (!feature) { camTrack.stop(); return false; }      // stopped while the camera was opening
  camTrack.enabled = videoOn;
  if (videoTx) await videoTx.sender.replaceTrack(camTrack);
  showPreview();
  if (WIRED) startWiredVideo();
  if (streaming) { startFpsMeter(); applyEncoding(); streamChanged(); }
  return ok;
}

function startWiredVideo() {
  if (!streaming) { WiredMedia.startVideo($('camVideo')); return; }
  const s = camTrack.getSettings();
  WiredMedia.startVideo($('camVideo'), { side: Math.max(s.width || 1920, s.height || 1080), fps: targetFps(), quality: 0.82, buffer: 1200 * 1024 });
}

async function startCamera(streamer) {
  if (!hasMedia()) return;
  streaming = streamer;
  try {
    const s = await openCamera(facing);
    camTrack = s.getVideoTracks()[0];
  } catch (e) {
    streaming = false;
    toast(e.name === 'NotAllowedError' ? 'Camera permission was blocked' : "Couldn't open the camera");
    return;
  }
  feature = streamer ? 'streamer' : 'camera';
  rot = 0; micOn = false;
  send({ t: 'feature', f: feature, wired: WIRED });
  $('camQual').classList.toggle('hidden', !streamer);
  if (WIRED) {                         // frames go over the cable instead of WebRTC
    showPreview();
    startWiredVideo();
    updateCamButtons();
    show('sCamera');
    holdWake();
    if (streamer) { startFpsMeter(); streamChanged(); }
    return;
  }
  newRtc();
  outStream.addTrack(camTrack);
  videoTx = rtc.addTransceiver(camTrack, { direction: 'sendonly', streams: [outStream] });
  audioTx = rtc.addTransceiver('audio', { direction: 'sendonly', streams: [outStream] });
  if (streamer && videoTx.setCodecPreferences && RTCRtpSender.getCapabilities) {
    // H.264 first: phones encode it in hardware, which is what makes 1080p60 possible
    const rank = c => /h264/i.test(c.mimeType) ? 0 : 1;
    const codecs = RTCRtpSender.getCapabilities('video').codecs.slice().sort((a, b) => rank(a) - rank(b));
    try { videoTx.setCodecPreferences(codecs); } catch (e) {}
  }
  showPreview();
  updateCamButtons();
  show('sCamera');
  holdWake();
  if (streamer) { startFpsMeter(); streamChanged(); }
  await negotiate();
}

function showPreview() {
  const v = $('camVideo');
  v.srcObject = new MediaStream([camTrack]);
  v.play().catch(() => {});
  layoutPreview();
}

function layoutPreview() {
  const v = $('camVideo');
  const vw = v.videoWidth, vh = v.videoHeight;
  if (!vw || !vh) return;
  const W = innerWidth, H = innerHeight;
  const side = rot % 180 !== 0;
  const s = Math.min(W / (side ? vh : vw), H / (side ? vw : vh));
  v.style.width = vw * s + 'px';
  v.style.height = vh * s + 'px';
  const mirror = facing === 'user' ? ' scaleX(-1)' : '';
  v.style.transform = `translate(-50%, -50%) rotate(${rot}deg)${mirror}`;
}
$('camVideo').addEventListener('resize', layoutPreview);
$('camVideo').addEventListener('loadedmetadata', layoutPreview);
addEventListener('resize', layoutPreview);

$('camSwitch').onclick = async () => {
  if (!camTrack) return;
  const next = facing === 'user' ? 'environment' : 'user';
  if (await reopenCamera(next)) {
    facing = localStorage.facing = next;
    layoutPreview();
    toast(facing === 'user' ? 'Front camera' : 'Back camera');
  } else if (feature) toast("Couldn't switch camera");
};

$('camRotate').onclick = () => {
  rot = (rot + 90) % 360;
  send({ t: 'rot', deg: rot });
  layoutPreview();
};

$('camMic').onclick = async () => {
  if (!audioTx && !WIRED) return;
  if (!micOn) {
    if (WIRED && !audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();   // inside the tap (iOS)
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      micTrack = s.getAudioTracks()[0];
    } catch (e) { toast('Microphone permission was blocked'); return; }
    if (WIRED) await WiredMedia.startAudio(micTrack, audioCtx);
    else await audioTx.sender.replaceTrack(micTrack);
    micOn = true;
  } else {
    if (WIRED) WiredMedia.stopAudio();
    else await audioTx.sender.replaceTrack(null);
    if (micTrack) micTrack.stop();
    micTrack = null; micOn = false;
  }
  send({ t: 'micstate', on: micOn, muted: false });
  updateCamButtons();
};

function updateCamButtons() {
  const b = $('camMic');
  b.classList.toggle('on', micOn);
  b.innerHTML = icon(micOn ? 'mic' : 'micOff') + `<span>${micOn ? 'Mic on' : 'Mic off'}</span>`;
}

$('camDark').onclick = () => setDark(true);
$('camStop').onclick = $('camBack').onclick = () => { endFeature(); show('sMenu'); };

// ---------------------------------------------------------------- microphone
let audioCtx = null, bubble = null, muted = false;

async function startMic() {
  if (!hasMedia()) return;
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();   // created inside the tap (iOS)
  try {
    const s = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false,
    });
    micTrack = s.getAudioTracks()[0];
  } catch (e) {
    audioCtx.close(); audioCtx = null;
    toast(e.name === 'NotAllowedError' ? 'Microphone permission was blocked' : "Couldn't open the microphone");
    return;
  }
  feature = 'mic';
  muted = false;
  send({ t: 'feature', f: 'mic', wired: WIRED });
  if (!WIRED) {
    newRtc();
    outStream.addTrack(micTrack);
    audioTx = rtc.addTransceiver(micTrack, { direction: 'sendonly', streams: [outStream] });
  }

  const an = audioCtx.createAnalyser();
  an.fftSize = 1024;
  audioCtx.createMediaStreamSource(new MediaStream([micTrack])).connect(an);
  audioCtx.resume();
  show('sMic');
  bubble = makeBubble($('micBubble'), an);
  updateMute();
  holdWake();
  if (WIRED) { await WiredMedia.startAudio(micTrack, audioCtx); send({ t: 'micstate', on: true, muted: false }); return; }
  await negotiate();
  send({ t: 'micstate', on: true, muted: false });
}

$('micMute').onclick = $('darkMute').onclick = () => {
  if (!micTrack) return;
  muted = !muted;
  micTrack.enabled = !muted;
  updateMute();
  send({ t: 'micstate', on: true, muted });
};
function updateMute() {
  [$('micMute'), $('darkMute')].forEach(b => {
    b.classList.toggle('on', muted);
    b.innerHTML = icon(muted ? 'micOff' : 'mic') + `<span>${muted ? 'Unmute' : 'Mute'}</span>`;
  });
  $('micHint').textContent = muted ? 'Muted. Your PC hears nothing.' : 'Your PC is hearing this phone';
  if (bubble) bubble.setMuted(muted);
}
$('micDark').onclick = () => setDark(true);
$('micStop').onclick = $('micBack').onclick = () => { endFeature(); show('sMenu'); };

// ---------------------------------------------------------------- camera video on / off
// Off: the PC gets a black picture, and the camera stays open so it comes back at once.
let videoOn = true;
function setVideo(on) {
  videoOn = on;
  if (camTrack) camTrack.enabled = on;
  WiredMedia.setBlank(!on);
  updateVideo();
  send({ t: 'videostate', off: !on });
}
function updateVideo() {
  $('darkVideo').classList.toggle('on', !videoOn);
  $('darkVideo').innerHTML = icon(videoOn ? 'video' : 'videoOff') + `<span>${videoOn ? 'Turn video off' : 'Turn video on'}</span>`;
  $('camVideoOn').classList.toggle('hidden', videoOn);   // so it can be turned back on after waking the screen
}
$('darkVideo').onclick = () => setVideo(!videoOn);
$('camVideoOn').onclick = () => setVideo(true);
updateVideo();

// ---------------------------------------------------------------- screen off (hold 3 s to wake)
const HOLD_MS = 3000, RING = 289;
let holdStart = 0, holdRaf = 0;

function setDark(on) {
  $('dark').classList.toggle('hidden', !on);
  $('darkMute').classList.toggle('hidden', feature !== 'mic');
  $('darkVideo').classList.toggle('hidden', feature !== 'camera' && feature !== 'streamer');
  send({ t: 'dark', on });
  if (on && document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(() => {});
  if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  resetHold();
}

function resetHold() {
  cancelAnimationFrame(holdRaf);
  holdStart = 0;
  $('wakeRing').style.strokeDashoffset = RING;
  $('wake').classList.remove('holding');
}

function holdTick() {
  const p = Math.min(1, (performance.now() - holdStart) / HOLD_MS);
  $('wakeRing').style.strokeDashoffset = RING * (1 - p);
  if (p >= 1) { if (navigator.vibrate) navigator.vibrate(30); setDark(false); return; }
  holdRaf = requestAnimationFrame(holdTick);
}

const wake = $('wake');
wake.addEventListener('pointerdown', e => {
  e.preventDefault();
  wake.setPointerCapture(e.pointerId);
  holdStart = performance.now();
  wake.classList.add('holding');
  holdRaf = requestAnimationFrame(holdTick);
});
['pointerup', 'pointercancel', 'pointerleave'].forEach(ev => wake.addEventListener(ev, resetHold));
$('dark').addEventListener('contextmenu', e => e.preventDefault());


// ---------------------------------------------------------------- screen share
// The phone uses its own built-in mirroring; the PC runs the matching receiver.
const IS_IOS = /iPhone|iPad|Macintosh.*Mobile/.test(navigator.userAgent);
let scrKind = 'scrcpy-wifi';   // how the PC is receiving (Android): scrcpy, scrcpy-wifi or miracast
let scrPairing = false;        // the PC is waiting for this phone's Wireless debugging code
let pcName = 'your PC', scrAudio =(() => { try { return localStorage.scrAudio !== '0'; } catch (e) { return true; } })();

function screenSteps() {
  const el = $('scrSteps');
  if (IS_IOS) {
    el.innerHTML = `<b>On this iPhone</b><ol>
      <li>Open <b>Control Center</b> (swipe down from the top-right corner).</li>
      <li>Tap <b>Screen Mirroring</b>.</li>
      <li>Choose <b>SCraMicShare</b>.</li></ol>`;
    $('scrNote').textContent = 'You can leave this page, and mirroring keeps going. To stop, tap Screen Mirroring again and choose Stop Mirroring, or tap Stop below.';
  } else if (scrKind === 'scrcpy-wifi' && scrPairing) {
    el.innerHTML = `<b>Pair over WiFi, one time</b><ol>
      <li>Open <b>Settings → About phone</b> and tap <b>Build number</b> 7 times (on some phones it's <b>Software version</b>). This turns on Developer options.</li>
      <li>Open <b>Developer options → Wireless debugging</b> and turn it on.</li>
      <li>Tap <b>Pair device with pairing code</b>.</li>
      <li>Type the code and port into the PC, and stay on that screen until it's done.</li></ol>`;
    $('scrNote').textContent = 'This phone must be on the same WiFi as the PC. Wireless debugging needs Android 11 or newer.';
  } else if (scrKind === 'scrcpy-wifi') {
    el.innerHTML = `<b>Over WiFi</b><ol>
      <li>Your screen opens on the PC by itself.</li>
      <li>Turn the phone sideways and the PC follows.</li></ol>`;
    $('scrNote').textContent = 'You can leave this page, and mirroring keeps going. Phone sound needs Android 11 or newer.';
  } else if (WIRED) {
    el.innerHTML = `<b>Over the cable</b><ol>
      <li>Your screen opens on the PC by itself.</li>
      <li>If the phone asks to allow screen recording or audio, tap <b>Allow</b> / <b>Start now</b>.</li>
      <li>Turn the phone sideways and the PC follows.</li></ol>`;
    $('scrNote').textContent = 'Phone sound needs Android 11 or newer.';
  } else {
    el.innerHTML = `<b>On this phone</b><ol>
      <li>Swipe down twice from the top to open Quick Settings.</li>
      <li>Tap <b>Smart View</b>, <b>Cast</b>, <b>Screen Cast</b>, <b>Wireless projection</b> or <b>Screen mirroring</b> (the name depends on the phone).</li>
      <li>Choose <b>${pcName.replace(/[<>&]/g, '')}</b>.</li></ol>`;
    $('scrNote').textContent = "Casting always includes the phone's sound. Google Pixel phones can't cast to Windows. Use Wired mode with a USB cable instead.";
  }
  // Android casting (Miracast) can't turn sound off, so the switch only shows where it works
  document.querySelector('#sScreen .toggle-row').classList.toggle('hidden', scrKind === 'miracast');
  // Android's receivers follow rotation by themselves
  $('scrRotAutoRow').classList.toggle('hidden', !IS_IOS);
  $('scrRotRow').classList.toggle('hidden', !IS_IOS);
  $('scrControlRow').classList.toggle('hidden', IS_IOS || scrKind === 'miracast');
}

function updScrAudio() { $('scrAudio').classList.toggle('on', scrAudio); }

function startScreen() {
  send({ t: 'feature', f: 'screen', wired: WIRED, os: IS_IOS ? 'ios' : 'android', audio: scrAudio });
  showScreen();
}

function showScreen() {
  feature = 'screen';
  scrKind = WIRED ? 'scrcpy' : 'scrcpy-wifi';
  $('scrState').textContent = 'Your PC is getting ready…';
  $('scrDot').className = 'dot wait';
  screenSteps(); updScrAudio();
  show('sScreen');
}
$('scrAudio').onclick = () => {
  scrAudio = !scrAudio;
  try { localStorage.scrAudio = scrAudio ? '1' : '0'; } catch (e) {}
  updScrAudio();
  send({ t: 'screen-audio', on: scrAudio });
  toast(IS_IOS ? 'Changed. Start Screen Mirroring again to apply it.' : 'Changed. The PC restarts the mirror.');
};
$('scrRotAuto').onclick = () => send({ t: 'rx-auto', on: !$('scrRotAuto').classList.contains('on') });
$('scrRotLeft').onclick = () => send({ t: 'rx-rotate', by: -1 });
$('scrRotRight').onclick = () => send({ t: 'rx-rotate', by: 1 });
$('scrControl').onclick = () => {
  send({ t: 'rx-control', on: !$('scrControl').classList.contains('on') });
  toast('Changed. The PC restarts the mirror.');
};
$('scrStop').onclick = $('scrBack').onclick = () => { endFeature(); show('sMenu'); };
