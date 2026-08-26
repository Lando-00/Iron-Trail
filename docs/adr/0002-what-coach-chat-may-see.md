# Coach chat may see set-level structured data, but never free text

Answering questions about rep schemes and session placement requires per-set
detail, which is finer-grained than the "deterministic aggregates only" rule the
beta was launched on. We widened the boundary to **structured data** — exercise
name, weight, reps, set type, set order, dates — and simultaneously made the
exclusion of **free text** explicit: workout titles and descriptions and
exercise notes never reach the model.

## Considered options

Sending everything deterministic, notes included, was considered and rejected.
Notes are where injury and pain text lives, the beta already has a second
member, and the EU-data-zone reasoning behind the hosted deployment was built
around health data specifically. Widening that far would also require amending a
published beta commitment. An explicit user-facing opt-in for notes was the
middle option; it was deferred rather than rejected, because it adds a consent
and storage surface for a capability nobody has asked for yet.

## Consequences

`prompts.py` instructed the model to "suggest 'check in with a clinician' if
pain signals show up in the user's session notes" while notes were never in the
context — a rule that had been dead text since it was written. This decision
resolves that contradiction by deleting the rule rather than quietly enabling
it.

Free text remains untrusted input wherever it is handled, independently of
whether it reaches the model. Exercise names and workout titles are
user-controlled and are already treated as data rather than instructions; that
does not change.
