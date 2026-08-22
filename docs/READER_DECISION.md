# Reader experiments and the v1.1 decision

Security Shift Intake v1.1 uses Tesseract 5 with the Portuguese language pack as its
only document reader. It is a local baseline and does not imply reliable cursive
handwriting recognition. The product stays safe by treating OCR as evidence for human
review and by keeping approval, export, and simulation behind explicit checks.

## Why this baseline remains

- It runs locally on the project's Windows reference machine and on the pinned Linux
  CI environment.
- It has a small, auditable dependency surface and does not transmit document bytes.
- Its limitations are visible in the review workflow: low-quality or incomplete
  readings remain blocked until a person supplies the required values.
- The v1.1 release corpus measures operational safety, not handwriting mastery.

The release gates require all committed validation sheets to run and require:

- `unsafe_clean=0`;
- `unsafe_approvable=0`;
- `unsafe_exportable=0`;
- `false_incident_unreviewed=0`;
- `safe_review_recall=1.0`.

Reader quality metrics remain useful for understanding correction effort, but they do
not replace those fail-closed operational gates.

## What the retired experiments taught us

The repository history preserves the implementation and detailed measurements from
the following experiments. They are not runtime options in v1.1.

- A local Qwen 2.5 VL 3B experiment fit the reference GPU at reduced resolution, but
  produced more false incidents and more human correction work than Tesseract.
- The 7B variant and PaddleOCR-VL did not fit the reference hardware and native-Windows
  constraints.
- A CPU PaddleOCR experiment detected text regions but did not reconstruct table rows.
  Its apparently low false-incident count came from producing no usable occurrence
  rows, so it was not promoted.
- BRESSAY was a useful directional handwriting check, but its student-essay domain did
  not match the occurrence form and it was never a release gate.

These conclusions explain the narrow v1.1 scope without keeping model adapters,
third-party benchmark harnesses, or historical reports in the active product tree.

## Rule for a future reader

A candidate reader must be evaluated before adoption against a versioned validation
corpus and a declared reference runtime. It must:

1. preserve every operational safety invariant above;
2. run on the supported local platform without an incompatible dependency stack;
3. execute every validation input with authenticated runtime and corpus metadata;
4. improve correction effort without winning by returning empty or structurally
   unusable output;
5. be integrated only after the acceptance thresholds are committed.

The existing `v1.0.0` tag and earlier commits retain the full experimental record.
This document is intentionally the concise public conclusion.
