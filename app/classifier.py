"""Run Jev over resumes and store the raw judgments.

Raw judgments (probabilities, scores, confidences) are stored unchanged so that
policy in `policy.py` and weights in the UI can change without re-running Jev.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient, SystemOneResponse, TypeSafeError

from . import questions as Q
from .extract import extract

MODEL = "jev-1.13.0"  # pinned: review thresholds in policy.py were chosen against this version
CONCURRENCY = 8


def file_id(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:16]


def _choice(ans) -> dict:
    return {
        "choice": ans.choice,
        "confidence": round(ans.confidence, 3),
        "probabilities": {k: round(v, 4) for k, v in ans.probabilities.items()},
    }


def _score(ans, levels: list[str]) -> dict:
    return {
        "score": round(ans.score, 3),
        "max": len(levels) - 1,
        "confidence": round(ans.confidence, 3),
        "probabilities": {int(k): round(v, 4) for k, v in ans.probabilities.items()},
    }


def _record_from_response(r, resp: SystemOneResponse) -> dict:
    c, s, n = resp.choices, resp.scores, resp.nouls
    name = None
    if "name" in c and c["name"].choice != "none":
        name = r.name_candidates[int(c["name"].choice[1:])]
    return {
        "status": "ok",
        "model": resp.model,
        "input_tokens": resp.usage.input_tokens if resp.usage else None,
        "name": name,
        "name_confidence": round(c["name"].confidence, 3) if "name" in c else None,
        "job_family": _choice(c["job_family"]),
        "industry": _choice(c["industry"]),
        "education": _choice(c["education"]),
        "scores": {k: _score(s[k], levels) for k, (_, levels) in Q.SCORES.items()},
        "tags": {k: round(n[f"tag_{k}"].noul, 4) for k in Q.TAGS},
        "skills": {k: round(n[f"skill_{k}"].noul, 4) for k in Q.SKILL_AREAS},
        "injection": round(n["injection"].noul, 4),
        "date_ranges": [
            {"dates": d.text, "line": d.context, "start": d.start, "end": d.end,
             "is_job": round(n[f"range_{i}"].noul, 4)}
            for i, d in enumerate(r.date_ranges)
        ],
    }


async def classify_pdf(client: AsyncTypeSafeClient, path: Path) -> dict:
    base = {"id": file_id(path), "filename": path.name}
    try:
        r = extract(path)
    except Exception as e:  # corrupt or encrypted PDF
        return {**base, "status": "error", "error": f"PDF read failed: {e}"}
    base |= {"pages": r.pages, "truncated": r.truncated, "email": r.email}
    if not r.has_text:
        return {**base, "status": "no_text",
                "error": "No extractable text (likely a scanned image PDF; needs OCR)."}
    try:
        resp = await client.system_one(Q.build_state(r), Q.build_questions(r))
    except TypeSafeError as e:
        return {**base, "status": "error", "error": f"Jev request failed: {type(e).__name__}: {e}"}
    return {**base, **_record_from_response(r, resp)}


async def classify_many(paths: list[Path], on_done=None) -> list[dict]:
    sem = asyncio.Semaphore(CONCURRENCY)
    async with AsyncTypeSafeClient(model=MODEL) as client:
        async def one(p: Path) -> dict:
            async with sem:
                rec = await classify_pdf(client, p)
            if on_done:
                on_done(rec)
            return rec
        return await asyncio.gather(*(one(p) for p in paths))
