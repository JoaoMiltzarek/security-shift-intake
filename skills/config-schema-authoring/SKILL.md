---
name: config-schema-authoring
description: >
  Use when adding or changing a report-type config, or anything touching fields,
  taxonomy, routing, or email templates. Keeps the system config-driven: the YAML
  structure is validated by a Pydantic schema-for-the-schema, routing rules are
  data (not code), and adding a report type is a new YAML + template with no
  pipeline code change.
---

# Config Schema Authoring

The whole point of the abstraction: **adding a new company/report type = a new YAML
file + a new email template, with no change to pipeline code.** Guard that.

## The YAML structure (`configs/<report_type>.yaml`)

```yaml
report_type: <slug>
fields:                       # one entry per form field
  - {name: ..., type: date|string|enum|bool|text, required: bool, handwritten: bool}
  - {name: ..., type: enum, values: [...]}        # enum REQUIRES values
classification:
  type:    {labels: [...]}
  urgency: {labels: [...]}
  sector:  {labels: [...]}
routing:                      # data, not code — evaluated in order, first match wins
  rules:
    - when: {urgency: critical}      -> [recipient_a, recipient_b]
    - when: {type: theft}            -> [...]
    - default                        -> [...]     # required, must be last
email_template: templates/<name>.j2
```

## Rules

1. **Validate the config with a Pydantic model** — the "schema-for-the-schema"
   (`src/schema/config.py`, `ReportConfig`). `make validate-config` must pass for a
   valid file and fail with a clear error for an invalid one. Cover both with tests.
2. **Routing rules are data, not code.** Never encode a recipient decision in an `if`
   statement — it belongs in the YAML `routing` block. The pipeline only *applies*
   the rules (`src/pipeline/route.py`).
3. **A default routing rule is mandatory** (catch-all, `when: null`, last) so every
   classification routes somewhere.
4. **enum fields require `values`**; the critic validates extracted values against them.
5. **Adding a report type must not touch pipeline code.** If a change requires editing
   `src/pipeline/*` to support a new field/route, that's a smell — push it into config.
   **Flag any PR that hardcodes field or routing logic.**

## Checklist

- [ ] New/changed config validates via `make validate-config`.
- [ ] An invalid variant fails with a clear, actionable error (tested).
- [ ] Routing has a default rule; specific rules are ordered most-specific-first.
- [ ] No field/routing logic leaked into `src/pipeline/` or `if` statements.
- [ ] A matching `email_template` exists for the configured path.
