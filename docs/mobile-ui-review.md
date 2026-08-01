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
| 9 | **Charts are genuinely responsive** | See *CSS-responsive chart heights* below |
| 10 | **Volume legend tail grouped into `other`** | Legend 247×121 → 209×83 on a 358px chart |
| 11 | **Stylesheet driven by CSS custom properties** | `_CSS` holds no colour literal; 87 computed-style snapshots identical before/after |
| 12 | **Theme picker** — `dark_gold`, `high_contrast`, `amoled` | Palette flips `--it-bg` `#0a0a0c` → `#000000` live; every palette held to 4.5:1 by test |
| 13 | **Tap targets re-fixed for Streamlit 1.60** | The 1.35-era `[data-baseweb="select"]` rule had silently stopped matching |

All mobile rules live in a single `@media (max-width: 720px)` block in
`iron_trail/ui.py`, so desktop is provably unchanged (verified: hero still
72px, no Menu button, `.block-container` padding still 32px at 1440px).

### CSS-responsive chart heights

Streamlit renders server-side and cannot see the viewport, so a chart used to
carry one hardcoded height for both screens. `ui.plotly_chart()` now drops
`layout.height`, sets `autosize`, and lets a `--it-chart-h` custom property —
flipped in the mobile media query — drive the box. Plotly measures that box, so
the **real SVG** resizes and the axes reflow live on rotation.

| Chart | 1440×900 | 390×844 before | 390×844 after |
|---|---|---|---|
| Strength e1RM | 980×440 *(unchanged)* | 358×440 | 358×**360** |
| Volume tonnage | 980×460 *(unchanged)* | 358×460 | 358×**380** |
| Volume push:pull | 980×320 *(unchanged)* | 358×320 | 358×**300** |
| Volume radar | 980×460 *(unchanged)* | 358×460 | 358×**380** |
| Adherence calendar | 980×320 *(unchanged)* | 358×320 | 358×**300** |
| Adherence archetypes / time of day | 980×260 *(unchanged)* | 358×260 | 358×**240** |

Also fixed in the same pass:

- **Date ticks.** A `tickformatstops` entry covers only the month-to-year tick
  band, so a phone renders `Mar '26` (**50.4px**, was `Mar 2026` at **57.6px**)
  while desktop keeps its 9 day-level ticks at 43.2px. The handoff suggested
  `nticks=4`, which was **not** used — it would have thinned the desktop axis
  from 9 ticks to 4 for no mobile gain, since Plotly already picks 3–4 ticks at
  358px on its own.
- **Y-axis title slivers.** `e1RM (kg)` rendered as a **19×57.4** vertical
  strip on both viewports. Strength and Volume push:pull now use `st.caption`
  instead.
- **Legend gap** tightened from `y=-0.24` to `-0.18`, which returns the space
  to the plot: the Volume tonnage plotting area goes 210 → **221px** tall on a
  phone with 14.7px still clear between the last tick and the legend.
- **Polar charts** keep symmetric margins so the radar stays centred.

### Theming

Colours were hardcoded in two places — the `_CSS` string and `theme.COLORS` —
which is why the picker was previously scoped at 2–3 days. Both steps landed:

1. `theme.css_variables()` emits a `:root` block of `--it-*` properties, plus
   bare `R, G, B` triples for the `rgba()` washes, borders and glows.
   `_CSS` now contains **no colour literal at all** (asserted by a test).
2. `theme.PALETTES` holds `dark_gold` (byte-identical to before),
   `high_contrast` and `amoled`. `theme.apply_palette()` mutates `COLORS` and
   the derived chart maps **in place** — pages read `theme.COLORS[...]` at
   render time — and re-registers the Plotly template. `ui.setup_page()`
   applies it before any figure is built.
3. The choice lives in session state and is mirrored into `?theme=`, so it
   survives navigation and can be shared. The default is left out of the URL.

The refactor is provably invisible: 36 selectors × 2 viewports of
`getComputedStyle` output on Overview, plus 15 on Quotes, are **identical**
before the refactor and after the whole palette stack landed.

**Known limitation.** `theme.COLORS` is process-global, so two concurrent
hosted sessions on different palettes can transiently trade *chart* accent
colours. The CSS side is always right, because the `:root` block is emitted per
response. Per-account theming would mean threading the palette through every
render call.

### Contrast reference (background `#0a0a0c`)

| Colour | Role | Ratio | AA body (4.5:1) |
|---|---|---:|---|
| `#e7e7e9` | primary text | 16.02:1 | pass |
| `#d4a843` | gold accent | 8.93:1 | pass |
| `#5b9cf0` | blue accent | 7.03:1 | pass |
| `#8a8a93` | secondary text | 5.78:1 | pass |
| ~~`#5b5b62`~~ → `#7d7d86` | muted text | ~~2.94:1~~ → 4.85:1 | ~~**fail**~~ → pass |

`tests/test_theme_palettes.py` now runs this check over **every** palette for
primary, secondary and muted text against that palette's own background, so a
new palette cannot ship below AA.

## Deferred (with rationale)

### Overview "recent workouts" table — *medium effort*

`st.dataframe` measures 358 wide with `scrollWidth` 367, so it scrolls
horizontally for a 3-column table. Replacing it with stacked card rows on
mobile would read better, but it changes a core Overview element and deserves
a design opinion first.

Streamlit's dataframe hover toolbar (Search / Download / Fullscreen) is the one
remaining sub-44px control on mobile, at **22.4×22.4**. It belongs with this
item: if the table becomes cards, the toolbar goes away with it.

### Badge grid — *medium effort*

Overview previews badges in `st.columns(8)`, giving 109px-wide cards on
desktop; mobile stacks them into a very long scroll. A CSS
`grid-template-columns: repeat(auto-fit, minmax(150px, 1fr))` would adapt at
both sizes, but it means replacing the `st.columns` badge walls on two pages.

### Adherence time-of-day axis — *small, needs a call*

`dtick=1` forces 24 hour labels onto a 358px-wide chart (~14px each, so they
collide). Tick counts are baked into the figure and cannot be media-queried, so
fixing mobile means thinning the desktop axis too — a product call, not a
styling one.

## Ranked backlog

| Rank | Item | Impact | Effort | Status |
|---:|---|---|---|---|
| 1 | Mobile Plotly defaults helper | High | Medium | **done** |
| 2 | CSS custom properties refactor | High (enables theming) | Medium | **done** |
| 3 | Overview recent-workouts mobile cards | Medium | Medium | deferred |
| 4 | Badge CSS grid | Medium | Medium | deferred |
| 5 | Volume legend grouping | Medium | Medium | **done** |
| 6 | Theme picker UI | Medium | Low *(after #2)* | **done** |
| 7 | Time-of-day tick density | Low | Low | deferred |

