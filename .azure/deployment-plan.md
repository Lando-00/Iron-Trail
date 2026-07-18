# IronTrail Azure Deployment Plan

> **Status:** Validated

Generated: 2026-07-11  
Last verified: 2026-07-18

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
| Full test suite | 53 tests passing on the x64 Python 3.12 environment |
| Ruff | Clean |
| Untracked | Only the intentionally untouched `scripts/spike_copilot_sdk.py` and `scripts/test_pdf_output.pdf` |
| Streamlit runtime | Offline |
| Azure resource group | `rg-IronTrail` exists in Sweden Central |
| Foundry account | `irontrail-resource`, AIServices S0, provisioning succeeded |
| Foundry project | `irontrail` under `irontrail-resource` |
| Foundry network | Keep public endpoint for beta; Entra/RBAC only, no committed API keys |
| Model deployments | `gpt-5-mini` DataZoneStandard at 10K TPM; retained idle |
| Hosting branch | `feature/azure-hosting` |
| Stage A implementation | Complete and locally validated |
| Remote branch | Pushed at `462fb1e` without merging |

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

- Any further Foundry inference after the stopped Stage B proof.
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
| Current execution scope | Stage C validation planning; no website deployment approved yet |

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
- Stage C enables Microsoft login for the owner only. Google OAuth and live
  cross-user testing are deferred to a later gate; no testers are invited in
  Stage C.

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
- Blob lifecycle rules remove active raw/normalized data after 30/60 days.
  Seven-day blob/container soft delete remains enabled for privileged recovery,
  so the effective maximum recoverable periods are 37/67 days. Expired table
  metadata is removed opportunistically and during administrative cleanup.
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
  model, run the approved ten-call synthetic proof, and confirm the cost
  appears against this subscription.
- Visual Studio credits are for development/testing and do not provide a
  production SLA. They are appropriate for this five-user private beta, not a
  later public production service.

### Stage B verified baseline and result (2026-07-15)

| Check | Current state |
|---|---|
| Subscription | Visual Studio Enterprise Subscription, enabled |
| CLI spending-limit field | Not exposed (`null`); Azure billing portal check required |
| Foundry account/project | `irontrail-resource` / `irontrail`, Sweden Central, succeeded |
| Existing model deployments | One: `gpt-5-mini`, exact approved configuration, provisioning succeeded |
| Model | `gpt-5-mini`, version `2025-08-07`, OpenAI, Generally Available |
| Supported SKU | `DataZoneStandard` confirmed live |
| Subscription quota | 300K TPM allocated, 10K used by the retained deployment |
| Platform capacity | 300K TPM available in Sweden Central |
| Proof allocation | 10K TPM, leaving 290K TPM unallocated |
| RAI policy | `Microsoft.DefaultV2` exists |
| Invoking identity | Inherited `Foundry User` plus subscription `Owner` |
| Portal credit evidence | EUR 129.75 remaining immediately before deployment |
| Live token prices | EUR 0.2413/M input; EUR 1.9307/M output |
| Buffered ten-call ceiling | EUR 0.01274172 |
| `rg-IronTrail` month-to-date cost | EUR 0.000585690382 attributed to the exact Foundry account |
| Subscription month-to-date cost | About EUR 0.1027, entirely Cloud Shell Storage |

---

## 8. Stage B Foundry Credit-Proof Plan

### Scope

Stage B may mutate exactly one existing Azure resource surface:

- Create one deployment named `gpt-5-mini` under the existing
  `irontrail-resource` account.
- Run ten synthetic-only inference calls.

It must not provision Container Apps, ACR, Storage, Key Vault, monitoring,
identity, DNS, networking, or any other website resource. It must not merge a
branch or use real workout/health data.

### Confirmed deployment configuration

| Setting | Value |
|---|---|
| Account/project | `irontrail-resource` / `irontrail` |
| Region | Sweden Central |
| Deployment name | `gpt-5-mini` |
| Model/version | `gpt-5-mini` / `2025-08-07` |
| Format | OpenAI |
| SKU | DataZoneStandard |
| Capacity | 10 (10K TPM) |
| Content filter | `Microsoft.DefaultV2` |
| Version upgrade | `OnceCurrentVersionExpired` |
| Dynamic quota | Not applicable to DataZoneStandard |
| Spillover | Disabled |

