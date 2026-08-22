# Reader decision and experiment history

Security Shift Intake v1.1 supports Tesseract 5 with the Portuguese language pack as its only
document reader. It is a local baseline for producing review evidence; it does not imply
reliable cursive-handwriting recognition.

The product remains useful when reading is weak because uncertainty stays visible. Missing or
ambiguous content blocks operational readiness, a person supplies the required values, and the
approved revision remains tied to the verified page bytes.

## Why this baseline remains

- It runs locally on the supported Windows workstation and pinned Ubuntu CI environment.
- It does not transmit a document to a reader service.
- Its dependency and runtime identity can be recorded and reproduced.
- Word geometry can point the reviewer to probable evidence on the exact OCR surface.
- Its failure mode is review work, not silent permission to export an uncertain draft.

The v1.1 release decision is governed by the structural-safety gates in
[`EVAL_RELEASE.md`](EVAL_RELEASE.md). Reader-quality observations explain correction effort, but
they cannot override a fail-closed gate.

## Conclusions preserved from earlier experiments

Earlier commits explored other local readers and handwriting diagnostics. They are not runtime
options in v1.1, and their old measurements are not current release evidence.

- One small multimodal prototype produced more false incidents and more correction work than
  the Tesseract baseline on the synthetic comparison.
- Larger multimodal variants did not fit the reference hardware and native-Windows dependency
  boundary.
- A separate OCR prototype detected regions but did not reconstruct usable table rows. Its low
  incident count resulted from empty output, so it was not promoted.
- A public handwriting diagnostic offered useful direction but did not match the occurrence
  form domain and was never a release gate.
- Private real-sheet diagnostics were too small and sensitive to support a public accuracy
  claim.

The annotated [`v1.0.0`](https://github.com/JoaoMiltzarek/security-shift-intake/tree/v1.0.0)
snapshot and the repository's Git history retain the detailed experimental implementation and
reports. The active v1.1 tree keeps only this concise conclusion so retired prototypes are not
mistaken for supported features.

## Rule for a future reader

A candidate reader must be evaluated before adoption against a versioned validation corpus and
a declared reference runtime. Its acceptance thresholds must be committed before the decisive
run. The candidate must:

1. preserve every operational safety invariant;
2. execute every validation input with authenticated corpus and runtime metadata;
3. run on the supported local platform without an incompatible dependency stack;
4. improve correction effort without winning by returning empty or structurally unusable
   output; and
5. keep document handling inside the declared privacy and deployment boundary.

Adopting a reader is a separate versioned change. It does not expand v1.1 into cloud processing,
autonomous classification, or unattended export.
