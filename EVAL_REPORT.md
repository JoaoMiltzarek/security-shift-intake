# EVAL_REPORT

Generated: 2026-07-13T22:22:31.450024+00:00  |  seed: 42

> All numbers below are produced by `make eval` (evals/run_eval.py). Nothing is hand-typed. Model-dependent metrics are marked *pending* until an API key is available (mock-first).

## Honesty caveats (spec §4)
- Font-handwriting is easier than real handwriting → Tier B scores are an optimistic upper bound.
- Synthetic templated labels make the classification eval partly circular; those numbers are directional. Transcription/extraction are the meaningful evals.

## Classification (held-out)
Test records: 300 (train 1400). Target macro-F1 >= 0.80.

| Model | Accuracy | Macro-F1 |
|---|---|---|
| trained sklearn | 1.000 | 1.000 |
| baseline: keyword | 1.000 | 1.000 |
| baseline: majority | 0.750 | 0.143 |

_Caveat: Synthetic templated descriptions make this partly circular; numbers are directional, not a real-world generalization estimate (spec §4)._

## Routing (regression guard)
Recipient-selection accuracy vs documented rules: **1.000** over 7 cases (target == 1.00).

## Transcription — Tesseract baseline
OCR baseline over 5 Tier B docs: mean CER **2.519**, mean WER **2.665**.
_Caveat: Directional baseline: OCR sees printed labels too, and font-handwriting is easier than real handwriting (optimistic upper bound, spec §4)._

## Pending (require a live API — mock-first)
- VLM transcription CER/WER, VLM extraction field accuracy, end-to-end accuracy, and the critic error-flag recall are computed once `ANTHROPIC_API_KEY` is set. They are not fabricated here.
