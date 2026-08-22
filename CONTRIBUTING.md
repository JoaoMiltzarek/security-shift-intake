# Contributing

Security Shift Intake handles sensitive operational documents through a conservative review
workflow. Contributions are welcome when they keep uncertainty visible, preserve evidence, and
leave consequential decisions with the human operator.

## Product boundary

The supported v1.1 path processes one single-page **Controle de Ocorrências** PDF or image on a
trusted workstation. It provides local OCR evidence, a single-operator review desk,
human-confirmed triage, CSV export, and a terminal delivery simulation.

Authentication, network deployment, multiple workers, real delivery, arbitrary form types,
multi-page aggregation, cloud readers, and model training are separate projects. Do not add one
as an incidental dependency or undocumented option.

## Non-negotiable domain rules

1. Missing or ambiguous occurrence evidence remains `unknown`; it never becomes no change.
2. `none` requires explicit human confirmation and zero occurrence rows.
3. `present` requires explicit human confirmation and one to ten valid occurrence rows.
4. A rule classification is a suggestion. Type, urgency, and sector must be confirmed or
   overridden by a human before approval.
5. Classification values must belong to the active taxonomy. A human override carries human
   provenance and cannot claim a rule identifier.
6. Routing and recipients are server-derived. A client never supplies or persists trusted
   recipients.
7. Every mutation requires the revision and state hash loaded by the reviewer, records human
   provenance, advances the revision, and invalidates an older approval.
8. Approval requires the centralized readiness contract: verified evidence, matching config,
   confirmed disposition and classification, no pending fields or validation errors, and a
   non-empty route.
9. CSV export and simulation require an approval matching the current revision and state hash.
10. Page use requires the stored key, bytes, hash, width, and height to match. Historical states
    without that identity remain viewable but fail closed until re-ingestion.
11. CSV cells that begin with formula-control characters remain neutralized.
12. `simulated` is terminal and means only that the local recorder accepted a simulation. It is
    not evidence of external delivery or receipt.

If a change weakens one of these rules, it needs a new product contract, threat analysis, and
versioned migration rather than a compatibility shortcut.

## Set up the development environment

Use Python 3.11.15 and the checked-in lockfile:

```console
uv python install 3.11.15
uv sync --locked --python 3.11.15
uv sync --locked --check
```

Run the canonical gates before committing:

```console
make format-check
make lint
make typecheck
make test
make validate-config
make privacy-check
make audit-deps
```

On Windows without GNU Make, run the corresponding locked commands directly:

```powershell
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy src data scripts evals
uv run --locked pytest
uv run --locked python -m scripts.validate_config configs/controle_ocorrencias.yaml
uv run --locked python -m scripts.privacy_check
uv run --locked python -m scripts.audit_locked_dependencies
```

Do not claim a dependency audit passed when the audit could not execute or obtain its advisory
data.

## Change discipline

- Start from a clean worktree and read the active contracts before editing.
- Keep one behavior, document, or removal per Conventional Commit.
- Include the direct regression test with a code change when separating them would leave a red
  commit.
- Preserve unrelated worktree changes; never rewrite another contributor's history or move a
  release tag.
- Use the lockfile and repository-root paths. Avoid machine-specific paths, clocks, random
  output, or network dependencies in tests.
- Keep business rules out of route handlers and templates. HTTP adapters parse and present;
  application services coordinate; domain modules decide; infrastructure performs I/O.
- Treat OCR text, image metadata, browser fields, stored legacy state, and YAML as untrusted
  inputs.
- Do not weaken same-origin checks, CSP, TrustedHost, request limits, path confinement, escaping,
  revision checks, or evidence hashes to make a test pass.
- Do not add remote fonts, analytics, CDNs, browser storage for document data, inline executable
  code, or hidden outbound requests.

## Test the behavior that changed

| Change | Minimum focused coverage |
|---|---|
| Ingest or evidence | Corrupt input, limits, cleanup, orientation, dimensions, bytes, hash, and confinement |
| Normalization | `unknown`, `none`, `present`, contradictory rows, date, and period |
| Classification | Normalized occurrence content, stable rule ID, multiple rows, confirmation, and override |
| Routing | Stable server rule ID, non-empty recipients, fallback, and no client recipient input |
| Review mutation | Expected revision/hash, human provenance, revalidation, and approval revocation |
| Approval/export/simulation | Every readiness blocker, current snapshot, lock, audit, and terminal state |
| UI | Escaping, CSP, accessibility, empty/rejected states, blockers, and real browser flow |
| Documentation | Local links, real Make targets, locked commands, and supported runtime names |

Mock readers keep unit tests deterministic. A mock result must never be presented as a measured
Tesseract or release result.

## Privacy checklist

Before committing a document, fixture, screenshot, generated output, log, or evaluation record:

- establish and document that every public asset is synthetic;
- inspect staged filenames and staged Git blobs for names, identifiers, addresses, coordinates,
  schedules, and operational details;
- keep real sheets, page images, databases, detailed transcripts, audit output, and curation
  records under `private/`;
- run `make privacy-check` and inspect `git diff --cached`;
- stop and exclude material whose provenance is uncertain.

The automated privacy guard is heuristic. Passing it does not replace review of the staged
content.

## Evidence and release records

The v1.1 safety corpus is built once in the pinned Linux checkpoint and then committed. Normal
CI verifies and consumes those bytes. A release result becomes public only through the
commit-bound, write-once process in [`docs/EVAL_RELEASE.md`](docs/EVAL_RELEASE.md).

Historical reader results are context, not evidence for the current code. A new reader, corpus,
runtime, threshold, or operational rule requires a new measured commit and candidate.
