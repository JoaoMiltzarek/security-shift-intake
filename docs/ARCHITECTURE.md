# Architecture

Security Shift Intake v1.1 is a local, table-only document intake system. It processes exactly
one page or image frame from a **Controle de Ocorrências** sheet and turns uncertain OCR into a
reviewable state. It is deliberately not a generic form platform or an autonomous incident
decision-maker.

## Supported boundary

- One PDF page or one PNG, JPEG, TIFF, BMP, or WebP frame per intake.
- One validated configuration: [`configs/controle_ocorrencias.yaml`](../configs/controle_ocorrencias.yaml).
- One application process and one operator on a trusted workstation.
- Loopback HTTP only, with no authentication or supported multi-worker coordination.
- Local Tesseract OCR, deterministic classification and routing, SQLite persistence, and an
  explicit human review gate.
- CSV export and a terminal local simulation; no delivery adapter.

Multi-page documents and multi-frame images are rejected before OCR. A different table layout
or domain can require extraction, normalization, output, and contract changes; YAML alone is
not presented as a universal plug-in surface.

## System view

```mermaid
flowchart LR
    I["Private PDF or image"] --> G["Ingest and rasterize"]
    G --> P["Hashed page artifact"]
    P --> O["Local Tesseract reader"]
    O --> X["Table extraction"]
    X --> N["Normalized incident model"]
    N --> V["Validation and rule suggestion"]
    V --> H["Human review in FastAPI and HTMX"]
    H --> S["SQLite state and audit"]
    S --> R["Readiness calculation"]
    R --> D["Derived route and previews"]
    D --> A["Approval bound to revision and hash"]
    A --> E["CSV export or local simulation"]
```

The browser is a presentation client. It can submit field values, disposition, and a
classification from the active taxonomy, but it cannot submit recipients or trusted output
text. The server derives those values from the current state and configuration.

## Pipeline

1. **Ingest** validates type and size, applies image EXIF orientation, composites transparency
   onto white, and rasterizes a PDF at the configured dimensions.
2. **Bind evidence** writes the reader-sized PNG under `private/` and records a
   `PageArtifactRef` with its storage key, SHA-256, width, and height.
3. **Read** runs Tesseract locally and records text, word geometry, reader identity, and raster
   settings. Tesseract confidence is a source-specific signal, not a calibrated probability.
4. **Extract** maps the supported header and five-column occurrence table into
   `RawDocumentExtraction`.
5. **Normalize** separates the layout from the domain, including shift date and period,
   occurrence rows, and the `unknown | none | present` disposition.
6. **Validate** preserves missing, ambiguous, and low-quality content as review blockers.
7. **Suggest triage** classifies only normalized occurrence content. Multiple rows resolve to
   one primary sheet decision by severity and then stable rule order.
8. **Review** lets a person correct the fields, explicitly confirm disposition, and confirm or
   override type, urgency, and sector.
9. **Derive** recalculates routing, spreadsheet rows, and the message preview from the current
   state. These outputs are not stored as operational truth.
10. **Approve and act** recalculates readiness under the draft lock. Export and simulation also
    require an approval for the exact current revision and stored-state hash.

The explicit orchestrator is [`src/orchestrator.py`](../src/orchestrator.py). It has a finite
per-sheet processing budget and preserves a coherent reviewable state when a reader times out.

## Core contracts

### Raw and normalized models

`RawDocumentExtraction` represents what was read from the fixed sheet layout. Each
`AuditedField` carries a value, source (`ocr`, `rule`, or `human`), review status, and optional
textual or geometric evidence.

`NormalizedIncidentModel` is the stable domain model. Its v1.1 disposition rules are:

- `unknown` means the occurrence state is not established and cannot be confirmed;
- `none` requires explicit human confirmation and cannot contain occurrence rows;
- `present` requires explicit human confirmation and at least one valid occurrence row.

The read-only `no_occurrence` property is a derived compatibility view. It is never an
independent source of truth.

### Persisted pipeline state

`PipelineState` schema v2 is strict and rejects contradictory or unknown shapes. A stored state
contains intake evidence, extraction and normalization results, validation findings, reader and
raster provenance, and the current classification decision. Routing and output previews are
derived on demand.

Known older states can still be opened for inspection. They remain marked as legacy and fail
closed because a historical path cannot establish the current evidence identity. There is no
silent hash backfill; re-ingestion is required.

### Evidence identity

`PageArtifactRef` replaces trust in a loose filesystem path. Reading a review image or allowing
an operational action requires all of the following:

- a storage key confined to the configured page-artifact root;
- an existing regular file;
- matching SHA-256 bytes;
- matching decoded width and height;
- exactly one page for the v1.1 product surface.

Changing, replacing, deleting, or redirecting the page therefore blocks image use, approval,
CSV export, and simulation.

### Classification and routing

`ClassificationDecision` records `incident_type`, `urgency`, `sector`, source, review status,
and the stable rule identifier when the source is a rule. A rule decision begins as a
suggestion. A no-change decision or an unchanged suggestion still needs explicit human
confirmation before it is operational.

`RoutingDecision` contains a stable rule ID and a non-empty recipient list. It exists only as a
server-side derivation from a confirmed classification and the active configuration.

### Readiness

One `ReadinessReport` controls every consequential action:

| Capability | Additional requirement |
|---|---|
| `approvable` | Evidence, config, disposition, fields, validation, classification, and route are current |
| `exportable` | `approvable` plus approval for the current revision and state hash |
| `simulatable` | Same snapshot requirement as export |

Stable blocker codes are `evidence_changed`, `config_mismatch`,
`disposition_unconfirmed`, `field_pending`, `validation_error`,
`classification_unconfirmed`, `routing_unresolved`, `approval_required`, and
`approval_stale`.

## Persistence and concurrency

SQLite stores drafts, immutable revision snapshots, and append-only audit entries. The database
keeps the historical delivery timestamp column for compatibility while the public model exposes
`simulated_at`. `simulated` is terminal: a simulated draft cannot be edited, approved, rejected,
exported, or simulated again.

Mutations carry the revision and SHA-256 that the reviewer loaded. A mismatch returns a conflict
instead of overwriting a newer edit. In-process per-draft locks serialize approval, export, and
simulation with their audit writes.

Those locks do not coordinate multiple operating-system processes. The supported deployment is
one Uvicorn process with one worker. Scaling to multiple workers requires a shared locking and
transaction design and is outside v1.1.

## HTTP and UI boundary

Stable entrypoints are `src.api.asgi:app`, `create_app`, the existing `/drafts` JSON routes, and
the HTMX review flow. The server disables public API documentation, rejects non-loopback clients
and hosts, checks same-origin state changes, limits request bodies, serves vendored assets, and
sets a restrictive content security policy.

`GET /drafts/{id}` exposes the current revision, `approved_revision`, `state_sha256`, readiness,
derived routing, spreadsheet rows, and message preview. It contains sensitive review data and is
safe only inside the documented loopback boundary.

## Technology

Python 3.11.15; Pydantic; Pillow and pypdfium2/PDFium; Tesseract and pytesseract; FastAPI,
HTMX, and Jinja; SQLModel and SQLite; pytest, Ruff, strict mypy, and GitHub Actions. The
supported path has no cloud reader, analytics, CDN, or outbound delivery integration.
