# Roadmap / Future Work

The v1.0 scope is deliberately small: a **local, privacy-first** pipeline that turns a
"Controle de ocorrências" sheet into a standardized spreadsheet + a copy-ready message,
with honest OCR, mandatory human review, and blocked unsafe automation. Everything below is
**explicitly out of scope for v1.0** and recorded here so the core stays clean.

## Better reading (the real fidelity ceiling)
Free local OCR (Tesseract) cannot read cursive handwriting — measured, not assumed
(see [AUDITORIA_FOLHAS_REAIS.md](AUDITORIA_FOLHAS_REAIS.md) and the OCR-iteration note).
Raising fidelity requires a better reader; all of these are deferred:
- **Local open VLM** (e.g. Ollama `llama3.2-vision`, `qwen2-vl`) behind the existing
  `VisionClient` — offline, no paid API.
- **PaddleOCR / TrOCR / handwriting-tuned HTR** as an alternative `VisionClient`.
- **Table-structure models** (Table Transformer / PaddleOCR PP-Structure) for robust cell
  segmentation instead of the line-heuristic table reader.
- **Cloud VLMs** (Anthropic/OpenAI/Google) — only with explicit opt-in; never default, never
  for real PII without consent. The provider abstraction already supports this.
- **Multi-engine OCR benchmark** to pick the best reader per document.

## Product
- **Multi-sheet aggregation**: combine several days/units/shifts into one message with
  `Vigilantes dia` / `Vigilantes noite`, like the operator's real daily summary.
- **Spreadsheet export**: write Output 1 to `.xlsx`/Google Sheets (today it is structured
  rows + a copy-ready table).
- **Richer occurrence-table editing in the UI** (add/remove rows, per-cell source/status).
- **Day/night shift split** modeled explicitly in `NormalizedShift`.

## Engineering
- **Confidence calibration** once a real labeled set exists (reliability curves).
- **Trained classifier on real labels** (the current classifier learns the synthetic
  generator's rules; see the eval caveats).
- **Packaging**: a one-command installer that bundles Tesseract + the Portuguese language data.

> Nothing here is required to run or evaluate v1.0. Each item is a deliberate, separable
> increment that preserves the privacy-first, human-in-the-loop, no-fabrication invariants.
