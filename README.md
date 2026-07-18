# 🏋️ IronTrail

> **A personal Hevy gym dashboard with personality.** Plateau detection that
> talks back ("💤 Bicep Curl has been napping for 412 days"), K-Means session
> archetypes, a 20-badge achievement wall, a Hall of Shame, and one-click
> writeback to your Obsidian vault as Markdown.

[![License: MIT](https://img.shields.io/badge/License-MIT-d4a843.svg)](./LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.57-FF4B4B.svg?logo=streamlit&logoColor=white)](https://streamlit.io/)

![Overview](docs/screenshots/01_overview.png)

## What it is

You export your [Hevy](https://hevyapp.com) workout CSV, drop it into
`data/raw/`, run `streamlit run streamlit_app.py`, and get a dashboard
that actually surfaces the things that matter weekly. **Local mode is still
the default:** no account, no hosted storage, and your CSV stays on your disk.
The repo also contains a separately gated Azure private-beta mode with
authentication, user-isolated storage, retention limits, and a metered AI
provider. The included 90-day synthetic dataset runs out of the box.

The differentiating bit vs prior art is **writeback into the vault**:
every workout becomes `Vault/Hevy/Daily/YYYY-MM-DD.md` with frontmatter,
tonnage, per-exercise breakdown, and your session notes preserved
verbatim. Phase 2 (see [`ROADMAP.md`](./ROADMAP.md)) closes the loop with
an LLM-written weekly review.

## Features

| Page | What it shows |
|---|---|
| 🏋️ **Overview** | Lifetime tonnage hero, last-30-day mini-metrics with sparklines, plateau watch, recent unlocks + next targets, **Hall of Shame + Hall of Fame**, recent workouts |
| 💪 **Strength** | Per-exercise e1RM trend with PR stars, optional forecast band, optional year-over-year overlay, **📸 PR Poster download** |
| 📊 **Volume** | Weekly tonnage stacked by muscle, push:pull ratio over time, 8-pattern movement radar against an 8-sets/week minimum-effective-volume target |
| 📅 **Adherence** | Calendar coloured by K-Means session archetype (Strength / Hypertrophy / Pump / Quick), archetype distribution, time-of-day histogram |
| 🏆 **Achievements** | 20-badge library with progress bars, closest-to-unlock callout, unlocked/locked walls |
| 😂 **Quotes** | Indecisive-naming clusters, single-word laments, self-roasting, emoji-heavy titles — your real workout titles surfaced as a wall |
| 💬 **Coach** | LLM-written weekly + monthly training reviews, "Ask Your Data" chat, 5 personality presets. Local mode uses your Copilot subscription; hosted mode uses a rate-limited Microsoft Foundry deployment. |

Plus a **💀 Hall of Shame** + **🏆 Hall of Fame** expander on Overview
(worst and best sessions with witty captions), a **📝 Generate daily
notes** button that writes per-workout Markdown into a Vault path of
your choosing, and an optional **`/lift-review`** Copilot CLI extension
at `~/.copilot/extensions/lift-trail/` for triggering reviews without
opening Streamlit.

### Gallery

<table>
<tr>
  <td align="center" width="50%">
    <b>💪 Strength</b><br>
    <img src="docs/screenshots/02_strength.png" alt="Strength page">
  </td>
  <td align="center" width="50%">
    <b>📊 Volume</b><br>
    <img src="docs/screenshots/03_volume.png" alt="Volume page">
  </td>
</tr>
<tr>
  <td align="center">
    <b>📅 Adherence</b><br>
    <img src="docs/screenshots/04_adherence.png" alt="Adherence page">
  </td>
  <td align="center">
    <b>🏆 Achievements</b><br>
    <img src="docs/screenshots/05_achievements.png" alt="Achievements page">
  </td>
</tr>
</table>

## Quickstart

```powershell
# Clone
git clone https://github.com/Lando-00/iron-trail.git
cd iron-trail

# Venv (Python 3.12)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install
pip install -r requirements.txt

# Run on the included synthetic sample data
streamlit run streamlit_app.py
```

Opens at `http://localhost:8501`. The sidebar starts on the synthetic
sample CSV — no Hevy export needed to see the app working.

On macOS / Linux, swap `Activate.ps1` for `source .venv/bin/activate`.

## Runtime modes

| Mode | Default | Data and AI behavior |
|---|---|---|
| `local` | Yes | Local CSV picker/upload, optional Vault filesystem writeback, Copilot SDK or mock Coach |
| `cloud` | No | Easy Auth identity gate, one-time invites, session-only upload by default, opt-in Azure storage, Foundry Coach with hard usage limits |

Set `IRONTRAIL_MODE=cloud` only in the prepared Azure container environment.
Cloud mode deliberately removes server filesystem/Vault path inputs. Markdown,
PDF, PR posters, and daily notes remain browser downloads.

## Use your own data

1. In the Hevy app: **Profile → Settings → Export Workout Data**.
2. Save the CSV into `data/raw/`. It's [gitignored](.gitignore) — your data
   stays local. The app auto-picks the most-recent CSV in that folder.
3. In the IronTrail sidebar, pick your CSV from the **Data source** dropdown.
4. Set your **Bodyweight (kg)** in the sidebar — it's used to compute load
   for bodyweight + bodyweight-assisted exercises (e.g. assisted pull-ups)
   and for any bodyweight-relative badge.
5. Optional: click **📝 Generate daily notes** to write one Markdown file
   per workout into the **Output directory** you specify (defaults to
   `./vault-output/` in the repo). Works with Obsidian, Logseq, or any
   tool that reads Markdown.

That's the whole setup — no API key, no account, no env file. Everything
that matters is exposed via the sidebar.

## 📝 Markdown writeback — what the button does

Click **📝 Generate daily notes** and every workout in the loaded CSV
becomes `<output>/Hevy/Daily/YYYY-MM-DD.md`. Example output for one
workout:

```markdown
---
date: 2026-05-14
title: "Short sesh"
duration_min: 47
tonnage_kg: 4030
set_count: 12
exercises_logged: 3
tags:
  - hevy/session
---

# Short sesh
`2026-05-14 20:50` — 47 min · **4,030 kg** · 12 working sets · 3 exercises

## Exercises
- **Butterfly (Pec Deck)** — 45kg × 10 · 50kg × 8 · 40kg × 2  _(top e1RM 63.3 kg)_
- **Incline Bench Press (Dumbbell)** — 60kg × 9 · 60kg × 6  _(top e1RM 78.0 kg)_
- **Lat Pulldown (Cable)** — 45kg × 8 · 55kg × 12 · 60kg × 5  _(top e1RM 77.0 kg)_

## Per-exercise notes
- **Incline Bench Press (Dumbbell):** 30kgs x 2dbs = 60kgs. 9 reps woo.
```

**Setups it works for:**

| You use… | Point the **Output directory** at… |
|---|---|
| Obsidian | Your vault root, e.g. `~/Documents/ObsidianVault` |
| Logseq | Your graph directory |
| Just text files | Any folder you like, e.g. `~/training-log` |
| Nothing in particular | Leave it as `vault-output/` and browse the files in VS Code / GitHub |

The CLI variant (`python scripts/write_vault_notes.py --vault <dir>`) does
the same thing headless — handy for cron / Task Scheduler / CI.

Frontmatter is numeric where it makes sense (`tonnage_kg`, `set_count`)
so it's filterable by Obsidian Dataview / Bases queries.

## 💬 The Coach — AI weekly + monthly reviews

The **Coach** page (`pages/6_💬_Coach.py`) is a first-class feature. The
provider is selected by runtime: local IronTrail can use the Copilot SDK;
hosted IronTrail uses a deployment-name-driven Microsoft Foundry provider
authenticated with managed identity.

```
You ──▶ click "Generate weekly review"
         │
         ▼
    coach.summary.build_weekly(df) ──▶ structured dict (sessions, top e1RMs,
         │                              plateaus, push:pull, archetype mix)
         ▼
    local:  coach.providers.copilot ──▶ your Copilot subscription
    cloud:  coach.providers.azure_foundry ──▶ managed identity + usage ledger
         │
         │ Markdown body
         ▼
    coach.render.weekly_review_md  ──▶  💾 Save to Vault  ⬇️ Download .md
                                       📄 Download PDF   📋 Copy
```

**Three triggers** — all share the same Python coach module:

| Trigger | Where | When to use |
|---|---|---|
| 💬 Coach page button | Streamlit dashboard | On-demand, you want to read it inline |
| `scripts/lift_review.py --vault <path>` | Terminal | Cron / Task Scheduler / scripting |
| `/lift-review` slash command | Copilot CLI | In-flow while working in your vault |

**Five personality presets** — same factual contract, different voice:
*Neutral · RP Strength · Stronger By Science · Calm Therapist · Goggins Mode*.

**Hallucination guard by construction** — every number you see in a
review comes from the structured summary, never from the LLM. The
rendered Markdown is composed as: frontmatter → **Stats** block (from
data) → **Reflections** block (from LLM) → footer.

### Installing the `/lift-review` slash command

The extension is **optional** — the Streamlit Coach page works without
it. If you want the slash command:

```powershell
# Clone wherever you keep projects
git clone https://github.com/Lando-00/Iron-Trail.git "$HOME\iron-trail"
cd "$HOME\iron-trail"
python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -r requirements.txt

# install the extension (Windows)
Copy-Item -Recurse extensions\lift-trail $env:USERPROFILE\.copilot\extensions\

# in the Copilot CLI: /clear  ← reloads extensions, /lift-review now available
```

Environment variables (set in your shell profile, all optional):

```
IRON_TRAIL_REPO   = ~/iron-trail                  # default
IRON_TRAIL_VAULT  = <repo>/vault-output          # default
IRON_TRAIL_VENV   = <repo>/.venv                 # default
```

Commands:

| Command | What it does |
|---|---|
| `/lift-review` | Generate the weekly review and save to `<vault>/Hevy/Reviews/YYYY-Www.md` |
| `/lift-review --personality goggins` | Same, but in the chosen voice |
| `/lift-recap` | Generate the monthly recap → `<vault>/Hevy/Monthly/YYYY-MM.md` |
| `/lift-review --vault D:/Other/Vault` | Override the vault path for one call |

## Configuration

### Default bodyweight

Edit `BODY_WEIGHT_KG` in [`iron_trail/config.py`](iron_trail/config.py) to
change the value the sidebar starts at. The sidebar input is authoritative
at runtime — this is just the default.

### Exercise → muscle map

[`data/lookups/exercise_muscle_map.csv`](data/lookups/exercise_muscle_map.csv)
maps every exercise name to:

| Column | Drives |
|---|---|
| `primary_muscle` | Volume-by-muscle stacked bar |
| `equipment` | Filtering / display |
| `movement_type` | Push:pull ratio (push / pull / legs / core / cardio) |
| `movement_pattern` | Movement radar (Horizontal Push / Squat / Hinge / etc.) |
| `load_type` | Bodyweight load substitution (`weighted` / `bodyweight` / `assisted` / `cardio`) |

Exercises you log but haven't mapped show up in the **Unmapped exercises**
expander on the Overview page — add a row for each.

## Data flow

```
┌─────────────────────────────────────────────────────────────┐
│  data/raw/your_hevy_export.csv      (gitignored, local-only) │
│  data/sample/sample_hevy_export.csv (committed, synthetic)   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  iron_trail.ingest.load_and_clean()                         │
│    - parse locale timestamps (dateparser)                   │
│    - join exercise_muscle_map.csv                           │
│    - substitute bodyweight for BW + assisted sets           │
│    - flag warmup vs working                                 │
│    - derive volume_kg and e1rm_kg per set                   │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
┌──────────────────────────┐  ┌──────────────────────────────┐
│  Streamlit pages         │  │  iron_trail.vault_notes      │
│   - Overview             │  │   write_daily_notes()        │
│   - Strength             │  │   → Vault/Hevy/Daily/        │
│   - Volume               │  │       YYYY-MM-DD.md          │
│   - Adherence            │  │   (frontmatter + per-ex      │
│   - Achievements         │  │    breakdown + notes)        │
└──────────────────────────┘  └──────────────────────────────┘
```

## Privacy

**Local mode**

- `data/raw/*` is gitignored; real workout exports stay on your machine.
- Streamlit usage telemetry is disabled.
- Uploaded bytes stay in the local Streamlit session.
- Vault writeback is explicit and targets a path you choose.

**Prepared Azure owner-only beta mode**

- Stage C uses Microsoft Entra ID for the assigned owner. Google and tester
  invitations remain deferred.
- Storage keys are partitioned by an opaque ID derived from the immutable
  provider principal, not display name or filename.
- Uploads remain session-only unless the user selects **Save privately**.
- Active raw files expire after 30 days; active normalized data expires after
  60 days. Azure Blob soft delete permits privileged recovery for seven
  additional days (37/67 days maximum).
- Users can export saved datasets or remove them from active IronTrail access.
  Deleted blobs can remain recoverable by privileged Azure operators for up to
  seven days.
- Raw CSVs, raw heart-rate samples, free-text notes, and export files are not
  sent to the hosted model. The Coach receives deterministic aggregates.
- The cloud image does not contain the Copilot SDK or the owner's credentials.
- Azure Monitor is enabled only when its connection string is provided; app
  code logs operational failures, not workout contents.

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| UI | [Streamlit](https://streamlit.io) 1.57 (multi-page) |
| Data | Pandas 2 |
| Charts | [Plotly](https://plotly.com/python/) 6 |
| Dates | [dateparser](https://github.com/scrapinghub/dateparser) (locale-aware) |
| ML | [scikit-learn](https://scikit-learn.org/) (K-Means archetypes) + numpy.polyfit (forecast) |
| Theme | Custom CSS in [`iron_trail/theme.py`](iron_trail/theme.py) |

## Deployment — Azure private beta

The deployment path is Azure Developer CLI + Bicep:

- Azure Container Apps Consumption, scale-to-zero, maximum one replica.
- Private Blob/Table storage with managed identity and lifecycle policies.
- Container Apps Easy Auth plus hashed single-use invite codes.
- Existing Microsoft Foundry account/project, with the model deployment
  configured separately.
- Application Insights + Log Analytics and a EUR 25 budget ceiling.

See [`.azure/deployment-plan.md`](.azure/deployment-plan.md) for the exact
architecture, phased approvals, cost assumptions, and hard-stop conditions.
The code-first stage does **not** authorize `azd provision` or `azd up`; model
credit proof and website deployment are separate later gates.

## Roadmap

See [`ROADMAP.md`](./ROADMAP.md). TL;DR:

- **Phase 1 — Done.** The dashboard you see in the screenshots above.
- **Phase 2 — AI Training Coach.** Weekly LLM-written review note in the
  vault.
- **Private beta — code first.** Authentication, storage isolation, Foundry,
  usage limits, container packaging, and Azure IaC.
- **Cross-source.** Samsung Health recovery context, then an Android Health
  Connect companion; do not build new integrations on deprecated Google Fit.

## Contributing

PRs welcome — see [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## Prior art / credits

IronTrail stands on the shoulders of every Hevy analytics project that came
before it. In particular:

- **[LiftShift](https://liftshift.app)** — beautiful React + IndexedDB
  in-browser dashboard with 425⭐. Inspired the session-intent / archetype
  classification angle.
- **[HevyWorkoutAnalyzer](https://hevyworkoutanalyzer.streamlit.app)** —
  the closest reference architecture (Streamlit + Pandas + Plotly). Living
  proof the stack works.
- **[casudo/Hevy-Insights](https://github.com/casudo/Hevy-Insights)** —
  FastAPI + Vue. Inspired the plateau-detection algorithm.
- **[radupana/openweight](https://github.com/radupana/openweight)** —
  exhaustive CSV column reference that saved an afternoon of reverse
  engineering.

## Project layout

```
iron-trail/
├── streamlit_app.py             # Overview page (entry point)
├── pages/                       # Auto-discovered Streamlit pages
│   ├── 1_💪_Strength.py
│   ├── 2_📊_Volume.py
│   ├── 3_📅_Adherence.py
│   ├── 4_🏆_Achievements.py
│   └── 5_😂_Quotes.py
├── iron_trail/                  # Python package
│   ├── analytics.py             # plateaus, archetypes, awards, hall of shame
│   ├── comedy.py                # captions + quotes
│   ├── config.py                # paths + default bodyweight
│   ├── ingest.py                # CSV → long-format cleaned DataFrame
│   ├── metrics.py               # e1RM, volume, streaks, push:pull
│   ├── normalize.py             # exercise-name normalisation
│   ├── theme.py                 # colour palette + CSS
│   ├── ui.py                    # shared rendering primitives
│   └── vault_notes.py           # Vault writeback
├── data/
│   ├── raw/                     # YOUR Hevy exports (gitignored)
│   ├── sample/                  # synthetic sample CSV (committed)
│   ├── lookups/                 # exercise_muscle_map.csv (committed)
│   └── processed/               # parquet cache (gitignored)
├── scripts/
│   ├── generate_sample_data.py  # rebuild the synthetic CSV (seed=42)
│   ├── snapshot_public.py       # Playwright screenshots → docs/screenshots/
│   ├── snapshot_pages.py        # local-dev variant → scripts/screenshots/
│   └── write_vault_notes.py     # CLI version of the sidebar button
├── docs/
│   └── screenshots/             # README screenshots (sample-data only)
├── .streamlit/config.toml       # theme + telemetry-off
├── requirements.txt
├── pyproject.toml
├── ROADMAP.md
├── CONTRIBUTING.md
└── LICENSE                      # MIT
```

## Data model

After `iron_trail.ingest.load_and_clean(path)`, you get a long-format
DataFrame with one row per set:

| Column | Notes |
|---|---|
| `workout_id`, `workout_date`, `title` | Workout-level identifiers |
| `start_time`, `end_time`, `duration_min` | Locale-parsed via `dateparser` |
| `exercise_title` | Normalised |
| `primary_muscle`, `equipment`, `movement_type`, `movement_pattern`, `load_type` | From `exercise_muscle_map.csv` |
| `set_type`, `set_index`, `is_warmup`, `is_working` | Set classification |
| `weight_kg_load` | Actual load: raw `weight_kg` for weighted, bodyweight for bodyweight, `BW − assist` for assisted |
| `reps` | Working reps |
| `volume_kg` | `weight_kg_load × reps` for working sets, `0` otherwise |
| `e1rm_kg` | Epley estimate: `weight_kg_load × (1 + reps / 30)` |

## Caveats

- **RPE is almost always null** in Hevy CSVs — don't build features on it.
- **Exercise name strings drift over time** (Hevy renames, custom-vs-canonical).
  The CSV doesn't have a stable exercise ID — the Pro API does. Watch out
  if you analyse multi-year history.
- **CSV timestamps are locale-strings without timezones.** `dateparser`
  handles non-English month names; we drop the timezone layer entirely.
- **Cardio volume is 0** by design — duration is a separate metric. Cardio
  is excluded from push:pull and the movement radar.

## Local dev on Windows ARM64 (Surface Pro)

The project runs fine on an ARM64 Windows host, but use **x86_64 Python**
because `pyarrow` (a hard Streamlit dependency) has no native Windows ARM64
wheel. x64 builds run under Windows' x86 emulation and performance is
comfortably fast for this single-user analytical workload.

```powershell
# Pick any x64 Python you have installed; this example uses 3.12 from
# the system Python installer:
& "C:\Program Files\Python312\python.exe" -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`python -c "import sys; print(sys.version)"` should report `64 bit (AMD64)`.

## Regenerate sample data

```powershell
python scripts/generate_sample_data.py
```

Deterministic (`seed=42`), 90 days, ~3 sessions/week with one missed week
and one plateaued lift.

## Regenerate README screenshots

```powershell
# Hide your real CSV so the app falls back to the sample
Move-Item data/raw/your_hevy_export.csv data/raw/_your_hevy_export.csv.bak

# In one terminal:
streamlit run streamlit_app.py --server.port 8507 --server.headless true

# In another (after ~12s for first health check):
python scripts/snapshot_public.py

# Restore your CSV
Move-Item data/raw/_your_hevy_export.csv.bak data/raw/your_hevy_export.csv
```

## License

[MIT](./LICENSE) © 2026 [Lando-00](https://github.com/Lando-00).
