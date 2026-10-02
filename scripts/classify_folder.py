"""Classify every PDF in a folder from the command line (same store as the web app).

    python -m scripts.classify_folder [folder] [--force]
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app import policy, store
from app.classifier import classify_many, file_id


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default=str(store.ROOT / "resumes"))
    ap.add_argument("--force", action="store_true", help="re-classify files already in the store")
    args = ap.parse_args()

    paths = sorted(Path(args.folder).glob("*.pdf"))
    done = store.load()
    todo = [p for p in paths if args.force or file_id(p) not in done or done[file_id(p)]["status"] == "error"]
    print(f"{len(paths)} PDFs, {len(todo)} to classify")

    def on_done(rec: dict) -> None:
        store.save_record(rec)
        d = policy.derive(rec)
        if d["status"] != "ok":
            print(f"  ✗ {d['filename']}: {d['error']}")
        else:
            flag = "  [review: " + "; ".join(d["review_reasons"]) + "]" if d["review_reasons"] else ""
            print(f"  ✓ {d['filename']}: {d['primary_family']} · {d['seniority_label']} · "
                  f"{d['years_experience']} yrs{flag}")

    asyncio.run(classify_many(todo, on_done))


if __name__ == "__main__":
    main()
