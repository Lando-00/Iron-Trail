# Infrastructure backlog

Gaps found while operating the hosted beta. Each entry states the evidence, the
proposed change, and why it is not already done.

---

## 1. Owner diagnostic access *(resolved 2026-08-21)*

**Found:** 2026-08-01, while restoring the lost `beta` AZD environment.

### Evidence

`infra/modules/application.bicep` granted Key Vault access to exactly one
principal — the workload's managed identity:

```bicep
roleAssignments: [
  {
    principalId: managedIdentity.outputs.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionIdOrName: keyVaultSecretsUserRoleId   // 4633458b-…
  }
]
```

No human principal was granted anything. Because the vault uses RBAC
(`enableRbacAuthorization: true`), subscription **Owner** does *not* confer
data-plane access, so the owner reading their own secrets got:

```
(Forbidden) Caller is not authorized to perform action on resource.
Action: 'Microsoft.KeyVault/vaults/secrets/readMetadata/action'
Assignment: (not found)
```

Recovering the environment therefore required a **manual, out-of-band**
`az role assignment create` — drift the templates knew nothing about.

### What was implemented

A `grantOwnerKeyVaultAccess` flag, defaulting to `'false'`, wired through
**both** deployment paths:

| File | Change |
|---|---|
| `infra/main.bicep` | New param; passed to both modules |
| `infra/modules/application.bicep` | Appends the owner to the vault module's `roleAssignments` |
| `infra/modules/stage_c2_patch.bicep` | Standalone `Microsoft.Authorization/roleAssignments` — this module treats the vault as `existing`, so it cannot use the vault module's array |
| `infra/main.parameters.json` | `IRONTRAIL_GRANT_OWNER_KV_ACCESS`, defaulting to `false` |
| `scripts/validate_stage_c2_whatif.py` | Narrow allowlist entry |
| `tests/test_stage_c_iac.py`, `tests/test_stage_c2_whatif.py` | Coverage |

Two details worth keeping:

- **String, not `bool`.** AZD substitutes environment values as strings, so a
  `bool` param would receive `"false"` and fail ARM type validation. This
  matches the existing `stageC2PatchMode` convention.
- **The what-if exemption is pinned.** It permits only `Create`, only the
  `Key Vault Secrets User` role ID, and only the expected owner object ID —
  so it cannot be widened into arbitrary RBAC. Negative tests cover a
  different principal, a broader role (Key Vault Administrator), `Delete`,
  `Modify`, and a missing expected owner.

### ⚠️ Required migration step before the next provision

The manual assignment created during recovery has a **random** name:

```
308855db-24a3-4a70-afd2-8743390715d8   Key Vault Secrets User   User   9f2b1274-…
```

Bicep uses a **deterministic** `guid(vaultId, ownerObjectId, roleId)` name.
Azure treats a role assignment as unique per *(scope, principal, role)*, so
creating the declared one while the manual one still exists returns
**`RoleAssignmentExists` (409)** and the deployment fails.

Delete the manual assignment first — the template will recreate it:

```powershell
$sub = "de3679a8-d52d-42bd-9d7c-f7bed44ffc6f"
$kv  = "kv-irontrail-t5padq"
$scope = "/subscriptions/$sub/resourceGroups/rg-IronTrail/providers/Microsoft.KeyVault/vaults/$kv"

az role assignment delete --ids `
  "$scope/providers/Microsoft.Authorization/roleAssignments/308855db-24a3-4a70-afd2-8743390715d8"
```

Then set `IRONTRAIL_GRANT_OWNER_KV_ACCESS=true` and provision. Verify
afterwards that exactly two assignments exist on the vault (the UAMI and the
owner) and that the owner's name is now the deterministic GUID.

> **Note:** `azd provision --preview` does **not** render role assignments in
> its resource summary — it was verified instead by inspecting the compiled ARM
> template. Do not read the preview's silence as "no RBAC change".

### Design decision

Standing human read access weakens least privilege, so three options were
considered:

| Option | Pro | Con |
|---|---|---|
| **A.** Permanent owner grant, flag-gated | Simple, in IaC, survives redeploy | Standing access to all secrets |
| **B.** Break-glass only — flag normally `false`, flipped during recovery | Least standing privilege | **Circular** — provisioning is what you need the secrets *for* |
| **C.** Entra PIM / just-in-time | Best practice | Needs a P2 licence; out of scope for a €25/mo beta |

**Chosen: A.** Option B is the trap we just fell into — you cannot provision
your way out of being unable to read the secrets that provisioning requires.
The owner is already subscription Owner and can self-grant at any time, so this
adds no privilege they lack; it makes the access *declared and auditable*
instead of improvised. The flag still defaults to `'false'`, so nothing is
granted unless an environment opts in.

### Storage diagnostics implemented

Storage uses the same data-plane RBAC boundary: subscription Owner cannot read
`IronTrailAuth`, `IronTrailData`, or `IronTrailUsage`. Standing access is not
warranted, and Blob access would expose workout files, so Storage diagnostics
remain separate from permanent Key Vault recovery:

- `IRONTRAIL_GRANT_OWNER_STORAGE_DIAGNOSTIC_ACCESS=false` is the default.
- Enabling it grants exactly **Storage Table Data Reader** to the approved
  owner at the storage-account scope.
- Both full and Stage C2 Bicep paths use deterministic role assignments.
- The what-if allowlist pins the principal, role, scope, and Create/Delete
  directions; Blob Reader and contributor roles are rejected.
- `scripts/audit_beta_state.py` reports only redacted aggregates for
  membership, invites, retention, usage, revision health, and model capacity.

The enable-audit-disable workflow was live-tested on 2026-08-21. One important
ARM behavior was confirmed: an incremental deployment does **not** delete a
conditional role assignment when its flag becomes false, even though provider
what-if reports a Delete. After setting the flag back to false, revoke the one
exact assignment explicitly by resource ID and verify zero owner roles remain
at the storage scope. Never use a broad role or assignee delete.

### Still open

- **No backup of the non-secret AZD keys.** Losing `.azure/beta/.env` cost an
  hour of recovery. The values are reconstructible from the live resources (see
  `docs/restore-beta-env.md`), but that should be a script, not archaeology.
  Suggest `scripts/export_beta_env_template.py` that writes the **key names
  only**, safe to commit.

---

## 2. `IRONTRAIL_MAX_USERS` drift *(resolved 2026-08-01)*

The live Container App reported `IRONTRAIL_MAX_USERS = 2` while
`.azure/deployment-plan.md` stated provider-only was live at `maxUsers=1`.
`azd deploy` cannot change environment variables — only `azd provision` can —
so the drift predated the 2026-08-01 deploys and its origin is unknown.

**Resolution:** the owner approved a flat ceiling of **5**, superseding the
staged `1 -> 2 -> 5` rollout rather than guessing which value was intended. The
isolation, suspension, and restoration gates are unchanged; capacity is not
permission, since every non-owner member still requires a single-use invite and
there are zero active invites.

Applied to the AZD environment on 2026-08-01. Takes effect on the live app only
after the next `azd provision`.

---

## 3. Storage encryption — reviewed, no action *(closed)*

Verified on `stirontrailt5padq`: AES-256 SSE **plus**
`requireInfrastructureEncryption: true` (double encryption at rest),
HTTPS-only, TLS 1.2 minimum. Customer-managed keys and client-side envelope
encryption were both evaluated and rejected for the beta — rationale in
`docs/persistent-dataset-design.md` §4.
