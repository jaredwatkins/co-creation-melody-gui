/* App wiring: state sync with the FastAPI backend, transport, generation
   flow (draft -> accept/discard), snapshots, import/export, MIDI-in. */
"use strict";

const $ = id => document.getElementById(id);
const api = {
  async get(path) { const r = await fetch(path); return r.json(); },
  async send(method, path, body) {
    const r = await fetch(path, {method,
      headers: {"Content-Type": "application/json"},
      body: body === undefined ? undefined : JSON.stringify(body)});
    return r.json();
  },
};

const state = {
  session: null,
  notes: [],
  draft: [],          // uncommitted AI notes
  job: null,
  model: {loaded: false},
  dirty: false,
};

const roll = new PianoRoll($("roll-scroll"));

// ---------- state sync ----------
let commitTimer = null;
function commit(notes, reason) {
  state.dirty = true;
  clearTimeout(commitTimer);
  commitTimer = setTimeout(async () => {
    await api.send("PUT", "/api/score", {notes, reason});
    state.dirty = false;
    refreshLogTail();
  }, 350);
}
roll.onCommit = commit;
roll.onSeek = t => { seekTo = t; setPlayhead(t); };

let seekTo = 0;
function applySession(sess) {
  state.session = sess;
  state.notes = sess.notes || [];
  roll.secPerBar = sess.seconds_per_bar;
  roll.setNotes(state.notes);
  $("session-name").value = sess.name;
  $("tempo").value = sess.tempo;
  $("undo").disabled = !sess.can_undo;
  renderSnapshots();
}

function setBanner(kind, text) {
  const b = $("turn-banner");
  b.className = "turn " + kind;
  b.textContent = text;
}

// ---------- model status ----------
async function pollModel() {
  const m = await api.get("/api/model/status");
  state.model = m;
  const chip = $("model-chip");
  if (m.loaded) {
    chip.className = "chip ready";
    chip.textContent = `model ready · ${m.device}`;
  } else if (m.error) {
    chip.className = "chip error";
    chip.textContent = "model failed to load";
    chip.title = m.error;
  } else {
    chip.className = "chip loading";
    chip.textContent = m.loading ? "model loading…" : "model not loaded";
    setTimeout(pollModel, 2000);
  }
  $("generate").disabled = !m.loaded;
}

// ---------- transport ----------
let playStartScore = null;
function setPlayhead(t) {
  roll.setPlayhead(t);
  const m = Math.floor(t / 60), s = t % 60;
  $("pos").textContent = `${m}:${s.toFixed(1).padStart(4, "0")}`;
  $("pos-bar").textContent = "bar " + (Math.floor(t / roll.secPerBar) + 1);
}

$("play").onclick = () => {
  if (AudioEngine.playing) { AudioEngine.stop(); $("play").textContent = "▶"; return; }
  const t = seekTo || 0;
  if (AudioEngine.play(allNotes(), t)) {
    $("play").textContent = "⏸";
    tickPlayhead();
    logEvent("play", {from: t});
  }
};
$("stop").onclick = () => {
  AudioEngine.stop();
  $("play").textContent = "▶";
  setPlayhead(0); seekTo = 0;
};

function allNotes() { return [...state.notes, ...state.draft]; }

function tickPlayhead() {
  if (!AudioEngine.playing) { $("play").textContent = "▶"; return; }
  const t = AudioEngine.playhead();
  if (t == null) { $("play").textContent = "▶"; setPlayhead(0); return; }
  setPlayhead(t); seekTo = t;
  requestAnimationFrame(tickPlayhead);
}

// ---------- tools ----------
document.querySelectorAll(".tool").forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll(".tool").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    roll.tool = btn.dataset.tool;
  };
});
$("snap").onchange = e => { roll.snapDiv = +e.target.value; roll.redraw(); };
$("undo").onclick = doUndo;