The deployment is created with one explicit ARM `PUT` using API
`2024-10-01`, including the SKU, model version, RAI policy, and version-upgrade
option in the same idempotent request.

### Preflight gate

Before the deployment:

1. Use Browser Companion to inspect Azure Cost Management/Billing.
2. Match both subscription name and subscription ID to the deployment target.
3. Proceed only if the portal shows either:
   - an explicit **spending limit enabled/on** indicator for that subscription,
     or
   - an explicit remaining monthly credit amount greater than the EUR 0.05
     proof ceiling.
4. Record the exact qualifying indicator and remaining credit if visible.
5. Capture the current authoritative Azure input/output token rates for
   `gpt-5-mini` DataZoneStandard.
6. Calculate the ten-call worst case:
   `0.02 × input-price-per-million + 0.003 × output-price-per-million`,
   converted to EUR with a 20% safety buffer when Azure displays another
   currency. Stop unless the result is at most EUR 0.05.
7. Re-query model, quota, capacity, RAI policy, existing deployments, and
   `rg-IronTrail` cost immediately before mutation.
8. Stop if the target, SKU, model version, quota, pricing, or billing guardrail differs
   from this plan.

The billing inspection is read-only. Stage B must not remove or change the
spending limit, payment method, subscription offer, or billing settings.
If the qualifying billing indicator is not visible before deployment, stop
without creating the model deployment.

### Deployment and validation

1. Persist a deployment intent in the proof ledger before submitting the PUT.
2. Assert that deployment name `gpt-5-mini` still does not exist. Never
   overwrite or silently adopt an unexpected deployment.
3. Submit the exact deployment payload once.
4. Poll until `Succeeded` or the initial five-minute timeout.
5. On timeout or ambiguous response, do not repeat the PUT. Read the deployment
   back and continue bounded read-only state polling for up to 15 minutes.
   If state remains ambiguous, stop for manual review.
6. Read the deployed resource back and verify every configured field.
7. Verify quota usage moved from 0 to 10 units for
   `OpenAI.DataZoneStandard.gpt-5-mini`.
8. Allow bounded read-only quota convergence polling; do not run inference
   until the exact 10-unit delta is visible.
9. Confirm no other deployment or Azure resource appeared.

If creation fails, capture the Azure error and stop. Do not retry with another
region, SKU, model version, capacity, or content policy without a new plan.

### Synthetic proof protocol

- Add a small reusable proof script on `feature/azure-hosting`.
- Authenticate with `AzureCliCredential`, binding proof traffic to the exact
  CLI tenant/user context captured in preflight; never read or copy the portal
  API key.
- Use the existing `AzureFoundryProvider`.
- Create a persistent proof ledger outside the repository before call 1. It
  contains a random `proof_run_id`, deployment configuration, pricing snapshot,
  each call index/status, request ID when returned, token usage, timestamps,
  and cost estimate. It never stores prompt or response prose.
- On resume, continue from the ledger. A call with a returned request ID or an
  uncertain timeout counts as consumed and is never replayed merely to reach
  ten calls.
- Send ten sequential synthetic prompts containing no Hevy, health, identity,
  Vault, or user data.
- Give each prompt a unique synthetic nonce so the calls are independently
  metered.
- Bound each request to at most 2,000 input tokens and 300 output tokens;
  prompts should normally be much smaller.
- Use short factual formatting tasks rather than fitness or medical advice.
- Respect 429 retry guidance and stop after the first non-transient failure.
- Record deployment, request count, prompt/completion tokens, timestamps,
  response IDs where available, and estimated cost. Do not persist response
  prose.
- Hard proof-call ceiling: EUR 0.05. Stop before a request that could exceed it.

### Billing verification

Success requires both:

1. The preflight billing portal confirms the Visual Studio credit/spending
   guardrail.
2. A Microsoft Foundry/Azure OpenAI cost record attributable to
   `rg-IronTrail` appears in Cost Management within 24 hours.

Cost ingestion can be delayed. After the calls:

