# Persistent single-dataset storage — design

> **Status:** Design approved for implementation · branch `feature/persistent-dataset`
> **Author:** overnight autopilot session, 2026-08-01
> **Scope:** hosted (`IRONTRAIL_MODE=cloud`) only. Local mode is unchanged.

## 1. Requirement

> "A user can only upload one Hevy workout `.csv`, but it should be saved on
> page reloads, and logout and relogin — it should come back. Data should be
> encrypted when stored in Azure."

Three distinct asks:

| # | Ask | Current behaviour | Gap |
|---|---|---|---|
| R1 | **One** CSV per user | Unlimited datasets per user | Needs single-slot semantics |
| R2 | Survives reload / logout / relogin | Persistence exists but is opt-in **and** the picker defaults to the synthetic sample | Needs auto-restore |
| R3 | Encrypted at rest in Azure | Already satisfied — see §4 | Documentation + optional hardening |

## 2. What already exists

Most of the machinery is built. `iron_trail/cloud_storage.py` already provides
`AzureDatasetRepository` with `save_hevy_dataset`, `list_datasets`,
`load_dataset`, `delete_dataset`, `delete_all` and `export_user_archive`,
backed by Blob (raw CSV + normalized Parquet) and Table (metadata), with
30-day raw / 60-day normalized retention.

So this is mostly a **wiring and semantics** change, not new infrastructure.

### Why the data doesn't currently "come back"

Two independent reasons, both in `iron_trail/sidebar.py::_render_cloud_data_source`:

1. **Saving is opt-in and two-step** — the user must tick *"Save privately"*
   and then press *"Save this dataset"*. Skipping either means the upload is
   session-only and dies with the browser tab.
2. **Restore defaults to the sample** — when there is no session upload the
   dataset `selectbox` is built as `[None, *records]`, and `None` renders as
   *"Synthetic sample"*. Because `None` is first it is the default selection,
   so a returning user sees sample data even when a saved dataset exists.

## 3. Design

### 3.1 Single-slot semantics (R1)

Add `AzureDatasetRepository.save_single_dataset(user_id, content, filename, df)`.

Ordering is **save-then-prune**, never prune-then-save:

1. Save the new dataset via the existing `save_hevy_dataset` path.
2. On success, delete every *other* `dataset_id` for that user.

If step 1 fails the user keeps their previous dataset; if step 2 partially
fails the user has a valid current dataset plus a stale one that the existing
retention sweep in `list_datasets` will eventually remove. There is no window
in which the user has no data.

`InMemoryDatasetRepository` gets the same method so tests and local runs stay
symmetrical.

### 3.2 Auto-restore (R2)

In `_render_cloud_data_source`, when there is no session upload:

- If the user has a saved dataset, load it **by default** and label it clearly.
- Offer the synthetic sample as an explicit alternative, not the default.

With single-slot there is at most one record, so the `selectbox` collapses to a
simple "your data / sample" toggle.

### 3.3 Persistence policy (the one real decision)

The approved Stage C design states *"Session-only uploads by default; explicit
opt-in Blob/Table persistence."* The requirement above asks for the opposite
default. That is a deliberate product decision by the data controller, so it is
implemented as a **flag**, not a hard-coded reversal:

```
IRONTRAIL_AUTO_PERSIST_UPLOADS = "true"   # new; default true in cloud mode
```

- `true` — an upload is saved to the user's single slot immediately, with a
  visible notice stating the data is stored and how to delete it.
- `false` — the previous explicit opt-in flow.

Rationale for defaulting to `true`: the hosted beta is invite-only, every user
has already redeemed a single-use invite, retention limits and one-click
*Delete All* already exist, and the alternative silently loses the user's data.
Setting the flag to `false` restores the original posture with no code change,
so this remains reversible and auditable.

**Docs to update on rollout:** `.azure/deployment-plan.md` §5 user-data model,
`README.md` runtime-modes table.

## 4. Encryption (R3)

### Already in place — verified on the live account `stirontrailt5padq`

```
az storage account list -g rg-IronTrail --query "[].{...}"
```

| Control | Value | Meaning |
|---|---|---|
| `encryption.services.blob.enabled` | `true` | AES-256 SSE at rest |
| `encryption.requireInfrastructureEncryption` | `true` | **Double** encryption — a second, independent AES-256 layer |
| `encryption.keySource` | `Microsoft.Storage` | Platform-managed keys, auto-rotated |
| `enableHttpsTrafficOnly` | `true` | Encrypted in transit |
| `minimumTlsVersion` | `TLS1_2` | No legacy TLS |

**R3 is already met, and exceeds the default** — infrastructure encryption
means the payload is encrypted twice at rest with separate keys. No change is
required to satisfy the requirement.

### Optional hardening (not implemented — deliberate)

| Option | Gain | Cost |
|---|---|---|
| **Customer-managed keys (CMK)** — Key Vault key + UAMI `Key Vault Crypto Service Encryption User` | Owner controls/revokes the key; revocation instantly bricks the data | Key Vault key ~free; adds a hard dependency — losing the key destroys all data, and key-rotation outages take the app down |
| **Client-side envelope encryption** — app encrypts the Parquet/CSV before upload, key in Key Vault | True defence against platform/operator read, and closes the "7-day privileged blob recovery" gap in the current privacy notice | Breaks server-side Parquet range reads, complicates export/recovery, and a lost key is unrecoverable |

**Recommendation: keep platform-managed double encryption for the beta.** The
realistic threat model here is *other tenants and other beta users*, which is
addressed by per-user blob path partitioning plus the authorization gate — not
by CMK. Revisit client-side encryption only if the beta ever holds data for
users who should not trust the operator.

## 5. Implementation checklist

- [x] `save_single_dataset` on both repositories (save-then-prune)
- [x] `runtime.auto_persist_uploads()` reading `IRONTRAIL_AUTO_PERSIST_UPLOADS`
- [x] Sidebar: auto-save on upload when enabled
- [x] Sidebar: auto-restore the saved dataset as the default source
- [x] Tests: single-slot replacement, prune-failure safety, auto-restore default
- [ ] Live two-user verification (blocked — belongs to the Stage C2 gate)
- [ ] Update `.azure/deployment-plan.md` + `README.md` when the policy is accepted

## 6. Risks

| Risk | Mitigation |
|---|---|
| Changes the documented consent posture | Flag-controlled and reversible; notice shown in the UI; delete controls already exist |
| A user's existing multiple datasets get pruned on next upload | Prune only runs on a *new* upload, and only after it succeeds; export is available first |
| Interacts with the in-flight Stage C2 rollout | Isolated on `feature/persistent-dataset`; touches no Bicep and no auth code |
