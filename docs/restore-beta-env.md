# Restoring the private `beta` AZD environment

> **Why this exists:** on 2026-07-31 the contents of `.azure/beta/.env` were
> lost during this repo's setup, leaving only `AZURE_ENV_NAME`. The file is
> gitignored by design, so there is no copy in git and no backup existed.
> **Deploys are unaffected** (`azd deploy` only needs the four values already
> restored). **`azd provision` will fail until this runbook is completed.**

## What is already restored

Recovered from the live Azure resources — the deployed Container App and its
Easy Auth config turned out to hold almost everything:

```
AZURE_ENV_NAME                     beta
AZURE_SUBSCRIPTION_ID              de3679a8-d52d-42bd-9d7c-f7bed44ffc6f
AZURE_LOCATION                     northeurope
AZURE_RESOURCE_GROUP               rg-IronTrail
AZURE_CONTAINER_REGISTRY_ENDPOINT  crirontrailt5padq.azurecr.io
AZURE_AAD_CLIENT_ID                5d4f71b2-231f-49c6-96ef-5a0978524baf
IRONTRAIL_OWNER_OBJECT_ID          9f2b1274-9c68-42a9-979e-9570fbc3ff9e
IRONTRAIL_GOOGLE_AUTH_ENABLED      true
IRONTRAIL_GOOGLE_CLIENT_ID         1033678335782-faetad6m32gcp4r7lpp19fsd6j9fkq9p.apps.googleusercontent.com
IRONTRAIL_MAX_USERS                2
IRONTRAIL_STAGE_C2_PATCH_MODE      true
```

Commands used to recover them (all read-only):

```powershell
$sub = "de3679a8-d52d-42bd-9d7c-f7bed44ffc6f"
az containerapp show -n ca-irontrail-t5padq -g rg-IronTrail --subscription $sub `
  --query "properties.template.containers[0].env" -o json
az containerapp auth show -n ca-irontrail-t5padq -g rg-IronTrail --subscription $sub -o json
az containerapp secret list -n ca-irontrail-t5padq -g rg-IronTrail --subscription $sub `
  --query "[].name" -o tsv
```

> **⚠️ `IRONTRAIL_MAX_USERS` is `2` on the live app, not `1`.** The plan's
> "Current preparation state" section says provider-only is live at
> `maxUsers=1`. `azd deploy` cannot change env vars (only `azd provision` can),
> so this predates the 2026-08-01 deploys. Reconcile the plan against reality
> before continuing Stage C2 — the beta may already be sitting at canary
> capacity.

## What is still missing

Only the four true secrets, which Azure will not return:

| Secret setting | Where to get it | Recoverable without you? |
|---|---|---|
| `google-client-secret` | Google Cloud Console → *IronTrail Beta* → Credentials. **Write-once** — generate a new one if not saved | No |
| `bootstrap-invite-hash` | SHA-256 of the original bootstrap code | No — see note |
| `beta-reveal-seed` | Private landing-reveal seed | No — generate a new one |
| `aad-client-secret` | Entra app registration `5d4f71b2-…` — also write-once | No |

**Bootstrap hash note:** the owner invite has already been redeemed
(`bootstrapClaimed=true`), so this value only needs to be *present and stable*
for the template to validate — it is no longer a live credential path. Do not
invent a value that would re-open bootstrap; reuse the original if you have it,
otherwise treat re-deriving it as a deliberate decision.

## Steps

### 1. Set the remaining secrets

Everything else is already set (see above). Run these **in your own terminal**,
not through an agent, so the values are never captured in a transcript:

```powershell
cd C:\Dev\active\iron-trail

azd env set IRONTRAIL_GOOGLE_CLIENT_SECRET  "<google-web-client-secret>" -e beta
azd env set IRONTRAIL_BOOTSTRAP_INVITE_HASH "<sha256-hex>"               -e beta
azd env set AZURE_AAD_CLIENT_SECRET         "<aad-client-secret>"        -e beta
```

If the Google secret was never saved, create a new one in the Google Cloud
Console (Credentials → the *IronTrail Beta* OAuth client → **Add secret**),
then set it here. The existing client ID and both redirect URIs stay valid, so
no Google re-registration is needed.

### 2. Reveal seed

The live seed cannot be read back from Container Apps. Generate a fresh private
seed and store it only in the AZD environment:

```powershell
$seed = -join ((1..48) | ForEach-Object { '{0:x}' -f (Get-Random -Max 16) })
azd env set IRONTRAIL_BETA_REVEAL_SEED $seed -e beta
```

Changing the seed changes the landing-page emoji/control pair, so re-learn the
new sequence before testing the reveal.

### 3. Validate before provisioning

```powershell
$py = "C:\venvs\3.12\irontrail\Scripts\python.exe"
& $py scripts\validate_stage_c2_config.py     # fail-closed; prints no secret values
& $py -m pytest -q
azd provision --preview --no-prompt -e beta   # must show no unexpected changes
```

Only run `azd provision` once the preview is clean and matches the Stage C2
what-if allowlist. Confirm the `maxUsers` value in the preview is the one you
actually intend, given the discrepancy flagged above.

## Prevention

`.azure/*` is gitignored (correctly — it holds secrets). To avoid a repeat,
keep an out-of-repo copy of the non-secret keys, e.g. an encrypted note or a
password manager entry listing which variables must exist. Do not commit the
file.
