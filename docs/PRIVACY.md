# Privacy boundary

Security shift sheets can contain names, locations, schedules, and incident details. The
supported v1 workflow keeps document processing on the operator's machine and keeps real
inputs and review state outside the repository.

## Supported deployment

- Tesseract OCR and deterministic triage run locally. The supported flow has no network
  reader or delivery adapter and does not upload a sheet.
- The FastAPI UI has no authentication. Run one process for one operator on
  `127.0.0.1`; do not expose it to a LAN, reverse proxy, or public host.
- `GET /drafts/{id}` includes review content. Anyone who can reach the local port can read
  it, so loopback binding is part of the security contract.
- Real inputs, SQLite state, page artifacts, and detailed audit output belong under
  `private/`, which is excluded from Git.

## What the automated checks do

`make privacy-check` reports configured indicators; it does not prove that arbitrary text
contains no personal or confidential information.

The check:

- rejects tracked databases and non-allowlisted document/image binaries;
- rejects sensitive binaries outside the repository-root `private/` boundary;
- rejects redirected public paths, including symlinks and Windows reparse points;
- scans public prose for organization sentinels, clock-like values, local home paths, and
  literal terms from the optional `private/pii_terms.txt` file;
- scans code and data for the same configured terms, except that clock-like values are
  allowed in code fixtures;
- treats a private term as synthetic in code only when that same term is declared by the
  versioned generators under `data/generators/`; the exemption never applies to public
  prose;
- fails closed when a scanned text file or its synthetic provenance cannot be read as
  UTF-8.

The pre-commit guard in [scripts/check_real_data.py](../scripts/check_real_data.py) inspects
staged Git blobs rather than mutable worktree copies. It blocks sensitive file types,
redirected paths, configured text indicators, and unreadable staged content. Generated
showcase media is allowed only by exact repository-root paths.

These checks are defense in depth. They cannot infer context, recognize every name, inspect
encrypted content, guarantee secure deletion, or replace a human review of the staged diff.

Release reporting is limited to allowlisted, value-free public evidence: aggregate metrics,
pseudonymous per-sheet counters, paired outcome labels, and synthetic examples. Detailed
transcriptions, field values, OCR snippets, source paths, and review records remain private.

## Handling a real sheet

1. Put the input under `private/reais/`.
2. Run the local intake and review the evidence in the loopback UI.
3. Confirm or correct the disposition and classification before approval. The final action
   is a local simulation; it does not send email, messages, or files.
4. Remove generated review state with `make purge-demo-data`.
5. Remove copied real inputs with `make purge-real-data CONFIRM=YES`.
6. Run `make privacy-check` and inspect `git diff --cached` before committing.

The purge commands remove named filesystem entries; this is not a secure erase and does not
overwrite storage blocks; backups, snapshots, synchronized copies, and storage remnants require
the operator's normal data retention and sanitization process.
