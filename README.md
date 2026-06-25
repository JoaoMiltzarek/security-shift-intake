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

## Quick demo
```bash
uv sync

# Public synthetic demo — no real file, no API, $0:
make demo-pipeline-mock        # creates review drafts; prints the URLs
INTAKE_CONFIG=configs/controle_ocorrencias.yaml uv run uvicorn src.api.app:app
#   open http://127.0.0.1:8000/

# Quality gate (200+ tests, mocked, $0) and the privacy guardrail:
make check
make privacy-check
```
Process a **real** sheet locally (needs Tesseract + the `por` language data; the file stays in
the gitignored `private/` folder, never committed):
```bash
make demo-pipeline FILE=private/reais/example.pdf
make purge-demo-data           # wipe temporary demo artifacts when done
```

## Architecture (in 10 seconds)
```
ingest → transcribe → OCR quality gate → extract → normalize → validate → classify/route → outputs → human gate
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
~360 tests (ruff + mypy strict + pytest), all mocked and offline at $0, green in CI. Coverage
includes: OCR quality gate, the two-model schema, normalization, the table extractor, the
critic, the human-approval gate (an unapproved/pending draft **cannot** be approved or sent),
the outputs, and the review UI.

## Roadmap
A better reader (local VLM / PaddleOCR / table models), multi-sheet aggregation, `.xlsx` export,
and richer occurrence-table editing — all deferred to keep v1.0 clean.
See [docs/ROADMAP.md](docs/ROADMAP.md).

## License
[MIT](LICENSE) © João Miltzarek. Synthetic data only; no real personal or organizational data
is included.
