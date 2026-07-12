# IronTrail Azure Deployment Plan

> **Status:** Stage A complete - Foundry credit proof pending

Generated: 2026-07-11  
Last verified: 2026-07-12

---

## 1. Project Overview

**Goal:** Modernize the existing IronTrail Streamlit application into an
invite-only, multi-user Azure website without exposing one user's workout or
health data to another user and without using the owner's GitHub Copilot
account for hosted AI.

**Path:** Modernize Existing

**Initial URL:** Azure-provided `azurecontainerapps.io` hostname. No custom
domain in the first release.

### Current baseline

| Item | State |
|---|---|
| Public remote | `origin/main` at `588eeb5` |
| Local branch | `main` at `334c530`, one commit ahead |
| Samsung Health | Parsing/summary foundation committed locally; not pushed |
| Samsung verification | 52 targeted tests pass; real export verification pending |
| Full test suite | Collection currently fails because `scripts/test_upload.py` executes during import |
| Ruff | 24 existing findings outside the new health package |
| Untracked | `.azure/`, `scripts/spike_copilot_sdk.py`, `scripts/test_pdf_output.pdf` |
| Streamlit runtime | Offline |
| Azure resource group | `rg-IronTrail` exists in Sweden Central |
| Foundry account | `irontrail-resource`, AIServices S0, provisioning succeeded |
| Foundry project | `irontrail` under `irontrail-resource` |
| Foundry network | Keep public endpoint for beta; Entra/RBAC only, no committed API keys |
| Model deployments | None |
| Hosting branch | `feature/azure-hosting` |
| Stage A implementation | Complete and locally validated |

The Samsung commit remains local until a later explicit push approval. The
public repository must never contain a real Hevy, Samsung Health, Health
Connect, or other personal health export.

### Planning status

Completed:

- Product scope, privacy boundary, retention, authentication, model policy,
  regions, budget, architecture, quotas, cost controls, and Git boundaries.
- Existing Foundry account/project creation and read-only verification.
- Stage A task/dependency graph.

Implemented:

- `feature/azure-hosting` from public `origin/main`; the local Samsung commit
  remains excluded.
- Local/cloud runtime split, one-time invite authorization, isolated opt-in
  storage, retention metadata, user export/deletion, and cloud-safe downloads.
- Managed-identity Foundry provider, application usage ledger, bounded uploads,
  non-root container, telemetry, AZD, and pinned AVM Bicep.

Still deferred:

- Any model deployment or paid Foundry inference.
- Any website infrastructure deployment.
- Google OAuth setup, live identity tests, and live two-user isolation tests.

---

## 2. Requirements

| Attribute | Value |
|---|---|
| Classification | Development / invite-only private beta |
| Scale | Small: maximum 5 invited testers |
| Budget | Cost-optimized; target ceiling EUR 25/month before credits |
| Subscription | Visual Studio Enterprise Subscription (selected in the local AZD environment) |
| App/data location | North Europe |
| AI location | Sweden Central, EU Data Zone deployment |
| Resource group | Reuse existing `rg-IronTrail` |
| Authentication | Microsoft and Google |
| Persistence default | Session-only; cloud persistence requires explicit opt-in |
| Raw retention | 30 days after opt-in upload |
| Normalized retention | 60 days |
| AI budget behavior | Disable hosted AI until the next month when the hard cap is reached |
| Custom domain | Deferred |
| Current execution scope | Code and infrastructure definitions only; no Azure deployment |

### Policy constraints

- The management-group policy `sys.blockwesteurope` denies West Europe
  deployments. This invalidated the original West Europe AI choice.
- The subscription's Security Center policy assignment is audit-oriented and
  does not currently block the selected resources.

---

## 3. Components Detected

| Component | Type | Technology | Path |
|---|---|---|---|
| Dashboard | Web application | Python 3.12, Streamlit 1.57 | `streamlit_app.py`, `pages/` |
| Analytics | Application library | Pandas, Plotly, scikit-learn | `iron_trail/` |
| AI Coach | Application library | Provider abstraction, local Copilot SDK | `iron_trail/coach/` |
| Samsung Health | Data adapter | ZIP/CSV parser and Pandas summaries | `iron_trail/health/` |
| Local writeback | Local-only feature | Markdown/PDF filesystem export | `iron_trail/vault_notes.py`, `iron_trail/coach/export/` |
| Tests | Test suite | pytest | `tests/` |

