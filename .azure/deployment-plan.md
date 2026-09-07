# Azure Deployment Plan

> **Status:** Validated

Generated: 2026-09-05

## 1. Project Overview

**Goal:** Migrate the Fabric Governance Hub to a VNet-integrated Azure Container Apps environment with private access to ACR, Key Vault, Log Analytics, and Application Insights while retaining public, Entra-protected application ingress.

**Path:** Modernize Existing

## 2. Requirements

| Attribute | Value |
|-----------|-------|
| Classification | Development |
| Scale | Small, one replica |
| Budget | Balanced |
| Subscription | `2824f36d-5777-4e2e-bccd-f5234733dd8b` |
| Location | `southcentralus` |
| Resource group | `rg-fb-governance-app` |

## 3. Components Detected

| Component | Type | Technology | Path |
|-----------|------|------------|------|
| Fabric Governance Hub | Web application | Python 3.12, Flask, Gunicorn | `app.py` |
| Container image | Container | Docker | `infra/Dockerfile` |
| Infrastructure | IaC | Bicep | `infra/` |

## 4. Recipe Selection

**Selected:** Bicep with Azure CLI

**Rationale:** The existing deployment uses a subscription-scope Bicep template and Azure CLI. No AZD project is present.

## 5. Architecture

**Stack:** Azure Container Apps Consumption

| Component | Azure Service | SKU |
|-----------|---------------|-----|
| Web application | Azure Container Apps | Consumption, 1 vCPU, 2 GiB, one replica |
| Image registry | Azure Container Registry | Premium |
| Secrets | Azure Key Vault | Standard |
| Logs | Log Analytics | PerGB2018 |
| APM | Application Insights | Workspace-based |
| Network | Virtual Network | `10.40.0.0/16` |
| Private connectivity | Azure Private Link | Three private endpoints |
| Monitor isolation | Azure Monitor Private Link Scope | PrivateOnly |
| Token rotation | Azure Container Apps Job | Scheduled daily; dedicated managed identity |

The new Container Apps environment and app are created in parallel. Public ingress remains enabled and protected by Easy Auth. Phase 1 creates private connectivity while ACR and Azure Monitor public access remain enabled to preserve the current app. Phase 2 disables their public access only after the new app passes health, DNS, image-pull, telemetry, and authentication checks. Retirement of the old app and environment is outside this deployment.

The Easy Auth token-store SAS is rotated by a scheduled Container Apps Job in the VNet-integrated environment. A dedicated user-assigned identity receives Blob delegation and data permissions on the token-store account plus Container App update permission scoped to the VNet-integrated app. The job runs daily, creates a six-day Entra user-delegation SAS, updates the existing Easy Auth secret, and restarts the active revision. Shared Key authorization remains disabled.

## 6. Provisioning Limit Checklist

| Resource Type | Number to Deploy | Total After Deployment | Limit/Quota | Notes |
|---------------|------------------|------------------------|-------------|-------|
| Microsoft.App/managedEnvironments | 1 | 2 | 50 | Azure quota CLI: Managed Environment Count; current count 1 |
| Microsoft.App/containerApps | 1 | 2 | Not exposed by quota API | Current count 1; what-if accepted the additional app |
| Microsoft.Network/virtualNetworks | 1 | 1 | 1,000 per region | Current count 0; standard documented limit |
| Microsoft.Network/privateEndpoints | 3 | 3 | 1,000 per VNet | Current count 0; standard documented limit |
| Microsoft.Network/privateDnsZones | 7 | 7 | 1,000 per subscription | Current count 0; standard documented limit |
| Microsoft.Insights/privateLinkScopes | 1 | 1 | 10 per region | Current count 0; standard documented limit |
| Microsoft.App/jobs | 1 | 1 | Not exposed by quota API | Scheduled rotation job in the existing environment |
| Microsoft.ManagedIdentity/userAssignedIdentities | 1 | 2 | 1,000 per subscription | Dedicated rotation identity |

**Status:** All requested resources are within limits. South Central US quota discovery and Azure what-if succeeded.

## 7. Execution Checklist

