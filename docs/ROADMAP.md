# Roadmap / Future Work

The v1.0 scope is deliberately small: a **local, privacy-first** pipeline that turns a
"Controle de ocorrências" sheet into a standardized spreadsheet + a copy-ready message,
with honest OCR, mandatory human review, and blocked unsafe automation. Everything below is
**explicitly out of scope for v1.0** and recorded here so the core stays clean.

## A escada de PRs do leitor (medição primeiro — PR-1 é a régua)

> **⚠️ Régua reposicionada:** as decisões de adoção de leitor passam a vir dos gates
> **G-S0…G-S3 e G1-S** do dataset sintético `tier_c`
> ([`DATASET_CONTRACT.md`](DATASET_CONTRACT.md) §10) + BRESSAY — nunca mais de folha
> real (G1–G3 abaixo = legado / avaliação local opcional). A fábrica `tier_c` entra
> pelas PRs D0–D6 do contrato (D0 contrato ✅ → D1 fontes OFL → D2 gabarito →
> D3 render → D4 degradação foto → D5 CLI/manifests → D6 eval sintético).

A PR-1 ("medição primeiro") construiu a régua que decide as PRs seguintes sem tocar o
orquestrador: eval instrumentado por leitor×DPI, probes, contrato VLM congelado e o
protocolo normativo [`EVAL_PROTOCOL.md`](EVAL_PROTOCOL.md). Cada seta abaixo é um
número dos gates G1–G3 (fórmulas exatas no protocolo; **hoje legado**):

- **G1** (`parse_table_success` VLM ≥ baseline **e** vitória pareada por campo com
  margem ≥ 2 **e** redução de `estimated_chars_to_type` **e** `tempo_por_folha` ≤ SLO)
  → **PR-2: escalonamento de página** (1 passo, fallback em erro — erro do VLM nunca
  apaga o baseline —, trace `escalation_*`, retenção por qualidade com tie → baseline).
  G1 reprovado → matar/adiar a via (fine-tune HTR M-E vira candidato se o CER platear).
- **G2** (`repairable_ratio ≥ 0.8` nos pendentes) → **PR-2b: reparo por recorte de
  bbox** (1 chamada/campo). Se `missing` domina os pendentes, a PR-2 compara **página
  inteira VLM × crop por região fixa** (rótulo impresso ancora a região em layout fixo)
  antes de qualquer decisão de matar o reparo.
- **G3** (algum leitor com `confidence_source = logprobs`, lido do schema, nunca
  inferido; ≥ 50 campos comparados) → **PR-3: calibração + threshold**. Hoje seria
  histograma de placeholders — por isso não existe ainda.
- **SLO pendente (decisão do usuário):** o alvo de `tempo_por_folha` precisa ser
  declarado em `EVAL_PROTOCOL.md` §5 **antes** de avaliar G1 como "passou".
- **Trilha de produto pós-prova** (independente dos gates): summary dia/noite (depende
  de `period`, hoje `None` em `normalize.py`) e export `.xlsx` (precisa replicar o
  guard de formula injection `_csv_safe`, CWE-1236).

## Better reading (the real fidelity ceiling)

> **Desfecho G1-S (2026-07-08, branch SSI-1003): REPROVADO.** No test do `bench-balanced`,
> `parse_table_success_rate` 0.1111 < 0.30 congelado (números em
> [eval_g1s_calibration.json](eval_g1s_calibration.json)); o VLM local já havia sido
> rejeitado na calibração (9 falsos incidentes). Nenhum leitor custo-zero foi adotado
> como transcritor automático. **Próximo candidato triado: PP-OCRv5** — pip nativo no
> Windows, < 1 GB VRAM, line-level; critério de adoção declarado em
> [READER_DECISION.md](READER_DECISION.md). Qualquer adoção exige novo ciclo
> val → congela → test ([DATASET_CONTRACT.md](DATASET_CONTRACT.md) §10).

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
