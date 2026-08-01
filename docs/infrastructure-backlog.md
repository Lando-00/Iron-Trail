# Infrastructure backlog

Gaps found while operating the hosted beta. Each entry states the evidence, the
proposed change, and why it is not already done.

---

## 1. Owner Key Vault access is not in IaC *(open)*

**Found:** 2026-08-01, while restoring the lost `beta` AZD environment.

### Evidence

`infra/modules/application.bicep:269-274` grants Key Vault access to exactly one
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

No human principal is granted anything. Because the vault uses RBAC
(`enableRbacAuthorization: true`), subscription **Owner** does *not* confer
data-plane access, so the owner reading their own secrets gets:

```
(Forbidden) Caller is not authorized to perform action on resource.
Action: 'Microsoft.KeyVault/vaults/secrets/readMetadata/action'
Assignment: (not found)
```

Recovering the environment therefore required a **manual, undocumented,
out-of-band** `az role assignment create`. That is drift: the deployed access
model no longer matches the template, and nothing in the repo records it.

### Why it matters

- **Drift** — a redeploy will not recreate the assignment, so the next person
  hits the same wall and improvises again.
- **Auditability** — the Stage C2 plan treats unapproved role assignments as a
  what-if rejection, yet this one is invisible to `what-if` because it was made
  by hand on the data plane.
- **Recovery** — Key Vault is the *only* place the beta secrets survive. If
  nobody can read it, the fallback is rotating live credentials, which causes
  an auth outage.

### Proposed change

`ownerObjectId` is already a parameter, so the addition is small. Gate it so it
is explicit and reviewable:

```bicep
@description('Grant the owner data-plane read on Key Vault for break-glass recovery.')
param grantOwnerKeyVaultAccess bool = false

// inside the Key Vault module's roleAssignments:
roleAssignments: concat(
  [
    {
      principalId: managedIdentity.outputs.principalId
      principalType: 'ServicePrincipal'
      roleDefinitionIdOrName: keyVaultSecretsUserRoleId
    }
  ],
  grantOwnerKeyVaultAccess ? [
    {
      principalId: ownerObjectId
      principalType: 'User'
      roleDefinitionIdOrName: keyVaultSecretsUserRoleId
    }
  ] : []
)
```

Then `IRONTRAIL_GRANT_OWNER_KV_ACCESS` in `main.parameters.json`, and extend
`scripts/validate_stage_c2_whatif.py` to allow exactly this one role assignment
when the flag is on — so it stays fail-closed.

### Open design question

Standing human read access to every secret is convenient but weakens the blast
radius argument. Three options:

| Option | Pro | Con |
|---|---|---|
| **A.** Permanent `Key Vault Secrets User` for the owner, flag-gated | Simple, in IaC, survives redeploy | Standing access to all secrets |
| **B.** Break-glass only — flag normally `false`, flipped during recovery | Least standing privilege, still in IaC | Requires a provision to recover, and provision needs the secrets → **circular** |
| **C.** Entra PIM / just-in-time elevation | Best practice | Needs a P2 licence; out of scope for a €25/mo beta |

**Recommendation: A, flag-gated and defaulted `false`, enabled for this beta.**
Option B is circular — you cannot provision your way out of not being able to
read the secrets you need in order to provision. The owner is already
subscription Owner and can self-grant at any time, so A grants no privilege
they lack; it just makes the access *declared and auditable* instead of
improvised.

### Also fix at the same time

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