### Phase 1: Planning
- [x] Analyze workspace
- [x] Gather requirements
- [x] Confirm subscription and location with user
- [x] Scan codebase
- [x] Select Bicep recipe
- [x] Plan architecture
- [x] User approved this plan

### Phase 2: Preparation
- [x] Generate private-network infrastructure
- [x] Build Bicep template
- [x] Run Azure what-if
- [x] Verify quotas and live prerequisites
- [x] Update status to Ready for Validation

### Phase 3: Validation
- [x] Run recipe validation workflow
- [x] Core validation: Azure CLI, authentication, Bicep build, ARM validation, and what-if
- [x] Azure Policy validation
- [x] Build verification
- [x] Static RBAC verification
- [x] Record validation proof
- [x] Update status to Validated

### Phase 4: Deployment
- [x] Deploy phase 1
- [x] Verify private connectivity and public endpoint
- [x] Add and verify Entra redirect URI for the parallel app
- [x] Configure and validate the private Easy Auth Blob token store
- [x] Validate delegated login and group authorization
- [ ] Deploy phase 2 public-access lockdown after explicit approval
- [x] Report deployed endpoint

### Phase 5: Token Rotation Automation
- [x] Select scheduled Container Apps Job architecture
- [x] Record user approval
- [x] Generate least-privilege identity, RBAC, and job infrastructure
- [x] Validate Bicep, ARM, policy, and what-if with zero deletes
- [x] Deploy the rotation automation
- [x] Trigger one execution and verify secret rotation and revision health

## 8. Validation Proof

| Check | Command Run | Result | Timestamp |
|-------|-------------|--------|-----------|
| Azure CLI and authentication | Official `validate-deployment.ps1` helper | Pass; subscription `ME-MngEnvMCAP826595-misantibanez-1` | 2026-09-05 |
| Bicep build | Official `validate-deployment.ps1` helper | Pass; only known non-blocking BCP081 type warnings | 2026-09-05 |
| ARM validation | `az deployment sub validate` through the official helper | Pass | 2026-09-05 |
| What-if | `az deployment sub what-if` through the official helper | Pass | 2026-09-05 |
| Resource-level what-if | `az deployment sub what-if --result-format ResourceIdOnly` | Pass; Create 27, Deploy 10, Ignore 3, Unsupported 2, Delete 0 | 2026-09-05 |
| Azure Policy | Azure Policy assignment list plus ARM validation | Pass; 8 effective assignments, no policy denial | 2026-09-05 |
| Static RBAC | Review of `infra/modules/role-assignments.bicep` | Pass; AcrPull, Key Vault Secrets User, and Key Vault Secrets Officer are resource-scoped | 2026-09-05 |
| Secret handling | Protected temporary parameters file | Pass; current secrets reused without output, placeholders, or persisted files | 2026-09-05 |
| Phase 1 deployment | `az deployment sub create --name fabric-gov-vnet-phase1-20260905-r2` | Pass; provisioning state Succeeded | 2026-09-05 |
| Container App health | Revision `ca-fabric-gov-dev-3d9c-vnet--mj4afgi` | Pass; Healthy, active, one replica, immutable image matched | 2026-09-05 |
| Private Link | ARM REST and in-replica DNS resolution | Pass; ACR, Key Vault, and AMPLS endpoints Succeeded/Approved and dependencies resolve to `10.40.2.x` | 2026-09-05 |
| Entra callback | App registration `fabric-governance-hub-web` | Pass; old and new HTTPS callbacks registered | 2026-09-05 |
| Easy Auth token store deployment | Deployment `fabric-gov-easyauth-tokenstore-20260905` | Pass; provisioning state Succeeded | 2026-09-06 |
| Token store private connectivity | In-replica DNS, managed identity, RBAC, and Blob probes | Pass; Storage resolves to `10.40.2.20`, private endpoint is Approved, and Blob access returns HTTP 200 | 2026-09-06 |
| Token store persistence | Sanitized `http-auth` logs and Blob metadata | Pass; Easy Auth Blob PUT returned HTTP 201 and persisted a non-empty session blob | 2026-09-06 |
| Entra group authorization | Delegated Graph grants and app manifest | Pass; `GroupMember.Read.All` has `AllPrincipals` admin consent and `groupMembershipClaims` is `SecurityGroup` | 2026-09-06 |
| Interactive login | New InPrivate browser session | Pass; callback completed and the application loaded for an authorized user | 2026-09-06 |
| Rotation Bicep build | `az bicep build --file infra/main.bicep` | Pass; zero diagnostics | 2026-09-06T15:41:10Z |
| Rotation ARM validation | `az deployment sub validate` with transient live secure parameters | Pass; provisioning state `Succeeded`, no policy denial | 2026-09-06T15:41:10Z |
| Rotation resource what-if | `az deployment sub what-if --result-format ResourceIdOnly` with `lockDownPrivateServices=false` | Pass; Create 5, Deploy 42, Unsupported 3, Ignore 8, Delete 0 | 2026-09-06T15:41:10Z |
| Rotation static RBAC | Review of `infra/modules/token-rotation-job.bicep` | Pass; Blob Delegator at account, Blob Data Contributor at container, Container Apps Contributor at target app | 2026-09-06T15:41:10Z |
| Rotation secret handling | Random temporary parameters file with cleanup in `finally` | Pass; live secrets used transiently and not printed or persisted | 2026-09-06T15:41:10Z |
| Rotation deployment | `az deployment sub create --name fabric-gov-token-rotation-20260906-r4` plus focused module deployment | Pass; scheduled Job and dedicated identity provisioned | 2026-09-06T16:17:36Z |
| Rotation live RBAC | Live role-assignment queries | Pass; Blob Delegator, Blob Data Contributor, Container Apps Contributor, Container Apps Operator, and Managed Identity Operator are resource-scoped | 2026-09-06T16:17:51Z |
| Rotation execution | ARM Job execution `job-fgov-sas-rotate-dev-3d9c-qt0fl8s` | Pass; `Succeeded`, no error logs, SAS expiry changed to `2026-09-12T16:18Z` | 2026-09-06T16:19:17Z |
| Post-rotation health | ARM revision query | Pass; revision `ca-fabric-gov-dev-3d9c-vnet--mj4afgi` is Healthy and RunningAtMaxScale | 2026-09-06T16:19:17Z |

