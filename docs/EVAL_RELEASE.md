# Schema/identity-validated v1 eval-evidence publication

This guide separates three different things that must never be conflated:

1. a diagnostic run, which may fail and is retained for debugging;
2. a validated CI release candidate, which passed the executable safety contract;
3. versioned release evidence, promoted once and indexed by hash.

The current inventory is [the eval catalog](evals/catalog.json). Historical and auxiliary
results remain useful context, but they do not become current release evidence by proximity or
by filename.

## Generate and validate in CI

The blocking `eval-safety` job installs the exact Python runtime, Tesseract and the Portuguese
language pack, verifies the Tier C v2 freeze, then runs:

```console
make gen-safety-sheets
make eval-safety DPI=150 OUT=/tmp/eval_safety
uv run --locked python -m scripts.publish_eval_evidence \
  --source /tmp/eval_safety/eval_synthetic_summary.json \
  --expected-commit "$(git rev-parse HEAD)"
```

CI keeps three intentionally different artifact classes:

- `eval-safety-diagnostics-${{ github.sha }}` uses `if: always()` and may contain a failed run;
- `eval-safety-intermediate-${{ github.sha }}` is the summary validated by the eval job alone;
- `eval-safety-release-candidate-${{ github.sha }}` is emitted only by the final job after
  `quality`, `smoke-eval`, `eval-safety` and `browser-smoke` all pass for the same commit.

The publisher requires Tesseract language `por`, the exact Python and `uv.lock`, the
integrity-validated manifest, full split coverage and every operational gate;
mock and `eng` results are never publishable. This is schema/identity-validated evidence, not a cryptographically
signed provenance attestation. A diagnostic artifact name or a green unit test is not a substitute
for these checks.

## Promote write-once

Let `C` be the full 40-character commit measured by CI. Check out `C` with the worktree clean and
keep the downloaded candidate outside the repository. First run check-only:

```console
uv run --locked python -m scripts.publish_eval_evidence \
  --source "<download>/eval_synthetic_summary.json" \
  --expected-commit "<C>"
```

Then explicitly authorize publication:

```console
uv run --locked python -m scripts.publish_eval_evidence \
  --source "<download>/eval_synthetic_summary.json" \
  --expected-commit "<C>" \
  --write
```

`--write` requires `HEAD == C` and a worktree clean state. It copies the candidate bytes without
reserializing them to the fixed v1 path, refuses a divergent existing artifact, and updates
`docs/evals/catalog.json` atomically. The artifact itself is write-once; an identical retry only
verifies it.

The subsequent commit may contain only the published JSON, catalog entry and narrative derived
from those measured bytes. Any change to code, configuration, dependencies, lockfile, manifest,
workflow or evaluator invalidates the candidate and requires a new CI run. Do not copy historical
metrics into the release path and do not rerun or tune against the historical held-out test split.

## Current state

Until the catalog contains exactly one `current_release` entry, validated v1 release evidence
is pending. That is an external release gate, not permission to publish mock numbers or to weaken
runtime attestation.
