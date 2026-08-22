# v1.1 release evidence

This guide defines how a diagnostic run becomes public release evidence. The stages are kept
separate so a local result, a green evaluator job, or a historical JSON file cannot be presented
as proof for a different commit.

## Current status

Validated v1.1 release evidence remains pending until all of these exist for the same immutable
commit:

1. the 45-input Linux-built corpus is committed and passes its independent integrity checks;
2. every blocking CI job passes;
3. the final CI job emits a release-candidate artifact for that commit;
4. the candidate passes the write-once publisher without modification; and
5. the resulting JSON, catalog entry, and narrative are committed as the only release delta.

No metric value is asserted in this guide. The final narrative must be derived from the promoted
JSON after the external checkpoint, not copied from historical experiments or a local run.

## Evidence stages

| Stage | Meaning | Public release evidence? |
|---|---|---|
| Local diagnostic | Useful for debugging; runtime or inputs may differ | No |
| CI diagnostics artifact | Preserved even when the evaluation fails | No |
| Validated intermediate | Passed the evaluator and publisher schema inside the eval job | No |
| Release candidate | All blocking jobs passed for one commit and CI revalidated the summary | Not yet |
| Promoted record | Candidate published write-once and committed with its catalog entry | Yes |

Artifact names carry the full measured commit:

- `eval-safety-diagnostics-${{ github.sha }}`;
- `eval-safety-intermediate-${{ github.sha }}`;
- `eval-safety-release-candidate-${{ github.sha }}`.

An artifact name is an identity hint, not a signature. The publisher validates schema and
repository identities; it does not provide a cryptographic supply-chain attestation.

## Required inputs and runtime

The release gate consumes the committed
`data/eval_corpora/v1.1/bench-balanced-val/` tree. It must authenticate exactly 45
`bench-balanced/val` PNG and ground-truth pairs against:

- the independent `tier_c-manifest/v2` freeze;
- each manifest PNG and canonical ground-truth SHA-256;
- the corpus-wide `SHA256SUMS` inventory;
- strict metadata and provenance schemas;
- the `uv.lock` and vendored-font identities from the corpus build commit.

The reference evaluation runs on Ubuntu 24.04 with Python 3.11.15, uv 0.11.28, Tesseract
package `5.3.4-1build5`, Portuguese language package `1:4.1.0-2`, engine 5.3.4, reader
`local_ocr`, language `por`, and DPI 150. A fallback language, mock reader, missing input,
partial run, or different runtime is not publishable.

Tesseract language `por` is mandatory for release evidence even when another installed language
can support a developer demo.

Corpus construction is documented in
[`DATASET_CONTRACT.md`](DATASET_CONTRACT.md). Normal release CI verifies and consumes those
committed bytes; it does not regenerate the inputs it evaluates.

## Blocking operational gates

The candidate must execute all 45 inputs and satisfy:

```text
unsafe_clean = 0
unsafe_approvable = 0
unsafe_exportable = 0
false_incident_unreviewed = 0
safe_review_recall = 1.0
operational_signal_complete_count = 45
```

These are fail-closed product-safety checks. They answer whether a known unsafe or structurally
incorrect state escaped review, approval, or export on the synthetic corpus. They do not answer
whether Tesseract transcribes real cursive accurately.

Reader metrics such as parsing rate, character error, missed incidents, false incidents, and
estimated correction work remain observations. They may expose weak OCR and review burden, but
they do not override a blocking operational gate and must not be generalized beyond the named
synthetic corpus.

## CI candidate

The blocking path in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) installs the
pinned runtime, verifies the committed corpus, runs the safety evaluator, and checks the output:

```console
make eval-safety DPI=150 OUT=/tmp/eval_safety
uv run --locked python -m scripts.publish_eval_evidence \
  --source /tmp/eval_safety/eval_synthetic_summary.json \
  --expected-commit "$(git rev-parse HEAD)"
```

The intermediate artifact is uploaded only after validation. Diagnostics are uploaded with
`if: always()` so a failed gate remains inspectable without becoming a candidate.

The final candidate job depends on `quality`, `quality-windows`, `eval-safety`, and
`browser-smoke`. It runs only for a push to `main`, downloads the intermediate for the same
workflow run, revalidates it, and then uploads the release candidate. Passing `eval-safety`
alone is insufficient.

## Promote the exact candidate

Let `C` be the candidate's full 40-character commit. Check out `C`, keep the worktree clean, and
download the candidate outside the repository. Validate it without writing:

```console
uv run --locked python -m scripts.publish_eval_evidence \
  --source "<download>/eval_synthetic_summary.json" \
  --expected-commit "<C>"
```

Then explicitly authorize the write-once publication:

```console
uv run --locked python -m scripts.publish_eval_evidence \
  --source "<download>/eval_synthetic_summary.json" \
  --expected-commit "<C>" \
  --write
```

`--write` requires `HEAD == C` and a worktree clean state. It copies the validated candidate
without reserializing its metrics, refuses a divergent existing release artifact, and updates
the catalog atomically. An identical retry verifies the same bytes; it does not create another
result.

## Allowed publication commit

The commit immediately after `C` may change only:

- the promoted release JSON;
- [`evals/catalog.json`](evals/catalog.json); and
- narrative derived directly from that JSON.

Any change to source code, configuration, dependencies, lockfile, corpus, manifest, workflow,
evaluator, or gate invalidates the candidate. Make that change first, rerun the complete CI path,
and promote a new candidate tied to the new commit.

The final CI confirmation must verify that this delta is release-only before the annotated
`v1.1.0` tag is created. The existing `v1.0.0` tag is historical and must not be moved.

## Required narrative and limitations

The release note must state the corpus, split, count, reader, DPI, Python version, Tesseract
engine and language pack, lock identity, measured commit, workflow run, and every blocking gate.
It must link to the promoted JSON and catalog entry.

It must also state these limitations:

- all release inputs are synthetic and table-shaped;
- font-rendered writing is not representative of real cursive handwriting;
- the safety gates measure fail-closed behavior, not field-level production accuracy;
- the corpus is small and tied to one generator, configuration, and release runtime;
- No real corporate document or public real-sheet metric supports the release claim;
- the application is local, single-operator, unauthenticated, and simulation-only.

Detailed OCR output, transcriptions, source paths, review state, and debugging artifacts remain
under `private/` or in access-controlled CI diagnostics. Only the strict public summary is
eligible for promotion.