### Hosting gaps found

- No authentication or authorization boundary.
- Uploaded data is session memory only and local file choices are shared at
  server scope.
- `st.cache_data` is global across Streamlit sessions.
- Vault path inputs write to the server filesystem, not a visitor's computer.
- The production Coach defaults to the owner's local Copilot authentication.
- There is no durable user/dataset model or per-user rate limiting.
- Samsung ZIP ingestion lacks explicit compressed-size, expanded-size,
  member-count, and compression-ratio limits.

---

## 4. Recipe Selection

**Selected:** Azure Developer CLI (AZD) with Bicep

**Rationale:**

- Azure-first, multi-resource deployment.
- One command can provision infrastructure and deploy the container.
- Bicep keeps the Azure architecture explicit and reviewable.
- The existing project has no IaC to preserve or convert.
- Deployment execution remains gated behind `azure-validate` and
  `azure-deploy`.

---

## 5. Architecture

**Stack:** Serverless containers with a user-assigned managed identity

```text
Microsoft / Google
        |
        v
Container Apps Easy Auth
        |
        v
IronTrail Streamlit container (North Europe, min 0 / max 1)
        |                 |
        | managed identity| aggregated summaries only
        v                 v
StorageV2             Microsoft Foundry (Sweden Central)
Blob + Tables         gpt-5-mini DataZoneStandard
        |
        v
Private per-user raw and normalized datasets
```

### Service mapping

| Component | Azure service | SKU / configuration |
|---|---|---|
| Streamlit website | Azure Container Apps | Consumption, 1 vCPU / 2 GiB, min 0, max 1, user-assigned identity |
| Container images | Azure Container Registry | Basic |
| Dataset files | Blob Storage | StorageV2, Standard_LRS, private containers |
| Invitations/metadata/usage | Azure Table Storage | Same StorageV2 account |
| Hosted AI account/project | Existing Microsoft Foundry resources | `irontrail-resource` / `irontrail`, Sweden Central |
| Hosted AI model | Azure OpenAI deployment | Later Stage B: `gpt-5-mini`, DataZoneStandard, initial 10K TPM |
| Secrets | Azure Key Vault | Standard |
| Telemetry | Application Insights | Workspace-based |
| Logs | Log Analytics workspace | Pay-as-you-go, 30-day retention and low daily cap |
| Cost alerts | Azure Cost Management budget | Alerts at EUR 10, EUR 20, and EUR 25 |

### Authentication and authorization

- Container Apps Easy Auth handles Microsoft and Google OAuth and its secure
  session cookie. IronTrail will not invent its own session token.
- Multiple-provider mode exposes only a login landing page to unauthenticated
  visitors.
- A shared `require_invited_user()` guard runs before data loading on every
  Streamlit page.
- Authorization uses expiring, single-use invite codes stored only as hashes.
  The first code binds the owner as administrator; the owner can issue up to
  four additional codes. Successful redemption binds the immutable
  provider/principal identifier.
- Storage keys use an internal opaque user identifier derived from the
  provider and principal ID, never a filename or display name.
- Unknown or uninvited identities can authenticate but cannot enter the
  dashboard or access data.
- The first deployment enables Microsoft login. Google support is implemented
  in code but its external OAuth configuration is added before any testers are
  invited.

### User-data model

```text
Blob: datasets/{user_id}/{dataset_id}/raw/...         expires after 30 days
Blob: datasets/{user_id}/{dataset_id}/normalized/...  expires after 60 days
Table Invitations: hashed one-time code -> bound identity/status/expiry
Table Users: user preferences and consent state
Table Datasets: user-partitioned dataset metadata and expiry
Table AiUsage: per-user daily/monthly counters and actual token usage
```

- Session-only is the default. Nothing is written to Azure until the user
  explicitly selects cloud persistence.
