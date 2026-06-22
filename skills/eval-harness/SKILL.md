---
name: eval-harness
description: >
  Use for any evaluation or metric in this project. Kills fabricated/inflated
  numbers: every metric is computed on a held-out set by code that runs, always
  with a baseline, macro-averaged for imbalanced classes, written to a generated
  report — never hand-typed. Targets defined before running; actuals reported
  honestly, including misses.
---

# Eval Harness

## Non-negotiables

1. **No hand-typed numbers.** Every number in `EVAL_REPORT.md` / a README comes
   from code that ran (`metrics.json` → report). If you can't compute it, mark it
   *pending* / *unavailable* — never write a plausible-looking figure (§8.7).
2. **Held-out only.** Metrics are computed on the test split, never on training
   data. Splits are leakage-free (M2.d).
3. **Always include a baseline.** A number without a baseline is not interpretable:
   - Classification → majority-class **and** a keyword/rule baseline.
   - Extraction/transcription → Tesseract OCR (proves the VLM earns its cost).
4. **Macro-average for imbalanced classes.** Report macro-F1 + per-class
   precision/recall + a confusion matrix, not just accuracy.
5. **Targets before running.** State the ship-worthy threshold first; report
   actual vs target honestly, including misses.

## Mandatory honesty caveats (write into the report)

- **Font-handwriting is easier than real handwriting** → Tier B transcription/
  extraction scores are an **optimistic upper bound**.
- **Synthetic labels make the classification eval partly circular** — it measures
  recovering the generator's rules, not real-world generalization. The
  transcription/extraction evals are the meaningful ones; classification is
  directional.

## Per-component metrics (spec §6)

- **Transcription (HTR):** CER + WER vs ground-truth text, free-text field vs
  short labels separately. Baseline: Tesseract.
- **Extraction:** field-level accuracy (exact for typed, normalized edit distance
  for free-text), per-field + aggregate. Baseline: Tesseract + same parser.
- **Classification:** accuracy + macro-F1 + per-class P/R + confusion matrix.
  Baselines: majority + keyword. LLM zero/few-shot vs trained sklearn.
- **Routing:** recipient-selection accuracy vs the YAML rules (regression guard).
- **End-to-end:** fraction fully correct (all required fields + classification +
  routing). Compounds errors — the honest "would this save time" number.
- **Critic value (the real KPI):** of records with an error, fraction the critic
  flagged MUST_REVIEW (recall on errors); of flagged, fraction truly problematic
  (precision).
- **Confidence calibration:** does reported confidence track correctness?

## Mock vs. real

Model-dependent metrics (VLM CER/WER, field accuracy on the real image,
end-to-end) require a live API key. Mock-first: until a key exists, the harness
records them as **pending (requires ANTHROPIC_API_KEY)** — it does not fabricate.
Offline-computable metrics (Tesseract baseline, trained-classifier classification,
routing) are produced for real.
