# Privacy & Security

Security shift sheets contain **PII** (guard names, people, units, incident details). This
project keeps the supported default flow on the operator's machine and keeps real data out of
the repository.

## Principles
- **Local-first, offline.** The default flow uses local OCR (Tesseract) + deterministic rules.
  **No external API** is called — not Anthropic, OpenAI, Google, AWS or Azure. No default command
  uploads a sheet.
- **External experiments cross a trust boundary.** Anthropic and remote-VLM paths can transmit
  document data outside the machine. They require explicit opt-in (`--allow-external`,
  `INTAKE_VISION=anthropic`, or `INTAKE_VLM_ALLOW_REMOTE=1`) and must not receive real PII without
  authorization and an applicable external-data policy.
- **Localhost only — no authentication.** The FastAPI review API/UI has no auth, and endpoints
  like `GET /drafts/{id}` return the full pipeline state (including the transcription). Run it
  bound to `127.0.0.1` for a single operator; **never expose it to a network or deploy it
  publicly** without adding authentication and access control first.
- **Real data lives only in `private/`** — gitignored. It holds: input sheets (`private/reais/`),
  the SQLite DB with PII (`private/app.db`), detailed audit (`private/audit/`), and the curated
  ground-truth (`private/curadoria/`).
- **Public artifacts are sanitized.** Any allowlisted, value-free public evidence is limited to
  run aggregates, pseudonymous per-sheet counters, paired outcome labels and synthetic examples.
  It contains no source names, field values, descriptions, transcriptions, OCR snippets or paths.
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
  content scans above. Synthetic showcase media is allowed only by exact generated names
  directly under `samples/`; the sole GIF exception is `samples/cockpit_demo.gif`. Similar
  names, nested GIFs and files under `assets/` remain blocked.
- **Retention / cleanup** (scoped, so curadoria isn't destroyed by accident):
  - `make purge-demo-data` — removes the demo's active filesystem entries: the DB
    (+ `-journal/-wal/-shm` sidecars), `audit/`, OCR page images (`page_images/`) and `debug/`.
  - `make purge-real-data CONFIRM=YES` — removes the active real-input filesystem entries.
  - `make purge-all-private CONFIRM=YES` — removes active entries under `private/`.

  This cleanup is **not a secure erase**: it does not overwrite storage blocks or remove
  backups, filesystem snapshots, synchronized copies or forensic remnants. When secure disposal
  is required, follow the operating system and storage-provider sanitization policy as a separate
  operation.

## Handling a real sheet (the safe procedure)
1. Put the sheet in `private/reais/` (gitignored).
2. `make demo-pipeline FILE=private/reais/<file>` — runs locally, stores a pending draft.
3. Review/correct in the UI; approve only when no field is pending. The v1 has no email/WhatsApp
   adapter: the final button runs an in-memory simulation, persists `delivery_mode=simulated`, and
   explicitly states that nothing was delivered externally.
4. `make purge-demo-data` (and `make privacy-check`) when done.