- Saved files remain private and are accessed only by the app's managed
  identity.
- Blob lifecycle rules enforce 30/60-day deletion. Expired table metadata is
  removed opportunistically and during administrative cleanup.
- Users receive explicit Download and Delete All Data controls.
- Hosted mode disables arbitrary server filesystem/Vault paths. Markdown and
  PDF remain browser downloads. Local mode keeps Obsidian writeback.

### AI Coach

- Local mode retains `CopilotProvider` for the owner.
- Hosted mode uses a new `AzureFoundryProvider`; the Copilot SDK is not
  installed or authenticated in the production container.
- Production authentication uses `ManagedIdentityCredential`; local Azure
  development uses `DefaultAzureCredential`.
- The project endpoint is configuration, not a secret. No API key is copied
  from the Foundry portal or committed; RBAC credentials are used.
- Only deterministic aggregates and recovery summaries are sent to the model.
  Raw CSVs, raw heart-rate samples, free-text workout notes, and health export
  files are excluded.
- User-entered labels are treated as untrusted data, not model instructions.
- Per user:
  - Up to 3 generated reviews per day and 30 per month.
  - Up to 15 chat calls per day and 200 per month.
  - Bounded input/output tokens and timeouts.
- Global:
  - Estimated AI-spend hard cap of EUR 10/month.
  - Azure deployment TPM/RPM quota is a second backstop.
  - When the cap is reached, only the AI Coach is disabled; deterministic
    dashboards remain available.

### Model selection

The application provider must be deployment-name driven rather than
hard-coding a model.

**Confirmed launch default:** `gpt-5-mini`

- Generally Available.
- Supports DataZoneStandard in Sweden Central.
- Better fit for health-adjacent coaching where alignment and predictable
  content filtering matter.
- Its context window already exceeds IronTrail's deliberately small aggregate
  prompts.

**Confirmed synthetic-only candidate:** `DeepSeek-V4-Flash` version `2026-04-23`

- The live Foundry page and catalog identify it as a Preview, Direct-from-Azure
  serverless/pay-as-you-go model.
- The wizard targets the existing Visual Studio subscription, project
  `IronTrail`, resource `irontrail-resource`, resource group `rg-IronTrail`,
  and Sweden Central with public network access enabled.
- It offers text input/output, a one-million-token context, free playground
  access, and serverless deployment options.
- The page does not expose a complete input/output price split. The user saw
  an indicated USD 8 per one million tokens; the exact meter must be confirmed
  before comparison.
- Microsoft explicitly warns that the model is less aligned, has higher harmful
  output risk, and scores lower on safety/jailbreak benchmarks.
- Catalog metadata offers Sweden Central only under GlobalStandard.
  DataZoneStandard locations for this model are currently US regions, so it
  does not satisfy the current EU Data Zone requirement for real health data.

DeepSeek may be evaluated later with synthetic summaries in the free
playground. It cannot replace the launch default unless pricing, safety, and
data-residency decisions are explicitly revisited.

The existing public Foundry endpoint is accepted for the low-cost beta. Access
uses Entra ID/RBAC and HTTPS; application code does not use or persist portal
API keys. A private endpoint/VNet is deferred because it adds fixed cost and
complexity and is not required for the five-user development beta.

### Managed identity and RBAC

The Container App's user-assigned identity receives only:

- `AcrPull` on the registry.
- `Storage Blob Data Contributor` on the dataset storage account.
- `Storage Table Data Contributor` on the metadata storage account.
- `Cognitive Services OpenAI User` on the Foundry account.
- `Key Vault Secrets User` only where an auth provider secret reference
  requires it.

Using a pre-created user-assigned identity avoids the circular dependency
between a new Container App identity and the private ACR image it must pull.

Shared-key storage access and public blob access are disabled.

---

## 6. Provisioning Limit Checklist

Resource counts were queried with Azure Resource Graph. Container Apps quota
came from `az quota list`. Foundry quota came from the Foundry
`model_quota_list` operation. Unsupported count quotas use current Microsoft
service-limit documentation.

