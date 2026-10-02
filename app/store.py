"""Tiny JSON-file store for raw classification records, keyed by file hash."""

from __future__ import annotations

import json
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UPLOADS = DATA / "uploads"
RESULTS = DATA / "results.json"

_lock = threading.Lock()


def load() -> dict[str, dict]:
    if not RESULTS.exists():
        return {}
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def save_record(rec: dict) -> None:
    with _lock:
        data = load()
        data[rec["id"]] = rec
        DATA.mkdir(exist_ok=True)
        tmp = RESULTS.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(RESULTS)


def delete_record(rec_id: str) -> None:
    with _lock:
        data = load()
        data.pop(rec_id, None)
        RESULTS.write_text(json.dumps(data, indent=1), encoding="utf-8")
