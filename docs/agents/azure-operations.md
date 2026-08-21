# Azure Operations

IronTrail's private beta is deployed with Azure Developer CLI and Bicep from
`feature/azure-hosting`. The Foundry account and model deployments already
exist; the application templates consume them rather than taking ownership of
their lifecycle.

## Subscription and environment

- Use the subscription selected in `.azure/beta/.env`; the machine's default
  Azure CLI subscription may be different.
- Pass `--subscription` explicitly to direct `az` commands.
- Never print or commit `.azure/beta/.env`, OAuth secrets, invite codes, owner
  object IDs, or captured beta output.
- AZD substitutes environment parameters as strings. Boolean-like Bicep flags
  therefore use constrained `'true'` / `'false'` string parameters.

## Validation boundary

For application changes:

```powershell
C:\venvs\3.12\irontrail\Scripts\python.exe -m pytest -q
C:\venvs\3.12\irontrail\Scripts\python.exe -m ruff check <changed-files>
```

For infrastructure changes, also run:

```powershell
az bicep build --file infra\main.bicep --stdout
azd provision --preview --no-prompt -e beta
```

`azd provision --preview` does not display role assignments in its resource
summary. Produce provider-level what-if JSON and pass it through
`scripts/validate_stage_c2_whatif.py` before applying a Stage C2 change. The
validator pins permitted resource types, property deltas, principals, role
IDs, scopes, and change directions.

Ruff has a pre-existing repository-wide baseline. Changed files must be clean;
do not use an infrastructure task as a reason to reformat unrelated modules.

## Deployment

`azure.yaml` gives the web service a Docker context of the repository root and
the Dockerfile copies that context. Before `azd deploy`:

1. Inspect `git status --short`.
2. Protect intentional tracked and untracked work without deleting it.
3. Confirm the release context is clean.
4. Deploy with `azd deploy web -e beta --no-prompt`.
5. Verify `/`, `/_stcore/health`, the active revision, traffic weight, and
   `maxReplicas=1`.
6. Restore protected local work and compare it with the pre-deploy status.

Never use `git clean`, `reset --hard`, or broad checkout restoration to prepare
a release.

## Data-plane RBAC

Subscription Owner does not grant Key Vault, Blob, or Table data-plane access.
Role assignments are unique per scope/principal/role, so a manually named
assignment can block a deterministic Bicep assignment with HTTP 409.

- Key Vault recovery uses its existing separately approved flag.
- Storage diagnostics use
  `IRONTRAIL_GRANT_OWNER_STORAGE_DIAGNOSTIC_ACCESS`.
- The Storage flag grants only **Storage Table Data Reader** at the storage
  account. It never grants Blob Reader or a contributor role.
- `scripts/audit_beta_state.py` prints redacted aggregates only; it never
  mutates Azure or displays identities, bodyweight, blob names, or workout
  content.

Diagnostic workflow:

1. Set the Storage diagnostic flag to `true`.
2. Validate provider-level what-if and provision the beta.
3. Wait for bounded RBAC propagation and run the audit with explicit resource
   arguments.
4. Set the flag back to `false`.
5. Delete the one exact Table Reader assignment by resource ID.
6. Verify zero owner roles remain at the storage-account scope.

An incremental ARM deployment does not delete a conditional role assignment
when its condition becomes false, even if what-if reports a Delete. Do not rely
on a second provision for revocation, and never use a broad assignee/role
delete.

## Current Coach operating point

- Reviews: `gpt-5-mini`, DataZoneStandard, 20K TPM.
- Chat: `gpt-5.6-luna`, DataZoneStandard, 30K TPM, reasoning effort `high`.
- OpenAI SDK retries: 2.
- Capacity does not replace application limits: per-user allowances and the
  global euro cap remain authoritative.

Capacity changes are made against the existing deployments only after reading
the model-specific regional quota. Update one deployment at a time, preserve
its model version and SKU, and read it back before touching the other.
