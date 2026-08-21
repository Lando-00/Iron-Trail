# IronTrail - AI Agent Guide

IronTrail is a personal Hevy workout dashboard and AI training coach. Start
with `CONTEXT.md`, `README.md`, `CONTRIBUTING.md`, and `ROADMAP.md` before
making a change.

## Operating rules

- `feature/azure-hosting` is the active, de-facto trunk branch. `main` lags
  significantly behind it and should not be assumed current.
- There is no CI. `pytest` and `ruff` runs are local-only validation gates.
  Ruff has a pre-existing non-zero baseline of errors across the repo — check
  that files you touched don't add new violations rather than mass-reformatting
  or "fixing" unrelated pre-existing errors.
- Keep the local mode as the default: real workout data stays on the user's
  machine and `data/raw/` remains gitignored.
- Do not commit real workout data, generated Vault notes, credentials, Azure
  secrets, or captured private-beta artifacts.
- Preserve the separation between local mode and the separately gated Azure
  cloud mode. Do not weaken Easy Auth, user isolation, retention, export/delete,
  or usage-budget boundaries.
- Keep the long-format, one-row-per-set DataFrame as the canonical ingest shape.
- Keep Streamlit pages self-contained and shared rendering primitives in the
  existing UI helpers.
- For larger changes, open a GitHub issue before implementation.
- Use Python 3.12 conventions, `ruff`, and `pytest`; run deployment validation
  for Azure or container changes.
- Deploy only from a clean Docker context. `azd deploy` packages the working
  directory, including untracked files not covered by `.dockerignore`.

## Source of truth

- Domain vocabulary and boundaries: `CONTEXT.md`
- User-facing behaviour: `README.md`
- Project scope and deferred work: `ROADMAP.md`
- Contribution and validation rules: `CONTRIBUTING.md`

## Agent skills

### Issue tracker

Issues and specifications live in GitHub Issues for `Lando-00/Iron-Trail`.
Use the authenticated `gh` CLI for tracker operations. See
`docs/agents/issue-tracker.md`.

### Triage labels

Use the canonical `needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, and `wontfix` labels. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. Read `CONTEXT.md` before changing
analytics, data flow, coach behaviour, Vault writeback, or cloud boundaries.
See `docs/agents/domain.md`.

### Azure operations

The private beta uses AZD/Bicep and an existing Foundry account. Always use the
subscription selected by the beta AZD environment, preserve fail-closed
what-if validation, and treat data-plane RBAC as separate from subscription
Owner. See `docs/agents/azure-operations.md`.
