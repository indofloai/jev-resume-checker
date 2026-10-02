# Jev Resume Classifier

Categorizes batches of PDF resumes with TypeSafe's **Jev** model, and lets you
browse, filter and re-rank them in a local web app.

## Setup

```sh
pip install -r requirements.txt
echo TYPESAFE_API_KEY=your_key_here > .env      # key from https://console.typesafe.ai
python scripts/generate_samples.py             # optional: 12 synthetic test resumes
uvicorn app.main:app --reload                  # open http://127.0.0.1:8000
```

Click **Classify ./resumes folder** or drag PDFs onto the page.
For large batches from the terminal: `python -m scripts.classify_folder [folder] [--force]`.

## How it works

| Step | Owner | File |
|---|---|---|
| PDF → text, find year ranges, name candidates, email | code | `app/extract.py` |
| ~33 parallel judgments per resume, **one request** | Jev | `app/questions.py` |
| Years of experience, gaps, review flags, tags | code | `app/policy.py` |
| Weighted "profile score" ranking, filters | code (browser) | `static/index.html` |

**Jev judgments per resume**
- *Choice*: job family (17 options), industry, highest education, which line is the name
- *Score*: seniority, leadership, technical depth, impact evidence, completeness
- *Noul*: 9 tags (people manager, remote, startup, certified, open source, freelance,
  career changer, stated break, student), 10 skill areas, prompt-injection check, and
  for each date range found by regex, "is this a job?". Tenure is summed in code
  because Jev is unreliable at date arithmetic.

Raw probabilities are stored in `data/results.json`; changing thresholds in
`policy.py` or weights in the UI does not re-run Jev. Files are keyed by content
hash, so re-scanning only classifies new PDFs.

**Needs review** when: job-family confidence < 0.5, seniority confidence < 0.3,
possible prompt injection, truncated text, or no extractable text (scanned PDF,
OCR not included). These thresholds are starting points. Tune them on your own data.

Cost: Jev 1.13 is $0.042 per million input tokens, roughly $0.0001 per resume.
