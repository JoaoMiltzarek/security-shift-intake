---
name: security-shift-intake-patterns
description: Coding, commit, and testing conventions extracted from the security-shift-intake git history — apply when contributing to this repo.
version: 1.0.0
source: local-git-analysis
analyzed_commits: 121
---

# Security Shift Intake — Repository Patterns

Patterns mined from this repo's git history (121 commits) and tree. Follow them when
contributing; when a pattern conflicts with current repository documentation or an
explicit user instruction, the current instruction wins.

## Commit Conventions

Conventional Commits with a **required ticket scope**, message in Portuguese, third-person
present tense, and **no Claude co-author trailer** (0 of the last 200 commits carry one):

```
<tipo>(SSI-<n>): descrição no presente
```

- Types seen (by frequency): `feat`, `fix`, `docs`, `chore`, `test`, `ci`, `build`, `refactor`.
- Scope is the Jira-style ticket derived from the branch name (`SSI-1002`, `SSI-1001` dominate).
- **One commit per micro-step** — a code change and the test that covers it land together;
  never bundle unrelated changes.
- Do **not** push — the human pushes. Run the gate before every commit (below).

## Code Architecture

```
src/
├── api/            # FastAPI app + approval gate, repository, page-image serving
├── clients/        # VisionClient / LLMClient providers (+ mocks) — the mockable boundary
├── pipeline/       # deterministic stages: ingest → transcribe → extract → normalize → validate → outputs
├── schema/         # Pydantic models + config loader (config-driven, not hardcoded)
├── classifier/     # routing/classification model
└── orchestrator.py # branches by config; applies the OCR quality gate
configs/*.yaml      # report types (controle_ocorrencias, htmicron_security) — behavior lives here
scripts/            # CLIs + guards (privacy_check, check_real_data, preflight, demo_pipeline)
evals/              # reproducible metric harnesses (no hand-typed numbers)
ui/{templates,static}  # HTMX review cockpit, vendored assets (no CDN, offline)
tests/              # flat test_*.py (61 files)
private/            # gitignored — the ONLY place real data / PII may live
```

Key invariant: the **anti-corruption boundary** `RawDocumentExtraction` ↔
`NormalizedIncidentModel` (single crossing at the `normalize` stage). The domain stays stable
as sheet layout changes.

## Workflows

### Add a pipeline stage or fix
1. Write/extend the mocked test first (`tests/test_<stage>.py`).
2. Implement the smallest change in `src/pipeline/<stage>.py` (or the owning package).
3. `make check` (ruff + mypy strict + pytest) and `make privacy-check` — both green.
4. Commit as `feat|fix(SSI-<n>): …`.

### Add a report type
- Write a new `configs/<type>.yaml` + output template. **No domain code change** — the
  orchestrator branches on config.

### Provider (Vision/LLM) work
- Implement against the `VisionClient` / `LLMClient` protocol; keep tests on the **mock**
  (`MockVisionClient` / `MockLLMClient`) so they are deterministic and cost $0.

## Testing Patterns

- Location/naming: flat `tests/test_*.py` (one per module/feature); pytest, `pythonpath = ["."]`.
- **Everything mocked, offline, $0** — the model layer never runs in tests.
- Gate = `make check` = `ruff check .` + `mypy src data scripts` (strict) + `pytest`.
- Hermetic guards use `tmp_path`; environment-dependent tests (real Tesseract) **skip cleanly**
  via `tesseract_available()`, never fail.
- **No fabricated metrics** — numbers come from `make eval` / evals on held-out data.

## Guardrails (non-negotiable)

- Synthetic data only in the repo; real sheets/PII live only in `private/` (gitignored).
- `make privacy-check` must pass before commit (no tracked binaries/DBs, no PII in public text).
- Human approval gate before any irreversible action; email is never auto-sent.
- Run the code and paste real output before calling a step done — "should work" is not done.
