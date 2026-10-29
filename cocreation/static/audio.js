/* WebAudio playback for the score — no native audio deps, so the packaged
   app stays self-contained. A light synth: pitched notes get a waveform by
   instrument family, drum channel gets filtered noise. */
"use strict";

const AudioEngine = {
  ctx: null,
  master: null,
  playing: false,
  sources: [],
  startCtxTime: 0,
  startOffset: 0,     // score seconds the current playback started at
  endSec: 0,

  ensure() {
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      this.master = this.ctx.createGain();
      this.master.gain.value = 0.25;
      this.master.connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended") this.ctx.resume();
    return this.ctx;
  },

  _wave(instr) {
    if (instr === 128) return null;               // drums -> noise
    if (instr >= 32 && instr <= 39) return "sawtooth";      // bass
    if (instr >= 40 && instr <= 55) return "sawtooth";      // strings / ensemble
    if (instr >= 56 && instr <= 79) return "square";        // brass / leads
    return "triangle";                                       // keys & default
  },

  _envGain(t, dur, vel) {
    const g = this.ctx.createGain();
    const peak = 0.5 * (vel / 127) + 0.05;
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(peak, t + 0.008);
    g.gain.exponentialRampToValueAtTime(peak * 0.6, t + Math.min(0.4, dur));
    g.gain.setValueAtTime(Math.max(0.0001, peak * 0.6), t + dur);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur + 0.15);
    return g;
  },

  _noiseBuffer() {
    if (this._noise) return this._noise;
    const len = this.ctx.sampleRate * 0.5;
    this._noise = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = this._noise.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    return this._noise;
  },

  scheduleNote(n, when) {
    const ctx = this.ctx;
    const vel = n.vel || 80;
    if (n.instr === 128) {
      const src = ctx.createBufferSource();
      src.buffer = this._noiseBuffer();
      const filt = ctx.createBiquadFilter();
      filt.type = "bandpass";
      filt.frequency.value = 200 + n.pitch * 60;
      filt.Q.value = 1.2;
      const g = this._envGain(when, Math.min(n.dur, 0.3), vel);
      src.connect(filt); filt.connect(g); g.connect(this.master);
      src.start(when); src.stop(when + Math.min(n.dur, 0.3) + 0.2);
      this.sources.push(src);
      return;
    }
    const f = 440 * Math.pow(2, (n.pitch - 69) / 12);
    const osc = ctx.createOscillator();
    osc.type = this._wave(n.instr);
    osc.frequency.value = f;
    const g = this._envGain(when, n.dur, vel);
    osc.connect(g); g.connect(this.master);
    osc.start(when); osc.stop(when + n.dur + 0.2);
    this.sources.push(osc);
  },

  play(notes, fromSec) {
    this.ensure();
    this.stop();
    const t0 = this.ctx.currentTime + 0.06;
    this.startCtxTime = t0;
    this.startOffset = fromSec;
    this.endSec = fromSec;
    let n = 0;
    for (const note of notes) {
      if (note.time + note.dur <= fromSec) continue;
      const onset = t0 + Math.max(0, note.time - fromSec);
      const dur = note.time < fromSec ? note.time + note.dur - fromSec : note.dur;
      this.scheduleNote({...note, dur}, onset);
      this.endSec = Math.max(this.endSec, note.time + note.dur);
      n++;
    }
    if (n === 0) return false;
    this.playing = true;
    return true;
  },

  stop() {
    for (const s of this.sources) { try { s.stop(); } catch (e) {} }
    this.sources = [];
    this.playing = false;
  },

  playhead() {
    if (!this.playing || !this.ctx) return null;
    const t = this.startOffset + this.ctx.currentTime - this.startCtxTime;
    if (t >= this.endSec + 0.3) { this.playing = false; return this.endSec; }
    return t;
  },

  blip(pitch, vel = 90, instr = 0) {
    this.ensure();
    this.scheduleNote({pitch, vel, instr, dur: 0.25}, this.ctx.currentTime + 0.01);
  },
};