- Query immediately, then at bounded read-only checkpoints up to 24 hours.
- Filter Cost Management to `rg-IronTrail` (and the AIServices resource where
  supported), group by service/resource, and record the exact query filter.
  Do not treat unrelated subscription-level Cloud Shell Storage cost as proof.
- Compare against the zero-cost `rg-IronTrail` baseline and the captured token totals.
- Stop the checks as soon as the Foundry charge appears.
- Do not generate extra calls merely to make the cost more visible.
- If asynchronous execution is needed, create a read-only four-hour check
  schedule with the 24-hour deadline embedded in its prompt; stop that schedule
  immediately on success or deadline.

### Outcomes

**Success**

- Keep the `gpt-5-mini` deployment for Stage C.
- Stop all proof calls.
- Record the proof in this plan and the Vault project note.
- Unblock Stage C planning, but do not deploy the website automatically.

**Credits or spending guardrail cannot be confirmed**

- If this occurs before deployment, create nothing and stop.
- If it occurs after deployment/calls, keep the model deployment present but
  disabled by policy: make no further calls.
- Keep Stage C blocked.
- Record the unresolved billing evidence and stop.

**Unexpected direct charge, wrong subscription, or guardrail regression**

- Make no further calls.
- Keep Stage C blocked.
- Do not alter billing settings or proceed to website deployment.

### Stage B execution result (2026-07-15)

- Browser Companion showed EUR 129.75 remaining on the exact Visual Studio
  Enterprise subscription immediately before deployment.
- The runner fetched the exact Sweden Central EUR retail meters, authenticated
  Cost Management zero-row baseline, exact identity, model, version, SKU,
  capacity, RAI policy, empty deployment list, and 300K TPM capacity.
- One create-only ARM `PUT` deployed `gpt-5-mini` `2025-08-07` as
  DataZoneStandard capacity 10 with `Microsoft.DefaultV2` and
  `OnceCurrentVersionExpired`. Full readback succeeded.
- Quota converged from 0 to exactly 10 units before inference.
- Call 1 was accepted and returned Azure request/completion IDs, but no
  assistant text. The private ledger consumed the index as `uncertain` and
  stopped. Calls 2-10 were not sent and must not be replayed under this proof.
- Azure Monitor independently confirmed exactly one HTTP 200 request at
  04:51Z with 58 input tokens and 300 output tokens. The output ceiling was
  fully consumed, explaining the empty assistant text. Meter-rate cost is
  approximately EUR 0.00059321 before the 20% safety buffer.
- Cost Management later attributed EUR 0.000585690382 to the exact
  `irontrail-resource` account. Usage Details independently reported 0.000058M
  input tokens and 0.0003M output tokens, matching Azure Monitor's 58/300
  evidence and the live EUR meter calculation.
- The Visual Studio credit billing path is therefore confirmed. The original
  project question did not require ten successful calls; that was an extra
  confidence protocol, not an Azure or product requirement.
- One metered HTTP 200 request plus exact token metrics and exact-account Cost
  Management attribution is sufficient proof for Stage B.
- The deployment remains present and idle. Stage C validation is now eligible,
  but website provisioning still requires separate explicit approval.
- The provider now requests minimal reasoning and classifies a future
  accepted empty completion as terminal while preserving usage metadata.
  Any rerun requires a new plan and explicit approval.

---

## 9. Stage C Owner-Only Website Plan

### Approved decisions

| Area | Stage C decision |
|---|---|
| Scope | Validate, deploy, and test |
| AZD environment | `beta` |
| Azure target | Visual Studio Enterprise Subscription; existing `rg-IronTrail` |
| Regions | North Europe app/data; existing Sweden Central Foundry |
| Authentication | Dedicated single-tenant Entra web app; Microsoft owner only |
| Owner identity | One explicitly configured Entra object ID (kept outside Git) |
| Google | Deferred beyond Stage C; no tester invitations |
| User ceiling | `IRONTRAIL_MAX_USERS=1` |
| Foundry smoke | One synthetic logical call, exactly one HTTP attempt |
| Failure policy | Retain resources, disable public ingress, invite nobody |
| Deletion policy | Seven-day privileged Blob recovery; 37/67-day maximum |
| Entra secret | 90-day lifetime with rotation record |
| Budget | EUR 25 alert threshold; not a hard spending stop |

