# Real-handwriting eval — BRESSAY (Phase 2)

The synthetic Tier B eval uses *font* handwriting, which the spec honestly calls an
"optimistic upper bound" (§4). To measure the reader on **real** Brazilian-Portuguese
handwriting, this project evals against **BRESSAY**, an offline-HTR dataset published
at **ICDAR 2024** (1,000 pages, 1,000 writers, ~30k lines), whose annotated
difficulties — crossed-out text, erasures, smudges, varied hands — match the real
"Controle de ocorrências" sheets.

> BRESSAY is third-party data and large, so it is **not vendored** in this repo. You
> download it locally (it is research data, not PII — but keep it out of git anyway).

## 1. Get the dataset

- Dataset card / download: <https://tc11.cvc.uab.es/datasets/BRESSAY_1>
- Paper (ICDAR 2024): <https://link.springer.com/chapter/10.1007/978-3-031-70536-6_19>
- Competition: <https://link.springer.com/chapter/10.1007/978-3-031-70552-6_21>
- Reference HTR repo: <https://github.com/arthurflor23/handwritten-text-recognition>

Download it to a folder of your choice (default expected: `data/bressay/`, which is
gitignored). You can also point anywhere with `BRESSAY_DIR=/path/to/bressay`.

## 2. Build the manifest

The harness reads a tiny, format-agnostic manifest so it does not depend on any one
release layout. Create `<BRESSAY_DIR>/manifest.jsonl`, one JSON object per line:

```json
{"image": "lines/0001.png", "text": "transcrição de referência desta linha"}
{"image": "lines/0002.png", "text": "..."}
```

- `image`: path to a line/page image, absolute or relative to `BRESSAY_DIR`.
- `text`: the ground-truth transcription for that image.

Use the partition BRESSAY designates for **test** so results are comparable to the
literature, and so you never evaluate on lines the reader was tuned on. A few lines of
Python over the release's label files is enough to emit this manifest.

## 3. Run it

```bash
# Tesseract baseline needs only Tesseract; the VLM column needs a local server:
ollama serve & ollama pull qwen2.5vl:3b     # ~4 GB-VRAM friendly (e.g. GTX 1050 Ti)

make eval-bressay                            # or: python -m evals.eval_htr_bressay --n 50
```

Output is JSON with two columns — `baseline_tesseract` and `vlm` — each reporting
`mean_cer` / `mean_wer`. If the dataset is absent, or no VLM server is reachable, the
respective column reports `available: false` with a reason — it never invents a number
(spec §8.7).

## 4. Read the result honestly

- The **VLM must beat the Tesseract baseline** to justify replacing it (spec §6).
- **Domain gap:** BRESSAY is student essays; occurrence forms differ in vocabulary and
  layout. These numbers are **directional** — also measure on your curated real sheets
  (`private/curadoria/*.json`) once they are `verified_by_user`.
- The headline number that retires the `EVAL_REPORT.md` "pending" lines is the VLM's
  CER/WER on real BR-PT handwriting, side by side with the baseline.
