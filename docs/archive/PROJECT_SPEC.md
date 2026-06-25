# Security Report Intake Pipeline — Project Spec

> **Purpose of this file.** This is the authoritative guide for building this project inside Claude Code. It is operational, not aspirational. When scope, architecture, or a "should I do X" question comes up, **this file is the tiebreaker**. If something here is ambiguous or contradicts reality (e.g. a library API changed), **stop and ask the human** — do not improvise around the spec.
>
> Distill the **Scope (§1)** and **Anti-Hallucination Protocol (§8)** into a short `CLAUDE.md` at the repo root so they are always in context.

---

## 1. Scope — the North Star

### The problem (one paragraph, no ambiguity)
Every morning at HT Micron, a security guard's shift report — a **printed form filled out entirely by hand**, scanned on the office printer into a **PDF** — must be read, transcribed into a spreadsheet, combined with shift/staffing info, and emailed to the technology-security and general-support teams. The process is 100% manual, repetitive, and prone to transcription error. This project automates the **read → structure → classify → route → draft** steps and replaces blind manual sending with a **human-approved** draft.

### What this system **is**
- A **configurable document-intake pipeline** that turns a scanned, handwritten report PDF into (a) a faithful transcription, (b) structured fields, (c) a classification (type / urgency / responsible sector), (d) a routed, pre-filled email draft.
- An **internal triage tool** whose job is to **reduce human transcription load and surface uncertainty**, not to achieve full autonomy.
- A portfolio artifact that **looks like a product**: typed API, tests, CI, reproducible evals, clean repo.

### What this system **is NOT** (anti-scope-creep)
- ❌ Not an "autonomous multi-agent" system. It is a **staged pipeline** (see §2). Do not add agent loops, planners, or tool-using agents. If the urge appears, re-read this line.
- ❌ Not an auto-sender. **Email is never sent without explicit human approval.** No exceptions.
- ❌ Not a multi-tenant SaaS (yet). One report type, one organization config. The abstraction exists in the *structure*; only one config is populated.
- ❌ Not trained on or storing **any real HT Micron data**. Synthetic data only (see §4 and §9).

### Non-negotiables (invariants — never violate)
1. **Human approval gate** before any irreversible action (sending email, writing to a system of record).
2. **Synthetic data only** in the repo. No real reports, names, or photos. Ever.
3. **No fabricated metrics.** Every number in a README/report is produced by code that ran. (See §8.)
4. **Config-driven, not hardcoded.** Fields, taxonomy, routing, and email templates live in YAML, not in `if` statements.

---

## 2. Architecture (final, with justifications and rejected alternatives)

### The pipeline
```
 PDF (scanned, handwritten)
        │
   [0] Ingest ──────────► rasterize PDF page → image(s) @ ~250 DPI
        │
   [1] Transcribe ──────► VLM reads image → faithful verbatim transcription
        │                 (preserves field labels; per-region confidence)
        │
   [2] Extract ─────────► transcription (+ image) → structured fields per YAML schema
        │                 (per-field value + confidence)
        │
   [3] Validate (critic)─► check types / required / allowed values; flag
        │                 low-confidence & invalid fields as MUST-REVIEW
        │
   [4] Classify ────────► incident type / urgency / responsible sector
        │                 (structured output; evolution path → trained model)
        │
   [5] Route + Draft ───► deterministic recipient from YAML rules;
        │                 fill email template
        │
   [6] Human Gate ──────► reviewer sees image | transcription | fields |
                          classification | draft → approve / edit / reject
                          → only then send
```

### Why a **staged pipeline**, not "multi-agent" (read this before any interview)
The honest framing: these are **deterministic stages**, not agents — there's no autonomous planning, no tool-use loops, no agent-to-agent negotiation. Calling them "agents" is buzzword inflation that a competent ML interviewer will probe. The strong narrative is:

> "I implemented it as a staged pipeline where **each stage uses the simplest tool that works**. I evaluated whether a multi-agent orchestration (e.g. LangGraph) added value at this scope and concluded it didn't — but I can describe exactly where it *would* (high branching, retries with state, parallel agents reconciling)."

That answer demonstrates **judgment**, which beats demonstrating that you can wire a trendy framework.

### Stage decisions, justified

