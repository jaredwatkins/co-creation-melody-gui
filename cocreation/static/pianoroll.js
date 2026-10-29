/* Canvas piano roll: keys strip + bar ruler + note grid.
   Human notes blue, committed AI notes orange, uncommitted AI draft ghosted. */
"use strict";

const KEY_W = 52, RULER_H = 26;
const ROW_H0 = 12, PXS0 = 36;      // row height px, px per second

class PianoRoll {
  constructor(scrollEl) {
    this.scroll = scrollEl;
    this.secPerBar = 2;
    this.snapDiv = 16;             // subdivisions per bar
    this.pxPerSec = PXS0;
    this.rowH = ROW_H0;
    this.notes = [];
    this.draft = [];
    this.selected = new Set();
    this.tool = "draw";
    this.playhead = null;
    this.onCommit = null;          // (mutated notes array, reason)

    this.inner = document.createElement("div");
    this.inner.style.position = "relative";
    this.keys = document.createElement("canvas");
    this.keys.style.cssText = "position:sticky;left:0;z-index:3;float:left;";
    this.ruler = document.createElement("canvas");
    this.ruler.style.cssText = "position:sticky;top:0;z-index:4;display:block;margin-left:" + KEY_W + "px;";
    this.roll = document.createElement("canvas");
    this.roll.style.cssText = "display:block;margin-left:" + KEY_W + "px;";

    scrollEl.innerHTML = "";
    this.inner.appendChild(this.ruler);
    this.inner.appendChild(this.keys);
    this.inner.appendChild(this.roll);
    scrollEl.appendChild(this.inner);

    this._bind();
  }

  get snapLen() { return this.secPerBar / this.snapDiv; }  // bar / {16,8,4,1}

  layout() {
    const end = Math.max(this._maxTime() + 4 * this.secPerBar, 24 * this.secPerBar);
    this.width = Math.ceil(end * this.pxPerSec);
    this.height = 128 * this.rowH;
    this.inner.style.width = (KEY_W + this.width) + "px";
    this.inner.style.height = (RULER_H + this.height) + "px";
    for (const [c, w, h] of [[this.roll, this.width, this.height],
                             [this.ruler, this.width, RULER_H],
                             [this.keys, KEY_W, this.height]]) {
      c.width = w * devicePixelRatio; c.height = h * devicePixelRatio;
      c.style.width = w + "px"; c.style.height = h + "px";
    }
    this.redraw();
  }

  _maxTime() {
    let m = 0;
    for (const n of [...this.notes, ...this.draft]) m = Math.max(m, n.time + n.dur);
    return m;
  }

  setNotes(notes) {
    this.notes = notes;
    this.layout();
    if (!this._scrolledToContent && notes.length) {
      this._scrolledToContent = true;
      const topPitch = Math.max(...notes.map(n => n.pitch));
      const botPitch = Math.min(...notes.map(n => n.pitch));
      const midY = this.p2y((topPitch + botPitch) / 2);
      this.scroll.scrollTop = Math.max(0, midY - this.scroll.clientHeight / 2);
    }
  }
  setDraft(notes) { this.draft = notes; this.layout(); }
  setPlayhead(t) { this.playhead = t; this._drawRoll(); }

  snap(t) { const s = this.snapLen; return Math.round(t / s) * s; }
  x2t(x) { return x / this.pxPerSec; }
  t2x(t) { return t * this.pxPerSec; }
  y2p(y) { return 127 - Math.floor(y / this.rowH); }
  p2y(p) { return (127 - p) * this.rowH; }

  noteAt(x, y) {
    const t = this.x2t(x), p = this.y2p(y);
    for (let i = this.notes.length - 1; i >= 0; i--) {
      const n = this.notes[i];
      if (n.pitch === p && t >= n.time && t <= n.time + n.dur) return n;
    }
    return null;
  }

