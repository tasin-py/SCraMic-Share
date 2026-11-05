'use strict';
// Wired camera / mic: JPEG frames and 16-bit PCM audio over one WebSocket.
// Plain TCP goes through the USB cable (adb reverse or iPhone USB hotspot),
// where WebRTC can't. Message = 1 type byte + payload:
//   1 = JPEG frame
//   2 = audio: uint32 sample rate (LE) + int16 mono samples
const WiredMedia = (() => {
  let ws = null, key = '';
  const MAX_BUFFER = 700 * 1024;     // if the cable is behind, skip frames instead of lagging

  function sock() {
    if (ws && ws.readyState <= 1) return ws;
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/media?role=phone&k=${encodeURIComponent(key)}`);
    ws.binaryType = 'arraybuffer';
    return ws;
  }
  const ready = () => ws && ws.readyState === 1;

  // ---------------------------------------------------------------- video
  let timer = 0, busy = false, blank = false;
  const cvs = document.createElement('canvas'), cx = cvs.getContext('2d');
  function startVideo(videoEl, opts) {
    const o = Object.assign({ side: 1280, fps: 30, quality: 0.74, buffer: MAX_BUFFER }, opts);
    stopVideo();
    sock();
    timer = setInterval(() => {
      if (!ready() || busy || ws.bufferedAmount > o.buffer) return;
      const vw = videoEl.videoWidth, vh = videoEl.videoHeight;
      if (!vw || !vh) return;
      const k = Math.min(1, o.side / Math.max(vw, vh));
      const w = Math.round(vw * k), h = Math.round(vh * k);
      if (cvs.width !== w || cvs.height !== h) { cvs.width = w; cvs.height = h; }
      if (blank) cx.fillRect(0, 0, w, h);    // video off: a black picture (the canvas default fill)
      else cx.drawImage(videoEl, 0, 0, w, h);
      busy = true;
      cvs.toBlob(b => {
        if (!b) { busy = false; return; }
        b.arrayBuffer().then(buf => {
          busy = false;
          if (!ready()) return;
          const out = new Uint8Array(buf.byteLength + 1);
          out[0] = 1; out.set(new Uint8Array(buf), 1);
          ws.send(out);
        });
      }, 'image/jpeg', o.quality);
    }, 1000 / o.fps);
  }
  function stopVideo() { clearInterval(timer); timer = 0; busy = false; }

  // ---------------------------------------------------------------- audio
  const WORKLET = `
  class Cap extends AudioWorkletProcessor {
    constructor() { super(); this.b = new Int16Array(960); this.n = 0; }
    process(inputs) {
      const c = inputs[0] && inputs[0][0];
      if (c) for (let i = 0; i < c.length; i++) {
        let v = c[i]; v = v < -1 ? -1 : v > 1 ? 1 : v;
        this.b[this.n++] = v * 32767;
        if (this.n === this.b.length) {
          const out = new Uint8Array(5 + this.b.length * 2);
          out[0] = 2; new DataView(out.buffer).setUint32(1, sampleRate, true);
          out.set(new Uint8Array(this.b.buffer), 5);
          this.port.postMessage(out, [out.buffer]);
          this.b = new Int16Array(960); this.n = 0;
        }
      }
      return true;
    }
  }
  registerProcessor('scramic-cap', Cap);`;
  let node = null, src = null, sink = null;
  const loaded = new WeakSet();
  async function startAudio(track, ctx) {
    stopAudio();
    sock();
    if (!loaded.has(ctx)) {
      const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
      await ctx.audioWorklet.addModule(url);
      loaded.add(ctx);
    }
    src = ctx.createMediaStreamSource(new MediaStream([track]));
    node = new AudioWorkletNode(ctx, 'scramic-cap', { numberOfOutputs: 1 });
    sink = ctx.createGain(); sink.gain.value = 0;       // keeps the node running, plays nothing
    src.connect(node); node.connect(sink); sink.connect(ctx.destination);
    node.port.onmessage = e => { if (ready() && ws.bufferedAmount < MAX_BUFFER * 2) ws.send(e.data); };
    ctx.resume();
  }
  function stopAudio() {
    [src, node, sink].forEach(n => { try { n && n.disconnect(); } catch (e) {} });
    if (node) node.port.onmessage = null;
    src = node = sink = null;
  }

  return {
    setKey(k) { key = k; },
    setBlank(on) { blank = on; },
    startVideo, stopVideo, startAudio, stopAudio,
    stop() { stopVideo(); stopAudio(); },
  };
})();