| Stage | Decision | Why | Rejected alternative |
|---|---|---|---|
| 0 Ingest | Rasterize PDF→PNG with PyMuPDF (`fitz`) at ~250 DPI | Provider-agnostic; VLMs consume images reliably; control over DPI/quality | Sending raw PDF to the API (provider-dependent, less control over preprocessing) |
| 1 Transcribe | **VLM** produces verbatim transcription as a **separate step** | (a) **Auditability** — reviewer sees what the model "read"; (b) **separable evaluation** — measure HTR (CER/WER) independently from field-mapping; (c) downstream extraction can run on text. **Note:** does *not* lower raw read-error vs. direct extraction; it makes error *visible and measurable*. | Direct structured extraction in one call (simpler/cheaper, but a black box — no intermediate to audit or measure; weaker eval story). At scale these could be collapsed for cost. |
| 2 Extract | VLM/LLM with **structured output** (Pydantic schema) → fields + per-field confidence | Handwritten forms have no fixed digital layout; structured output enforces a typed contract | Classical template/regex extraction (brittle on handwriting and free-text); pure OCR (see baseline below) |
| 3 Validate (critic) | Deterministic schema validation + confidence thresholding → `MUST_REVIEW` flags | The single most useful stage: catches type/required violations and routes uncertainty to the human. This is where a "second pass" genuinely earns its place. | A second LLM "critic agent" (more cost/nondeterminism; most checks are deterministic and belong in code) |
| 4 Classify | **LLM with structured output** as the production path; ship a **trained sklearn classifier** as the documented *evolution path* | Taxonomy is small; LLM zero/few-shot is strong with no labeled volume. Trained model earns its place only when there's **real** labeled volume, or latency/cost/offline constraints. | Training a classical model from day one (no real labels → it only learns the synthetic generator's rules; see §4 caveat) |
| 5 Route + Draft | **Deterministic** routing from YAML rules; template-filled draft | Routing is a business rule, not an ML problem; keep it auditable and config-driven | LLM "decides" the recipient (unnecessary nondeterminism for a lookup) |
| 6 Human Gate | Real API endpoints + persisted `pending` state + audit log; UI on top | Required invariant; must be a real state machine, not a UI button | Streamlit-only "approve" button with no backing state (not auditable, not testable) |

### Provider abstraction
All model calls go through a single `VisionClient` / `LLMClient` interface so the provider (Claude vision, GPT-4V, etc.) is swappable and **mockable in tests**. Do not scatter raw API calls through the codebase.

### Why **no LangGraph** (and no orchestration framework) right now
The pipeline is **linear with one conditional** (the validate→review branch). LangGraph pays off on **cyclic graphs, conditional branching with persisted state, multi-agent handoffs, and human-in-the-loop interrupts at scale**. Here, a **typed function pipeline + explicit orchestrator + Pydantic state object** is more readable and signals deeper understanding. Document this as "considered and rejected, with the conditions under which I'd adopt it." Revisit only if branching/retry-with-state complexity grows.

---

## 3. Stack (final, justified — nothing "because it's trending")

| Tool | Role | Why this, not something else |
|---|---|---|
| **Python 3.11+** | language | Ecosystem fit for ML + typing maturity |
| **uv** (or Poetry) | dependency & venv management, lockfile | Reproducible installs; pinned versions (anti-hallucination, §8) |
| **Pydantic v2** | typed models for pipeline state, schema, config | Enforces the data contract between stages; powers structured output validation |
| **PyMuPDF (`fitz`)** | PDF → image rasterization | Fast, no system deps, precise DPI control |
| **FastAPI + Uvicorn** | the real API (pipeline behind it, approval endpoints) | Typed, testable, OpenAPI docs for free — this is where "product" lives |
| **HTMX + Jinja2** | thin review UI (server-rendered) | Minimal JS; reviewer screen ships fast; engineering rigor stays in the API. (Swap to a small React app only if you want React on the CV.) |
| **SQLite + SQLModel/SQLAlchemy** | persist drafts, statuses, audit log | A real state machine for the approval gate without infra overhead |
| **A VLM via the chosen API** (Claude vision default) | transcription + extraction | Handwriting (HTR) is hard for classical OCR; VLMs read it and return structured output. **Verify the current model ID before coding (§8).** Behind `VisionClient`. |
| **scikit-learn** | the trained classifier (evolution-path demo) | Standard, interpretable baselines (LogReg / linear SVM / NB) |
| **Tesseract (`pytesseract`)** | **baseline only** for extraction eval | To *prove* the VLM earns its cost vs. classical OCR — not for production |
| **pytest + pytest-mock** | tests | Mock the model layer → deterministic, zero API cost in CI |
| **ruff** (lint+format) + **mypy/pyright** (types) | quality gates | Cheap signals; run in CI |
| **GitHub Actions** | CI | Lint → typecheck → tests → smoke-eval on a tiny fixture |
| **Pillow / OpenCV** | synthetic scan-degradation (skew, blur, noise) | Needed to make synthetic PDFs resemble real scans (§4) |

