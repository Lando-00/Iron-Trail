# lift-trail — Copilot CLI extension

Adds two slash commands to the GitHub Copilot CLI that call IronTrail's
headless review script:

| Command | What it does |
|---|---|
| `/lift-review` | Generate a weekly review in `<vault>/Hevy/Reviews/YYYY-Www.md` |
| `/lift-recap` | Generate a monthly recap in `<vault>/Hevy/Monthly/YYYY-MM.md` |

The extension is a thin local shim. It uses the clone's Python environment and
the current user's Copilot authentication; it contains no API key.

## Install

Windows:

```powershell
Copy-Item -Recurse extensions\lift-trail "$HOME\.copilot\extensions\"
```

macOS / Linux:

```bash
cp -R extensions/lift-trail ~/.copilot/extensions/
```

Run `/clear` in Copilot CLI to reload extensions.

## Environment variables

| Variable | Default | What it does |
|---|---|---|
| `IRON_TRAIL_REPO` | `~/iron-trail` | Path to the IronTrail clone |
| `IRON_TRAIL_VAULT` | `<repo>/vault-output` | Where reviews are written |
| `IRON_TRAIL_VENV` | `<repo>/.venv` | Python environment containing IronTrail |

## Examples

```text
/lift-review
/lift-review --personality goggins
/lift-review --since 2026-04-13
/lift-recap
/lift-review --vault C:/path/to/ObsidianVault
```

