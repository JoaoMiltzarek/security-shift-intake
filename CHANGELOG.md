# Changelog

This file records user-visible changes. Internal refactors and dependency maintenance appear only
when they change the supported behavior, safety boundary, or reproducibility of the product.

## [1.1.0] - Unreleased

The v1.1.0 code line is still awaiting its promoted release evidence and annotated tag. This
entry describes the intended release surface without asserting unpublished metrics.

### Added

- **Human-confirmed triage** — Reviewers can confirm or override the suggested incident type,
  urgency, and sector using only the active taxonomy. Rule suggestions retain their stable
  provenance.
- **Structured readiness** — The API and review flow expose why approval, CSV export, or
  simulation is unavailable instead of reducing every failure to a disabled button.
- **Evidence identity** — Each review page is bound to its storage key, SHA-256, width, and
  height. A changed, missing, redirected, or replaced artifact blocks operational actions.
- **Versioned state** — New drafts use strict pipeline-state schema v2. Known historical states
  remain readable but require re-ingestion before approval or export.
- **Reproducible corpus checkpoint** — A pinned Ubuntu workflow builds the 45-input v1.1 safety
  corpus with recorded Python, OCR, lockfile, font, runner, workflow, and commit identities.
- **Cross-platform quality gate** — The locked quality suite runs on Ubuntu 24.04 and Windows
  2025, while browser and OCR release gates remain canonical on Linux.

### Improved

- **Safer review edits** — Disposition requires an explicit choice, occurrence rows reject
  contradictory no-change content, and edits recalculate validation and revoke stale approval.
- **Deterministic sheet triage** — Classification uses normalized occurrence content. Multiple
  rows select one primary decision by severity and stable rule order.
- **Server-derived operations** — Recipients, routing rule, spreadsheet rows, and message preview
  are derived from the current state and config; the browser cannot provide trusted recipients.
- **Revision-bound output** — Approval, CSV export, and simulation recheck evidence, config,
  readiness, revision, and stored-state hash under the draft lock.
- **Terminal simulation** — A simulated draft has a clear terminal status and `simulated_at`
  representation. Simulation still means no external message or file was sent.
- **Image intake** — Photos honor EXIF orientation, transparent images are composited on white,
  corrupt inputs produce sanitized failures, and page/dimension limits share one contract.
- **Configuration validation** — Unknown nested keys, duplicate YAML keys, blank or duplicate
  identifiers, invalid processing budgets, shadowing routes, and unsupported table shapes fail at
  startup.

### Security and privacy

- Page serving and operational gates now verify the exact evidence bytes rather than trusting a
  stored path.
- State-changing review requests carry the revision and hash loaded by the reviewer; stale tabs
  receive a conflict instead of overwriting a newer revision.
- Privacy guards inspect staged Git blobs, fail closed on unreadable text, and limit synthetic
  exemptions to values declared by versioned generators.
- Public documentation now states the heuristic privacy boundary and loopback-only deployment
  without describing the application as an authenticated production service.

### Removed from the supported surface

- The second scalar-form path and generic arbitrary-form claim.
- Retired local reader adapters, private real-sheet evaluation harnesses, and third-party
  handwriting experiments from the active product workflow.
- Persisted recipients and output previews as operational sources of truth.
- Unmeasured fixed classification confidence presented as if it were a probability.

The detailed experiment record remains available in the immutable `v1.0.0` tag and Git history;
[`docs/READER_DECISION.md`](docs/READER_DECISION.md) preserves the concise conclusion.

### Migration notes

- Re-ingest a source document to create a v2 state with verifiable page evidence. Historical
  drafts are not silently upgraded.
- Reconfirm disposition and classification after editing. Any edit requires a new approval
  before CSV export or simulation.
- Keep running the application as one process on loopback. Authentication, multiple workers,
  network deployment, real delivery, and arbitrary form types remain outside v1.1.

### Known limitations

- Tesseract is a local baseline and is not reliable for general cursive handwriting.
- The product accepts exactly one page or image frame from the supported occurrence table.
- Human confirmation is mandatory; the tool does not make autonomous incident decisions.
- CSV is the only file export, and delivery is simulated locally.
- Release safety evidence uses a small synthetic corpus and cannot establish real-document OCR
  accuracy.

See [`docs/EVAL_RELEASE.md`](docs/EVAL_RELEASE.md) for the release-evidence checkpoint and
[`docs/ROADMAP.md`](docs/ROADMAP.md) for work intentionally deferred beyond v1.1.