**Rejected on "trendy" grounds:** LangGraph/LangChain (overkill, §2); a vector DB (no retrieval problem here); a heavyweight frontend SPA (the value is the API + pipeline, not the UI).

---

## 4. Data Strategy (synthetic, statistically honest)

> The hardest and most differentiating part. Most portfolios fake this with uniform-random "looks similar" data. Don't.

### Two tiers of data
- **Tier A — structured ground truth (cheap, lots):** the labels/fields generated *first*, from a documented generative model. Used to eval classification & routing, and as the source for rendering images.
- **Tier B — rendered handwritten PDFs (harder, fewer):** Tier A records rendered into a form layout with handwriting fonts, then degraded to look scanned. Used to eval transcription & extraction. **This is the scientifically stronger eval** (the VLM cannot know the generator's rules — it has to actually read the image).

### Generative model — documented priors (NOT uniform random)
Encode realistic priors and **preserve joint distributions**, not just marginals:
- **Incident occurrence:** most shifts are routine/no-incident; serious incidents are rare. (e.g. ~70% no notable incident, long tail of severity.)
- **Type distribution:** skewed (a few common types dominate).
- **`urgency | type`:** conditional, not independent (a fire alarm isn't "low").
- **`sector | type`:** mostly deterministic mapping with occasional ambiguity.
- **Temporal patterns:** time-of-day / shift effects on incident likelihood.
- **Staffing:** plausible guard names/shifts (synthetic) consistent across the report.

Every prior **must be documented with its source**. Your own knowledge of the real job is a *legitimate* source — **state it explicitly** ("priors elicited from operator domain knowledge").

### Realistic messiness (in realistic proportions)
Inject, with documented rates: abbreviations, common misspellings, partially filled fields, blank *optional* fields, crossed-out/corrected text, ambiguous characters (0/O, 1/l). Clean data would make the eval a lie.

### Rendering pipeline (Tier B)
1. Lay out a form template matching the real form's field structure.
2. Fill it using **several handwriting fonts** (rotate fonts + per-glyph jitter/rotation/baseline noise to avoid one uniform "hand").
3. **Scan-degradation pass** (Pillow/OpenCV): slight skew/rotation, blur, Gaussian/salt-pepper noise, binarization/threshold, JPEG compression — mimic printer-scan→PDF.
4. Export to PDF (then §2 stage 0 rasterizes it back — round-trips the real path).

### Honest caveats (put these in the README, verbatim spirit)
- **Font-handwriting is *easier* than real human handwriting.** Transcription/extraction scores on Tier B are an **optimistic upper bound** on real-world HTR. Say so.
- **Synthetic labels make the classification eval partly circular** — it measures "can the model recover the generator's rules," not real-world generalization. The **transcription/extraction eval is the meaningful one**; classification numbers are directional.
- **Reproducibility:** seed everything; version the generation config; split train/val/test with **no leakage** (hold out distinct parameter draws / seed batches, never the same rendered doc across splits).

### Config schema (YAML) — the generalization abstraction
One config drives the whole pipeline. Example (`configs/htmicron_security.yaml`):
```yaml
report_type: htmicron_security_shift
fields:
  - name: shift_date            {type: date,    required: true,  handwritten: true}
  - name: guard_name            {type: string,  required: true,  handwritten: true}
  - name: post                  {type: string,  required: true,  handwritten: true}
  - name: shift_period          {type: enum,    required: true,  values: [day, night], handwritten: true}
  - name: incident_occurred     {type: bool,    required: true,  handwritten: true}
  - name: incident_description  {type: text,    required: false, handwritten: true}
classification:
  type:    {labels: [routine, access_violation, equipment, safety, theft, other]}
  urgency: {labels: [low, medium, high, critical]}
  sector:  {labels: [tech_security, general_support, facilities]}
routing:                         # deterministic; data, not code
  rules:
    - when: {urgency: critical}                  -> [tech_security_oncall, general_support]
    - when: {type: theft}                        -> [tech_security, general_support]
    - when: {type: equipment}                    -> [facilities]
    - default                                    -> [general_support]
email_template: templates/security_shift.j2
```
Validate the config itself with a Pydantic model (a schema for the schema). Adding a new company later = new YAML, **no code change** — that's the whole point.

---

## 5. Build Plan (small, verifiable milestones)

Each milestone has an explicit **Definition of Done (DoD)**. A milestone is not "done" until its DoD command runs and produces the stated output. Provide a `Makefile` with these targets.

- **M0 — Skeleton.** Repo structure (§ below), `uv` env, ruff+mypy configured, empty FastAPI app, CI runs.
  - **DoD:** `make lint typecheck test` passes (even with one trivial test); CI green on push.
- **M1 — Config + schema models.** Pydantic models for report schema, fields, routing, pipeline state; load + validate `htmicron_security.yaml`.
  - **DoD:** `make validate-config` validates the YAML; an invalid YAML fails with a clear error; unit tests cover both.
- **M2 — Synthetic data: Tier A.** Generative model with documented priors → structured records + labels; train/val/test split.
  - **DoD:** `make gen-data` writes seeded records to `data/synthetic/`; a test asserts the *distribution* (e.g. incident rate within tolerance, `urgency|type` respected), proving it's not uniform.
- **M3 — Synthetic data: Tier B.** Render records → handwritten form PDFs → scan-degrade.
  - **DoD:** `make gen-pdfs` produces PDFs + a `ground_truth.jsonl`; eyeball a sample (committed as a few example images); README states the font-handwriting caveat.
- **M4 — Ingest + Transcribe.** PDF→image; `VisionClient` (real + mock); transcription stage returns text + confidence.
  - **DoD:** runs end-to-end on a sample PDF with the **mock** client in tests; a manual `make demo-transcribe FILE=...` runs the real model on one PDF and prints the transcription.
- **M5 — Extract + Validate.** Structured extraction against schema; critic flags low-confidence/invalid fields.
  - **DoD:** unit tests (mocked) cover a clean record, a low-confidence field, and a schema-invalid field → correct `MUST_REVIEW` flags.
- **M6 — Classify + Route + Draft.** LLM classification (structured output, mockable); deterministic routing; Jinja email draft.
  - **DoD:** given a fixed structured record, routing + draft are deterministic and unit-tested; classification tested with mocked LLM.
- **M7 — Approval gate (API + state + UI).** Persist drafts with `pending/approved/rejected`; audit log; FastAPI endpoints; HTMX review screen (image | transcription | fields | classification | draft → approve/edit/reject).
  - **DoD:** integration test drives `submit → review → approve → (mocked) send`; sending is **blocked** unless status is `approved`; audit row written. A test asserts an unapproved draft **cannot** be sent.
- **M8 — Eval harness + report.** Reproducible evals per component with baselines; generate `EVAL_REPORT.md` from real numbers.
  - **DoD:** `make eval` produces `metrics.json` + `EVAL_REPORT.md` (CER/WER, field accuracy, macro-F1, confusion matrix, end-to-end, Tesseract baseline). **No number is hand-typed.**

### Suggested repo structure
```
.
├── CLAUDE.md                 # condensed scope + anti-hallucination rules
├── PROJECT_SPEC.md           # this file
├── Makefile                  # gen-data, gen-pdfs, eval, lint, typecheck, test, demo-*
├── pyproject.toml / uv.lock  # pinned deps
├── configs/
│   └── htmicron_security.yaml
├── src/
│   ├── schema/               # Pydantic: report schema, config, pipeline state
│   ├── clients/              # VisionClient, LLMClient (+ mock implementations)
│   ├── pipeline/             # ingest, transcribe, extract, validate, classify, route, draft
│   ├── orchestrator.py       # runs the stages, builds the state object
│   ├── classifier/           # sklearn evolution-path model + training script
│   └── api/                  # FastAPI app, approval endpoints, audit log
├── ui/                       # Jinja templates + HTMX
├── data/
│   ├── generators/           # Tier A (records) + Tier B (rendering, degradation)
│   └── synthetic/            # generated artifacts (gitignored if large)
├── evals/                    # harness + baselines + report generator
├── tests/                    # unit (mocked), integration, distribution tests
└── .github/workflows/ci.yml
```

---

## 6. Success Criteria & Metrics (per component)

> Every metric is computed on a **held-out** set by code. Always report a **baseline**. Macro-averages where classes are imbalanced.

- **Transcription (HTR).** Character Error Rate (CER) and Word Error Rate (WER) vs. ground-truth text, reported **separately for the handwritten free-text field** vs. short labeled fields. This is the headline HTR number.
- **Extraction.** Field-level accuracy (exact match for typed fields; normalized edit distance for free-text). Report **per-field** and aggregate. Two cuts: (a) on the real image, (b) on **ground-truth transcription input** (isolates pure field-mapping from read errors). **Baseline:** Tesseract OCR + same parser → shows the VLM earns its cost.
- **Classification.** Accuracy + **macro-F1** + per-class precision/recall + confusion matrix. **Baselines:** majority-class and a keyword/rule baseline. Compare LLM zero-shot vs. few-shot vs. trained sklearn. (Caveat from §4 restated in the report.)
- **Routing.** Recipient-selection accuracy vs. the YAML rules (tests that the pipeline *applies* rules correctly; near-100% expected — a regression guard).
- **End-to-end.** Fraction of reports fully correct (all required fields right **and** correct classification **and** correct routing). Compounds errors — the most honest "would this save me time" number.
- **Human-in-the-loop value (the real KPI).** Of the records with an actual error, what fraction did the critic correctly flag as `MUST_REVIEW`? (recall on errors) And of flagged records, how many were truly problematic? (precision). Goal: the human only checks the uncertain ones, and **real errors rarely slip through unflagged**.
- **Confidence calibration.** Does model-reported confidence correlate with actual correctness? (Drives the review threshold.) Report a reliability curve or at least binned accuracy-vs-confidence.

Define **target thresholds before running** (e.g. "ship-worthy if handwritten-field CER < X and error-flag recall > Y"), and report **actuals vs. targets** honestly — including misses.

---

## 7. Skills to create in Claude Code

Create these as `skills/<name>/SKILL.md` (the standard skill format: a `name`, a triggering `description`, then the body). They encode the project's hard-won rules so Claude Code follows them consistently instead of re-deciding each time.

### `synthetic-data-generation`
- **Objective:** ensure every data-generation task follows the *statistically honest* method, not uniform-random shortcuts.
- **SKILL.md contents:** the documented priors and where they come from; the rule "generate structured ground truth first, then render, then degrade"; mandatory realistic-messiness injection with rates; the seeding/versioning/no-leakage split rules; the **required honesty caveats** to write into any report (font-handwriting upper bound; synthetic-label circularity); a checklist that fails the task if distributions are uniform or correlations are dropped.

### `vlm-document-extraction`
- **Objective:** a consistent contract for all vision/LLM extraction calls.
- **SKILL.md contents:** always go through `VisionClient`/`LLMClient` (never raw API calls); always request **structured output** validated by a Pydantic model; always return **per-field confidence**; the validate/critic pattern (schema check + threshold → `MUST_REVIEW`); a retry/repair step for malformed structured output; and the rule **"verify the current model ID and the API request/response shape in the official docs before writing the call"** (model names and params change).

### `human-approval-gate`
- **Objective:** the reusable safety pattern for any irreversible action.
- **SKILL.md contents:** the state machine (`pending → approved/rejected`), the rule that the execute step (send email) **must assert `status == approved`** and is otherwise blocked; mandatory audit-log entry (who/what/when); the requirement for a test proving an unapproved item **cannot** be executed; "never auto-execute, never bypass the gate for convenience."

### `eval-harness`
- **Objective:** kill fabricated/inflated metrics; enforce rigorous evaluation.
- **SKILL.md contents:** every metric computed on a **held-out** set by code that runs; **always include a baseline**; macro-averages for imbalanced classes; output is a generated report (`metrics.json` → `EVAL_REPORT.md`) — **no hand-typed numbers**; targets defined before running and actuals reported honestly including misses; the per-component metric list from §6.

### `config-schema-authoring`
- **Objective:** keep the system config-driven and consistent across report types.
- **SKILL.md contents:** the YAML structure (fields/classification/routing/template); validate the config with a Pydantic "schema-for-the-schema"; routing rules are **data, not code**; adding a report type = new YAML + new template, **no pipeline code change** — flag any PR that hardcodes field/routing logic.

---

## 8. Anti-Hallucination Protocol for Claude Code

Operational rules. Follow them on every task in this repo.

1. **Verify library versions before using version-specific APIs.** Check the installed version (`uv pip show <pkg>` / `pip show`) and the official docs for *that* version. Do not assume.
2. **Never invent a method, parameter, or model name.** If you can't confirm it in the docs or the installed source, **stop and say so** — don't guess a plausible-looking signature.
3. **Confirm the model API before coding the call.** Current model IDs and the request/response shape for the vision/LLM provider must be checked against official docs (they change). Put the model ID in config, not scattered literals.
4. **Tests with or before implementation.** No stage is "implemented" without a test. Mock the model layer so tests are deterministic and cost $0.
5. **Run the code before declaring a step done.** Paste the actual command and its real output. "Should work" is not done.
6. **Stop and ask when ambiguous.** If the task is under-specified or conflicts with this spec, ask one crisp question — do not assume and build the wrong thing.
7. **Never report a metric you didn't compute.** Numbers come from code that ran on a held-out set. No estimates, no "approximately," no inflation.
8. **Be explicit about mocked vs. real.** Clearly label any mocked/stubbed behavior in code comments, commit messages, and the README. Never present a mock as working functionality.
9. **Pin everything.** Use the lockfile; don't float versions.
10. **Synthetic-only guard.** Before any commit, confirm no real data slipped in (see §9). When in doubt, treat data as real and exclude it.

---

## 9. Known Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **Confidential data leak** (real HT Micron reports/names committed) | Hard rule: synthetic only. `.gitignore` real-data dirs; a **pre-commit hook** scanning staged files for likely real data (employee-name patterns, "HT Micron", attachments); README states the policy; never paste a real report into the repo or an issue. |
| **Vision-API cost at scale** | Trivial at current volume (~1 report/day). Document the scaling story: hybrid (cheap OCR for any printed regions, VLM only for handwriting) and collapsing transcribe+extract into one call as cost mitigations — design `VisionClient` so these are swappable without touching the pipeline. |
| **False positive → unnecessary email** | The human gate exists precisely for this; **never auto-send**. Track false-routing rate in evals; surface low-confidence classification to the reviewer. |
| **Over-claiming in interviews** ("multi-agent AI!") | Build the honest narrative in (§2): it's a staged pipeline; be ready to say where multi-agent *would* apply. Accuracy of self-description is part of the portfolio. |
| **Synthetic-data validity overstates real performance** | Caveats written into README/EVAL_REPORT (§4): font-handwriting upper bound; synthetic-label circularity for classification; transcription/extraction as the meaningful evals. |
| **PII inside incident text** (even synthetic forms describe people) | Treat incident descriptions as sensitive by convention: don't log raw transcription at INFO level in shareable logs; redact in any committed example. Demonstrates enterprise data-handling instinct. |
| **Schema drift / hardcoding** | `config-schema-authoring` skill + a test that fails if routing/field logic is hardcoded instead of config-driven. |
| **Silent extraction errors slipping past review** | The critic's **error-flag recall** is a first-class metric (§6); tune the confidence threshold so real errors are flagged even at the cost of some extra human checks. |

---

### How to start (first command to the human if anything is unclear)
Re-read §1. If scope is clear, begin at **M0** and do not skip a milestone's DoD. If a library API, model ID, or requirement is uncertain, apply §8 rule 6: **stop and ask.**