No custom domain, private networking, zone redundancy, Google OAuth, Samsung
Health, Health Connect, Analytics Lab, merge to `main`, or real
workout/health data is in Stage C.

### Preparation fixes

1. Verify account-relative Blob lifecycle prefixes remain
   `datasets/raw/` and `datasets/normalized/`, matching the `datasets`
   container plus application blob names.
2. Point Container Apps probes to `/_stcore/health`.
3. Configure hosted Foundry with environment-backed minimal reasoning, an
   explicit 1,200-token output ceiling, and zero SDK retries.
4. Bind first-admin bootstrap to provider `aad` and the approved owner object
   ID.
5. Set max users to one and retain AAD-only login.
6. Purge sensitive Streamlit state when authentication disappears or identity
   changes.
7. Document seven-day privileged Blob recovery and effective 37/67-day
   maximum retention.
8. Add static/runtime tests plus a machine-readable deployment what-if
   allowlist.

### Fail-closed identity rollout

1. Create or verify a dedicated `IronTrail Beta` single-tenant Entra web app
   by stable ID, with no Graph permissions, owner assignment, assignment
   required, and a 90-day secret captured without stdout.
2. Generate a private bootstrap code; store only its hash in AZD/Key Vault.
3. Create/select AZD `beta` with confirmed Azure/Foundry values and
   `authReady=false`.
4. Initial provisioning uses `Return401`, preventing access to the placeholder
   and real image before callback registration.
5. After `WEB_URL` exists, register
   `${WEB_URL}/.auth/login/aad/callback`, enable ID-token issuance, verify exact
   app/service-principal IDs, and then apply `authReady=true`.
6. `AllowAnonymous` exposes only the application login landing page;
   `require_invited_user()` remains the data boundary.

### Validation and deployment

1. Complete preparation fixes and set this plan to `Ready for Validation`.
2. Invoke `azure-validate`: full Ruff/pytest, production image/health/isolation,
   AZD schema/package/preview, Bicep, policy/quota, static RBAC, leak scan,
   baseline capture, and machine-enforced what-if.
3. Reject Delete, Replace, unexpected existing-resource modification,
   unapproved role assignments, extra resource types, or any Foundry
   account/project mutation.
4. Set `Validated` only when every proof row passes.
5. Invoke `azure-deploy`; never run deployment commands outside that skill.
6. Record resources, image digest, revision, URL, RBAC, probes, budget, quota,
   and cost baseline.

### Owner checkpoint and acceptance

Execution pauses at `WAITING_FOR_OWNER_BOOTSTRAP`. Resume only after the user
signs in and a UAMI-backed read proves one AAD admin with the approved principal
ID, `bootstrapClaimed=true`, and zero invitations.

Use only bundled/synthetic data to verify:

- anonymous/login/logout/relogin, all pages, downloads, websockets, probes, and
  sensitive session-state clearing;
- session-only uploads leave no durable records;
- opt-in Blob/Table partitioning, export, delete-selected, Delete All, and the
  seven-day recovery wording;
- one synthetic Coach call returns text with one HTTP request, atomic usage
  completion, no raw prompt/log data, and healthy cost caps;
- min 0/max 1, single revision, UAMI/RBAC, expected inventory, 0.25-GB/day log
  cap, 30-day logs, and EUR 10/20/25 alerts.

### Failure and completion

- Auth/privacy/isolation/cost/unexpected-resource failure disables external
  ingress; scale-to-zero alone is not containment.
- Remove the Entra redirect if authentication/privacy is unsafe.
- Retain resources for repair; never delete automatically.
- Keep max users one and invite nobody.
- Success is owner-only. Google plus live two-user isolation is Stage C2.
- Update plans, public-safe docs, Vault, SQL, and outputs; commit/push
  `feature/azure-hosting` without merging.

---

## 10. Health Integration Roadmap

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

## 11. Autopilot Execution Contract

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

### Approved Stage B boundary

The user approved:

