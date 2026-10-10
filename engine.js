/* codestory animation engine (MIT). Shared by player.html and walkthrough.html; `build` embeds it.
   A small timeline: tweens of opacity, visibility, position, scale, stroke offset and plain-object values,
   placed at absolute times. Every value is a pure function of the playhead, so seeking and scrubbing in either
   direction always land on the same frame. */
(function (global) {
"use strict";
const EASE = {
  none: (p) => p,
  "power1.out": (p) => 1 - (1 - p) * (1 - p),
  "power1.inOut": (p) => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2),
  "power2.out": (p) => 1 - Math.pow(1 - p, 3)
};
const NOT_PROPS = new Set(["duration", "ease", "stagger", "onUpdate", "immediateRender"]);
const TRANSFORMS = new Set(["x", "y", "scale"]);
const isEl = (t) => typeof Element !== "undefined" && t instanceof Element;
const toList = (t) => (t == null ? [] : isEl(t) || typeof t.length !== "number" ? [t] : Array.from(t));

function applyProp(target, prop, v, xform) {
  if (!isEl(target)) { target[prop] = v; return; }
  if (TRANSFORMS.has(prop)) { let s = xform.get(target); if (!s) xform.set(target, (s = { x: 0, y: 0, scale: 1 })); s[prop] = v; s.dirty = true; return; }
  if (prop === "autoAlpha") { target.style.opacity = v; target.style.visibility = v <= 0.001 ? "hidden" : "inherit"; return; }
  if (prop === "opacity") { target.style.opacity = v; return; }
  target.style[prop] = v;
}
function flushTransforms(xform) {
  xform.forEach((s, el) => {
    if (!s.dirty) return;
    s.dirty = false;
    el.style.transform = (s.x || s.y ? "translate(" + s.x + "px," + s.y + "px)" : "") + (s.scale !== 1 ? " scale(" + s.scale + ")" : "");
  });
}

function makeTimeline(opts) {
  opts = opts || {};
  const tracks = new Map(), tweens = [], xform = new Map();
  let total = 0, time = 0, playing = false, speed = 1, raf = 0, last = 0;

  function baseValue(target, prop) {
    if (!isEl(target)) return +target[prop] || 0;
    if (prop === "x" || prop === "y") return 0;
    if (prop === "scale") return 1;
    const cs = getComputedStyle(target);
    if (prop === "autoAlpha") return cs.visibility === "hidden" ? 0 : parseFloat(cs.opacity);
    if (prop === "opacity") return parseFloat(cs.opacity);
    return parseFloat(target.style[prop]) || 0;
  }
  function track(target, prop) {
    let m = tracks.get(target);
    if (!m) tracks.set(target, (m = new Map()));
    let tr = m.get(prop);
    if (!tr) m.set(prop, (tr = { target, prop, base: baseValue(target, prop), list: [] }));
    return tr;
  }
  // value of one property at time t: the latest segment that has started wins
  function valueAt(tr, t) {
    let cur = null;
    for (const seg of tr.list) { if (seg.start <= t) cur = seg; else break; }
    if (!cur) { const first = tr.list[0]; return first && first.immediate ? first.from : tr.base; }
    const p = cur.dur > 0 ? Math.min(1, (t - cur.start) / cur.dur) : 1;
    return cur.from + (cur.to - cur.from) * cur.ease(p);
  }
  function add(targets, fromVars, toVars, at, kind) {
    const vars = kind === "from" ? fromVars : toVars;
    const d = vars.duration != null ? vars.duration : 0.5;
    const ease = EASE[vars.ease] || EASE["power1.out"];
    const immediate = kind !== "to" && vars.immediateRender !== false;
    const t0 = at == null ? total : at;
    const props = Object.keys(vars).filter((k) => !NOT_PROPS.has(k));
    toList(targets).forEach((target, i) => {
      const start = t0 + i * (vars.stagger || 0);
      const tw = { start, dur: d, onUpdate: vars.onUpdate, lastP: undefined };
      props.forEach((prop) => {
        const tr = track(target, prop), now = valueAt(tr, start);
        const seg = { start, dur: d, ease, immediate,
          from: kind === "to" ? now : +(kind === "from" ? vars[prop] : fromVars[prop]),
          to: kind === "from" ? now : +toVars[prop] };
        let k = tr.list.findIndex((x) => x.start > start);
        if (k < 0) k = tr.list.length;
        tr.list.splice(k, 0, seg);
      });
      tweens.push(tw);
      total = Math.max(total, start + d);
    });
    return api;
  }
  function render() {
    tracks.forEach((m) => m.forEach((tr) => applyProp(tr.target, tr.prop, valueAt(tr, time), xform)));
    flushTransforms(xform);
    for (const tw of tweens) {
      if (!tw.onUpdate) continue;
      const p = tw.dur > 0 ? Math.min(1, Math.max(0, (time - tw.start) / tw.dur)) : time >= tw.start ? 1 : 0;
      if (p !== tw.lastP) { tw.lastP = p; tw.onUpdate(); }
    }
    if (opts.onUpdate) opts.onUpdate();
  }
  function frame(now) {
    if (!playing) return;
    time = Math.min(total, time + Math.min(0.1, (now - last) / 1000) * speed);
    last = now;
    render();
    if (time >= total) { playing = false; if (opts.onComplete) opts.onComplete(); return; }
    raf = requestAnimationFrame(frame);
  }
  const api = {
    to: (t, v, at) => add(t, null, v, at, "to"),
    from: (t, v, at) => add(t, v, null, at, "from"),
    fromTo: (t, f, v, at) => add(t, f, v, at, "fromTo"),
    addLabel: () => api,
    play() { if (time >= total) time = 0; if (!playing) { playing = true; last = performance.now(); raf = requestAnimationFrame(frame); } return api; },
    pause() { playing = false; cancelAnimationFrame(raf); return api; },
    paused: () => !playing,
    isActive: () => playing,
    time: () => time,
    duration: () => total,
    seek(t) { time = Math.max(0, Math.min(total, t)); render(); return api; },
    progress(p) { return p === undefined ? (total ? time / total : 0) : api.seek(p * total); },
    timeScale(s) { if (s === undefined) return speed; speed = s; return api; },
    kill() { return api.pause(); }
  };
  return api;
}
const anim = {
  timeline: makeTimeline,
  set(targets, vars) {
    const xform = new Map();
    toList(targets).forEach((t) => Object.keys(vars).forEach((k) => applyProp(t, k, vars[k], xform)));
    flushTransforms(xform);
  }
};

global.CodestoryAnim = { anim, makeTimeline, EASE };
})(window);