| Resource type | Deploy | Total after | Limit/quota | Result/source |
|---|---:|---:|---:|---|
| Resource groups | 0 | 9 | 980/subscription | Existing `rg-IronTrail`; official ARM limits |
| `Microsoft.App/managedEnvironments` | 1 | 1 | 20/region | Within limit; quota `ManagedEnvironmentCount` |
| `Microsoft.App/containerApps` | 1 | 1 | 800/type/resource group | Within limit; ARM resource limit |
| `Microsoft.ContainerRegistry/registries` | 1 | 1 | 100/subscription | Within limit; ACR service limits |
| `Microsoft.Storage/storageAccounts` | 1 | 2 | 250/region by default | Within limit; ARG + Storage limits |
| `Microsoft.KeyVault/vaults` | 1 | 1 | 800/type/resource group | Within limit; ARM resource limit |
| `Microsoft.OperationalInsights/workspaces` | 1 | 1 | 1,000/subscription | Within limit; Azure Monitor limits |
| `Microsoft.Insights/components` | 1 | 1 | 1,000/subscription | Within limit; Azure Monitor limits |
| `Microsoft.CognitiveServices/accounts` | 0 | 1 | 100 AI Services S0 accounts | Existing `irontrail-resource`; Foundry quota |
| `gpt-5-mini` DataZoneStandard | 1 at 10K TPM | 10K TPM | 300K TPM in Sweden Central | Within limit; current usage 0 |

**Status:** All planned resources are within current limits.

---

## 7. Cost Estimate and Controls

Indicative July 2026 retail pricing; actual billing remains authoritative.

| Item | Expected monthly cost |
|---|---:|
| Container Registry Basic | About EUR 4.45 fixed |
| Container Apps Consumption | About EUR 0 at beta usage if within the monthly free grant; allow EUR 0-2 contingency |
| Blob/Table Storage | Usually below EUR 0.50 for five testers and short retention |
| Key Vault + monitoring | About EUR 0-1 at low transaction/log volume |
| Foundry `gpt-5-mini` | About EUR 1-5 under normal beta use; app hard cap EUR 10 |
| **Expected total** | **About EUR 5.5-12/month** |
| **Planning ceiling** | **EUR 25/month** |

Cost controls:

- Container App scales to zero and cannot exceed one replica initially.
- Consumption free grant: 180,000 vCPU-seconds, 360,000 GiB-seconds, and
  2 million requests per subscription per month.
- Short storage lifecycle and no database/server minimum charge.
- Log retention and ingestion cap.
- AI per-user quotas plus a global fail-closed cap.
- Azure budget alerts are informational and do not replace application caps.
- A later optimization can publish a public image to GHCR and remove the
  roughly EUR 4.45 ACR fixed cost.

### Visual Studio credit and Foundry proof

- The selected Visual Studio Enterprise benefit is an individual Dev/Test
  credit subscription. Microsoft documentation lists a renewable monthly
  credit for eligible Enterprise Standard subscriptions and applies it to
  standard Azure consumption meters.
- Foundry models sold directly by Azure, including Azure OpenAI models, are
  Microsoft-billed token meters in Cost Management. The selected
  `gpt-5-mini` deployment is not a third-party Marketplace managed-compute
  model.
- A base-model DataZoneStandard deployment is pay-per-token rather than a
  fine-tuned-model hourly hosting commitment.
- The existing Foundry account/project has no model deployments, so there is
  currently no token usage from IronTrail.
- The subscription already exposes `gpt-5-mini` DataZoneStandard quota in
  Sweden Central, which confirms service eligibility but not the remaining
  credit balance.
- DeepSeek-V4-Flash is also Direct from Azure and Microsoft-billed, but its
  Preview status and GlobalStandard-only Sweden deployment make it a synthetic
  evaluation candidate rather than the health-data default.
- Azure MCP cannot prove the current Visual Studio credit balance. Before the
  website is provisioned, the later Azure stage must verify that the
  subscription spending limit is enabled, deploy only the minimal Foundry
  resources, make one tiny metered request, and confirm the cost appears
  against this subscription.