- The exact deployment configuration in
  [Confirmed deployment configuration](#confirmed-deployment-configuration).
- Ten bounded synthetic proof calls.
- Browser Companion billing inspection.
- Read-only Cost Management checks for up to 24 hours.
- Keeping the deployment after success.
- Keeping it deployed but making no further calls if the billing guardrail
  cannot be confirmed.

No website deployment is approved by this Stage B authority.

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

## 12. Execution Checklist

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
- [x] Push `feature/azure-hosting`; do not merge.

### Stage B: Foundry credit proof

- [x] Confirm remaining Visual Studio benefit.
- [x] Capture authoritative live token prices and prove the ten-call worst case is <= EUR 0.05.
- [x] Revalidate model, DataZoneStandard quota/capacity, RAI policy, and target.
- [x] Add and test the synthetic credit-proof script.
- [x] Validate the exact one-resource deployment payload.
- [x] Deploy `gpt-5-mini` at 10K TPM and verify its full configuration.
- [x] Verify quota changed by exactly 10K TPM.
- [x] Run a bounded synthetic call and record Azure request, token, quota, and
  billing evidence. The planned calls 2-10 were retired as unnecessary.
- [x] Check Cost Management and confirm the exact-account Foundry charge.
- [x] Record Stage B completion and make Stage C eligible for validation.

### Stage C: Full validation and website deployment - later explicit stage

- [x] Verify lifecycle prefixes; fix health probes, owner binding, session cleanup,
  Foundry minimal reasoning/zero retries, and owner-only settings.
- [x] Create the dedicated assigned Entra app and private bootstrap material.
- [x] Configure the private AZD `beta` environment.
- [x] Enforce the deployment preview allowlist.
- [x] Update this status to `Ready for Validation`.
- [x] Invoke `azure-validate` for the complete architecture.
- [x] Verify local and containerized application behavior.
- [ ] Deploy fail-closed with Microsoft owner login; Google remains deferred.
- [ ] Complete and verify the owner bootstrap checkpoint.
- [ ] Keep automated two-identity isolation tests; defer live cross-user testing
  to Stage C2 before testers.
- [ ] Verify opt-in persistence and 30/60-day expiry configuration.
- [ ] Verify AI quotas, global disable behavior, and no Copilot credentials.
- [x] Record validation proof and set status to `Validated`.

- [ ] Invoke `azure-deploy`.
- [ ] Smoke-test the Azure-provided URL.
- [ ] Confirm monitoring and cost alerts.
- [ ] Record deployed endpoints and set status to `Deployed`.

---

## 13. Validation Proof

The `azure-validate` skill must populate this section before the plan can move
to `Validated`.

| Check | Command run | Result | Timestamp |
|---|---|---|---|
| Python lint | `ruff check .` | Pass | 2026-07-12 |
| Python tests | `python -m pytest -q` | 34 passed | 2026-07-12 |
| Container build | `docker build -t irontrail:stage-a .` | Pass | 2026-07-12 |
| Container health | Port 80 `/` and `/_stcore/health` | HTTP 200 | 2026-07-12 |
| Cloud image isolation | Non-root UID 10001; no `copilot` package | Pass | 2026-07-12 |
| Deployment architecture | AZD remote build targeting `amd64` | Schema pass | 2026-07-12 |
| Bicep compilation | `az bicep build --file infra/main.bicep` | Pass | 2026-07-12 |
| Azure template validation | `az deployment sub validate` with dummy auth values | Succeeded; no resources created | 2026-07-12 |
| AZD schema | `azd show --output json --no-prompt` | Pass | 2026-07-12 |
| Independent code review | Two review passes over auth, storage, AI limits, HTML, telemetry, container, and IaC | All findings resolved | 2026-07-12 |
| Privacy boundary | Raw data absent; Samsung code excluded; no introduced personal paths or credentials | Pass | 2026-07-12 |
| Stage B proof runner | `ruff check .`; `python -m pytest -q` | 53 passed | 2026-07-15 |
| Foundry deployment | Exact create-only ARM payload and full readback | Succeeded | 2026-07-15 |
| Foundry quota | `OpenAI.DataZoneStandard.gpt-5-mini` | 0 -> 10 of 300 | 2026-07-15 |
| Synthetic proof | Private resumable ledger | Stopped on accepted empty completion at call 1; no replay | 2026-07-15 |
| Azure Monitor call evidence | `AzureOpenAIRequests`, `InputTokens`, `OutputTokens` | HTTP 200; 1 request; 58 input; 300 output | 2026-07-15 |
| Foundry billing attribution | Authenticated Cost Management query filtered to `rg-IronTrail` | EUR 0.000585690382 on `irontrail-resource` | 2026-07-18 |
| Stage C final tests | `ruff check .`; `python -m pytest -q` | 68 passed | 2026-07-18 |
| Stage C Bicep | `az bicep build --file infra/main.bicep --stdout` | Pass | 2026-07-18 |
| Stage C production image | Docker build; root + `/_stcore/health`; UID/package inspection | HTTP 200; UID 10001; no Copilot SDK | 2026-07-18 |
| Stage C Entra app | Single tenant, assignment required, owner assigned, no Graph permissions | Pass; redirect intentionally absent | 2026-07-18 |
| AZD environment | Private `beta` values and secret-presence checks | Target/location/owner/authReady verified | 2026-07-18 |
| AZD auth/schema | `azd auth login --check-status`; `azd show --output json --no-prompt` | Pass | 2026-07-18 |
| AZD provision preview | `azd provision --preview --no-prompt` | Only approved web resources create; Foundry/RG skipped | 2026-07-18 |
| Subscription what-if | `az deployment sub what-if --no-pretty-print`; Stage C allowlist | Pass, including five exact symbolic UAMI roles | 2026-07-18 |
| Subscription template validation | `az deployment sub validate` | Succeeded | 2026-07-18 |
| AZD package | `azd package --no-prompt` | Pass | 2026-07-18 |
| Policy/provider/quota | Policy assignments, provider registration, North Europe Container Apps quota | Pass; West Europe-only restriction irrelevant; 20 environments available | 2026-07-18 |
| Static RBAC | UAMI role mapping for ACR, Blob, Table, Key Vault, Foundry | Five approved roles, one principal reference | 2026-07-18 |
| Privacy/secret boundary | Tracked-file scan, raw/processed inventory, ignored private AZD environment | No secret matches; only `.gitkeep` data tracked | 2026-07-18 |
| Predeployment baseline | Resources, RBAC, policy, provider, cost, Foundry deployment/quota | Two existing Foundry resources; one model; quota 10/300 | 2026-07-18 |
| First application publish | `azd deploy --no-prompt` | Stopped before publish: AZD requires canonical `linux/amd64`, not `amd64` | 2026-07-18 |
| Publish metadata fix | `linux/amd64`; Ruff/pytest; AZD schema/package/preview | 69 passed; package and preview pass | 2026-07-18 |
| First authenticated owner request | Microsoft login through Easy Auth | Failed closed: Storage firewall denied UAMI Table access | 2026-07-18 |
| Storage firewall correction | Public endpoint enabled; default action Allow; shared keys/public blobs remain disabled | 69 tests, Bicep, subscription validation pass | 2026-07-18 |

---

## 14. Files to Generate

| File/component | Purpose | Status |
|---|---|---|
| `.azure/deployment-plan.md` | Deployment source of truth | Complete |
| `azure.yaml` | AZD service definition | Complete |
| `infra/main.bicep` and modules | Azure resources, roles, lifecycle, budgets; reference existing Foundry resources | Complete |
| `Dockerfile`, `.dockerignore` | Reproducible Streamlit container | Complete |
| `iron_trail/auth.py` | Easy Auth identity normalization and invite guard | Complete |
| `iron_trail/cloud_storage.py` | User-partitioned Blob/Table persistence | Complete |
| `iron_trail/coach/providers/azure_foundry.py` | Hosted AI provider | Complete |
| `scripts/foundry_credit_proof.py` | Private-ledger Stage B deployment, call, quota, and cost proof runner | Complete |
| `iron_trail/usage_limits.py` | Per-user/global AI reservation ledger | Complete |
| Tests | Auth, isolation, retention, uploads, AI limits | Complete |

---

## 15. Git and Release Boundary

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

## 16. Next Step

Invoke `azure-deploy` for the validated owner-only `beta` environment.
Provision and deploy fail-closed with `Return401`, record `WEB_URL`, then
configure the exact Entra callback and apply the narrow `authReady=true`
update. Google and testers remain deferred.
