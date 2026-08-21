targetScope = 'subscription'

@description('AZD environment name used for resource tags and deterministic names.')
param environmentName string

@description('Location for the web application, storage, and monitoring resources.')
param location string = 'northeurope'

@description('Existing IronTrail resource group.')
param resourceGroupName string = 'rg-IronTrail'

@description('Existing Microsoft Foundry account.')
param foundryAccountName string = 'irontrail-resource'

@description('Model deployment name created during the later Foundry credit-proof stage.')
param modelDeploymentName string = 'gpt-5-mini'

@description('Deployment used for weekly and monthly reviews. Defaults to modelDeploymentName.')
param reviewDeploymentName string = ''

@description('Deployment used for the Ask Coach chat. Defaults to modelDeploymentName.')
param chatDeploymentName string = ''

@allowed([
  '0'
  '1'
  '2'
])
@description('Maximum OpenAI SDK retries for transient hosted Coach failures.')
param aiMaxRetries string = '2'

@description('Microsoft identity application client ID used by Container Apps Easy Auth.')
param aadClientId string

@secure()
@description('Microsoft identity application secret stored in Key Vault.')
param aadClientSecret string

@secure()
@description('SHA-256 hash of the first administrator invite code.')
param bootstrapInviteHash string

@secure()
@minLength(16)
@description('Private seed for the anonymous beta landing reveal sequence.')
param betaRevealSeed string

@description('Immutable Entra object ID allowed to redeem the bootstrap administrator invite.')
param ownerObjectId string

@allowed([
  'false'
  'true'
])
@description('''Grant the owner Key Vault Secrets User for break-glass recovery.
Without this the vault's RBAC leaves no human able to read the beta secrets:
subscription Owner does not confer data-plane access, so recovering a lost AZD
environment requires an out-of-band role assignment that drifts from IaC.
Declared as a string to match the other AZD-substituted flags.''')
param grantOwnerKeyVaultAccess string = 'false'

@allowed([
  'false'
  'true'
])
@description('''Temporarily grant the owner Storage Table Data Reader for
read-only beta diagnostics. This deliberately excludes Blob data access and
defaults off so the role exists only during an explicit audit.''')
param grantOwnerStorageDiagnosticAccess string = 'false'

@allowed([
  'false'
  'true'
])
@description('Whether the verified login landing page may accept anonymous requests.')
param authReady string = 'false'

@allowed([
  'false'
  'true'
])
@description('Whether Google is configured as an Easy Auth identity provider.')
param googleAuthEnabled string = 'false'

@allowed([
  'false'
  'true'
])
@description('Whether an existing beta must use the narrow Stage C2 patch path.')
param stageC2PatchMode string = 'false'

@description('Google OAuth web client ID.')
@minLength(1)
param googleClientId string = 'disabled'

@secure()
@description('Google OAuth web client secret.')
param googleClientSecret string = ''

@allowed([
  '1'
  '2'
  '3'
  '4'
  '5'
])
@description('Maximum number of active beta members, including the owner.')
param maxUsers string = '1'

@description('Current deployed Container App image used by the Stage C2 patch.')
param currentContainerImage string = ''

@description('Current deployed Container App URL used by the Stage C2 patch.')
param currentWebUrl string = ''

@description('Monthly Azure budget in EUR for this resource group.')
param monthlyBudgetEur int = 25

var stageC2PatchEnabled = toLower(stageC2PatchMode) == 'true' || toLower(googleAuthEnabled) == 'true'

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' existing = {
  name: resourceGroupName
}