- Visual Studio credits are for development/testing and do not provide a
  production SLA. They are appropriate for this five-user private beta, not a
  later public production service.

---

## 8. Health Integration Roadmap

### Samsung Health

The local Phase 3.1 foundation is useful but not production-ready:

- Parses Samsung ZIP data for heart rate, HRV, sleep, weight, steps, stress,
  and workouts.
- Builds daily and per-workout summaries plus recovery flags.
- Has 52 passing targeted tests and a synthetic sample.
- Is not wired into Streamlit, hosted storage, or the Coach.
- Has placeholders for workout reconciliation and Health Sync CSV.
- Has not been validated against a real Samsung export.
- Needs ZIP-bomb and memory-limit hardening before hosted upload.

Planned heart-rate surfaces:

- Recovery page with resting-HR, HRV, sleep, stress, and coverage trends.
- Per-workout average/max HR and time in zones.
- Time-overlap reconciliation between Hevy and wearable workouts.
- Relationships between recovery context and deterministic performance
  metrics.
- Aggregate recovery context in Coach reviews, with no raw samples.
- Observational language and a clear non-medical disclaimer.

### Google / Android Health Connect

- Do not build on the deprecated Google Fit APIs; support ends after 2026.
- Health Connect is an on-device Android API, not a cloud OAuth/REST service.
- After Samsung stabilizes the canonical health schema, design an Android
  companion that reads least-privilege Health Connect records and uploads
  normalized data through an authenticated API.
- A future small API service can run in the same Container Apps environment.
- Google Takeout may later provide manual legacy backfill.
- Google Health API is a separate future option for Fitbit/Pixel cloud data,
  not a substitute for arbitrary Health Connect data.

---

## 9. Autopilot Execution Contract

### Approved now: Stage A, code-first

Autopilot may proceed without further prompts to:

- Create `feature/azure-hosting` from `origin/main`, leaving local `main` and
  Samsung commit `334c530` untouched.
- Modify application code, tests, documentation, dependencies, Dockerfiles,
  AZD/Bicep definitions, and this plan.
- Run builds, linters, tests, container checks, Bicep compilation, and
  non-provisioning Azure validation.
- Make small logical commits.
- Push `feature/azure-hosting` after all code checks pass.

Autopilot must leave `scripts/spike_copilot_sdk.py` and
`scripts/test_pdf_output.pdf` untouched and uncommitted. It must not merge the
feature branch.

### Deferred: Stage B, Foundry credit proof

No Azure resource is created during Stage A. A later explicit Azure stage will:

1. Verify the Visual Studio credit/spending-limit state.
2. Reuse the existing `rg-IronTrail`, `irontrail-resource`, and `irontrail`
   project and create only the `gpt-5-mini` DataZoneStandard deployment.
3. Make one bounded test call.
4. Confirm billing and quota behavior before continuing.

### Deferred: Stage C, website deployment

Only after the Foundry credit proof succeeds will the full Container Apps,
ACR, Storage, Key Vault, monitoring, auth, and budget deployment run.

### Hard stops

Autopilot must stop before:

- Creating any additional Azure resource during Stage A. The existing
  `rg-IronTrail`, `irontrail-resource`, and `irontrail` project are read-only
  dependencies during code work.
- Pushing Samsung Health code or real health/workout data.
- Exceeding the EUR 25/month plan.
- Bypassing a failed isolation, authentication, upload-safety, or AI-limit
  test.
- Changing repository visibility, adding a custom domain, merging to `main`,
  or deleting Azure resources.

---

## 10. Execution Checklist

### Phase 1: Planning

- [x] Analyze workspace and Git baseline.
- [x] Gather product, privacy, scale, budget, and retention requirements.
- [x] Confirm subscription and regions.
- [x] Check policy constraints.
- [x] Select AZD/Bicep recipe and architecture.
- [x] Validate resource limits and Foundry quota.
- [x] Estimate costs and define hard controls.
- [x] User approves Stage A code-first autopilot.

### Stage A: Code and deployment definitions

