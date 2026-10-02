"""Deterministic preprocessing: PDF -> text, plus candidate spans Jev selects from.

Jev reads text only and is weak at dates/arithmetic, so code does:
  * PDF text extraction and cleanup
  * finding year ranges ("2018 - 2022", "2021 - Present") with their line context
  * finding name candidates (first few short lines) and the email address
Jev later judges which year ranges are employment, and which line is the name.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

MAX_CHARS = 24_000  # comfortably inside Jev's 32k-token state budget
MAX_DATE_RANGES = 24
MAX_NAME_CANDIDATES = 6

CURRENT_YEAR = dt.date.today().year
_YEAR = r"(?:19[5-9]\d|20\d\d)"
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+"
_RANGE_RE = re.compile(
    rf"(?:{_MONTH})?(?P<start>{_YEAR})\s*(?:-|–|—|to)\s*(?:{_MONTH})?"
    rf"(?P<end>{_YEAR}|present|current|now|today)",
    re.IGNORECASE,
)
_SINGLE_RE = re.compile(rf"\b(?:summer|spring|fall|winter)\s+(?P<year>{_YEAR})\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


@dataclass
class DateRange:
    text: str
    context: str  # the line it appeared on, so Jev can tell job vs. education
    start: int
    end: int


@dataclass
class ExtractedResume:
    text: str
    pages: int
    truncated: bool
    date_ranges: list[DateRange]
    name_candidates: list[str]
    email: str | None

    @property
    def has_text(self) -> bool:
        return len(self.text.strip()) >= 200


def read_pdf_text(path: Path) -> tuple[str, int]:
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages), len(reader.pages)


def clean_text(raw: str) -> str:
    text = raw.replace("\x00", "").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def find_date_ranges(text: str) -> list[DateRange]:
    ranges: list[DateRange] = []
    for line in text.splitlines():
        for m in _RANGE_RE.finditer(line):
            end_raw = m.group("end").lower()
            end = CURRENT_YEAR if not end_raw.isdigit() else int(end_raw)
            start = int(m.group("start"))
            if start <= end:
                ranges.append(DateRange(m.group(0), line.strip()[:200], start, end))
        for m in _SINGLE_RE.finditer(line):
            year = int(m.group("year"))
            ranges.append(DateRange(m.group(0), line.strip()[:200], year, year))
    return ranges[:MAX_DATE_RANGES]


def find_name_candidates(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "@" in line or any(ch.isdigit() for ch in line) or len(line) > 60:
            continue
        out.append(line)
        if len(out) >= MAX_NAME_CANDIDATES:
            break
    return out


def extract(path: Path) -> ExtractedResume:
    raw, pages = read_pdf_text(path)
    text = clean_text(raw)
    truncated = len(text) > MAX_CHARS
    text = text[:MAX_CHARS]
    email = _EMAIL_RE.search(text)
    return ExtractedResume(
        text=text,
        pages=pages,
        truncated=truncated,
        date_ranges=find_date_ranges(text),
        name_candidates=find_name_candidates(text),
        email=email.group(0) if email else None,
    )

