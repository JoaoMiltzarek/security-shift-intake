# security-shift-intake

Document-intake pipeline that turns scanned, handwritten shift reports into structured data: VLM-based transcription &amp; extraction, classification, deterministic routing, and a human-approval gate before any action. Config-driven (YAML schema) — synthetic data only.

## Quickstart

```bash
uv sync                 # install deps from the lockfile
make lint typecheck test
make validate-config    # validate configs/htmicron_security.yaml
make gen-data           # Tier A: structured synthetic records -> data/synthetic/
make gen-pdfs           # Tier B: handwritten-form PDFs -> data/synthetic/tier_b/ + samples/
```

See `samples/` for committed example renders of the Tier B output.

## Synthetic data & honesty caveats

This project trains/evaluates on **synthetic data only** — no real reports, names, or
photos, ever. The data is generated in two tiers (see `data/generators/` and
`skills/synthetic-data-generation/`):

- **Tier A** — structured ground-truth records from *documented, non-uniform priors*
  (joint distributions preserved: `urgency|type`, `sector|type`, day/night effects).
- **Tier B** — those records rendered into handwritten-style form PDFs, then
  scan-degraded (skew, blur, noise, JPEG) to mimic a printer-scan → PDF.

Read these caveats before trusting any number:

- **Font-handwriting is *easier* than real human handwriting.** Transcription and
  extraction scores on Tier B are an **optimistic upper bound** on real-world HTR.
  (No handwriting fonts are bundled; without fonts in `assets/fonts/`, rendering falls
  back to a typed font — even further from real handwriting.)
- **Synthetic labels make the classification eval partly circular** — it measures
  "can the model recover the generator's rules," not real-world generalization. The
  transcription/extraction evals are the meaningful ones; classification numbers are
  directional.
- **Reproducibility:** everything is seeded and versioned; train/val/test splits hold
  out disjoint records (no leakage).
