---
name: synthetic-data-generation
description: >
  Use whenever generating or modifying synthetic data for this project (Tier A
  structured records or Tier B rendered PDFs). Enforces the statistically honest
  generation method — documented priors, preserved joint distributions, realistic
  messiness, seeding, no-leakage splits — instead of uniform-random shortcuts.
---

# Synthetic Data Generation

This project's evals are only meaningful if the synthetic data is generated
honestly. Uniform-random "looks similar" data makes every downstream number a lie.
Follow these rules on every data-generation task.

## The method (in order — never skip a step)

1. **Generate structured ground truth FIRST** (Tier A), from a documented
   generative model. These are the labels/fields.
2. **THEN render** Tier A records into form layouts with handwriting fonts (Tier B).
3. **THEN degrade** the rendered images to look scanned (skew, blur, noise, JPEG).

The VLM must actually *read the image* — it cannot recover the generator's rules
from a Tier B PDF. That is why Tier B is the scientifically stronger eval.

## Documented priors (NOT uniform random)

Every prior must be **documented with its source** in code comments. Operator
domain knowledge is a legitimate source — **state it explicitly**
("priors elicited from operator domain knowledge").

Encode realistic priors and **preserve joint distributions**, not just marginals:

- **Incident occurrence**: most shifts are routine/no-incident; serious incidents
  rare. (~70% no notable incident, long tail of severity.)
- **Type distribution**: skewed — a few common types dominate.
- **`urgency | type`**: conditional, not independent (a fire alarm isn't "low").
- **`sector | type`**: mostly deterministic mapping, with occasional ambiguity.
- **Temporal patterns**: time-of-day / shift effects on incident likelihood.
- **Staffing**: plausible synthetic guard names/shifts, consistent across a report.

## Realistic messiness (documented rates)

Inject, with documented rates: abbreviations, common misspellings, partially
filled fields, blank *optional* fields, crossed-out/corrected text, ambiguous
characters (0/O, 1/l). Clean data would make the eval a lie. **Keep the clean
ground-truth label alongside the messy surface text** — never lose the truth.

## Reproducibility

- **Seed everything.** Same seed → same output (use a passed-in RNG, never global
  `random` state implicitly).
- **Version the generation config.**
- **Split train/val/test with NO leakage**: hold out distinct parameter draws /
  seed batches; never let the same rendered doc appear across splits.

## Required honesty caveats (write these into any report/README)

- **Font-handwriting is easier than real human handwriting** → transcription /
  extraction scores on Tier B are an **optimistic upper bound**. Say so.
- **Synthetic labels make the classification eval partly circular** — it measures
  "can the model recover the generator's rules," not real-world generalization.
  The transcription/extraction eval is the meaningful one; classification numbers
  are directional.

## Checklist — the task FAILS if any of these is false

- [ ] Distributions are non-uniform and documented with a source.
- [ ] Joint/conditional distributions are preserved (`urgency|type`, `sector|type`).
- [ ] Messiness injected at documented rates; clean ground truth preserved.
- [ ] RNG is seeded and deterministic (a test proves same seed → same output).
- [ ] Train/val/test split has no leakage (a test proves disjoint records).
- [ ] A distribution test asserts the data is NOT uniform.
- [ ] Honesty caveats are present in the README / report.
