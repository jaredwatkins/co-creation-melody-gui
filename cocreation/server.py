"""FastAPI app exposing the co-creation session to the browser UI."""

import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               Response)
from pydantic import BaseModel, Field

from .engine import (DEFAULT_MODEL_ID, ModelEngine, midi_bytes_to_notes,
                     notes_to_midi_bytes)
from .store import SNAPSHOT_LABELS, Session

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class ScoreUpdate(BaseModel):
    notes: list
    reason: str = "edit"
    job_id: str | None = None


class GenerateRequest(BaseModel):
    start_bar: int | None = None
    bars: int = Field(default=2, ge=1, le=32)
    top_p: float = Field(default=0.98, gt=0.0, le=1.0)
    instruments: str = "match"  # 'match' | 'free'


class NewSessionRequest(BaseModel):
    name: str = "Untitled session"
    tempo: float = Field(default=120.0, gt=20, le=400)
    seed: str = "demo"  # 'demo' | 'empty' | 'keep'


class LogEvent(BaseModel):
    type: str
    data: dict = {}


class SettingsUpdate(BaseModel):
    tempo: float | None = None
    time_sig: dict | None = None
    name: str | None = None


def _clean_note(raw):
    n = {
        "time": max(0.0, float(raw.get("time", 0))),
        "dur": min(max(0.01, float(raw.get("dur", 0.25))), 30.0),
        "pitch": min(max(0, int(raw.get("pitch", 60))), 127),
        "instr": min(max(0, int(raw.get("instr", 0))), 128),
        "vel": min(max(1, int(raw.get("vel", 90))), 127),
        "src": raw.get("src", "human") if raw.get("src") in ("human", "ai") else "human",
    }
    n["id"] = str(raw.get("id") or "")[:16] or os.urandom(5).hex()
    return n


