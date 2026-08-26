# Coach chat retrieves through a typed query surface, not model-authored SQL

Coach chat used to receive one pre-built context dict assembled from a keyword
guess at which exercises the question mentioned, so any question needing a slice
nobody anticipated was answered with "that isn't in the loaded summary". We
replaced the guess with a **query surface**: an enumerated menu of typed queries
the model selects from, executed in Pandas, with the results fed back for the
answer.

## Considered options

Giving the model SQL over a per-session DuckDB or SQLite view of the frame was
the obvious alternative and was rejected for two reasons. It moves the
correctness of the arithmetic into the model — a subtly wrong `GROUP BY`
produces a confident wrong PR with nothing to check it against — which
contradicts the standing rule that numeric facts come from deterministic
computation. It also hands the model an unbounded read of every column,
including the free text that ADR-0002 excludes. A persisted database was
rejected separately: it is a new user-data surface in cloud mode that the
existing blob retention rules do not cover, and it contradicts the long-format
DataFrame remaining canonical.

## Consequences

The model chooses *which* query but never authors one, so an unrecognised query
name or argument is a typed error rather than a silently empty result set. That
error is returned to the model as a query result, so a miss becomes something
the Coach can state honestly instead of an invisible gap.

Retrieval runs as a provider-agnostic text protocol — the model emits a query
batch as JSON in its normal reply — rather than native OpenAI tool calling.
This is forced by local mode: `CopilotProvider` flattens all messages into a
single `send_and_wait` string and denies every tool permission by design, so
native tool calling is structurally impossible there. Local mode is the default
and must not be the worse product. The text protocol also lets `MockProvider`
script a query batch, so the whole loop is exercised in `pytest` offline
instead of only in production.

Queries are batched into a single round, giving a fixed two provider calls per
question, with one repair round reserved for a malformed batch. Because
allowance is counted in questions rather than calls, the per-user chat call
limit must cover that worst case while the user-facing figure stays unchanged.