- [x] Establish a clean test/lint baseline.
- [x] Add local/cloud runtime modes and centralized auth guard.
- [x] Add per-user storage, retention, deletion, and export services.
- [x] Add Azure Foundry provider and enforce usage caps.
- [x] Harden uploaded CSV/ZIP handling.
- [x] Add Dockerfile, `azure.yaml`, and Bicep modules.
- [x] Configure Easy Auth, managed identity, RBAC, budgets, and monitoring.
- [x] Compile and validate Bicep/AZD without provisioning.
- [ ] Push `feature/azure-hosting`; do not merge.

### Stage B: Foundry credit proof - later explicit stage

- [ ] Confirm spending limit and remaining Visual Studio benefit.
- [ ] Invoke `azure-validate` for the minimal Foundry deployment.
- [ ] Reuse the existing Foundry account/project and deploy only `gpt-5-mini`.
- [ ] Make one tiny request and verify Cost Management/credit behavior.

### Stage C: Full validation and website deployment - later explicit stage

- [ ] Update this status to `Ready for Validation`.
- [ ] Invoke `azure-validate` for the complete architecture.
- [ ] Verify local and containerized application behavior.
- [ ] Test Microsoft and Google login.
- [ ] Test two simultaneous users and prove negative cross-user access.
- [ ] Verify opt-in persistence and 30/60-day expiry configuration.
- [ ] Verify AI quotas, global disable behavior, and no Copilot credentials.
- [ ] Record validation proof and set status to `Validated`.

- [ ] Invoke `azure-deploy`.
- [ ] Smoke-test the Azure-provided URL.
- [ ] Confirm monitoring and cost alerts.
- [ ] Record deployed endpoints and set status to `Deployed`.

---

## 11. Validation Proof

The `azure-validate` skill must populate this section before the plan can move
to `Validated`.

| Check | Command run | Result | Timestamp |
|---|---|---|---|
| Python lint | `ruff check .` | Pass | 2026-07-12 |
| Python tests | `python -m pytest -q` | 28 passed | 2026-07-12 |
| Container build | `docker build -t irontrail:stage-a .` | Pass | 2026-07-12 |
| Container health | `/_stcore/health` and `/` | HTTP 200 | 2026-07-12 |
| Cloud image isolation | Non-root UID; no `copilot` package | Pass | 2026-07-12 |
| Bicep compilation | `az bicep build --file infra/main.bicep` | Pass | 2026-07-12 |
| Azure template validation | `az deployment sub validate` with dummy auth values | Succeeded; no resources created | 2026-07-12 |
| AZD schema | `azd show --output json --no-prompt` | Pass | 2026-07-12 |

---

## 12. Files to Generate

| File/component | Purpose | Status |
|---|---|---|
| `.azure/deployment-plan.md` | Deployment source of truth | Complete |
| `azure.yaml` | AZD service definition | Complete |
| `infra/main.bicep` and modules | Azure resources, roles, lifecycle, budgets; reference existing Foundry resources | Complete |
| `Dockerfile`, `.dockerignore` | Reproducible Streamlit container | Complete |
| `iron_trail/auth.py` | Easy Auth identity normalization and invite guard | Complete |
| `iron_trail/cloud_storage.py` | User-partitioned Blob/Table persistence | Complete |
| `iron_trail/coach/providers/azure_foundry.py` | Hosted AI provider | Complete |
| `iron_trail/usage_limits.py` | Per-user/global AI reservation ledger | Complete |
| Tests | Auth, isolation, retention, uploads, AI limits | Complete |

---

## 13. Git and Release Boundary

- Do not push the Samsung commit yet.
- Do not amend or squash the existing Samsung commit.
- Do not commit the two old untracked diagnostic artifacts.
- Create `feature/azure-hosting` from `origin/main`, not from local `main`, so
  the paused Samsung commit is excluded.
- Push the validated feature branch, but do not merge it.
- Make Azure work in small logical commits.
- No force push.
- Any future Samsung push contains source, tests, lookups, and synthetic data
  only. Real exports remain local and ignored.

---

## 14. Next Step

Push the validated Stage A feature branch without merging it. The next
separately approved stage deploys only `gpt-5-mini` and verifies Visual Studio
credit billing before any website infrastructure.
