"""FastAPI server: upload resumes, classify them with Jev, browse the results.

Run:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import asyncio
import csv
import io
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import policy, store
from .classifier import classify_many, file_id

ROOT = store.ROOT
RESUMES_DIR = ROOT / "resumes"

app = FastAPI(title="Jev Resume Classifier")
jobs: dict[str, dict] = {}  # in-memory progress for running batches


def _start_job(paths: list[Path]) -> str:
    job_id = uuid.uuid4().hex[:8]
    job = jobs[job_id] = {"id": job_id, "total": len(paths), "done": 0, "errors": 0, "finished": False}

    def on_done(rec: dict) -> None:
        store.save_record(rec)
        job["done"] += 1
        job["errors"] += rec["status"] != "ok"

    async def run() -> None:
        try:
            await classify_many(paths, on_done)
        except Exception as e:  # e.g. missing API key
            job["fatal"] = f"{type(e).__name__}: {e}"
        job["finished"] = True

    asyncio.create_task(run())
    return job_id


def _pending(paths: list[Path], force: bool) -> list[Path]:
    if force:
        return paths
    done = store.load()
    return [p for p in paths if file_id(p) not in done or done[file_id(p)]["status"] == "error"]


@app.get("/api/taxonomy")
def taxonomy() -> dict:
    return policy.taxonomy()


@app.get("/api/results")
def results() -> list[dict]:
    return [policy.derive(r) for r in store.load().values()]


@app.post("/api/upload")
async def upload(files: list[UploadFile], force: bool = False) -> dict:
    store.UPLOADS.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            continue
        dest = store.UPLOADS / Path(f.filename).name
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(dest)
    if not saved:
        raise HTTPException(400, "No PDF files received.")
    todo = _pending(saved, force)
    return {"job": _start_job(todo) if todo else None, "queued": len(todo), "skipped": len(saved) - len(todo)}


@app.post("/api/scan-folder")
async def scan_folder(force: bool = False) -> dict:
    paths = sorted(RESUMES_DIR.glob("*.pdf"))
    todo = _pending(paths, force)
    return {"job": _start_job(todo) if todo else None, "queued": len(todo), "skipped": len(paths) - len(todo)}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    if job_id not in jobs:
        raise HTTPException(404)
    return jobs[job_id]


def _pdf_path(rec_id: str) -> Path:
    rec = store.load().get(rec_id)
    if not rec:
        raise HTTPException(404)
    for d in (store.UPLOADS, RESUMES_DIR):
        if (d / rec["filename"]).exists():
            return d / rec["filename"]
    raise HTTPException(404, "PDF file no longer on disk.")


@app.get("/api/pdf/{rec_id}")
def pdf(rec_id: str) -> FileResponse:
    return FileResponse(_pdf_path(rec_id), media_type="application/pdf")


@app.delete("/api/results/{rec_id}")
def delete(rec_id: str) -> dict:
    store.delete_record(rec_id)
    return {"ok": True}


@app.get("/api/export.csv")
def export_csv() -> StreamingResponse:
    rows = [policy.derive(r) for r in store.load().values()]
    buf = io.StringIO()
    w = csv.writer(buf)
    score_keys = list(policy.Q.SCORES)
    w.writerow(["filename", "name", "email", "status", "primary_family", "family_confidence",
                "secondary_family", "seniority", "years_experience", "industry", "education",
                *score_keys, "tags", "skills", "review_reasons"])
    for r in rows:
        ok = r["status"] == "ok"
        w.writerow([
            r["filename"], r.get("name"), r.get("email"), r["status"],
            r.get("primary_family"), r["job_family"]["confidence"] if ok else "",
            r.get("secondary_family"), r.get("seniority_label"), r.get("years_experience"),
            r["industry"]["choice"] if ok else "", r["education"]["choice"] if ok else "",
            *[r["scores"][k]["score"] if ok else "" for k in score_keys],
            "; ".join(r.get("tag_list", [])), "; ".join(r.get("skill_list", [])),
            "; ".join(r.get("review_reasons", [])),
        ])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=resume_categories.csv"})


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