async function doUndo() {
  if (state.draft.length) {   // undo first clears the AI draft
    state.draft = [];
    roll.setDraft([]);
    $("draft-actions").classList.add("hidden");
    setBanner("human", "Your turn — sketch the melody");
    return;
  }
  const r = await api.send("POST", "/api/undo");
  if (r.ok) applySession(r.session);
}

// ---------- generation ----------
$("generate").onclick = async () => {
  const body = {
    bars: +$("gen-bars").value || 2,
    top_p: +$("gen-topp").value || 0.98,
    instruments: $("gen-match").checked ? "match" : "free",
  };
  const r = await api.send("POST", "/api/generate", body);
  if (r.detail) { setBanner("ai", r.detail); return; }
  state.job = r.job_id;
  $("generate").disabled = true;
  $("gen-progress").classList.remove("hidden");
  setBanner("ai", "AI is composing…");
  pollJob();
};

async function pollJob() {
  const j = await api.get("/api/jobs/" + state.job);
  const pct = Math.min(99, Math.round(100 * j.progress / Math.max(1, j.total)));
  const bar = document.querySelector("#gen-progress .bar");
  bar.style.setProperty("--p", pct + "%");
  document.querySelector("#gen-progress span").textContent =
    `${j.elapsed}s elapsed · ${pct}%`;
  if (j.status === "running") { setTimeout(pollJob, 800); return; }
  $("gen-progress").classList.add("hidden");
  $("generate").disabled = false;
  if (j.status === "error") {
    setBanner("ai", "generation failed: " + (j.error || "?"));
    return;
  }
  const newNotes = (j.result && j.result.notes) || [];
  if (!newNotes.length) {
    setBanner("human", "AI returned nothing — try again");
    return;
  }
  state.draft = newNotes;
  roll.setDraft(state.draft);
  $("draft-actions").classList.remove("hidden");
  setBanner("draft", `AI draft ready — ${newNotes.length} notes. Keep or discard?`);
  logEvent("draft_ready", {job_id: state.job, n_notes: newNotes.length});
}

$("accept").onclick = async () => {
  const merged = [...state.notes, ...state.draft];
  state.draft = [];
  roll.setDraft([]);
  $("draft-actions").classList.add("hidden");
  setBanner("human", "Your turn — sketch the melody");
  await api.send("PUT", "/api/score",
                 {notes: merged, reason: "accept_generation", job_id: state.job});
  state.notes = merged;
  roll.setNotes(state.notes);
  refreshLogTail();
};

$("discard").onclick = async () => {
  state.draft = [];
  roll.setDraft([]);
  $("draft-actions").classList.add("hidden");
  setBanner("human", "Your turn — sketch the melody");
  await api.send("POST", "/api/log",
                 {type: "discard_generation", data: {job_id: state.job}});
  refreshLogTail();
};

// ---------- snapshots ----------
document.querySelectorAll("[data-snap]").forEach(btn => {
  btn.onclick = async () => {
    await api.send("POST", "/api/snapshots?label=" + btn.textContent);
    const s = await api.get("/api/state");
    applySession(s.session);
    refreshLogTail();
  };
});

function renderSnapshots() {
  const ul = $("snap-list");
  ul.innerHTML = "";
  for (const s of (state.session.snapshots || [])) {
    const li = document.createElement("li");
    const when = new Date(s.created_at * 1000).toLocaleTimeString();
    li.innerHTML = `<span class="lab">${s.label}</span> ${s.n_notes} notes · ${when}
      <a href="/api/snapshots/${s.label}/midi" title="download .mid">mid</a>
      <a href="#" data-restore="${s.label}">restore</a>`;
    ul.appendChild(li);
  }
  ul.querySelectorAll("[data-restore]").forEach(a => {
    a.onclick = async e => {
      e.preventDefault();
      const r = await api.send("POST", `/api/snapshots/${a.dataset.restore}/restore`);
      if (r.ok) applySession(r.session);
    };
  });
}