  _bind() {
    const el = this.roll;
    el.addEventListener("contextmenu", e => e.preventDefault());
    el.addEventListener("pointerdown", e => this._down(e));
    el.addEventListener("pointermove", e => this._move(e));
    el.addEventListener("pointerup", e => this._up(e));
    el.addEventListener("dblclick", e => this._dbl(e));
    // bar ruler doubles as the scrub bar: click or drag to move the playhead
    let scrubbing = false, scrubT = 0;
    this.ruler.addEventListener("pointerdown", e => {
      scrubbing = true;
      el_setPointerCapture(this.ruler, e);
      if (this.onSeek) {
        scrubT = Math.max(0, this.x2t(e.offsetX));
        this.onSeek(scrubT, false);
      }
    });
    this.ruler.addEventListener("pointermove", e => {
      if (scrubbing && this.onSeek) {
        scrubT = Math.max(0, this.x2t(e.offsetX));
        this.onSeek(scrubT, false);
      }
    });
    const endScrub = () => {
      if (scrubbing && this.onSeek) this.onSeek(scrubT, true);
      scrubbing = false;
    };
    this.ruler.addEventListener("pointerup", endScrub);
    this.ruler.addEventListener("pointercancel", endScrub);
    this.scroll.addEventListener("wheel", e => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        this.pxPerSec = Math.min(120, Math.max(14, this.pxPerSec * (e.deltaY < 0 ? 1.15 : 0.87)));
        this.layout();
      }
    }, {passive: false});
  }

  _pos(e) {
    const r = this.roll.getBoundingClientRect();
    return {x: e.clientX - r.left, y: e.clientY - r.top};
  }

  _down(e) {
    const {x, y} = this._pos(e);
    el_setPointerCapture(this.roll, e);
    const n = this.noteAt(x, y);
    this._drag = null;

    if (this.tool === "draw") {
      if (n) { this._startMove(e, n); return; }
      const t = Math.max(0, this.snap(this.x2t(x)));
      const pitch = this.y2p(y);
      const note = {id: "new" + Math.random().toString(16).slice(2, 8),
                    time: t, dur: this.snapLen, pitch, instr: 0, vel: 90, src: "human"};
      this.notes.push(note);
      this._drag = {kind: "resize", note, x0: x};
      if (window.AudioEngine) AudioEngine.blip(pitch, 90, 0);
      this.redraw();
      return;
    }
    if (this.tool === "erase") {
      if (n) this._remove(n);
      return;
    }
    // select tool
    if (n) {
      if (!e.shiftKey) this.selected.clear();
      this.selected.add(n.id);
      this._startMove(e, n);
    } else {
      this.selected.clear();
      this.redraw();
    }
  }

  _startMove(e, n) {
    const rightEdge = this.t2x(n.time + n.dur) - this._pos(e).x < 7;
    this._drag = {kind: rightEdge ? "resize" : "move", note: n,
                  t0: n.time, p0: n.pitch, d0: n.dur, x: this._pos(e).x, y: this._pos(e).y};
  }

  _move(e) {
    const {x, y} = this._pos(e);
    this.hover = {x, y};
    if (!this._drag) { this._drawRoll(); return; }
    const d = this._drag, n = d.note;
    if (d.kind === "resize") {
      n.dur = Math.max(this.snapLen / 2, this.snap(this.x2t(x) - n.time) || this.snapLen);
    } else {
      const dt = this.snap(this.x2t(x) - this.x2t(d.x));
      const dp = this.y2p(y) - this.y2p(d.y);
      n.time = Math.max(0, d.t0 + dt);
      n.pitch = Math.min(127, Math.max(0, d.p0 + dp));
    }
    this.redraw();
  }

  _up(e) {
    const d = this._drag;
    if (d && this.onCommit) {
      const n = d.note;
      const changed = d.kind === "resize" ? n.dur !== d.d0
                                          : (n.time !== d.t0 || n.pitch !== d.p0);
      if (changed || d.kind === "resize") this.onCommit(this.notes, "edit");
    }
    this._drag = null;
  }

  _dbl(e) {
    const {x, y} = this._pos(e);
    const n = this.noteAt(x, y);
    if (n) this._remove(n);
  }

  _remove(n) {
    this.notes = this.notes.filter(m => m.id !== n.id);
    this.selected.delete(n.id);
    if (this.onCommit) this.onCommit(this.notes, "edit");
    this.redraw();
  }

  deleteSelected() {
    if (!this.selected.size) return;
    this.notes = this.notes.filter(m => !this.selected.has(m.id));
    this.selected.clear();
    if (this.onCommit) this.onCommit(this.notes, "edit");
    this.redraw();
  }

  // ---------- drawing ----------
  redraw() { this._drawKeys(); this._drawRuler(); this._drawRoll(); }

  _ctx(c) {
    const ctx = c.getContext("2d");
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    return ctx;
  }

  _drawKeys() {
    const ctx = this._ctx(this.keys);
    ctx.fillStyle = "#14161c"; ctx.fillRect(0, 0, KEY_W, this.height);
    for (let p = 0; p < 128; p++) {
      const y = this.p2y(p), black = [1,3,6,8,10].includes(p % 12);
      ctx.fillStyle = black ? "#171a20" : "#e9e9ee";
      ctx.fillRect(0, y, KEY_W - 6, this.rowH);
      ctx.strokeStyle = "#0b0d11";
      ctx.strokeRect(0, y, KEY_W - 6, this.rowH);
      if (p % 12 === 0) {
        ctx.fillStyle = "#667"; ctx.font = "9px sans-serif";
        ctx.fillText("C" + (p / 12 - 1), KEY_W - 22, y + this.rowH - 2);
      }
    }
  }

  _drawRuler() {
    const ctx = this._ctx(this.ruler);
    ctx.fillStyle = "#14161c"; ctx.fillRect(0, 0, this.width, RULER_H);
    ctx.font = "10px sans-serif";
    for (let bar = 0; bar * this.secPerBar * this.pxPerSec < this.width; bar++) {
      const x = bar * this.secPerBar * this.pxPerSec;
      ctx.fillStyle = "#3a4152"; ctx.fillRect(x, 4, 1, RULER_H - 4);
      ctx.fillStyle = "#8b93a3"; ctx.fillText(String(bar + 1), x + 5, 16);
    }
  }

  _drawRoll() {
    const ctx = this._ctx(this.roll);
    const W = this.width, H = this.height, spb = this.secPerBar, pxs = this.pxPerSec;
    ctx.fillStyle = "#0b0d11"; ctx.fillRect(0, 0, W, H);

    // octave shading + rows
    for (let p = 0; p < 128; p++) {
      const y = this.p2y(p);
      if ([1,3,6,8,10].includes(p % 12)) {
        ctx.fillStyle = "rgba(255,255,255,0.025)";
        ctx.fillRect(0, y, W, this.rowH);
      }
      if (p % 12 === 0) {
        ctx.fillStyle = "rgba(255,255,255,0.06)";
        ctx.fillRect(0, y, W, 1);
      }
    }
    // grid: snap divisions faint, bars strong
    const snapW = this.snapLen * pxs;
    for (let x = 0; x < W; x += snapW) {
      ctx.fillStyle = "rgba(255,255,255,0.04)";
      ctx.fillRect(Math.round(x), 0, 1, H);
    }
    for (let x = 0; x < W; x += spb * pxs) {
      ctx.fillStyle = "rgba(140,160,220,0.22)";
      ctx.fillRect(Math.round(x), 0, 1, H);
    }

    const drawNote = (n, color, ghost) => {
      const x = this.t2x(n.time), y = this.p2y(n.pitch);
      const w = Math.max(3, n.dur * pxs);
      ctx.globalAlpha = ghost ? 0.45 : 0.92;
      ctx.fillStyle = color;
      roundRect(ctx, x + 0.5, y + 1, w - 1, this.rowH - 2, 3);
      ctx.fill();
      if (this.selected.has(n.id)) {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1.5;
        roundRect(ctx, x + 0.5, y + 1, w - 1, this.rowH - 2, 3);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    };

    for (const n of this.notes)
      drawNote(n, n.src === "ai" ? "#f78d4f" : "#4f8ff7", false);
    for (const n of this.draft)
      drawNote(n, "#b48ef7", true);

    // playhead
    if (this.playhead != null) {
      const x = this.t2x(this.playhead);
      ctx.fillStyle = "rgba(180,142,247,0.9)";
      ctx.fillRect(x, 0, 1.5, H);
    }
    // hover crosshair for draw tool
    if (this.hover && this.tool === "draw" && !this._drag) {
      ctx.fillStyle = "rgba(255,255,255,0.05)";
      ctx.fillRect(0, Math.floor(this.hover.y / this.rowH) * this.rowH, W, this.rowH);
    }
  }
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function el_setPointerCapture(el, e) {
  try { el.setPointerCapture(e.pointerId); } catch (_) {}
}
