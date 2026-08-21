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
- **Coach**: the review pipeline that builds a structured statistical summary,
  obtains bounded prose from an LLM, and renders the final Markdown/PDF output.
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
- Numeric facts in reviews come from the structured summary; the LLM supplies
  reflections and prose, not authoritative measurements.

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
