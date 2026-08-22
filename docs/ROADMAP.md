# Roadmap

Security Shift Intake v1.1 is intentionally narrow: one local occurrence sheet, one operator,
human-confirmed triage, CSV export, and simulation. The items below are possible follow-up work,
not commitments or hidden v1.1 features.

## Near-term v1.x improvements

### Reduce review friction

- Improve keyboard navigation and accessibility in the review desk.
- Make evidence selection clearer when several OCR tokens repeat on one line.
- Add focused explanations for each readiness blocker without exposing internal state details.
- Measure review time and correction effort on synthetic tasks without collecting real document
  content.

### Improve table reading

- Evaluate column-aware table extraction so item, time, description, action, and resolution do
  not depend on line heuristics.
- Test another local reader only through a versioned corpus, declared runtime, and thresholds
  committed before the decisive run.
- Add confidence calibration only after an independently labeled, legally usable dataset exists;
  current confidence values are not probabilities.

A reader is not adopted merely because it transcribes more text. It must preserve fail-closed
behavior, avoid invented incidents, run on the supported workstation, and reduce correction
effort without winning through empty output.

### Improve local packaging

- Package Python, Tesseract, and the Portuguese language data behind a reproducible installer.
- Add a guided first-run check for loopback binding, writable private storage, and OCR runtime.
- Define backup and retention guidance for local state without claiming secure deletion.

## Deliberate product extensions

Each item below changes the product contract and should be designed as a separate versioned
increment:

- **Multi-sheet aggregation:** combine reviewed shifts only after each source page keeps its own
  evidence and approval identity.
- **Multi-page input:** define page-to-sheet semantics before accepting more than one page; do
  not silently concatenate OCR text.
- **XLSX export:** preserve the CSV formula-injection defenses and add spreadsheet-specific
  tests.
- **Per-occurrence triage:** model classification and routing for each row instead of choosing
  one primary decision for the sheet.
- **Real delivery adapters:** require an explicit destination model, idempotency, failure
  handling, confirmation, and auditable receipt semantics. Simulation remains the v1.1 limit.

## Separate deployment project

Authentication, authorization, multiple users, multiple workers, LAN or internet exposure,
TLS termination, shared storage, and centralized secrets are not incremental toggles for the
current application. They require a new threat model and coordination design.

At minimum, that project would need:

- authenticated identities and role-based authorization;
- tenant and document isolation;
- durable cross-process locking and transactional job ownership;
- encrypted transport and managed secrets;
- retention, backup, deletion, and incident-response policies;
- security testing for the supported proxy and deployment topology.

Until then, the supported boundary remains one process, one operator, and loopback only.

## Data and evaluation work

- Expand synthetic layout and degradation diversity through a new versioned corpus rather than
  changing v1.1 hashes in place.
- Add legally reviewed public data only when its license, role, and non-goals are documented.
- Publish a release result only through the commit-bound procedure in
  [`EVAL_RELEASE.md`](EVAL_RELEASE.md).
- Keep real operational sheets private and optional; they do not become a public benchmark.

## Non-goals for the v1 line

- autonomous incident decisions;
- unattended export or delivery;
- cloud document processing;
- model training on operational documents;
- public release of real sheets, transcriptions, or identifiers;
- configuration-only support for arbitrary form types.

The roadmap can change as evidence improves. The safety, privacy, and human-confirmation
contracts change only through explicit versioned work with tests.
