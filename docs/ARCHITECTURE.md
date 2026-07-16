# Architecture

A linear pipeline of **deterministic stages**, each using the simplest tool that works. No
agents, no hidden control flow: a typed `PipelineState` flows through an explicit orchestrator
([src/orchestrator.py](../src/orchestrator.py)). The model layer is behind a single interface
so it is swappable and **mockable in tests** (the whole suite runs offline at $0).

## Pipeline

```
 folha (PDF/foto/scan, manuscrita)
        │
   [0] Ingest ────────► rasteriza PDF→imagem (~150 DPI p/ OCR local) ou abre a foto
        │
   [1] Transcribe ────► OCR local (Tesseract) → texto + confiança         (VisionClient)
        │
   [2] Extract ───────► texto → RawDocumentExtraction (cabeçalho + linhas) (table_rules)
        │
   [3] Normalize ─────► Raw → NormalizedIncidentModel (domínio estável)
        │
   [4] Validate (critic)─► por linha; baixa confiança/ausente → must_review
        │
   [O] OCR Quality Gate ─► good / low / FAILED
        │                  FAILED → classificação unknown/manual_review + rascunho BLOQUEADO
   [5] Classify ───────► tipo / urgência / setor (bloqueado se OCR failed)
        │
   [6] Route ──────────► destinatários determinísticos das regras YAML
        │
   [7] Outputs ────────► Output 1: planilha DIA|UNIDADE|OBJETO|DESCRIÇÃO
        │                Output 2: mensagem copy-ready (bloqueada se houver pendência)
        │
   [8] Human Gate ─────► revisão: corrige campos → regenera; aprovar só sem pendência
```

The v1 input boundary accepts **exactly one page or image frame**.
Supported formats are PDF, PNG, JPEG, TIFF, BMP and WebP. Ingest treats a multi-page PDF or
multi-frame image as unsupported v1 scope: it is **rejected before OCR**, so content from another
page cannot be paired with the page-0 evidence cockpit. Defensive aggregation fields retained for
legacy state are not a public multi-page contract; persisted multi-page state is not approvable or
exportable.

Two report types coexist; switching between the two implemented families is selected by config
without a code change:
- **`controle_ocorrencias`** (v1.0): the occurrence-table sheet → the path above.
- **`htmicron_security`** (legacy): a single-incident scalar form → `extract`/`validate`/Jinja
  draft. Kept for non-regression.

## The two models (anti-corruption layer)

The domain is deliberately decoupled from the sheet layout (the layout can change):

- **`RawDocumentExtraction`** — *what was read from the sheet* (layout-coupled): header + rows,
  each cell an **`AuditedField`** = `value` + `confidence` + `source` (`ocr`|`rule`|`human`) +
  `status` (`accepted`|`must_review`|`missing`|`ambiguous`) + `evidence`.
- **`NormalizedIncidentModel`** — *what the domain understands* (stable): shift (date, guards,
  unit) + a list of normalized occurrences and the `unknown | none | present` disposition.
  `none` requires explicit S/A evidence (or an explicit human confirmation); an empty or
  unreadable table is `unknown`. In schema_version 1.1, `no_occurrence` is a derived compatibility
  field, never an independent source of truth.

The `normalize` stage is the only boundary between them. Models live in
[src/schema/extraction.py](../src/schema/extraction.py).

Confidence values are source-specific routing signals, not calibrated probabilities:
rule-based values use conservative fixed placeholders, Tesseract supplies mean word confidence,
and VLM fallback values are labeled placeholders. The critic's `must_review` decision, not the
numeric signal alone, drives the human gate.

## Safety properties

- **OCR is honest.** Free OCR can't read cursive; the OCR Quality Gate
  ([src/pipeline/ocr_quality.py](../src/pipeline/ocr_quality.py)) detects this and enters a safe
  mode — no auto-classification, no operational draft — routing to manual transcription.
- **Never guess.** Low-confidence/ambiguous values go to the human (`must_review`); they are
  never silently trusted.
- **Structural uncertainty fails closed.** `unknown blocks approval and export`; only explicit
  evidence can turn it into `none` or `present`.
- **Human gate.** A draft cannot be **approved** while any field is pending. The v1 has no external
  delivery adapter: its `MockSender` records a terminal simulation only, after explicit approval,
  and the audit/UI identify that mode without claiming receipt — enforced in
  [src/api/gate.py](../src/api/gate.py).
- **Config-driven within a bounded surface.** Fields, taxonomy and routing within the implemented
  schema families live in YAML ([configs/](../configs/)). A new table layout or domain can require extractor, normalizer and output code
  plus contract/integration tests; configuration alone is
  not claimed as a universal sheet-type plugin system.

## Stack
Python 3.11.15 · Pydantic v2 (typed contracts) · pypdfium2/PDFium + Pillow (ingest) ·
Tesseract/pytesseract (local OCR) · FastAPI + HTMX + Jinja2 (approval API + review UI) ·
SQLModel + SQLite (drafts,
audit) · pytest + ruff + mypy(strict) + GitHub Actions. Anthropic Vision is factory-selectable
only through explicit external opt-in. The Anthropic LLM adapter is not wired into the v1
executable path; offline fake-SDK tests cover request/response shape, not live integration.
