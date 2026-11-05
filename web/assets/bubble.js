// Orange voice bubble: a soft circle that swells and wobbles with the audio level.
// makeBubble(canvas, analyser|null) -> { setAnalyser(a), setMuted(bool), stop() }
function makeBubble(canvas, analyser) {
  const ctx = canvas.getContext('2d');
  let data = analyser ? new Uint8Array(analyser.fftSize) : null;
  let lvl = 0, t = 0, muted = false, raf = 0, shown = 0;

  function level() {
    if (!analyser || muted) return 0;
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) { const v = (data[i] - 128) / 128; sum += v * v; }
    return Math.min(1, Math.pow(Math.sqrt(sum / data.length) * 5, 0.8));
  }

  function frame() {
    raf = requestAnimationFrame(frame);
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const target = level();
    lvl += (target - lvl) * (target > lvl ? 0.55 : 0.14);
    shown += ((muted ? 1 : 0) - shown) * 0.12;
    t += 1 / 60;

    const cx = w / 2, cy = h / 2;
    const base = Math.min(w, h) * 0.15 * (1 + Math.sin(t * 1.6) * 0.015);
    const N = 96;
    ctx.beginPath();
    for (let i = 0; i <= N; i++) {
      const a = (i / N) * Math.PI * 2;
      const r = base * (1 + lvl * 0.55)
        + Math.sin(a * 3 + t * 2.1) * base * (0.01 + lvl * 0.07)
        + Math.sin(a * 5 - t * 2.9) * base * (lvl * 0.05)
        + Math.sin(a * 2 + t * 1.3) * base * 0.01;
      const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.closePath();

    const g = ctx.createRadialGradient(cx - base * 0.35, cy - base * 0.45, base * 0.05, cx, cy, base * 1.5);
    const mix = (a, b) => a.map((v, i) => Math.round(v + (b[i] - v) * shown));
    const c1 = mix([255, 196, 140], [150, 150, 150]);
    const c2 = mix([255, 128, 38], [95, 95, 95]);
    const c3 = mix([226, 78, 10], [60, 60, 60]);
    g.addColorStop(0, `rgb(${c1})`);
    g.addColorStop(0.55, `rgb(${c2})`);
    g.addColorStop(1, `rgb(${c3})`);
    ctx.shadowColor = `rgba(255,122,26,${(0.35 + lvl * 0.4) * (1 - shown)})`;
    ctx.shadowBlur = base * (0.35 + lvl * 0.6);
    ctx.fillStyle = g;
    ctx.fill();
  }
  frame();

  return {
    setAnalyser(a) { analyser = a; data = a ? new Uint8Array(a.fftSize) : null; },
    setMuted(m) { muted = !!m; },
    stop() { cancelAnimationFrame(raf); },
  };
}
