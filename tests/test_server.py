"""API smoke tests — exercises the FastAPI surface without loading the model."""

import pytest
from fastapi.testclient import TestClient

import cocreation.store as store
from cocreation.engine import ModelEngine
from cocreation.server import create_app
from cocreation.store import Session, demo_seed_notes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", str(tmp_path))
    session = Session(session_id="test1234")
    app = create_app(session=session, engine=ModelEngine())
    return TestClient(app)


def test_state_and_score(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    assert r.json()["session"]["id"] == "test1234"

    notes = demo_seed_notes()
    r = client.put("/api/score", json={"notes": notes})
    assert r.status_code == 200
    assert r.json()["diff"]["added"] == len(notes)

    r = client.get("/api/state")
    assert len(r.json()["session"]["notes"]) == len(notes)

    r = client.post("/api/undo")
    assert r.json()["session"]["notes"] == []


def test_generate_requires_loaded_model(client):
    r = client.post("/api/generate", json={"bars": 2})
    assert r.status_code == 409
    assert "loading" in r.json()["detail"]


def test_snapshot_and_export(client):
    client.put("/api/score", json={"notes": demo_seed_notes()})
    r = client.post("/api/snapshots")
    assert r.json()["snapshot"]["label"] == "V0"

    r = client.get("/api/snapshots/V0/midi")
    assert r.status_code == 200
    assert r.content[:4] == b"MThd"

    r = client.get("/api/export/midi")
    assert r.status_code == 200
    assert r.content[:4] == b"MThd"

    r = client.get("/api/export/log")
    assert r.status_code == 200
    assert b"score" in r.content


def test_import_midi(client):
    from cocreation.engine import notes_to_midi_bytes
    data = notes_to_midi_bytes(demo_seed_notes())
    r = client.post("/api/import", files={"file": ("seed.mid", data)})
    assert r.status_code == 200
    assert len(r.json()["notes"]) == len(demo_seed_notes())


def test_new_session_demo_seed(client):
    r = client.post("/api/session/new", json={"seed": "demo"})
    s = r.json()["session"]
    assert len(s["notes"]) > 0
    assert s["snapshots"][0]["label"] == "V0"


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Co-Create" in r.text
