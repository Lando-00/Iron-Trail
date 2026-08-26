# IronTrail Domain Context

IronTrail is a personal Hevy workout dashboard with an AI training coach. It
turns exported workout CSV data into deterministic analytics, playful but
bounded dashboard views, and optional Markdown writeback to an Obsidian Vault.

## Core vocabulary

- **Workout**: one exported Hevy session with its exercises, sets, notes,
  duration, and timestamp.
- **Set**: the canonical long-format unit in the ingest DataFrame.
- **e1RM**: estimated one-rep max used for strength trends and PR detection.
- **Tonnage**: total training load used for volume and progress summaries.
- **Session archetype**: the K-Means classification of a workout such as
  Strength, Hypertrophy, Pump, or Quick.
- **Plateau**: an exercise whose e1RM has not achieved a meaningful PR within
  the configured time window, with regression treated separately.
- **Coach**: the AI training assistant as a whole. It has two distinct
  surfaces, **Coach review** and **Coach chat**, which share a provider and a
  grounding discipline but nothing else.
- **Coach review**: the pipeline that builds a structured statistical summary,
  obtains bounded prose from an LLM, and renders the final Markdown/PDF output.
- **Coach chat**: the conversational surface, where the user asks a question in
  their own words and the Coach answers from their own training data.
- **Query surface**: the enumerated set of typed questions Coach chat may ask
  of a user's training data. The model chooses which query to run and with what
  arguments; it never authors the computation and never sees data outside the
  surface.
- **Orientation payload**: what Coach chat knows before it asks anything — the
  name of every exercise the user has logged, plus headline training stats. It
  is the vocabulary the model draws its query arguments from, so every logged
  lift appears in it and no lift is ever invented.
- **Movement pattern**: the mechanical grouping of an exercise, such as
  horizontal push or vertical pull. It cuts across primary muscle: close-grip
  bench is triceps-primary but shares its pattern with the barbell bench.
- **Related exercises**: the lifts a user has actually logged that share a
  movement pattern with a named exercise. Relatedness is mechanical, not
  muscular, and is always bounded by what the user trains.
- **Vault writeback**: explicit generation of Markdown notes under a user-
  selected output directory; it is not an implicit cloud sync.
- **Profile**: durable per-user settings that outlive a Streamlit session.
  Bodyweight is stored in `data/processed/profile.json` locally and in the
  user's reserved cloud profile row when hosted.
- **Single-slot dataset**: the one saved Hevy CSV allowed per cloud user. A new
  save completes before the previous record is pruned, so a failed replacement
  never leaves the user with no dataset.
- **Visibility isolation**: one signed-in account cannot see another account's
  saved data through the application. This is distinct from the expanded
  sentinel/export/delete/cache and suspend/restore acceptance matrix; record
  only the checks that were actually performed.

## Runtime boundaries

- **Local mode** is the default and accepts local CSV input, optional Vault
  writeback, and Copilot SDK or mock coaching.
- **Cloud mode** is separately gated by Azure authentication and authorization,
  auto-saves uploads into each user's single dataset slot by default, and has
  explicit retention, export/delete, identity, and usage-budget controls. The
  auto-save behavior can be disabled by configuration without changing local
  mode.
- Real workout data is private and must remain outside Git. Synthetic sample
  data is the safe public-demo fixture.
- The **Coach chat allowance** is counted in questions, not in provider calls.
  One question the user asks is one unit of allowance, however many calls
  answering it happens to take.
- Numeric facts come from deterministic computation over the training data;
  the LLM supplies reflections and prose, not authoritative measurements. This
  holds for Coach review and Coach chat alike.
- **Structured data** is the machine-derived fields of a set: exercise name,
  weight, reps, set type, set order, and dates. **Free text** is what a human
  typed: workout titles and descriptions, and exercise notes. Structured data
  may reach the model. Free text may not, and is treated as untrusted input
  wherever it is handled.

## Locked project shape

- The ingest pipeline remains long-format, one row per set.
- Streamlit pages remain self-contained while shared UI primitives stay in the
  existing helpers.
- Phase 1 and Phase 2 are shipped; future API, Health Connect, and other ideas
  remain deferred until actual CSV friction justifies them.
- The `/lift-review` and `/lift-recap` Copilot CLI extension is optional; the
  dashboard must remain usable without it.

## Development workflow

- `feature/azure-hosting` is the active, de-facto trunk branch; `main` lags
  significantly behind it and should not be assumed current.
- There is no CI. `python -m pytest -q` and `ruff check .` are the only,
  local-only validation gates before a change is considered done. Ruff has a
  known repository-wide non-zero baseline, so changed files must add no new
  findings; do not mass-fix unrelated code.

## Source of truth

- Product behaviour and setup: `README.md`
- Scope and deferred work: `ROADMAP.md`
- Contribution and validation rules: `CONTRIBUTING.md`
- Python configuration and test targets: `pyproject.toml`

Use this vocabulary in issues, specifications, tests, and implementation
notes. Update this file when a durable domain decision changes.
