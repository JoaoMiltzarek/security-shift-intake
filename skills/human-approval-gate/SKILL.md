---
name: human-approval-gate
description: >
  Use for any irreversible action (sending an email, writing to a system of
  record). Enforces the reusable safety pattern: a pending → approved/rejected
  state machine, an execute step that asserts status == approved, a mandatory
  audit log, and a test proving an unapproved item cannot be executed.
---

# Human Approval Gate

The project's #1 non-negotiable invariant: **no irreversible action without
explicit human approval.** Never auto-execute, never bypass the gate "for
convenience."

## The state machine

```
pending ──approve──▶ approved ──send──▶ (sent)
   └─────reject────▶ rejected
```

- New items start `pending`.
- A human moves them to `approved` or `rejected`.
- The execute step (send email / write to system of record) runs **only** from
  `approved`.

## Rules

1. **The execute step asserts `status == approved`** and is otherwise blocked.
   Blocking is a hard failure (raise / HTTP 409), not a silent no-op — and the
   downstream side effect (the actual send) must not run.
2. **Every state change writes an audit row** (who / what / when). Submissions,
   approvals, rejections, sends, and *blocked* attempts are all audited.
3. **Persisted state is the source of truth** for the gate — not a UI flag, not
   an in-memory boolean. A real state machine, backed by the database.
4. **There must be a test proving an unapproved item cannot be executed** — that
   a `pending`/`rejected` item fails to send and the sender is never called.

## In this repo

- Status lives on the persisted `Draft` (`src/api/models.py`); the gate is
  `src/api/gate.py`; audit rows are `AuditEntry`.
- Sending goes through a `Sender` interface (mockable). The mock records sends so
  tests can assert the side effect did or did not happen.
- Mock vs. real sending is always labelled (§8.8). The gate logic is identical
  for both.
