# lift-trail — Copilot CLI extension

Adds two slash commands to the GitHub Copilot CLI that hook into
**IronTrail**:

| Command | What it does |
|---|---|
| `/lift-review` | Generate a weekly training review and save to `<vault>/Hevy/Reviews/YYYY-Www.md` |
| `/lift-recap` | Generate a monthly training recap and save to `<vault>/Hevy/Monthly/YYYY-MM.md` |

Both shell out to `scripts/lift_review.py` in the IronTrail repo,
which uses the same Copilot SDK Python provider as the Streamlit Coach
page. **The extension itself is a thin shim (~150 lines)** — no API key,
no network setup, no provider config.

## Install (Windows)

\\\powershell
Copy-Item -Recurse extensions\lift-trail C:\Users\lovan\.copilot\extensions\
\\\

## Install (macOS / Linux)

\\\ash
cp -R extensions/lift-trail ~/.copilot/extensions/
\\\

Then `/clear` in the Copilot CLI to reload extensions.

## Environment variables

| Variable | Default | What it does |
|---|---|---|
| `IRON_TRAIL_REPO` | `D:/Dev/iron-trail` (Win) or `~/iron-trail` (*nix) | Path to the iron-trail repo |
| `IRON_TRAIL_VAULT` | `<repo>/vault-output` | Where reviews get written |
| `IRON_TRAIL_VENV` | `<repo>/.venv` | Python venv with iron-trail's deps installed |

## Usage examples

\\\
/lift-review
/lift-review --personality goggins
/lift-review --since 2026-04-13
/lift-recap
/lift-review --vault D:/Some/Other/Vault
\\\

Streams progress into the CLI timeline; final line is the path of the
written note.
