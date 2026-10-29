"""Model engine: converts between app note dicts, anticipation event tokens,
and MIDI, and wraps model loading + background generation.

Note dict shape (the unit the whole app works in):

    {"id": str, "time": float seconds, "dur": float seconds,
     "pitch": int 0-127, "instr": int 0-128 (128 = drums),
     "vel": int 1-127, "src": "human" | "ai"}
"""

import io
import threading
import time
import uuid

import mido

from anticipation import ops
from anticipation.config import MAX_INSTR, TIME_RESOLUTION
from anticipation.convert import compound_to_events, midi_to_events
from anticipation.vocab import (ANOTE_OFFSET, CONTROL_OFFSET, DUR_OFFSET,
                                NOTE_OFFSET, REST, SEPARATOR, TIME_OFFSET)

DEFAULT_MODEL_ID = "stanford-crfm/music-small-800k"
TICKS_PER_SECOND = TIME_RESOLUTION  # 100 ticks/s at the token level


def _new_id():
    return uuid.uuid4().hex[:10]


def notes_to_events(notes):
    """App notes -> anticipation event-token list (model input)."""
    compound = []
    for n in sorted(notes, key=lambda x: (x["time"], x["pitch"])):
        compound += [
            int(round(n["time"] * TIME_RESOLUTION)),
            max(1, int(round(n["dur"] * TIME_RESOLUTION))),
            int(n["pitch"]),
            int(n.get("instr", 0)),
            int(n.get("vel", 80)),
        ]
    return compound_to_events(compound)


def events_to_notes(events, src):
    """Anticipation event tokens -> app notes. Velocity is not modeled by the
    transformer, so generated/imported notes get a default velocity."""
    notes = []
    for t, d, n in zip(events[0::3], events[1::3], events[2::3]):
        if n in (SEPARATOR, REST) or n >= CONTROL_OFFSET:
            continue
        note = n - NOTE_OFFSET
        notes.append({
            "id": _new_id(),
            "time": (t - TIME_OFFSET) / TIME_RESOLUTION,
            "dur": (d - DUR_OFFSET) / TIME_RESOLUTION,
            "pitch": note % 128,
            "instr": note // 128,
            "vel": 72,
            "src": src,
        })
    return notes


def notes_to_midi(notes, tempo=500000):
    """App notes -> mido.MidiFile, preserving per-note velocity and
    instrument program changes (unlike the token path, which drops velocity)."""
    mid = mido.MidiFile(ticks_per_beat=TIME_RESOLUTION // 2)
    track = mid.add_track()
    track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))

    # map instrument codes onto MIDI channels; drums always channel 9
    instr_channels = {}
    next_channel = 0

    def channel_for(instr):
        nonlocal next_channel
        if instr == 128:
            return 9
        if instr not in instr_channels:
            if next_channel >= 16:  # ran out of channels: reuse channel 0
                instr_channels[instr] = 0
            else:
                if next_channel == 9:
                    next_channel += 1
                instr_channels[instr] = next_channel
                next_channel += 1
        return instr_channels[instr]

    abs_msgs = []  # (tick, order, message-builder)
    for n in notes:
        instr = int(n.get("instr", 0))
        ch = channel_for(instr)
        on = int(round(n["time"] * TIME_RESOLUTION))
        off = max(on + 1, int(round((n["time"] + n["dur"]) * TIME_RESOLUTION)))
        pitch = int(n["pitch"])
        vel = int(n.get("vel", 80))
        if ch != 9:
            abs_msgs.append((on, 0, mido.Message(
                "program_change", program=instr, channel=ch, time=0)))
        abs_msgs.append((on, 1, mido.Message(
            "note_on", note=pitch, velocity=vel, channel=ch, time=0)))
        abs_msgs.append((off, 2, mido.Message(
            "note_off", note=pitch, velocity=0, channel=ch, time=0)))

    abs_msgs.sort(key=lambda m: (m[0], m[1]))
    last = 0
    for tick, _, msg in abs_msgs:
        msg.time = max(0, tick - last)
        last = tick
        track.append(msg)
    return mid


def notes_to_midi_bytes(notes):
    mid = notes_to_midi(notes)
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


def midi_bytes_to_notes(data, src="human"):
    """Uploaded MIDI -> app notes. Goes through anticipation's own parser so
    the imported score is in exactly the token space the model sees; velocities
    are re-read from the raw file afterwards so they stay faithful."""
    mid = mido.MidiFile(file=io.BytesIO(data))
    events = midi_to_events(mid)
    notes = events_to_notes(events, src)

    # recover real velocities keyed on (pitch, onset-tick)
    vel = {}
    time_s = 0.0
    open_notes = {}
    tempo = 500000
    tpb = mid.ticks_per_beat or 480
    for msg in mido.merge_tracks(mid.tracks):
        if msg.type == "set_tempo":
            tempo = msg.tempo
        time_s += mido.tick2second(msg.time, tpb, tempo)
        if msg.type == "note_on" and msg.velocity > 0:
            open_notes.setdefault((msg.note, msg.channel), []).append(
                (time_s, msg.velocity))
        elif msg.type in ("note_off", "note_on"):
            key = (msg.note, msg.channel)
            if open_notes.get(key):
                onset, v = open_notes[key].pop(0)
                vel[(msg.note, round(onset * TIME_RESOLUTION))] = v
    for n in notes:
        key = (n["pitch"], round(n["time"] * TIME_RESOLUTION))
        if key in vel:
            n["vel"] = vel[key]
    return notes