module application './modules/application.bicep' = if (!stageC2PatchEnabled) {
  name: 'irontrail-application-${environmentName}'
  scope: resourceGroup
  params: {
    aadClientId: aadClientId
    aadClientSecret: aadClientSecret
    authReady: authReady
    betaRevealSeed: betaRevealSeed
    bootstrapInviteHash: bootstrapInviteHash
    environmentName: environmentName
    foundryAccountName: foundryAccountName
    googleAuthEnabled: googleAuthEnabled
    googleClientId: googleClientId
    googleClientSecret: googleClientSecret
    location: location
    maxUsers: maxUsers
    modelDeploymentName: modelDeploymentName
    reviewDeploymentName: empty(reviewDeploymentName) ? modelDeploymentName : reviewDeploymentName
    chatDeploymentName: empty(chatDeploymentName) ? modelDeploymentName : chatDeploymentName
    aiMaxRetries: aiMaxRetries
    ownerObjectId: ownerObjectId
    grantOwnerKeyVaultAccess: grantOwnerKeyVaultAccess
    grantOwnerStorageDiagnosticAccess: grantOwnerStorageDiagnosticAccess
    currentContainerImage: currentContainerImage
  }
}

module stageC2Patch './modules/stage_c2_patch.bicep' = if (stageC2PatchEnabled) {
  name: 'irontrail-stage-c2-patch-${environmentName}'
  scope: resourceGroup
  params: {
    aadClientId: aadClientId
    authReady: authReady
    betaRevealSeed: betaRevealSeed
    environmentName: environmentName
    foundryAccountName: foundryAccountName
    googleAuthEnabled: googleAuthEnabled
    googleClientId: googleClientId
    googleClientSecret: googleClientSecret
    location: location
    maxUsers: maxUsers
    modelDeploymentName: modelDeploymentName
    reviewDeploymentName: empty(reviewDeploymentName) ? modelDeploymentName : reviewDeploymentName
    chatDeploymentName: empty(chatDeploymentName) ? modelDeploymentName : chatDeploymentName
    aiMaxRetries: aiMaxRetries
    ownerObjectId: ownerObjectId
    grantOwnerKeyVaultAccess: grantOwnerKeyVaultAccess
    grantOwnerStorageDiagnosticAccess: grantOwnerStorageDiagnosticAccess
    currentContainerImage: currentContainerImage
    currentWebUrl: currentWebUrl
  }
}

// Stage C2 preserves the existing budget; budget changes require a separate
// approved infrastructure rollout rather than widening this auth-only patch.
module budget 'br/public:avm/res/consumption/budget/rg-scope:0.1.0' = if (!stageC2PatchEnabled) {
  name: 'irontrail-budget-${environmentName}'
  scope: resourceGroup
  params: {
    amount: monthlyBudgetEur
    contactRoles: [
      'Owner'
    ]
    enableTelemetry: false
    name: 'budget-${environmentName}'
    thresholds: [
      40
      80
      100
    ]
    thresholdType: 'Actual'
  }
}

output AZURE_RESOURCE_GROUP string = resourceGroup.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = stageC2PatchEnabled ? stageC2Patch!.outputs.containerRegistryEndpoint : application!.outputs.containerRegistryEndpoint
output AZURE_CONTAINER_APPS_ENVIRONMENT_NAME string = stageC2PatchEnabled ? stageC2Patch!.outputs.containerAppsEnvironmentName : application!.outputs.containerAppsEnvironmentName
output SERVICE_WEB_NAME string = stageC2PatchEnabled ? stageC2Patch!.outputs.containerAppName : application!.outputs.containerAppName
output SERVICE_WEB_RESOURCE_GROUP_NAME string = resourceGroup.name
output WEB_URL string = stageC2PatchEnabled ? stageC2Patch!.outputs.webUrl : application!.outputs.webUrl
output IRONTRAIL_STORAGE_BLOB_URL string = stageC2PatchEnabled ? stageC2Patch!.outputs.storageBlobUrl : application!.outputs.storageBlobUrl
output IRONTRAIL_STORAGE_TABLE_URL string = stageC2PatchEnabled ? stageC2Patch!.outputs.storageTableUrl : application!.outputs.storageTableUrl
output IRONTRAIL_KEY_VAULT_NAME string = stageC2PatchEnabled ? stageC2Patch!.outputs.keyVaultName : application!.outputs.keyVaultName
output IRONTRAIL_MANAGED_IDENTITY_CLIENT_ID string = stageC2PatchEnabled ? stageC2Patch!.outputs.managedIdentityClientId : application!.outputs.managedIdentityClientId
