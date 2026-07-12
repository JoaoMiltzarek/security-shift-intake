# Privacy & Security

Security shift sheets contain **PII** (guard names, people, units, incident details). This
project is built so that data never leaves the operator's machine and never lands in the repo.

## Principles
- **Local-first, offline.** The default flow uses local OCR (Tesseract) + deterministic rules.
  **No external API** is called — not Anthropic, OpenAI, Google, AWS or Azure. A real sheet is
  never uploaded anywhere.
- **Localhost only — no authentication.** The FastAPI review API/UI has no auth, and endpoints
  like `GET /drafts/{id}` return the full pipeline state (including the transcription). Run it
  bound to `127.0.0.1` for a single operator; **never expose it to a network or deploy it
  publicly** without adding authentication and access control first.
- **Real data lives only in `private/`** — gitignored. It holds: input sheets (`private/reais/`),
  the SQLite DB with PII (`private/app.db`), detailed audit (`private/audit/`), and the curated
  ground-truth (`private/curadoria/`).
- **Public artifacts are sanitized.** READMEs, docs and the committed audit report carry only
  **aggregate metrics + synthetic examples** — no names, times, descriptions or OCR snippets.
- **No fabricated metrics.** Every number comes from code that ran; model-dependent metrics are
  marked pending rather than invented.

## Guardrails (run them)
- **`make privacy-check`** — fails if any sensitive binary/DB is git-tracked, if a real sheet
  sits outside `private/`, or if PII appears in committable text. Exact text coverage:
  - **prose** (`.md .yaml .yml .txt .rst`): org sentinel + `HH:MM` times + terms from the
    gitignored `private/pii_terms.txt`;
  - **code/data** (`.py .js .html .j2 .json .jsonl .csv .toml`): org sentinel (in data
    formats; source files legitimately name the org) + `pii_terms` — except under the
    synthetic-by-contract trees `data/` and `tests/`, whose domain vocabulary overlaps
    private terms by design. The `HH:MM` heuristic is prose-only (synthetic fixtures
    legitimately contain times) — a **documented limitation**, not full coverage.
  The report generators call the same PII scan and **refuse to write** a public report
  that contains PII.
- **Pre-commit guard** ([scripts/check_real_data.py](../scripts/check_real_data.py)) — blocks
  committing real-data binaries (`.pdf/.jpg/.png/...`, DB files) anywhere, and scans
  non-source text (including `.json`) for org-name sentinels. `.json` is **not**
  extension-blocked (legitimate synthetic/metrics JSON is committed) — it relies on the
  content scans above.
- **Retention / cleanup** (scoped, so curadoria isn't destroyed by accident):
  - `make purge-demo-data` — wipes the demo's transient artifacts: the DB (+ `-journal/-wal/-shm`
    sidecars), `audit/`, the OCR page images (`page_images/`) and `debug/`.
  - `make purge-real-data CONFIRM=YES` — wipes the real input sheets.
  - `make purge-all-private CONFIRM=YES` — wipes everything under `private/`.

## Handling a real sheet (the safe procedure)
1. Put the sheet in `private/reais/` (gitignored).
2. `make demo-pipeline FILE=private/reais/<file>` — runs locally, stores a pending draft.
3. Review/correct in the UI; approve only when no field is pending. Email is never auto-sent.
4. `make purge-demo-data` (and `make privacy-check`) when done.