def _event_triplets(events):
    return [tuple(events[i:i + 3]) for i in range(0, len(events) - len(events) % 3, 3)]


def diff_events(before, after):
    """Multiset subtraction of event triplets: which triplets in `after` were
    not in `before`. Used to separate freshly generated tokens from echoed
    human control tokens in a generation result."""
    remaining = list(_event_triplets(before))
    out = []
    for trip in _event_triplets(after):
        try:
            remaining.remove(trip)
        except ValueError:
            out.extend(trip)
    return out


class JobProgress:
    """tqdm stand-in injected into anticipation.sample so a generation job's
    progress can be polled over HTTP."""

    def __init__(self, job):
        self.job = job

    def __call__(self, iterable, *args, **kwargs):
        self.total = len(iterable)
        self.job["total"] = self.total
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, dt):
        self.job["progress"] = self.job.get("progress", 0) + dt


class ModelEngine:
    """Lazy-loading singleton wrapper around the HF checkpoint. Generation
    runs on a worker thread; status is polled via the jobs dict."""

    def __init__(self, model_id=DEFAULT_MODEL_ID):
        self.model_id = model_id
        self.model = None
        self.device = "cpu"
        self.loading = False
        self.load_error = None
        self.jobs = {}
        self._lock = threading.Lock()

    def status(self):
        return {
            "model_id": self.model_id,
            "loaded": self.model is not None,
            "loading": self.loading,
            "device": self.device,
            "error": self.load_error,
        }

    def pick_device(self):
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def load(self, background=True):
        if self.model is not None or self.loading:
            return
        self.loading = True
        self.load_error = None
        if background:
            threading.Thread(target=self._load_impl, daemon=True).start()
        else:
            self._load_impl()

    def _load_impl(self):
        try:
            import torch
            from transformers import AutoModelForCausalLM
            self.device = self.pick_device()
            self.model = AutoModelForCausalLM.from_pretrained(self.model_id).to(self.device)
            self.model.eval()
            torch.set_num_threads(max(1, torch.get_num_threads()))
        except Exception as exc:  # surfaced through /api/model/status
            self.load_error = str(exc)
        finally:
            self.loading = False

    def generate(self, job_id, notes, start_time, end_time, top_p=0.98,
                 instruments=None):
        """Run generation on a thread. `instruments`: None = free; a set of
        instr codes = constrain output to those timbres."""
        import anticipation.sample as sample
        from anticipation.vocab import MAX_NOTE, NOTE_OFFSET as NO

        job = self.jobs[job_id]
        try:
            inputs = notes_to_events(notes)

            original_tqdm = sample.tqdm
            original_instr = sample.instr_logits

            if instruments:
                allowed = set(int(i) for i in instruments)

                def restricted(logits, full_history):
                    for instr in range(MAX_INSTR):
                        if instr not in allowed:
                            lo = NO + instr * 128
                            logits[lo:lo + 128] = -float("inf")
                    return logits
                sample.instr_logits = restricted

            sample.tqdm = JobProgress(job)
            try:
                out = sample.generate(
                    self.model, start_time=start_time, end_time=end_time,
                    inputs=inputs, top_p=top_p)
            finally:
                sample.tqdm = original_tqdm
                sample.instr_logits = original_instr

            new_events = diff_events(inputs, out)
            job["result"] = {"notes": events_to_notes(new_events, src="ai")}
            job["status"] = "done"
        except Exception as exc:
            job["status"] = "error"
            job["error"] = str(exc)
        finally:
            job["finished_at"] = time.time()

    def start_generation(self, notes, start_time, end_time, top_p=0.98,
                         instruments=None):
        if self.model is None:
            raise RuntimeError("model is not loaded yet")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("a generation is already running")
        job_id = uuid.uuid4().hex[:12]
        self.jobs[job_id] = {
            "id": job_id, "status": "running", "progress": 0,
            "total": max(1, int(round((end_time - start_time) * TIME_RESOLUTION))),
            "started_at": time.time(),
        }

        def run():
            try:
                self.generate(job_id, notes, start_time, end_time, top_p, instruments)
            finally:
                self._lock.release()

        threading.Thread(target=run, daemon=True).start()
        return job_id

    def job_status(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            return None
        return {
            "id": job_id,
            "status": job["status"],
            "progress": job.get("progress", 0),
            "total": job.get("total", 1),
            "elapsed": round(time.time() - job["started_at"], 1),
            "result": job.get("result"),
            "error": job.get("error"),
        }
