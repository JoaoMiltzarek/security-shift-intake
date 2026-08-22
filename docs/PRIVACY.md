# Privacy boundary

Security shift sheets can contain names, locations, schedules, access details, and incident
descriptions. Security Shift Intake is designed to process those documents on one trusted
workstation, but repository checks cannot prove that arbitrary sensitive information is absent.
Privacy therefore depends on both technical controls and deliberate operator review.

## Supported handling model

The supported v1.1 flow uses local Tesseract OCR, deterministic rules, a loopback review UI,
SQLite, and local page artifacts. It has no network document reader or real delivery adapter and
does not intentionally upload a sheet.

That statement applies only to the project-controlled path. Operating-system telemetry,
backups, synchronized folders, shell history, antivirus, browser extensions, screenshots, and
other software on the workstation are outside the application's control.

The UI has no authentication. Anyone who can reach its port can read review content, so one
process on loopback is part of both the security and privacy contract.

## Material that stays private

Keep all of the following under the ignored repository-root `private/` tree or another approved
non-repository location:

- real PDF or image inputs;
- reader-sized page artifacts and OCR geometry;
- SQLite databases and sidecars;
- transcriptions, extracted field values, review edits, and audit details;
- real-sheet curation and detailed evaluation output;
- local logs, screenshots, exports, and delivery simulations that contain document content;
- `private/pii_terms.txt`, when used to add local detection terms.

Do not put real or uncertain material in `samples/`, `assets/`, `docs/`, test fixtures, GitHub
Actions artifacts intended for publication, issues, or commit messages.

## What the automated guards enforce

`make privacy-check` and the pre-commit guard are defense in depth. Together they:

- reject tracked databases and non-allowlisted document or image binaries;
- permit public sample media only at reviewed repository-relative paths with exact SHA-256
  identities;
- reject sensitive binaries outside the canonical `private/` boundary;
- resolve paths and reject public symlinks or Windows reparse points that redirect content;
- scan public prose for configured organization terms, clock-like values, home-directory paths,
  and literal terms from `private/pii_terms.txt`;
- inspect staged Git blobs rather than trusting a different mutable worktree copy;
- fail closed when staged or scanned text cannot be decoded and inspected;
- allow a private term inside code or generated data only when the versioned synthetic
  generators declare the same exact value as fictional provenance.

The synthetic exemption is intentionally narrow. It does not apply to public prose, arbitrary
fixtures, comments claiming that a value is fake, filename patterns, or an entire directory.

## What the guards cannot prove

Passing the checks does not prove that content is anonymous, non-sensitive, licensed, or safe to
publish. The checks cannot reliably:

- recognize every personal name, address, badge, plate, unit, or free-form identifier;
- understand whether an otherwise ordinary phrase reveals an operational fact;
- inspect encrypted, compressed, corrupted, or unsupported content semantically;
- detect text rendered only inside an allowlisted image;
- establish consent, authorization, data ownership, or retention obligations;
- securely erase storage blocks, backups, snapshots, synchronized copies, or exported files.

A human must review every staged path and diff. When provenance is uncertain, exclude the
material.

## Public evidence allowlist

Public release evidence is constructed from an explicit schema, not by deleting fields from a
detailed report. It may contain:

- aggregate metrics from the committed synthetic corpus;
- pseudonymous per-sheet counters and paired outcome labels;
- runtime, corpus, manifest, commit, and workflow identities;
- synthetic examples whose exact bytes are independently reviewed and hash-allowlisted.

It must not contain source values, OCR snippets, transcriptions, names, identifiers, real paths,
review notes, or correlatable real document IDs. Detailed diagnostics remain private even when
the aggregate run is publishable.

## Handle a real sheet locally

1. Confirm that you are authorized to process the document.
2. Put it under `private/reais/`.
3. Run the local intake and keep the server on loopback.
4. Confirm or correct disposition, fields, and classification before approval.
5. Export only when the destination and retention are appropriate.
6. End the session and remove generated review state.

```console
make purge-demo-data
make purge-real-data CONFIRM=YES
make privacy-check
git diff --cached
```

The purge commands remove named filesystem entries. This is logical removal, not a secure erase;
it does not overwrite storage blocks or remove backups, snapshots, synced copies, shell history,
or exports. Follow the workstation's approved retention and media-sanitization process for those
copies.

## Before every public commit

- Confirm that each public binary is synthetic and listed by exact path and hash.
- Review `git diff --cached --name-status` and `git diff --cached`.
- Run `make privacy-check` against the staged state.
- Check generated metadata, logs, screenshots, and alt text as carefully as source code.
- Stop if a check cannot read content or if provenance cannot be established.

See [`../SECURITY.md`](../SECURITY.md) for the supported deployment boundary and private
vulnerability reporting channel.
