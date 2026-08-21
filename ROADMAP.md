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

## Phase 2 — AI Training Coach ✅

The Coach lives in the dashboard as a first-class feature. Reviews
generate inline, render as Markdown right in the page, and offer four
export buttons (Save to Vault · Download .md · PDF · Copy).

- **Coach page** (`pages/6_💬_Coach.py`) — four tabs:
  - 📅 **Weekly** — generates an LLM-written review of the last complete
    ISO week, grounded in a structured Stats block (numbers from data,
    prose from the LLM).
  - 🗓️ **Monthly** — same but over a 4-week window, with per-exercise
    1RM trajectory and archetype mix.
  - 💬 **Ask Coach** — multi-turn chat scoped to the loaded CSV,
    8-turn history cap.
  - 🎭 **Settings** — personality preset + provider status.
- **Provider** — official `github-copilot-sdk` Python package, wrapping the
  user's existing Copilot Pro subscription. No extra API key. A
  deterministic `MockProvider` (`COACH_LLM=mock`) lets contributors hack
  without burning tokens.
- **Five personality presets** — Neutral, RP Strength, Stronger By
  Science, Calm Therapist, Goggins Mode. Identical factual contract,
  different tone.
- **Hallucination guard** — numeric facts in every review come from the
  structured summary, never the LLM. Renderer composes: frontmatter →
  Stats block (from data) → Reflections block (from LLM) → footer.
- **Vault writeback** —
  `<vault>/Hevy/Reviews/YYYY-Www.md` and `<vault>/Hevy/Monthly/YYYY-MM.md`,
  with queryable YAML frontmatter (`session_count`, `total_volume_kg`,
  `push_pull_ratio`, `personality`, tags).
- **PDF export** — `xhtml2pdf` pure-Python pipeline, dark+gold CSS,
  emoji-fallback table for the bits the PDF font can't render.
- **`/lift-review` slash command** — user-global Copilot CLI extension at
  `~/.copilot/extensions/lift-trail/`. Two commands: `/lift-review` and
  `/lift-recap`. Both shell out to `scripts/lift_review.py` and stream
  progress into the CLI timeline.
- **🏆 Hall of Fame** — gold-glow inverse of Hall of Shame. Best sessions
  ranked by an underrated-metric score (volume × muscles hit × top
  weight × top e1RM). 30 captions across three tones (heavy day,
  marathon day, all-round day) with smart picker.
- **📸 PR Poster generator** — 1080×1080 PNG, dark+gold, JetBrains Mono
  numbers. Auto-detects PRs from the loaded CSV; available as a button
  on the Strength page and as a batch CLI at `scripts/render_pr_poster.py`.

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

## Private Azure beta — Invite-only deployed

The hosted path keeps the local app intact and adds a separate cloud mode:

- Stage C began with owner-only Microsoft Easy Auth and an owner-bound
  bootstrap code. Stage C2 now enables Microsoft and Google with hashed,
  single-use tester invitations.
- Uploads automatically replace the signed-in user's one saved dataset by
  default; configuration can restore the session-only/explicit-save flow.
- 30-day raw and 60-day normalized active retention, plus export/delete
  controls and seven-day privileged Blob recovery.
- A managed-identity Microsoft Foundry provider with per-user allowances and
  a global monthly hard cap. Local mode continues using Copilot.
- Container Apps Consumption with scale-to-zero and one maximum replica while
  Streamlit state remains process-local.
- Docker, AZD, Bicep, monitoring, RBAC, lifecycle, and budget definitions.
- A **Private Beta in Progress** anonymous landing screen with accessible
  fireworks and a server-seeded discovery sequence that reveals sign-in
  without weakening the Easy Auth or application authorization boundary.

Stage C2 is deployed and live-tested at the Azure-provided URL with one
Microsoft owner, one invited Google member, a five-user ceiling, and zero
unused invites. Persistence, export, delete-selected, Delete All, lifecycle
recovery, Foundry, monitoring, RBAC, and cost guardrails have passed. Basic
cross-account visibility isolation is owner-accepted: the Google member could
not see the owner's saved data. The larger synthetic
list/load/cache/export/delete and suspend/restore matrix remains optional
expanded hardening and is not represented as completed evidence.

## Other ideas

Maybe someday, no commitments:

- **Lift Wrapped** — annual end-of-year slideshow (most-loved lift, biggest
  jump, longest streak, archetype shift). Spotify Wrapped for the gym.
- **Spotify correlation** — does playlist BPM correlate with session volume?
  Cross-reference Hevy timestamps against Spotify listening history.
- **Weather context** — overlay outdoor temperature on adherence. Did the
  cold snap actually wreck the streak or am I making excuses?
- **Form-check uploader** — drop a phone video of a heavy set, vision LLM
  returns form notes.
