# Mobile polish — session handoff

> **Branch:** `feature/mobile-polish` · **Worktree:** `C:\Dev\active\iron-trail-mobile`
> **Base:** `feature/azure-hosting` @ `e61ba1e`
> **Owner:** a separate Copilot session running in autopilot
> **Created:** 2026-08-01

## Why this branch exists

The main worktree (`C:\Dev\active\iron-trail`) is busy with the Stage C2 Google
OAuth rollout and has uncommitted infra work. This branch runs **styling-only**
changes in parallel so the two streams don't collide. Styling touches
`iron_trail/ui.py`, `iron_trail/theme.py` and the `pages/` render calls — almost
no overlap with the auth/infra files, so it should merge cleanly.

## What just landed (do not redo)

Commit `5e2f666` already fixed the urgent mobile problems. Read
[`docs/mobile-ui-review.md`](./mobile-ui-review.md) first — it has the measured
before/after numbers.

- Sidebar reachable on mobile (floating gold **MENU** button)
- Tabs restyled as a segmented control (44px pills, gold selected state)
- 44px tap targets, non-wrapping hero, Plotly modebar hidden — all inside the
  single `@media (max-width: 720px)` block in `iron_trail/ui.py`
- `text_muted` raised from `#5b5b62` (2.94:1, failed WCAG AA) to `#7d7d86` (4.85:1)
- Adherence calendar default 52 → 26 weeks
- Coach chat renamed **Ask Coach** with starter prompts

## The work — in priority order

### 1. Mobile Plotly defaults helper *(highest impact)*

Charts are still laid out for desktop. Add one helper to `iron_trail/ui.py` and
route every `st.plotly_chart` call through it.

```python
MOBILE_PLOT_CONFIG = {"displayModeBar": False, "responsive": True}

def mobile_plotly_chart(fig, *, height: int = 360) -> None:
    fig.update_layout(
        height=height,
        margin=dict(l=36, r=10, t=24, b=64),
        legend=dict(orientation="h", yanchor="top", y=-0.24, font=dict(size=10)),
    )
    fig.update_xaxes(tickfont=dict(size=10), nticks=4, automargin=True)
    fig.update_yaxes(tickfont=dict(size=10), automargin=True)
    st.plotly_chart(fig, use_container_width=True, config=MOBILE_PLOT_CONFIG)
```

Specific measured problems it must fix:

| Page | Problem | Fix |
|---|---|---|
| Volume | x-tick `Jul 2025` is 58px of text in a 29px box | `tickformat="%b '%y"`, `nticks=4` |
| Volume | stacked legend has too many muscle categories | group tail into `other` via `nlargest(6)` |
| Strength | y-axis title renders as a 19×57 vertical sliver | drop axis title, use `st.caption("e1RM in kg")` |
| All | desktop margins waste width at 390px | shared margins above |

Verify each chart visually at 390×844 **and** 1440×900 — desktop must not regress.

### 2. CSS custom properties refactor *(prerequisite for theming)*

Colours are hardcoded hex in two places: the `_CSS` string in `ui.py` and
`COLORS` in `theme.py`. Convert `_CSS` literals to `var(--it-*)` and emit a
`:root` block built from the active palette. **Do this as its own commit** — it
is a large mechanical diff and must be visually identical when finished.

### 3. Theme picker *(only after #2)*

`theme.PALETTES` with `dark_gold` (current), `high_contrast`, `amoled`. Rebuild
the Plotly template from the active palette. Persist via `st.query_params` for
local mode; the hosted app already has a user record if you want it per-account.
Every palette must keep `text_muted` ≥ 4.5:1 against its own background — there
is already a test enforcing this for the default palette.

### 4. Overview "recent workouts" table → mobile cards

`st.dataframe` measures 358 wide with `scrollWidth` 367, so it scrolls
horizontally for a 3-column table. Stack it into card rows under 720px.

### 5. Badge grid

Overview uses `st.columns(8)` (109px cards on desktop); mobile stacks into a very
long scroll. Replace with
`grid-template-columns: repeat(auto-fit, minmax(150px, 1fr))`.

## How to work here

```powershell
cd C:\Dev\active\iron-trail-mobile

# Use the existing x64 env — do NOT create a venv, and do NOT use ARM64
# (pyarrow/cryptography/httptools have no ARM64 wheels).
$py = "C:\venvs\3.12\irontrail\Scripts\python.exe"

& $py -m pytest -q          # 124 tests must stay green
& $py -m ruff check .       # must add no NEW findings (some pre-exist at HEAD)

$env:COACH_LLM = "mock"
& $py -m streamlit run streamlit_app.py --server.port 8620 --server.headless true
```

Use port **8620+** — other sessions use 8601-8610. Verify with real browser
measurements (Playwright), not by eye: check `getBoundingClientRect()` and
`getComputedStyle()` at 390×844 and 1440×900.

## Rules

- **Styling only.** Do not touch `iron_trail/auth.py`, `cloud_storage.py`,
  `usage_limits.py`, `infra/**`, `azure.yaml`, or anything named `stage_c2*`.
- **Do not deploy.** The main session owns Azure. No `azd` commands.
- **Do not merge to `main`**, and do not merge this branch yourself.
- Real Hevy exports in `data/raw/` are gitignored — only the synthetic sample
  (`data/sample/sample_hevy_export.csv`, seed 42) may appear in commits or
  screenshots.
- Keep all mobile rules in the single `@media (max-width: 720px)` block in
  `ui.py`; tests assert on its contents.
- Small logical commits. Include the `Co-authored-by: Copilot` trailer.
- Delete any `.png` screenshots and `.playwright-mcp/` before finishing.

## Done means

`pytest -q` green, no new ruff findings, every changed page screenshotted at
both viewports with before/after measurements recorded, and
`docs/mobile-ui-review.md` updated to move items from "Deferred" to
"Implemented".
