import os
import uuid
import shutil
import json
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from processing import (
    ingest_url_to_file,
    transcribe_to_srt,
    find_highlights,
    render_clips_with_captions,
)

API_VERSION = "0.1.0"

DATA_ROOT = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_ROOT, exist_ok=True)

app = FastAPI(title="Open Shorts API", version=API_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProcessRequest(BaseModel):
    project_id: str
    clip_length_sec: int = 15
    max_clips: int = 6
    aspect: str = "9:16"  # "9:16" or "1:1" or "16:9"
    style: str = "default" # caption style theme
    language: Optional[str] = None


@app.post("/api/projects", response_model=dict)
def create_project():
    pid = str(uuid.uuid4())
    path = os.path.join(DATA_ROOT, "projects", pid)
    os.makedirs(path, exist_ok=True)
    return {"project_id": pid}


@app.post("/api/upload")
def upload_file(project_id: str = Form(...), file: UploadFile = File(...)):
    proj_dir = os.path.join(DATA_ROOT, "projects", project_id)
    if not os.path.isdir(proj_dir):
        raise HTTPException(404, "Unknown project_id")

    filename = file.filename or "input.mp4"
    dest = os.path.join(proj_dir, "input", filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return {"ok": True, "path": dest}


@app.post("/api/ingest_url", response_model=dict)
def ingest_url(project_id: str = Form(...), url: str = Form(...)):
    proj_dir = os.path.join(DATA_ROOT, "projects", project_id)
    if not os.path.isdir(proj_dir):
        raise HTTPException(404, "Unknown project_id")
    input_path = ingest_url_to_file(url, os.path.join(proj_dir, "input"))
    return {"ok": True, "path": input_path}


@app.post("/api/process", response_model=dict)
def process_video(req: ProcessRequest):
    proj_dir = os.path.join(DATA_ROOT, "projects", req.project_id)
    if not os.path.isdir(proj_dir):
        raise HTTPException(404, "Unknown project_id")

    # 1) Find an input file (first one wins)
    input_dir = os.path.join(proj_dir, "input")
    if not os.path.isdir(input_dir):
        raise HTTPException(400, "No inputs found for this project.")
    candidates = [os.path.join(input_dir, x) for x in os.listdir(input_dir) if x.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".m4a", ".mp3"))]
    if not candidates:
        raise HTTPException(400, "No supported media files in project input.")
    src_path = sorted(candidates)[0]

    work_dir = os.path.join(proj_dir, "work")
    out_dir  = os.path.join(proj_dir, "clips")
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    # 2) Transcribe -> SRT
    srt_path = os.path.join(work_dir, "transcript.srt")
    if not os.path.isfile(srt_path):
        transcribe_to_srt(src_path, srt_path, language=req.language)

    # 3) Pick highlight windows
    highlights = find_highlights(src_path, srt_path, target_len=req.clip_length_sec, max_clips=req.max_clips)

    # 4) Render clips with captions
    manifest = render_clips_with_captions(
        src_path=src_path,
        srt_path=srt_path,
        clips=highlights,
        out_dir=out_dir,
        aspect=req.aspect,
        style=req.style
    )

    # Save manifest
    with open(os.path.join(proj_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    return {"ok": True, "clips": manifest}


@app.get("/api/projects/{project_id}/clips", response_model=dict)
def list_clips(project_id: str):
    out_dir  = os.path.join(DATA_ROOT, "projects", project_id, "clips")
    if not os.path.isdir(out_dir):
        return {"clips": []}
    files = [x for x in sorted(os.listdir(out_dir)) if x.endswith(".mp4")]
    return {"clips": files}


@app.get("/api/projects/{project_id}/clips/{filename}")
def get_clip(project_id: str, filename: str):
    clip_path = os.path.join(DATA_ROOT, "projects", project_id, "clips", filename)
    if not os.path.isfile(clip_path):
        raise HTTPException(404, "Clip not found")
    return FileResponse(clip_path, media_type="video/mp4", filename=filename)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": API_VERSION}
