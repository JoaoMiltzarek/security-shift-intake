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

Two report types coexist, selected by config (no code change):
- **`controle_ocorrencias`** (v1.0): the occurrence-table sheet → the path above.
- **`htmicron_security`** (legacy): a single-incident scalar form → `extract`/`validate`/Jinja
  draft. Kept for non-regression.

## The two models (anti-corruption layer)

The domain is deliberately decoupled from the sheet layout (the layout can change):

- **`RawDocumentExtraction`** — *what was read from the sheet* (layout-coupled): header + rows,
  each cell an **`AuditedField`** = `value` + `confidence` + `source` (`ocr`|`rule`|`human`) +
  `status` (`accepted`|`must_review`|`missing`|`ambiguous`) + `evidence`.
- **`NormalizedIncidentModel`** — *what the domain understands* (stable): shift (date, guards,
  unit) + a list of normalized occurrences, or `no_occurrence` for an `S/A` sheet.

The `normalize` stage is the only boundary between them. Models live in
[src/schema/extraction.py](../src/schema/extraction.py).

## Safety properties

- **OCR is honest.** Free OCR can't read cursive; the OCR Quality Gate
  ([src/pipeline/ocr_quality.py](../src/pipeline/ocr_quality.py)) detects this and enters a safe
  mode — no auto-classification, no operational draft — routing to manual transcription.
- **Never guess.** Low-confidence/ambiguous values go to the human (`must_review`); they are
  never silently trusted.
- **Human gate.** A draft cannot be **approved** while any field is pending, and email is never
  sent without explicit approval — enforced in [src/api/gate.py](../src/api/gate.py).
- **Config-driven.** Fields, taxonomy, routing live in YAML
  ([configs/](../configs/)); a new sheet type = a new config, not new code.

## Stack
Python 3.11 · Pydantic v2 (typed contracts) · PyMuPDF + Pillow (ingest) · Tesseract/pytesseract
(local OCR) · FastAPI + HTMX + Jinja2 (approval API + review UI) · SQLModel + SQLite (drafts,
audit) · pytest + ruff + mypy(strict) + GitHub Actions. The Anthropic vision/LLM clients exist
behind the same interface as an **optional, non-default** path (proves swappability) — they are
not used in the local zero-cost flow.
