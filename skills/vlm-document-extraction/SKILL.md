---
name: vlm-document-extraction
description: >
  Use for every vision/LLM call in this project — transcription, structured
  extraction, classification. Enforces one mockable client interface, structured
  output validated by Pydantic, per-field confidence, the validate/critic pattern,
  and verifying the model API before writing the call.
---

# VLM / LLM Document Extraction

A consistent contract for all model calls. Follow it every time.

## Always go through the client interface

- Every model call goes through `VisionClient` / `LLMClient` (`src/clients/`).
  **Never** scatter raw `anthropic.Anthropic()` calls through the pipeline.
- This keeps the provider swappable and, above all, **mockable in tests** — tests
  use `MockVisionClient`, run offline, and cost $0.

## Always request structured output, validated by Pydantic

- For extraction/classification, request structured output and validate it with a
  Pydantic model (the typed contract between stages).
- Return **per-field confidence**, not just values — the critic needs it.
- Add a **retry/repair** step for malformed structured output (one re-ask before
  failing), so a single bad JSON response doesn't crash the stage.

## The validate / critic pattern (deterministic, in code)

After extraction, run a deterministic check — schema validity (types, required,
allowed enum values) **plus** confidence thresholding — and flag failing or
low-confidence fields as `MUST_REVIEW`. This belongs in code, not a second LLM.

## Verify the model API before writing the call (§8.2, §8.3)

- **Confirm the current model ID and the request/response shape in the official
  docs before coding the call** — model names and params change. Put the model ID
  in **config** (`src/clients/settings.py`), never as a scattered literal.
- Never invent a method, parameter, or model name. If you can't confirm it, stop
  and say so.

## Mock vs. real — always labelled (§8.8)

Clearly label any mocked/stubbed behavior in code comments, commit messages, and
the README. Never present a mock as working functionality. Real calls are
validated by running them (`make demo-transcribe`) — not by "should work".
