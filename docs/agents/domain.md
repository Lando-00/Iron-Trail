# Domain Docs

IronTrail is a single-context repository.

Before exploring or changing domain behaviour:

1. Read `CONTEXT.md`.
2. Read `README.md`, `CONTRIBUTING.md`, and `ROADMAP.md` for the current
   product contract.
3. Read the relevant tests and `pyproject.toml` configuration before changing
   ingest, analytics, rendering, or deployment behaviour.

Use the vocabulary from `CONTEXT.md` in issue titles, specifications, tests,
and implementation notes. If a change affects local/cloud separation, real
data protection, Vault writeback, or Azure access boundaries, call that out
explicitly in the specification and review.
