"""Session state: the score, undo history, V0-V3 snapshots, and the JSONL
event log that makes a co-writing session reproducible as study data."""

import json
import os
import time
import uuid

DATA_DIR = os.environ.get("COCREATION_DATA_DIR",
                          os.path.join(os.path.expanduser("~"), ".cocreation"))
SNAPSHOT_LABELS = ["V0", "V1", "V2", "V3"]
MAX_UNDO = 20


def demo_seed_notes():
    """A simple 4-bar C-major melody at 120bpm so a new user (or study
    participant) can start immediately. 4/4 at 120bpm = 2s per bar."""
    melody = [
        (0.0, 0.5, 60), (0.5, 0.5, 62), (1.0, 0.5, 64), (1.5, 0.5, 65),   # bar 1
        (2.0, 1.0, 67), (3.0, 0.5, 65), (3.5, 0.5, 64),                  # bar 2
        (4.0, 0.5, 62), (4.5, 0.5, 64), (5.0, 0.5, 65), (5.5, 0.5, 62),  # bar 3
        (6.0, 2.0, 60),                                                  # bar 4
    ]
    return [{
        "id": uuid.uuid4().hex[:10],
        "time": t, "dur": d, "pitch": p, "instr": 0, "vel": 90, "src": "human",
    } for t, d, p in melody]


class Session:
    def __init__(self, session_id=None, name="Untitled session", tempo=120.0):
        self.id = session_id or uuid.uuid4().hex[:8]
        self.name = name
        self.tempo = float(tempo)
        self.time_sig = {"num": 4, "den": 4}
        self.notes = []
        self.snapshots = {}          # label -> {"label", "created_at", "notes"}
        self.next_snapshot = 0
        self.created_at = time.time()
        self._undo = []
        self._redo = []
        self.dir = os.path.join(DATA_DIR, "sessions", self.id)
        self.log_path = os.path.join(self.dir, "events.jsonl")
        self.state_path = os.path.join(self.dir, "session.json")
        os.makedirs(self.dir, exist_ok=True)

    # ---- timing helpers -------------------------------------------------
    @property
    def seconds_per_bar(self):
        return self.time_sig["num"] * (4.0 / self.time_sig["den"]) * (60.0 / self.tempo)

    # ---- event log --------------------------------------------------------
    def log(self, event_type, **data):
        rec = {"t": round(time.time() - self.created_at, 3),
               "type": event_type, **data}
        with open(self.log_path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")

    # ---- score mutation ---------------------------------------------------
    def set_notes(self, notes, actor="human", reason="edit"):
        """Replace the whole score; records an undo step and logs a compact
        diff so the study log captures what actually changed."""
        old = {n["id"]: n for n in self.notes}
        new = {n["id"]: n for n in notes}
        added = [n for nid, n in new.items() if nid not in old]
        removed = [n for nid, n in old.items() if nid not in new]
        changed = [n for nid, n in new.items()
                   if nid in old and n != old[nid]]

        self._undo.append(self.notes)
        self._undo = self._undo[-MAX_UNDO:]
        self._redo = []
        self.notes = notes
        self.log("score", actor=actor, reason=reason,
                 added=len(added), removed=len(removed), changed=len(changed),
                 total=len(notes),
                 added_notes=added, removed_ids=[n["id"] for n in removed])
        self.save()
        return {"added": len(added), "removed": len(removed),
                "changed": len(changed)}

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(self.notes)
        self.notes = self._undo.pop()
        self.log("undo", total=len(self.notes))
        self.save()
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(self.notes)
        self.notes = self._redo.pop()
        self.log("redo", total=len(self.notes))
        self.save()
        return True

    # ---- snapshots ---------------------------------------------------------
    def snapshot(self, label=None):
        if label is None:
            if self.next_snapshot >= len(SNAPSHOT_LABELS):
                label = f"V{self.next_snapshot}"
            else:
                label = SNAPSHOT_LABELS[self.next_snapshot]
        self.next_snapshot += 1
        snap = {"label": label, "created_at": time.time(),
                "n_notes": len(self.notes),
                "notes": [dict(n) for n in self.notes],
                "tempo": self.tempo, "time_sig": self.time_sig}
        self.snapshots[label] = snap
        self.log("snapshot", label=label, n_notes=len(self.notes))
        self.save()
        return snap

    # ---- persistence -------------------------------------------------------
    def save(self):
        tmp = self.state_path + ".tmp"
        data = self.to_dict(include_notes=True)
        data["snapshots_full"] = self.snapshots  # full note data; API keeps summaries
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.state_path)

    def to_dict(self, include_notes=True):
        d = {
            "id": self.id, "name": self.name, "tempo": self.tempo,
            "time_sig": self.time_sig,
            "seconds_per_bar": self.seconds_per_bar,
            "snapshots": [{"label": s["label"], "created_at": s["created_at"],
                           "n_notes": s["n_notes"]}
                          for s in self.snapshots.values()],
            "can_undo": bool(self._undo),
            "can_redo": bool(self._redo),
            "next_snapshot": self.next_snapshot,
        }
        if include_notes:
            d["notes"] = self.notes
        return d

    @classmethod
    def load_latest(cls):
        root = os.path.join(DATA_DIR, "sessions")
        if not os.path.isdir(root):
            return None
        candidates = []
        for sid in os.listdir(root):
            path = os.path.join(root, sid, "session.json")
            if os.path.exists(path):
                candidates.append((os.path.getmtime(path), path))
        if not candidates:
            return None
        path = max(candidates)[1]
        try:
            with open(path) as fh:
                data = json.load(fh)
            sess = cls(session_id=data["id"], name=data["name"],
                       tempo=data["tempo"])
            sess.time_sig = data.get("time_sig", {"num": 4, "den": 4})
            sess.notes = data.get("notes", [])
            sess.snapshots = data.get("snapshots_full", {})
            sess.next_snapshot = data.get("next_snapshot", 0)
            return sess
        except Exception:
            return None
