# Privacy & Security

Security shift sheets contain **PII** (guard names, people, units, incident details). This
project is built so that data never leaves the operator's machine and never lands in the repo.

## Principles
- **Local-first, offline.** The default flow uses local OCR (Tesseract) + deterministic rules.
  **No external API** is called — not Anthropic, OpenAI, Google, AWS or Azure. A real sheet is
  never uploaded anywhere.
- **Real data lives only in `private/`** — gitignored. It holds: input sheets (`private/reais/`),
  the SQLite DB with PII (`private/app.db`), detailed audit (`private/audit/`), and the curated
  ground-truth (`private/curadoria/`).
- **Public artifacts are sanitized.** READMEs, docs and the committed audit report carry only
  **aggregate metrics + synthetic examples** — no names, times, descriptions or OCR snippets.
- **No fabricated metrics.** Every number comes from code that ran; model-dependent metrics are
  marked pending rather than invented.

## Guardrails (run them)
- **`make privacy-check`** — fails if any sensitive binary/JSON is git-tracked, if a real sheet
  sits outside `private/`, or if a public text file contains PII (org sentinel, `HH:MM` times,
  or terms listed in the gitignored `private/pii_terms.txt`). The report generators call the same
  PII scan and **refuse to write** a public report that contains PII.
- **Pre-commit guard** ([scripts/check_real_data.py](../scripts/check_real_data.py)) — blocks
  committing `.pdf/.jpg/.png/.json` real data and org-name sentinels in data files.
- **Retention / cleanup** (scoped, so curadoria isn't destroyed by accident):
  - `make purge-demo-data` — wipes only temporary demo artifacts (DB + `audit/`).
  - `make purge-real-data CONFIRM=YES` — wipes the real input sheets.
  - `make purge-all-private CONFIRM=YES` — wipes everything under `private/`.

## Handling a real sheet (the safe procedure)
1. Put the sheet in `private/reais/` (gitignored).
2. `make demo-pipeline FILE=private/reais/<file>` — runs locally, stores a pending draft.
3. Review/correct in the UI; approve only when no field is pending. Email is never auto-sent.
4. `make purge-demo-data` (and `make privacy-check`) when done.
