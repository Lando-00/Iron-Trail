# Contributing

IronTrail is a personal project I share publicly because it might be useful
to someone else who logs in [Hevy](https://hevyapp.com). PRs and issues are
genuinely welcome — particularly for:

- **Exercise muscle-map additions.** `data/lookups/exercise_muscle_map.csv` is
  the single biggest source of "this should be mapped but isn't" gaps.
  Add rows for any exercise the dashboard flags as `unmapped` in the
  Overview page's expander.
- **Bug fixes.** Especially around locale-specific date parsing, unusual
  Hevy export edge cases, or anything that crashes a page.
- **Theme + UI polish.** The custom theme in `iron_trail/theme.py` and
  helpers in `iron_trail/ui.py` are deliberately minimal — tasteful tweaks
  welcome.
- **Additional achievement badges.** The 20-badge library in
  `iron_trail/analytics.py` is happy to grow.

## Larger changes

For anything bigger — new pages, new analytics, restructuring the data
pipeline — please **open an issue first** so we can talk it through before
you spend time on it. The project has opinions about what it does and
doesn't want to be (see [`ROADMAP.md`](./ROADMAP.md) and the non-goals
section of the project plan).

Before a larger contribution, read [`CONTEXT.md`](./CONTEXT.md) for domain
vocabulary and boundaries, then [`ROADMAP.md`](./ROADMAP.md) for deliberately
deferred work. Agent-assisted contributors should also follow
[`AGENTS.md`](./AGENTS.md) and the focused guides under
[`docs/agents/`](./docs/agents/).

## Style

- **Python.** `ruff` config in `pyproject.toml`, line length 100,
  type-hinted, `from __future__ import annotations`.
- **Pandas.** Long-format DataFrame (one row per set) is the canonical
  shape — see `iron_trail/ingest.py`. Don't introduce a parallel wide-format
  pipeline.
- **Streamlit.** Pages are self-contained — sidebar + load + render. Shared
  rendering primitives live in `iron_trail/ui.py`.
- **Tests.** Run `python -m pytest -q` and `ruff check .`. For deployment
  changes, also build the Docker image and compile the Bicep entry point.
  There is no CI, and `ruff check .` has a pre-existing non-zero baseline of
  errors across the repo — verify the files you changed don't add new
  violations rather than mass-reformatting or fixing unrelated pre-existing
  errors.

## Don't

- **Don't commit real workout data.** `data/raw/*` is gitignored for a
  reason. Sanity-check `git status` before any PR.
- **Don't add heavy native dependencies.** The project deliberately runs on
  x64 Python under Windows-on-ARM emulation so it works on a Surface Pro
  without a build toolchain.
