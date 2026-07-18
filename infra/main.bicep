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

@description('Microsoft identity application client ID used by Container Apps Easy Auth.')
param aadClientId string

@secure()
@description('Microsoft identity application secret stored in Key Vault.')
param aadClientSecret string

@secure()
@description('SHA-256 hash of the first administrator invite code.')
param bootstrapInviteHash string

@description('Immutable Entra object ID allowed to redeem the bootstrap administrator invite.')
param ownerObjectId string

@allowed([
  'false'
  'true'
])
@description('Whether the verified login landing page may accept anonymous requests.')
param authReady string = 'false'

@description('Monthly Azure budget in EUR for this resource group.')
param monthlyBudgetEur int = 25

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' existing = {
  name: resourceGroupName
}

module application './modules/application.bicep' = {
  name: 'irontrail-application-${environmentName}'
  scope: resourceGroup
  params: {
    aadClientId: aadClientId
    aadClientSecret: aadClientSecret
    authReady: authReady
    bootstrapInviteHash: bootstrapInviteHash
    environmentName: environmentName
    foundryAccountName: foundryAccountName
    location: location
    modelDeploymentName: modelDeploymentName
    ownerObjectId: ownerObjectId
  }
}

module budget 'br/public:avm/res/consumption/budget/rg-scope:0.1.0' = {
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
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = application.outputs.containerRegistryEndpoint
output AZURE_CONTAINER_APPS_ENVIRONMENT_NAME string = application.outputs.containerAppsEnvironmentName
output SERVICE_WEB_NAME string = application.outputs.containerAppName
output SERVICE_WEB_RESOURCE_GROUP_NAME string = resourceGroup.name
output WEB_URL string = application.outputs.webUrl
output IRONTRAIL_STORAGE_BLOB_URL string = application.outputs.storageBlobUrl
output IRONTRAIL_STORAGE_TABLE_URL string = application.outputs.storageTableUrl
output IRONTRAIL_KEY_VAULT_NAME string = application.outputs.keyVaultName
output IRONTRAIL_MANAGED_IDENTITY_CLIENT_ID string = application.outputs.managedIdentityClientId
