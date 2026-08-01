# Mobile UI review — findings and decisions

> **Date:** 2026-08-01 · measured at 390×844 (iPhone-class) and 1440×900
> **Method:** every page loaded in a real browser; all numbers below are
> measured from the live DOM, not estimated.

## Context

A beta tester could not find the Coach chat, which prompted a wider mobile
audit. Two separate problems turned out to exist: **discoverability** (things
that are present but don't look interactive) and **ergonomics** (things too
small or too dense to use on a phone).

## Implemented

| # | Fix | Evidence |
|---|---|---|
| 1 | **Sidebar reachable on mobile** — `header { display: none }` was hiding the only sidebar toggle | Sidebar was unreachable at 390px: no nav, no uploader |
| 2 | **Tabs styled as a segmented control** | Default tabs were 14px grey text with 0 padding and read as a caption — the root cause of the tester's miss |
| 3 | **44px tap targets** | Menu 90×38 → 94×44; nav links 239×28 → 44 high; selects 38 → 44 |
| 4 | **Hero number no longer wraps** | `1,522,292kg` was a 144px two-line block → now 47px, one line (`clamp(40px, 12vw, 72px)`) |
| 5 | **Plotly modebar hidden on mobile** | Buttons measured 24×22 — unhittable, and they overlapped the plot |
| 6 | **Muted text meets WCAG AA** | `#5b5b62` = **2.94:1** on `#0a0a0c` (fails AA). Now `#7d7d86` = **4.85:1** |
| 7 | **Adherence default 52 → 26 weeks** | 52 weeks ≈ 6.9px per week on a 358px chart |
| 8 | **Coach chat discoverability** | Renamed *Ask Your Data* → *Ask Coach*, added 4 starter prompts, cross-linked from the Weekly/Monthly empty states |

All mobile rules live in a single `@media (max-width: 720px)` block in
`iron_trail/ui.py`, so desktop is provably unchanged (verified: hero still
72px, no Menu button, `.block-container` padding still 32px at 1440px).

### Contrast reference (background `#0a0a0c`)

| Colour | Role | Ratio | AA body (4.5:1) |
|---|---|---:|---|
| `#e7e7e9` | primary text | 16.02:1 | pass |
| `#d4a843` | gold accent | 8.93:1 | pass |
| `#5b9cf0` | blue accent | 7.03:1 | pass |
| `#8a8a93` | secondary text | 5.78:1 | pass |
| ~~`#5b5b62`~~ → `#7d7d86` | muted text | ~~2.94:1~~ → 4.85:1 | ~~**fail**~~ → pass |

`tests/test_ui.py::test_muted_text_passes_wcag_aa_on_the_app_background`
computes this from `theme.COLORS`, so a regression fails the build.

## Deferred (with rationale)

### Mobile Plotly defaults helper — *medium effort, worth doing*

Charts are still laid out for desktop. A shared helper would fix tick density,
legend placement and margins in one place:

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

Deferred because it touches every chart call across five pages and needs
per-chart visual QA — too much to land unreviewed in one overnight batch.
Specific issues it would fix:

- Volume x-ticks: `Jul 2025` is 58px of text in a 29px box → use `%b '%y`.
- Volume stacked legend: too many muscle categories; group the tail into
  `other` via `nlargest(6)`.
- Strength y-axis title renders as a 19×57 vertical sliver → drop the axis
  title and use `st.caption("e1RM in kg")`.

### Overview "recent workouts" table — *medium effort*

`st.dataframe` measures 358 wide with `scrollWidth` 367, so it scrolls
horizontally for a 3-column table. Replacing it with stacked card rows on
mobile would read better, but it changes a core Overview element and deserves
a design opinion first.

### Badge grid — *medium effort*

Overview previews badges in `st.columns(8)`, giving 109px-wide cards on
desktop; mobile stacks them into a very long scroll. A CSS
`grid-template-columns: repeat(auto-fit, minmax(150px, 1fr))` would adapt at
both sizes, but it means replacing the `st.columns` badge walls on two pages.

### Theme picker — *2–3 days, strategic*

**Feasible, but it is a refactor, not a feature.** The blocker is that colours
are hardcoded hex in two places: the `_CSS` string in `ui.py` and `COLORS` in
`theme.py`.

Recommended shape:

1. Move palettes into `theme.PALETTES` (`dark_gold`, `high_contrast`, `amoled`).
2. Convert `_CSS` literals to CSS custom properties, emitting a `:root` block
   per selected palette, so `_CSS` itself becomes theme-agnostic.
3. Rebuild the Plotly template from the active palette.
4. Persist the choice — `st.query_params` is the cheap option; the hosted app
   should store it on the user record instead, since it already has one.

```python
PALETTES = {
    "dark_gold":     {"bg": "#0a0a0c", "text_primary": "#e7e7e9", "text_muted": "#7d7d86", ...},
    "high_contrast": {"bg": "#000000", "text_primary": "#ffffff", "text_muted": "#9a9aa3", ...},
    "amoled":        {"bg": "#000000", "text_primary": "#f2f2f4", "text_muted": "#8d8d96", ...},
}
```

Not attempted overnight: touching every colour in the app is a
high-blast-radius change that needs side-by-side visual review on each page,
and it would have collided with the in-flight Stage C2 work.

**Recommendation:** do step 1–2 (CSS variables) as its own PR first — it is
valuable on its own and makes the picker a small follow-up.

## Ranked backlog

| Rank | Item | Impact | Effort |
|---:|---|---|---|
| 1 | Mobile Plotly defaults helper | High | Medium |
| 2 | CSS custom properties refactor | High (enables theming) | Medium |
| 3 | Overview recent-workouts mobile cards | Medium | Medium |
| 4 | Badge CSS grid | Medium | Medium |
| 5 | Volume legend grouping | Medium | Medium |
| 6 | Theme picker UI | Medium | Low *(after #2)* |
