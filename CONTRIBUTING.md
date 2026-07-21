# Contributing to Security Shift Intake

Security Shift Intake is an evidence-review system for sensitive operational documents.
Changes are welcome when they preserve its conservative trust model: extraction is evidence,
uncertainty stays visible, and a human remains responsible for every consequential decision.

## Supported product boundary

The supported v1 path processes one single-page `controle_ocorrencias` PDF or image on the
operator's machine. It provides a local, single-user review cockpit, standardized CSV output,
a copy-ready message, and a terminal **delivery simulation**.

Authentication, network deployment, real delivery adapters, multi-page aggregation, advanced
XLSX, agent loops, RAG, and model training are separate future projects. Do not introduce them
as incidental changes.

## Non-negotiable invariants

1. Missing or ambiguous evidence remains `unknown`; it must never become “no occurrence.”
2. `none` requires explicit human confirmation and zero occurrence rows.
3. `present` requires one to ten structurally valid occurrence rows.
4. Every edit records human provenance and advances the revision.
5. Approval, export, and simulation bind to the current revision, content hash, report type,
   and configuration fingerprint.
6. Editing approved content revokes the previous approval.
7. CSV cells beginning with formula-control characters remain neutralized.
8. The unauthenticated web application is loopback-only. Network exposure is unsupported.
9. Repository fixtures and public artifacts are synthetic. Real sheets stay under the
   gitignored `private/` boundary.
10. Metrics and product claims must be reproducible from catalogued evidence; a mock is never
    presented as a measured reader result.

## Development setup

Use the pinned Python release and the checked-in lockfile:

```console
uv sync --locked --python 3.11.15 --all-groups
```

Run the canonical local gates before requesting review:

```console
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy src data scripts evals
uv run --locked pytest
uv run --locked python -m scripts.privacy_check
```

Run `uv run --locked pip-audit --local --strict --progress-spinner off` whenever dependency
resolution is available. Do not claim a clean vulnerability audit when that command could not
run.

## Change discipline

- Start from a clean worktree and inspect the current architecture before editing.
- Keep changes small, independently testable, and expressed as Conventional Commits.
- Add or update tests with the behavior they protect. Prefer deterministic local fixtures.
- Keep business rules out of route handlers and templates. Web adapters parse and present;
  application services orchestrate; domain modules decide; infrastructure performs I/O.
- Treat OCR/VLM output as untrusted, layout-coupled evidence. Preserve source, method,
  confidence, probable page region, and correction history where available.
- Use the lockfile. Do not invent library APIs or model identifiers; verify installed versions
  and official documentation first.
- Never weaken CSP, same-origin checks, request limits, TrustedHost, path confinement, escaping,
  or `no-store` protections to make a test pass.
- Never add `innerHTML`, `eval`, inline event handlers, sensitive browser storage, remote fonts,
  analytics, CDNs, or hidden outbound requests.
- Never push, rewrite history, or move release tags on another contributor's behalf.

## Evidence and release records

Files catalogued under `docs/evals/` are evidence, not marketing copy. Preserve their exact
bytes and hashes. Publishing a new release artifact requires the repository's write-once
publisher, the expected commit identity, and the evaluation protocol documented in
[`docs/EVAL_RELEASE.md`](docs/EVAL_RELEASE.md).

Historical reader failures remain historical. A new reader is promoted only after it passes the
same frozen structural-safety contract. Synthetic safety gates do not prove accuracy on real
corporate handwriting.

## Privacy checklist

Before every commit that touches documents, fixtures, screenshots, generated outputs, or logs:

- confirm that every tracked sample is synthetic;
- inspect staged filenames and content for names, identifiers, addresses, coordinates, or
  operational details;
- keep databases, page images, quarantine data, curation records, and real sheets under
  `private/`;
- run `uv run --locked python -m scripts.privacy_check`;
- stop and exclude the material when its provenance is uncertain.

## Review checklist

A review is complete only when the relevant behavior is exercised, failure states are explicit,
and the worktree contains no unrelated generated artifacts. For security-sensitive changes,
include regression coverage for loopback confinement, same-origin mutation, input limits, CSP,
escaping, traversal protection, revision/hash checks, and fail-closed occurrence semantics.