**Validated by:** azure-validate workflow

**Notes:** The rotation what-if reported three `Unsupported` entries for existing dynamic role-assignment analyses; they are not validation failures. No resource deletion occurred. The first runtime probe exposed Windows CRLF characters in the embedded Bash script; `replace(rotationScript, '\r', '')` now normalizes it before execution. Live linked-resource checks also required Container Apps Operator on the managed environment and Managed Identity Operator on the app identity. The active Easy Auth secret uses an Entra user-delegation SAS because Shared Key authorization remains disabled. Job `job-fgov-sas-rotate-dev-3d9c` now rotates it daily at 02:15 UTC with a six-day lifetime.

## 9. Files

| File | Purpose | Status |
|------|---------|--------|
| `.azure/deployment-plan.md` | Deployment source of truth | Complete |
| `infra/main.bicep` | Subscription-scope orchestration | Complete |
| `infra/modules/virtual-network.bicep` | Dedicated VNet and subnets | Complete |
| `infra/modules/private-link.bicep` | Private endpoints, DNS, and AMPLS | Complete |
| `infra/Dockerfile` | Application container | Complete |

## 10. Next Steps

1. Obtain explicit approval for phase 2.
2. Redeploy with `lockDownPrivateServices=true` and verify the current app is no longer required.
### Official Azure Validate workflow
- [x] Run `az bicep build` for the complete subscription-scope template with `lockDownPrivateServices=false`.
- [x] Run ARM subscription deployment validation with current secure parameters supplied transiently.
- [x] Run subscription what-if with `lockDownPrivateServices=false`; explicitly record create/modify/delete counts and policy/RBAC findings.
- [x] Run resource-level what-if and confirm zero deletes.
- [x] Review role assignments for the scheduled token-rotation job identity and app update scope.
