# Security Shift Intake — Local Document AI for Security Incident Logs

[![CI](https://github.com/JoaoMiltzarek/security-shift-intake/actions/workflows/ci.yml/badge.svg)](https://github.com/JoaoMiltzarek/security-shift-intake/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Offline, privacy-first document-extraction pipeline for handwritten **security incident sheets**
("Controle de ocorrências"). It turns a scanned/photographed sheet into two useful outputs — a
**standardized spreadsheet** and a **copy-ready message** — with local OCR, mandatory human
review, audit trails, and safe automation gates.

> **OCR is best-effort. Human approval is mandatory. Unsafe automation is blocked.**

```
folha (PDF/foto) → OCR local → extração estruturada → revisão humana → planilha + mensagem
```

## The problem
Every shift, a guard fills a paper occurrence sheet by hand; someone retypes it into a
spreadsheet and a message. It's manual, repetitive, and error-prone. And it's hard to automate
honestly: the sheets are **handwritten** (free OCR fails on cursive), the data is **sensitive
PII** (must not go to an external API), and automation **must not invent** information.

## The solution
A staged, **config-driven** pipeline that runs **100% locally** (no paid API, no cloud):
local OCR → best-effort extraction → an **OCR quality gate** → auditable per-field results →
normalization → **human review** → blocked drafts when unsafe → an immutable audit trail.
It doesn't replace the human; it **reduces transcription load and surfaces uncertainty**.

### Two outputs
**Output 1 — standardized spreadsheet**

| DIA | UNIDADE | OBJETO | DESCRIÇÃO |
|---|---|---|---|
| 25/06/2026 | 1 | Alarme | HH:MM - Alarme disparou 4 vezes |
| 25/06/2026 | 2 | Sem alteração | |

**Output 2 — copy-ready message** (paste into WhatsApp/e-mail; never auto-sent):

```
Bom dia,

DIA | UNIDADE | OBJETO | DESCRIÇÃO
25/06/2026 | 1 | Alarme | HH:MM - Alarme disparou 4 vezes
25/06/2026 | 2 | Sem alteração |

Vigilantes: ...
```

If any required field is pending, the message is marked **`RASCUNHO INCOMPLETO`** and lists
exactly what to fix — it never goes out as a clean operational message.

## Evidence cockpit (auditable review)
The review screen is an **evidence cockpit**: the OCR page image sits beside the extracted
fields, and clicking a field highlights the **probable region** the value came from. Every
value answers *where it came from, with what confidence, by which method, and whether a human
reviewed it*:

- **`exact`** — the value matched a contiguous run of OCR words (box = union of those words).
- **`token_window`** — the value's tokens matched within one OCR line (partial score).
- **`none`** — no match; the field shows a textual fallback, never a blank or a wrong box.
- **`human_edit`** — a human edited the value, so the old OCR box is **discarded**.

The box is **probable evidence, not ground truth** — a hint that points the reviewer at the
most likely source region. Boxes are normalized (0..1) against the *same* downscaled image
Tesseract read, so the overlay lines up; the image is served **path-safe** from the gitignored
`private/` tree. When the reader emits no geometry (mock/VLM path), the cockpit degrades to the
plain review layout. Reviewed sheets export to **CSV** — but the button is **blocked while any
field is pending**, and the CSV always carries the post-review values, never the raw OCR.

## Quick demo
```bash
uv sync

# Public synthetic demo — no real file, no API, $0:
make demo-pipeline-mock        # creates review drafts; prints the URLs
INTAKE_CONFIG=configs/controle_ocorrencias.yaml uv run uvicorn src.api.app:app
#   open http://127.0.0.1:8000/

# Quality gate (412 tests, mocked, $0) and the privacy guardrail:
make check
make privacy-check
```
Process a **real** sheet locally (needs Tesseract + the `por` language data; the file stays in
the gitignored `private/` folder, never committed):
```bash
# Defaults to the v1 occurrence-table config (configs/controle_ocorrencias.yaml);
# override with CONFIG=configs/htmicron_security.yaml for the legacy scalar form.
make demo-pipeline FILE=private/reais/example.pdf
make purge-demo-data           # wipe temporary demo artifacts when done
```

### See the evidence cockpit
The clickable overlay needs real OCR geometry, so run the **Tesseract** path on the committed
synthetic sheet, then open the printed review URL (image left, fields right, click to highlight):
```bash
make demo-pipeline FILE=samples/sample_doc-00000.png CONFIG=configs/controle_ocorrencias.yaml
INTAKE_CONFIG=configs/controle_ocorrencias.yaml uv run uvicorn src.api.app:app
```
> The mock demo (`make demo-pipeline-mock`) has no OCR geometry, so it shows the cockpit's
> textual-fallback layout, not the clickable overlay.

## Architecture (in 10 seconds)
```
ingest → transcribe → extract → normalize → validate → OCR quality gate → classify/route → outputs → human gate
```
Two decoupled models keep the domain stable as the sheet layout changes:
- **`RawDocumentExtraction`** — what was read (header + table cells), each an **`AuditedField`**
  (value + confidence + source `ocr|rule|human` + status + evidence).
- **`NormalizedIncidentModel`** — what the domain understands (shift + occurrences, or `S/A`).

Full details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Why this schema:
[docs/ADR_controle_ocorrencias_schema.md](docs/ADR_controle_ocorrencias_schema.md).

## Privacy & security
Real sheets are PII and stay **only in `private/`** (gitignored). No external API is used in
the default flow. Public artifacts carry **aggregate metrics + synthetic examples only**.
`make privacy-check` fails on any tracked real data or PII in public files; scoped
`purge-*` targets clean up without destroying validated curadoria. See
[docs/PRIVACY.md](docs/PRIVACY.md).

> **Run it on localhost only.** The review API/UI has **no authentication** and its endpoints
> return the full document state (including the transcription). It is a single-operator local
> tool — do **not** expose it to a network or deploy it publicly without adding auth first.

## Results & honest limitations
- **The pipeline is correct and safe** (verified on real sheets, preliminary):
  reshaping to the occurrence-table model + the OCR gate took **blocking errors from 2 → 0**
  (no false incident on an `S/A` sheet; a real occurrence is now represented, not dropped).
  Numbers and methodology: [docs/AUDITORIA_FOLHAS_REAIS.md](docs/AUDITORIA_FOLHAS_REAIS.md).
- **OCR fidelity is the honest ceiling.** Tesseract reads printed labels well but **cannot read
  cursive handwriting** — measured across DPIs and preprocessing variants, no meaningful gain.
  So real handwritten values come back low-confidence and are routed to **human review**; the
  system never presents OCR noise as trustworthy data, and never auto-classifies a document it
  couldn't read. Raising fidelity needs a better reader — see Roadmap.
- **Synthetic evals** (classification/routing) are reproducible via `make eval`
  ([EVAL_REPORT.md](EVAL_REPORT.md)); their caveats (templated labels are partly circular) are
  stated there. No number in this repo is hand-typed.

## What was tested
412 tests (ruff + mypy strict + pytest), all mocked and offline at $0, green in CI. Coverage
includes: OCR quality gate, the two-model schema, normalization, the table extractor, the
critic, the human-approval gate (an unapproved/pending draft **cannot** be approved or sent),
the outputs, the review UI, and the evidence cockpit — the 3-level locator (`exact` /
`token_window` / `none`), `human_edit` dropping the OCR box, path-traversal-safe page-image
serving, XSS-safe overlay rendering, and CSV export blocked until review is complete.

## Roadmap
A better reader (local VLM / PaddleOCR / table models), multi-sheet aggregation, `.xlsx` export,
and richer occurrence-table editing — all deferred to keep v1.0 clean.
See [docs/ROADMAP.md](docs/ROADMAP.md).

## License
[MIT](LICENSE) © João Miltzarek. Synthetic data only; no real personal or organizational data
is included.
