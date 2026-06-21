# CLAUDE.md — security-shift-intake

> Condensed operating rules for this repo. The authoritative source is
> [`PROJECT_SPEC.md`](PROJECT_SPEC.md) — when anything here is ambiguous or conflicts with
> reality, **stop and ask the human** (§8.6). Do not improvise around the spec.

## Scope (§1) — the North Star

**What this is:** a **configurable, staged document-intake pipeline** that turns a scanned,
handwritten security shift-report PDF into (a) a faithful transcription, (b) structured
fields, (c) a classification (type / urgency / responsible sector), and (d) a routed,
pre-filled email **draft**. It is an internal triage tool to **reduce transcription load and
surface uncertainty** — not to achieve autonomy.

**What this is NOT (anti-scope-creep):**
- ❌ Not "autonomous multi-agent." It is a **staged pipeline** (deterministic stages). No
  agent loops, planners, or tool-using agents.
- ❌ Not an auto-sender. **Email is never sent without explicit human approval. No exceptions.**
- ❌ Not multi-tenant SaaS. One report type, one org config — abstraction lives in the
  *structure*, only one config is populated.
- ❌ Not trained on or storing **any real HT Micron data**. **Synthetic data only.**

**Non-negotiable invariants:**
1. **Human approval gate** before any irreversible action (send email, write to a system of record).
2. **Synthetic data only** in the repo. No real reports, names, or photos. Ever.
3. **No fabricated metrics.** Every number in a README/report is produced by code that ran.
4. **Config-driven, not hardcoded.** Fields, taxonomy, routing, and email templates live in
   YAML, not in `if` statements.

## Anti-Hallucination Protocol (§8) — follow on every task

1. **Verify library versions before using version-specific APIs** (`uv pip show <pkg>` + the
   docs for *that* version). Don't assume.
2. **Never invent a method, parameter, or model name.** If you can't confirm it, **stop and
   say so** — don't guess a plausible signature.
3. **Confirm the model API before coding the call.** Current model IDs and request/response
   shapes change — check official docs. Put the model ID in **config**, not scattered literals.
4. **Tests with or before implementation.** No stage is "implemented" without a test. **Mock
   the model layer** so tests are deterministic and cost $0.
5. **Run the code before declaring a step done.** Paste the actual command and its real
   output. "Should work" is not done.
6. **Stop and ask when ambiguous.** One crisp question beats building the wrong thing.
7. **Never report a metric you didn't compute.** Numbers come from code on a held-out set.
8. **Be explicit about mocked vs. real** in code, commits, and the README. Never present a
   mock as working functionality.
9. **Pin everything.** Use the lockfile (`uv.lock`); don't float versions.
10. **Synthetic-only guard.** Before any commit, confirm no real data slipped in. When in
    doubt, treat data as real and exclude it.

## Build discipline (how we work here)

- Work proceeds in **milestones (M0–M8)**; each has a **Definition of Done** that only counts
  when its command runs and produces the stated output (`make lint typecheck test`, etc.).
- Inside each milestone, work in **small tested micro-steps**: one isolated change → a test
  covering it (mocked) → run the real command and confirm output → only then advance. This
  keeps any regression attributable to the last step.
- DoD task runner is `make`. Tests run via `uv run pytest`. Provider calls go through
  `VisionClient` / `LLMClient` and are mockable.
