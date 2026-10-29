"""Unit tests for the note/event/MIDI conversion layer — no model required."""

import io
import json
import os

import mido
import pytest

from cocreation.engine import (diff_events, events_to_notes,
                               midi_bytes_to_notes, notes_to_events,
                               notes_to_midi_bytes)
from cocreation.store import Session, demo_seed_notes


@pytest.fixture
def notes():
    return [
        {"id": "a", "time": 0.0, "dur": 0.5, "pitch": 60, "instr": 0,
         "vel": 90, "src": "human"},
        {"id": "b", "time": 0.5, "dur": 0.5, "pitch": 64, "instr": 0,
         "vel": 80, "src": "human"},
        {"id": "c", "time": 1.0, "dur": 1.0, "pitch": 67, "instr": 128,
         "vel": 100, "src": "ai"},
    ]


def test_notes_events_roundtrip(notes):
    events = notes_to_events(notes)
    assert len(events) == 9  # 3 events x 3 tokens
    back = events_to_notes(events, src="human")
    by_pitch = {n["pitch"]: n for n in back}
    for orig in notes:
        got = by_pitch[orig["pitch"]]
        assert got["time"] == pytest.approx(orig["time"], abs=0.02)
        assert got["dur"] == pytest.approx(orig["dur"], abs=0.02)
        assert got["instr"] == orig["instr"]


def test_notes_midi_roundtrip(notes):
    data = notes_to_midi_bytes(notes)
    assert data[:4] == b"MThd"
    back = midi_bytes_to_notes(data)
    by_pitch = {n["pitch"]: n for n in back}
    assert set(by_pitch) == {60, 64, 67}
    for orig in notes:
        got = by_pitch[orig["pitch"]]
        assert got["time"] == pytest.approx(orig["time"], abs=0.02)
        assert got["dur"] == pytest.approx(orig["dur"], abs=0.02)
        assert got["instr"] == orig["instr"]
        assert got["vel"] == orig["vel"]


def test_midi_velocity_preserved():
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mid.add_track()
    tr.append(mido.Message("note_on", note=72, velocity=111, time=0))
    tr.append(mido.Message("note_off", note=72, velocity=0, time=480))
    buf = io.BytesIO()
    mid.save(file=buf)
    (n,) = midi_bytes_to_notes(buf.getvalue())
    assert n["pitch"] == 72
    assert n["vel"] == 111


def test_diff_events(notes):
    before = notes_to_events(notes)
    after = before + [before[-3] + 200, before[-2], before[-1]]
    new = diff_events(before, after)
    assert len(new) == 3


def test_session_log_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("COCREATION_DATA_DIR", str(tmp_path))
    # store.DATA_DIR was read at import time — patch the module attr too
    import cocreation.store as store
    monkeypatch.setattr(store, "DATA_DIR", str(tmp_path))

    sess = Session()
    sess.set_notes(demo_seed_notes(), reason="seed")
    snap = sess.snapshot()
    assert snap["label"] == "V0"
    assert snap["n_notes"] == len(sess.notes)

    sess.set_notes([], reason="clear")
    sess.undo()
    assert len(sess.notes) == snap["n_notes"]

    with open(sess.log_path) as fh:
        events = [json.loads(l) for l in fh]
    types = [e["type"] for e in events]
    assert types[:3] == ["score", "snapshot", "score"] or "score" in types
    assert "undo" in types

    with open(sess.state_path) as fh:
        saved = json.load(fh)
    assert saved["notes"] == sess.notes
