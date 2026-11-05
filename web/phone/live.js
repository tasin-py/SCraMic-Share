'use strict';
// Shared by Teacher mode and PC Control:
//   createZoom   - two-finger pinch to zoom / pan the PC screen view
//   createTouchMouse - tap = click, drag = mouse drag, long-press = right-click

// ---------------------------------------------------------------- pinch zoom
// The stage (PC screen) lives inside `area`, which clips it. Zoom is a CSS
// transform on the stage, so getBoundingClientRect() keeps mapping touches to
// the right spot on the PC screen at any zoom.
function createZoom(area, stage, opts) {
  const MAX = 6;
  let W = 1, H = 1, sw = 1, sh = 1;
  let z = 1, tx = 0, ty = 0;
  const touches = new Map();      // pointerId -> {x, y}
  let active = false, base = null;

  function clamp() {
    const cw = sw * z, ch = sh * z;
    tx = cw <= W ? (W - cw) / 2 : Math.min(0, Math.max(W - cw, tx));
    ty = ch <= H ? (H - ch) / 2 : Math.min(0, Math.max(H - ch, ty));
  }
  function apply() {
    clamp();
    stage.style.transform = `translate(${tx}px, ${ty}px) scale(${z})`;
    if (opts.onChange) opts.onChange(z);
  }
  // size of the clipping area and of the stage at zoom 1
  function fit(areaW, areaH, stageW, stageH) {
    const cx = (W / 2 - tx) / (sw * z), cy = (H / 2 - ty) / (sh * z);   // keep the same spot centered
    W = areaW; H = areaH; sw = stageW; sh = stageH;
    tx = W / 2 - cx * sw * z; ty = H / 2 - cy * sh * z;
    apply();
  }
  function reset() { z = 1; apply(); if (opts.onEnd) opts.onEnd(z); }

  function local(e) { const r = area.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
  function rebase() {
    const pts = [...touches.values()];
    const m = { x: pts.reduce((a, p) => a + p.x, 0) / pts.length, y: pts.reduce((a, p) => a + p.y, 0) / pts.length };
    const d = pts.length > 1 ? Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) : 0;
    base = { m, d, z, tx, ty };
  }

  const el = opts.target || stage;
  el.addEventListener('pointerdown', e => {
    if (e.pointerType !== 'touch' || (e.target.closest && e.target.closest('[data-nozoom]'))) return;
    // A new first finger means every earlier finger is gone, even if the browser
    // never told us (that happens around the on-screen keyboard). Start clean.
    if (e.isPrimary) { touches.clear(); active = false; }
    touches.set(e.pointerId, local(e));
    const start = touches.size >= 2 || (touches.size === 1 && opts.panOne && opts.panOne(e));
    if (!active && start) {
      active = true;
      if (opts.onStart) opts.onStart();
    }
    if (active) {
      try { el.setPointerCapture(e.pointerId); } catch (_) {}
      rebase();
      e.preventDefault(); e.stopImmediatePropagation();
    }
  }, true);

  el.addEventListener('pointermove', e => {
    if (!touches.has(e.pointerId)) return;
    touches.set(e.pointerId, local(e));
    if (!active) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const pts = [...touches.values()];
    const m = { x: pts.reduce((a, p) => a + p.x, 0) / pts.length, y: pts.reduce((a, p) => a + p.y, 0) / pts.length };
    if (pts.length > 1 && base.d > 0) {
      const d = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      z = Math.min(MAX, Math.max(1, base.z * d / base.d));
    }
    // the spot that was under the fingers stays under the fingers
    const cx = (base.m.x - base.tx) / base.z, cy = (base.m.y - base.ty) / base.z;
    tx = m.x - cx * z; ty = m.y - cy * z;
    apply();
  }, true);

  function lift(e) {
    if (!touches.has(e.pointerId)) return;
    touches.delete(e.pointerId);
    if (!active) return;
    e.preventDefault(); e.stopImmediatePropagation();
    if (touches.size) rebase();
    else { active = false; if (opts.onEnd) opts.onEnd(z); }
  }
  el.addEventListener('pointerup', lift, true);
  el.addEventListener('pointercancel', lift, true);
  const forget = () => { touches.clear(); if (active) { active = false; if (opts.onEnd) opts.onEnd(z); } };
  addEventListener('blur', forget);
  document.addEventListener('visibilitychange', forget);

  return {
    fit, reset, apply,
    get z() { return z; },
    get active() { return active; },
  };
}

// ---------------------------------------------------------------- touch -> mouse
// norm(e) gives [x, y] in 0..1 over the PC screen. send() delivers to the PC.
function createTouchMouse(send, norm) {
  const MOVE_PX = 9, LONG_MS = 550;
  let st = null;

  function down(e) {
    const p = norm(e);
    st = { id: e.pointerId, x0: e.clientX, y0: e.clientY, p0: p, drag: false, done: false, last: null };
    send({ t: 'm', a: 'move', x: p[0], y: p[1] });
    st.timer = setTimeout(() => {           // long-press = right click
      if (!st || st.drag) return;
      st.done = true;
      send({ t: 'm', a: 'click', b: 'r', x: st.p0[0], y: st.p0[1] });
      if (navigator.vibrate) navigator.vibrate(18);
    }, LONG_MS);
  }
  function move(e) {
    if (!st || e.pointerId !== st.id || st.done) return;
    const p = norm(e);
    if (!st.drag && Math.hypot(e.clientX - st.x0, e.clientY - st.y0) > MOVE_PX) {
      st.drag = true;
      clearTimeout(st.timer);
      send({ t: 'm', a: 'down', b: 'l', x: st.p0[0], y: st.p0[1] });
    }
    if (st.drag) send({ t: 'm', a: 'move', x: p[0], y: p[1] });
  }
  function up(e) {
    if (!st || e.pointerId !== st.id) return;
    clearTimeout(st.timer);
    const p = norm(e);
    if (st.drag) send({ t: 'm', a: 'up', b: 'l', x: p[0], y: p[1] });
    else if (!st.done) send({ t: 'm', a: 'click', b: 'l', x: st.p0[0], y: st.p0[1] });
    st = null;
  }
  function cancel() {
    if (!st) return;
    clearTimeout(st.timer);
    if (st.drag) send({ t: 'm', a: 'up', b: 'l' });
    st = null;
  }
  return { down, move, up, cancel, get busy() { return !!st; } };
}

function postExit() { parent.postMessage({ t: 'exit' }, location.origin); }