def create_app(session: Session | None = None,
               engine: ModelEngine | None = None) -> FastAPI:
    app = FastAPI(title="Human–AI Co-Creation", docs_url="/api/docs")
    loaded = session or Session.load_latest()
    session = loaded or Session()
    engine = engine or ModelEngine()

    app.state.session = session
    app.state.engine = engine
    app.state.fresh = loaded is None

    # ---- pages -----------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index():
        with open(os.path.join(STATIC_DIR, "index.html")) as fh:
            return fh.read()

    @app.get("/static/{path:path}")
    def static_files(path: str):
        full = os.path.normpath(os.path.join(STATIC_DIR, path))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            raise HTTPException(404)
        return FileResponse(full, headers={"Cache-Control": "no-cache"})

    # ---- state -------------------------------------------------------------
    @app.get("/api/state")
    def get_state():
        return {
            "session": session.to_dict(),
            "model": engine.status(),
            "fresh": app.state.fresh,
        }

    @app.post("/api/session/new")
    def new_session(req: NewSessionRequest):
        nonlocal session
        old_notes = session.notes if req.seed == "keep" else []
        session = Session(name=req.name, tempo=req.tempo)
        app.state.session = session
        app.state.fresh = False
        session.log("session_new", name=req.name, tempo=req.tempo, seed=req.seed)
        if req.seed == "demo":
            from .store import demo_seed_notes
            session.set_notes(demo_seed_notes(), actor="human", reason="seed")
            session.snapshot("V0")
        elif old_notes:
            session.set_notes(old_notes, actor="human", reason="carried_over")
        return {"session": session.to_dict()}

    @app.post("/api/settings")
    def update_settings(req: SettingsUpdate):
        if req.tempo is not None:
            session.tempo = float(req.tempo)
        if req.time_sig is not None:
            session.time_sig = {
                "num": int(req.time_sig.get("num", 4)),
                "den": int(req.time_sig.get("den", 4)),
            }
        if req.name is not None:
            session.name = req.name
        session.log("settings", tempo=session.tempo, time_sig=session.time_sig)
        session.save()
        return {"session": session.to_dict()}

    # ---- score --------------------------------------------------------------
    @app.put("/api/score")
    def put_score(req: ScoreUpdate):
        notes = [_clean_note(n) for n in req.notes]
        diff = session.set_notes(notes, reason=req.reason)
        if req.job_id:
            session.log("generation_accept", job_id=req.job_id, **diff)
        return {"ok": True, "diff": diff, "session": session.to_dict()}

    @app.post("/api/undo")
    def undo():
        if not session.undo():
            return {"ok": False, "session": session.to_dict()}
        return {"ok": True, "session": session.to_dict()}

    # ---- generation -----------------------------------------------------------
    @app.post("/api/generate")
    def generate(req: GenerateRequest):
        if engine.model is None:
            engine.load(background=True)
            raise HTTPException(409, "model is still loading — try again shortly")
        spb = session.seconds_per_bar
        if req.start_bar is not None:
            start_time = req.start_bar * spb
        else:
            end = max((n["time"] + n["dur"] for n in session.notes), default=0.0)
            start_time = round(end / spb) * spb  # next bar boundary
        end_time = start_time + req.bars * spb

        instruments = None
        if req.instruments == "match":
            instruments = {n["instr"] for n in session.notes} or {0}

        try:
            job_id = engine.start_generation(
                [dict(n) for n in session.notes],
                start_time=start_time, end_time=end_time,
                top_p=req.top_p, instruments=instruments)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))

        session.log("generate", job_id=job_id, start_time=start_time,
                    end_time=end_time, bars=req.bars, top_p=req.top_p,
                    instruments=req.instruments)
        return {"job_id": job_id, "start_time": start_time, "end_time": end_time}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        status = engine.job_status(job_id)
        if status is None:
            raise HTTPException(404)
        return status

    @app.post("/api/log")
    def log_event(ev: LogEvent):
        session.log(ev.type, **ev.data)
        return {"ok": True}

    # ---- import / export ----------------------------------------------------
    @app.post("/api/import")
    async def import_midi(file: UploadFile = File(...)):
        data = await file.read()
        try:
            notes = midi_bytes_to_notes(data)
        except Exception as exc:
            raise HTTPException(400, f"could not parse MIDI: {exc}")
        session.log("import", filename=file.filename, n_notes=len(notes))
        return {"notes": notes}

    @app.get("/api/export/midi")
    def export_midi():
        data = notes_to_midi_bytes(session.notes)
        session.log("export_midi", n_notes=len(session.notes))
        return Response(
            content=data, media_type="audio/midi",
            headers={"Content-Disposition":
                     f'attachment; filename="{session.name.replace(" ", "_")}.mid"'})

    @app.get("/api/export/session")
    def export_session():
        return JSONResponse(
            session.to_dict(),
            headers={"Content-Disposition":
                     f'attachment; filename="{session.id}_session.json"'})

    @app.get("/api/export/log")
    def export_log():
        if not os.path.exists(session.log_path):
            return Response(content="", media_type="application/x-ndjson")
        return FileResponse(
            session.log_path, media_type="application/x-ndjson",
            filename=f"{session.id}_events.jsonl")

    # ---- snapshots -------------------------------------------------------------
    @app.post("/api/snapshots")
    def take_snapshot(label: str | None = None):
        snap = session.snapshot(label if label in SNAPSHOT_LABELS else None)
        return {"snapshot": {"label": snap["label"], "n_notes": snap["n_notes"]}}

    @app.get("/api/snapshots/{label}/midi")
    def snapshot_midi(label: str):
        snap = session.snapshots.get(label)
        if snap is None:
            raise HTTPException(404)
        return Response(
            content=notes_to_midi_bytes(snap["notes"]), media_type="audio/midi",
            headers={"Content-Disposition":
                     f'attachment; filename="{session.id}_{label}.mid"'})

    @app.post("/api/snapshots/{label}/restore")
    def snapshot_restore(label: str):
        snap = session.snapshots.get(label)
        if snap is None:
            raise HTTPException(404)
        restored = [dict(n, id=os.urandom(5).hex()) for n in snap["notes"]]
        session.set_notes(restored, reason=f"restore_{label}")
        return {"ok": True, "session": session.to_dict()}

    # ---- model -------------------------------------------------------------------
    @app.get("/api/model/status")
    def model_status():
        return engine.status()

    @app.post("/api/model/load")
    def model_load():
        engine.load(background=True)
        return engine.status()

    return app


def main():
    import argparse
    import threading
    import webbrowser

    import uvicorn

    parser = argparse.ArgumentParser(prog="cocreate",
                                     description="Human–AI co-creation web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0,
                        help="0 = pick a free port (default)")
    parser.add_argument("--preferred-port", type=int, default=8745)
    parser.add_argument("--model", default=DEFAULT_MODEL_ID)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    port = args.port
    if not port:
        import socket
        with socket.socket() as s:
            try:
                s.bind((args.host, args.preferred_port))
                port = args.preferred_port
            except OSError:
                s.bind((args.host, 0))
                port = s.getsockname()[1]

    app = create_app(engine=ModelEngine(model_id=args.model))
    url = f"http://{args.host}:{port}"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Co-Creation running at {url}")
    uvicorn.run(app, host=args.host, port=port, log_level="warning")
