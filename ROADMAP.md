# Roadmap

IronTrail's scope is "the gym dashboard I actually want to look at every week,
plus a feedback loop into my second brain." Everything past Phase 1 is
intentionally lazy — features only ship when I'd genuinely use them.

## Phase 1 — Done ✅

The Streamlit dashboard that's currently live. Five pages, deterministic
charts, no surprises.

- **Custom theme** — dark/glass aesthetic with Inter Tight + JetBrains Mono,
  hero block, mini-metric cards with sparklines, callouts.
- **Overview page** — lifetime hero stat, last-30-day rollup, plateau watch,
  recent unlocks, Hall of Shame, recent workouts table, unmapped-exercise
  catcher.
- **Strength page** — per-exercise e1RM (Epley) trend, PR markers, optional
  numpy-polyfit forecast with widening confidence band, optional
  year-over-year overlay.
- **Volume page** — weekly tonnage stacked by muscle, push:pull ratio chart,
  8-pattern movement radar vs an 8-sets/week target.
- **Adherence page** — calendar coloured by session archetype (Strength /
  Hypertrophy / Pump / Quick — K-Means on volume × duration × reps),
  archetype distribution, time-of-day histogram.
- **Achievements page** — 20-badge library with progress bars,
  "closest-to-unlock" callout, unlocked/locked wall.
- **Plateau detection** — per-exercise: counts sessions since the last 2.5 kg
  e1RM PR; flags `plateaued` (60–180d) or `regressing` (180d+ or e1RM down ≥5%
  from peak) with a personality message.
- **Hall of Shame** — worst recent sessions ranked by an underperformance
  score with witty captions.
- **Vault writeback** — each workout becomes `Vault/Hevy/Daily/YYYY-MM-DD.md`
  with frontmatter (date, title, duration, tonnage, set count, exercises_logged,
  tags) plus a per-exercise breakdown and preserved notes. Triggered from the
  Overview sidebar or via `scripts/write_vault_notes.py`.
- **Sample data** — deterministic 90-day synthetic CSV (`seed=42`) ships so
  the public demo runs without anyone's real data.

## Phase 2 — AI Training Coach

A scheduled job that summarises last week's training and writes a Markdown
review note into the Obsidian vault. Closes the loop: dashboard for drill-in,
weekly review for the bird's-eye.

- **Weekly summary builder** — structured JSON: sessions, exercises, volumes,
  PRs, plateaus, push:pull ratio, streak status, archetype mix.
- **LLM call** — JSON + curated system prompt → Markdown review. System prompt
  is grounded on Stronger By Science / Renaissance Periodization with an
  explicit "do not invent numbers" rule.
- **Write to vault** — `Vault/Hevy/Reviews/YYYY-Www.md` with frontmatter
  structured enough to support a future `quartz-vault` query
  ("show all weeks where push:pull ratio < 0.8").
- **Provider** — likely [GitHub Models](https://github.com/marketplace/models)
  for the free tier, or a Copilot CLI extension hooked to `/hevy-review`.
- **Scheduler** — Windows Task Scheduler is the path of least resistance.
  GitHub Actions cron is cleaner but needs the CSV pushed to a private repo
  or auto-fetched via the Pro API.

## Phase 3 — Cross-source

Triggered when CSV re-export becomes the actual blocker.

- **Hevy Pro API** — swap from CSV to incremental sync via
  `/v1/workouts/events?since=`. Needs a €5/mo subscription.
- **Samsung Health Connect bridge** — pull resting HR + body weight to
  correlate training load with recovery. Lets the LLM weekly review say "your
  resting HR has been elevated and your volume is up — consider a deload" with
  actual data behind it.
- **Strength Standards percentile** — join e1RM × bodyweight × sex against
  the public [Symmetric Strength](https://symmetricstrength.com/) tables so
  every lift gets a "you're in the top X% for your bracket" badge.

## Other ideas

Maybe someday, no commitments:

- **PR poster generator** — auto-render a shareable poster the moment a PR
  lands. Big number, exercise name, before/after.
- **Lift Wrapped** — annual end-of-year slideshow (most-loved lift, biggest
  jump, longest streak, archetype shift). Spotify Wrapped for the gym.
- **Spotify correlation** — does playlist BPM correlate with session volume?
  Cross-reference Hevy timestamps against Spotify listening history.
- **Weather context** — overlay outdoor temperature on adherence. Did the
  cold snap actually wreck the streak or am I making excuses?
- **Hall of Fame** — the inverse of Hall of Shame. Top sessions ranked by
  underrated metrics (best rep-quality, biggest e1RM jump, longest superset
  chain).
