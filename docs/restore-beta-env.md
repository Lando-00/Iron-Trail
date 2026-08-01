# Restoring the private `beta` AZD environment

> **Why this exists:** on 2026-07-31 the contents of `.azure/beta/.env` were
> lost during this repo's setup, leaving only `AZURE_ENV_NAME`. The file is
> gitignored by design, so there is no copy in git and no backup existed.
> **Deploys are unaffected** (`azd deploy` only needs the four values already
> restored). **`azd provision` will fail until this runbook is completed.**

## What is already restored

These were recovered from the live Azure resources and are set:

```
AZURE_ENV_NAME                     beta
AZURE_SUBSCRIPTION_ID              de3679a8-d52d-42bd-9d7c-f7bed44ffc6f
AZURE_LOCATION                     northeurope
AZURE_RESOURCE_GROUP               rg-IronTrail
AZURE_CONTAINER_REGISTRY_ENDPOINT  crirontrailt5padq.azurecr.io
```

## What is still missing

| Variable | Where to get it | Recoverable without you? |
|---|---|---|
| `IRONTRAIL_GOOGLE_CLIENT_ID` | Google Cloud Console → *IronTrail Beta* → Credentials | No |
| `IRONTRAIL_GOOGLE_CLIENT_SECRET` | Same — **secret is write-once**, generate a new one if not saved | **No** |
| `IRONTRAIL_OWNER_OBJECT_ID` | Your Entra object ID | Yes — command below |
| `IRONTRAIL_BOOTSTRAP_INVITE_HASH` | SHA-256 of the original bootstrap code | No — but see note |
| `IRONTRAIL_BETA_REVEAL_SEED` | Private seed for the landing-page reveal | No — generate a new one |
| `IRONTRAIL_GOOGLE_AUTH_ENABLED` | `true` | Yes |
| `IRONTRAIL_MAX_USERS` | `1` (raise per the Stage C2 plan) | Yes |
| `IRONTRAIL_STAGE_C2_PATCH_MODE` | `true` | Yes |

**Bootstrap hash note:** the owner invite has already been redeemed
(`bootstrapClaimed=true`), so this value only needs to be *present and stable*
for the template to validate — it is no longer a live credential path. Do not
invent a value that would re-open bootstrap; reuse the original if you have it,
otherwise treat re-deriving it as a deliberate decision.

## Steps

### 1. Recover what can be recovered

```powershell
cd C:\Dev\active\iron-trail

# Your Entra object ID
az ad signed-in-user show --query id -o tsv
```

### 2. Set the non-secret values

```powershell
azd env set IRONTRAIL_GOOGLE_AUTH_ENABLED true -e beta
azd env set IRONTRAIL_MAX_USERS 1 -e beta
azd env set IRONTRAIL_STAGE_C2_PATCH_MODE true -e beta
azd env set IRONTRAIL_OWNER_OBJECT_ID "<object-id-from-step-1>" -e beta
```

### 3. Set the secrets

Run these **in your own terminal**, not through an agent, so the values are
never captured in a transcript:

```powershell
azd env set IRONTRAIL_GOOGLE_CLIENT_ID     "<google-web-client-id>"     -e beta
azd env set IRONTRAIL_GOOGLE_CLIENT_SECRET "<google-web-client-secret>" -e beta
azd env set IRONTRAIL_BOOTSTRAP_INVITE_HASH "<sha256-hex>"              -e beta
```

If the Google secret was never saved, create a new one in the Google Cloud
Console (Credentials → the *IronTrail Beta* OAuth client → **Add secret**),
then set it here and re-run provision. The existing client ID and the two
redirect URIs stay valid, so no Google re-registration is needed.

### 4. Reveal seed

The live seed cannot be read back from Container Apps. Generate a fresh private
seed and store it only in the AZD environment:

```powershell
$seed = -join ((1..48) | ForEach-Object { '{0:x}' -f (Get-Random -Max 16) })
azd env set IRONTRAIL_BETA_REVEAL_SEED $seed -e beta
```

Changing the seed changes the landing-page emoji/control pair, so re-learn the
new sequence before testing the reveal.

### 5. Validate before provisioning

```powershell
$py = "C:\venvs\3.12\irontrail\Scripts\python.exe"
& $py scripts\validate_stage_c2_config.py     # fail-closed; prints no secret values
& $py -m pytest -q
azd provision --preview --no-prompt -e beta   # must show no unexpected changes
```

Only run `azd provision` once the preview is clean and matches the Stage C2
what-if allowlist.

## Prevention

`.azure/*` is gitignored (correctly — it holds secrets). To avoid a repeat,
keep an out-of-repo copy of the non-secret keys, e.g. an encrypted note or a
password manager entry listing which variables must exist. Do not commit the
file.
