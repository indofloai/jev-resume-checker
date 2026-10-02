"""Code-owned policy on top of raw Jev judgments.

Everything here is recomputed on read, so thresholds can be changed without
re-running Jev. The thresholds are starting points: tune them on your own
resumes by checking which records you would have wanted flagged.
"""

from __future__ import annotations

from . import questions as Q

TAG_THRESHOLD = 0.5          # Noul probability above which a tag/skill is shown as present
JOB_RANGE_THRESHOLD = 0.5    # a date range counts as employment above this
SECONDARY_FAMILY_MIN = 0.15  # second-most-likely family shown if it has at least this probability
REVIEW_FAMILY_CONFIDENCE = 0.5
REVIEW_SENIORITY_CONFIDENCE = 0.3
REVIEW_INJECTION = 0.5
GAP_YEARS = 1                # a gap of at least this many whole years between jobs is flagged

SENIORITY_LABELS = ["Entry / Student", "Junior", "Mid-level", "Senior", "Lead / Manager", "Executive"]


def _employment(rec: dict) -> tuple[float, list[dict], list[str]]:
    jobs = [d for d in rec.get("date_ranges", []) if d["is_job"] >= JOB_RANGE_THRESHOLD]
    intervals = sorted((d["start"], max(d["end"], d["start"] + 0.25)) for d in jobs)
    merged: list[list[float]] = []
    for s, e in intervals:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    years = round(sum(e - s for s, e in merged), 1)
    gaps = [f"{int(a[1])}–{int(b[0])}" for a, b in zip(merged, merged[1:]) if b[0] - a[1] >= GAP_YEARS]
    return years, jobs, gaps


def experience_band(years: float) -> str:
    if years < 1:
        return "<1 yr"
    if years < 3:
        return "1–3 yrs"
    if years < 6:
        return "3–6 yrs"
    if years < 10:
        return "6–10 yrs"
    return "10+ yrs"


def derive(rec: dict) -> dict:
    if rec.get("status") != "ok":
        return {**rec, "review_reasons": [rec.get("error", rec.get("status"))]}

    fam = rec["job_family"]
    ranked = sorted(fam["probabilities"].items(), key=lambda kv: kv[1], reverse=True)
    secondary = ranked[1][0] if len(ranked) > 1 and ranked[1][1] >= SECONDARY_FAMILY_MIN else None

    sen = rec["scores"]["seniority"]
    sen_level = max(sen["probabilities"], key=lambda k: sen["probabilities"][k])

    years, jobs, gaps = _employment(rec)

    reasons = []
    if rec["injection"] >= REVIEW_INJECTION:
        reasons.append("Possible prompt injection in resume")
    if fam["confidence"] < REVIEW_FAMILY_CONFIDENCE:
        reasons.append(f"Uncertain job family ({fam['confidence']:.2f})")
    if sen["confidence"] < REVIEW_SENIORITY_CONFIDENCE:
        reasons.append(f"Uncertain seniority ({sen['confidence']:.2f})")
    if rec.get("truncated"):
        reasons.append("Resume text truncated")

    return {
        **rec,
        "primary_family": fam["choice"],
        "secondary_family": secondary,
        "seniority_label": SENIORITY_LABELS[int(sen_level)],
        "years_experience": years,
        "experience_band": experience_band(years),
        "employment_gaps": gaps,
        "tag_list": [k for k, p in rec["tags"].items() if p >= TAG_THRESHOLD] + (["employment_gap"] if gaps else []),
        "skill_list": [k for k, p in rec["skills"].items() if p >= TAG_THRESHOLD],
        "review_reasons": reasons,
    }


def taxonomy() -> dict:
    """Labels the UI needs to render filters and weight controls."""
    return {
        "families": Q.JOB_FAMILIES,
        "industries": Q.INDUSTRIES,
        "education": Q.EDUCATION,
        "scores": {k: {"question": q, "levels": lv} for k, (q, lv) in Q.SCORES.items()},
        "tags": list(Q.TAGS) + ["employment_gap"],
        "skills": Q.SKILL_AREAS,
        "seniority_labels": SENIORITY_LABELS,
    }
