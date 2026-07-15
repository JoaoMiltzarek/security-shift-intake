# Real-handwriting eval — BRESSAY (Phase 2)

The synthetic Tier B eval uses *font* handwriting, which the spec honestly calls an
"optimistic upper bound" (§4). To measure the reader on **real** Brazilian-Portuguese
handwriting, this project evals against **BRESSAY**, an offline-HTR dataset published
at **ICDAR 2024** (1,000 pages, 1,000 writers, ~30k lines), whose annotated
difficulties — crossed-out text, erasures, smudges, varied hands — match the real
"Controle de ocorrências" sheets.

> BRESSAY is third-party research data and is **not vendored** in this repository.
> Download and retain it only under its applicable terms, keep it outside Git, and do
> not treat the dataset as project-owned or publicly releasable data. The narrow
> `datasets/bressay/` working-tree allowlist only lets the local benchmark coexist
> with `make privacy-check`; Git tracking remains prohibited.

## 1. Get the dataset

- Dataset card / download: <https://tc11.cvc.uab.es/datasets/BRESSAY_1>
- Paper (ICDAR 2024): <https://link.springer.com/chapter/10.1007/978-3-031-70536-6_19>
- Competition: <https://link.springer.com/chapter/10.1007/978-3-031-70552-6_21>
- Reference HTR repo: <https://github.com/arthurflor23/handwritten-text-recognition>

Download it under `datasets/bressay/` (the only working-tree location exempted by the
privacy scan, and still forbidden from Git tracking). You can also point the evaluator
elsewhere with `BRESSAY_DIR=/path/to/bressay`, but only the canonical repository-root
directory receives the local privacy-scan exemption.

## 2. Build the manifest

The harness reads a tiny, format-agnostic manifest so it does not depend on any one
release layout. Generate it from the release's **test** partition (comparable to the
literature; never lines the reader was tuned on):

```bash
uv run --locked python -m scripts.build_bressay_manifest --bressay-dir datasets/bressay --n 20
# options: --level line|page|word, --out <path>; ids sem imagem/gt são contados no stderr
```

The script reads `sets/test.txt` + `data/{lines,pages}/` and emits
`<BRESSAY_DIR>/manifest.jsonl`, one JSON object per line:

```json
{"image": "data/lines/0001.png", "text": "transcrição de referência desta linha"}
```

- `image`: path to a line/page image, absolute or relative to `BRESSAY_DIR`.
- `text`: the ground-truth transcription for that image.

## 3. Run it

```bash
# Tesseract baseline needs only Tesseract; the VLM column needs a local server:
ollama serve & ollama pull qwen2.5vl:3b     # ~4 GB-VRAM friendly (e.g. GTX 1050 Ti)

make eval-bressay
# equivalent locked invocation: uv run --locked python -m evals.eval_htr_bressay --n 50
```

Output is JSON with two columns — `baseline_tesseract` and `vlm` — each reporting
`mean_cer` / `mean_wer`. If the dataset is absent, or no VLM server is reachable, the
respective column reports `available: false` with a reason — it never invents a number
(spec §8.7).

## 4. Read the result honestly

- **BRESSAY is a secondary, non-blocking diagnostic** (~20 samples: "does the reader
  read PT-BR handwriting at all?"). It does not participate in G1-S or in the v1
  release gates. Machine-readable governance records it as `thresholded: false`.
- Reader adoption is measured on the frozen synthetic Tier C ruler; v1 release safety
  is decided by `make eval-safety`. BRESSAY can motivate investigation, but cannot
  promote or reject a reader by itself.
- **Domain gap:** BRESSAY is student essays; occurrence forms differ in vocabulary and
  layout. These numbers are **directional**. The historical run in
  `docs/eval_bressay_baseline.json` did not authenticate a versioned dataset manifest,
  the effective OCR runtime/language pack, or a predeclared CER tolerance; it is not
  evidence that the current release gate passed and is not proof of "no regression".