// ---------- import / export ----------
$("import-btn").onclick = () => $("import-file").click();
$("import-file").onchange = async e => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  const r = await (await fetch("/api/import", {method: "POST", body: fd})).json();
  if (r.notes) {
    const merged = [...state.notes, ...r.notes];
    await api.send("PUT", "/api/score", {notes: merged, reason: "import"});
    state.notes = merged;
    roll.setNotes(merged);
    roll.layout();
  }
  e.target.value = "";
};
$("export-midi").onclick = () => {
  logEvent("export_click", {});
  location.href = "/api/export/midi";
};
$("export-log").onclick = () => window.open("/api/export/log", "_blank");

$("new-session").onclick = async () => {
  if (state.notes.length &&
      !confirm("Start a new session? Current notes will stay saved in the previous session's folder."))
    return;
  const r = await api.send("POST", "/api/session/new",
                           {name: "Untitled session", tempo: +$("tempo").value || 120, seed: "demo"});
  state.draft = [];
  roll.setDraft([]);
  applySession(r.session);
  setBanner("human", "Your turn — sketch the melody");
};

$("session-name").onchange = e =>
  api.send("POST", "/api/settings", {name: e.target.value});
$("tempo").onchange = async e => {
  const r = await api.send("POST", "/api/settings", {tempo: +e.target.value});
  applySession(r.session);
};

// ---------- MIDI in ----------
$("midi-in").onchange = async e => {
  if (!e.target.checked || !navigator.requestMIDIAccess) {
    $("midi-status").textContent = e.target.checked ? "unsupported" : "";
    return;
  }
  try {
    const access = await navigator.requestMIDIAccess();
    for (const input of access.inputs.values()) {
      input.onmidimessage = msg => {
        const [st, note, vel] = msg.data;
        if ((st & 0xf0) === 0x90 && vel > 0) {
          const t = roll.snap(seekTo || 0);
          const n = {id: "midi" + Math.random().toString(16).slice(2, 8),
                     time: t, dur: roll.snapLen, pitch: note, instr: 0,
                     vel, src: "human"};
          state.notes.push(n);
          AudioEngine.blip(note, vel, 0);
          seekTo = t + roll.snapLen;
          roll.setNotes(state.notes);
          commit(state.notes, "midi_in");
        }
      };
    }
    $("midi-status").textContent = access.inputs.size ? "listening" : "no device";
  } catch (err) {
    $("midi-status").textContent = "denied";
    e.target.checked = false;
  }
};

// ---------- session log tail ----------
async function refreshLogTail() {
  const txt = await (await fetch("/api/export/log")).text();
  const lines = txt.trim().split("\n").slice(-10);
  $("log-tail").textContent = lines.join("\n");
}

function logEvent(type, data) {
  api.send("POST", "/api/log", {type, data}).then(refreshLogTail);
}

// ---------- keyboard ----------
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  const k = e.key.toLowerCase();
  if (k === "d") setTool("draw");
  else if (k === "s") setTool("select");
  else if (k === "e") setTool("erase");
  else if (k === " ") { e.preventDefault(); $("play").click(); }
  else if (k === "delete" || k === "backspace") roll.deleteSelected();
  else if ((e.ctrlKey || e.metaKey) && k === "z") { e.preventDefault(); doUndo(); }
});
function setTool(t) {
  document.querySelector(`[data-tool="${t}"]`).click();
}

// ---------- boot ----------
(async function init() {
  const s = await api.get("/api/state");
  applySession(s.session);
  if (s.fresh) {
    // very first run: seed a demo melody so there's something to continue
    const r = await api.send("POST", "/api/session/new",
                             {name: s.session.name, tempo: s.session.tempo, seed: "demo"});
    applySession(r.session);
  }
  await api.send("POST", "/api/model/load");
  pollModel();
  refreshLogTail();
  setBanner("human", "Your turn — sketch the melody");
})();
