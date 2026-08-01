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

Only three values, and **all three already exist in Key Vault
`kv-irontrail-t5padq`** — nothing needs rotating or re-creating:

| AZD variable | Key Vault secret |
|---|---|
| `IRONTRAIL_AAD_CLIENT_SECRET` | `aad-client-secret` |
| `IRONTRAIL_BOOTSTRAP_INVITE_HASH` | `bootstrap-invite-hash` |
| `IRONTRAIL_BETA_REVEAL_SEED` | `beta-reveal-seed` |

`IRONTRAIL_GOOGLE_CLIENT_SECRET` was re-issued by the owner on 2026-08-01 and
is already set.

### The catch: Key Vault uses RBAC, and the owner has no data-plane role

Subscription **Owner** does *not* grant secret read access. `az keyvault secret
list` returns `(Forbidden) ... Assignment: (not found)` — only the container's
user-assigned managed identity can read. Grant yourself the data role first
(you have Owner, so you can), then remove it afterwards if you prefer least
privilege.

> **⚠️ This adds a role assignment.** The Stage C2 plan treats unapproved role
> assignments as a what-if rejection. This one is on the *data plane* for a
> human, is not part of the Bicep template, and will not appear in an
> infrastructure what-if — but record it as a deliberate, reversible act.

```powershell
$sub = "de3679a8-d52d-42bd-9d7c-f7bed44ffc6f"
$kv  = "kv-irontrail-t5padq"
$me  = "9f2b1274-9c68-42a9-979e-9570fbc3ff9e"

az role assignment create --assignee $me --role "Key Vault Secrets User" `
  --scope "/subscriptions/$sub/resourceGroups/rg-IronTrail/providers/Microsoft.KeyVault/vaults/$kv"

Start-Sleep -Seconds 30   # RBAC propagation
```

Then pipe the values straight into AZD so they are never printed to a terminal
or captured in an agent transcript:

```powershell
cd C:\Dev\active\iron-trail

azd env set IRONTRAIL_AAD_CLIENT_SECRET `
  (az keyvault secret show --vault-name $kv -n aad-client-secret --query value -o tsv) -e beta
azd env set IRONTRAIL_BOOTSTRAP_INVITE_HASH `
  (az keyvault secret show --vault-name $kv -n bootstrap-invite-hash --query value -o tsv) -e beta
azd env set IRONTRAIL_BETA_REVEAL_SEED `
  (az keyvault secret show --vault-name $kv -n beta-reveal-seed --query value -o tsv) -e beta
```

Reading the existing seed preserves the current landing-page emoji/control
pair, so there is no need to re-learn the reveal sequence.

Optional cleanup once provisioning is done:

```powershell
az role assignment delete --assignee $me --role "Key Vault Secrets User" `
  --scope "/subscriptions/$sub/resourceGroups/rg-IronTrail/providers/Microsoft.KeyVault/vaults/$kv"
```

### If Key Vault access is refused entirely

Only then fall back to re-issuing. `google-client-secret` and
`aad-client-secret` are write-once in their respective consoles; the reveal
seed can be regenerated with:

```powershell
$seed = -join ((1..48) | ForEach-Object { '{0:x}' -f (Get-Random -Max 16) })
azd env set IRONTRAIL_BETA_REVEAL_SEED $seed -e beta
```

**Bootstrap hash note:** the owner invite has already been redeemed
(`bootstrapClaimed=true`), so this value only needs to be *present and stable*
for the template to validate — it is no longer a live credential path. Do not
invent a value that would re-open bootstrap.

## Steps

### 1. Recover the three remaining secrets from Key Vault

See the section above — grant yourself `Key Vault Secrets User`, then pipe each
secret directly into `azd env set`.

### 2. Validate before provisioning

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
