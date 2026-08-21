targetScope = 'resourceGroup'

@description('AZD environment name used for deterministic existing-resource names.')
param environmentName string

@description('Location of the existing IronTrail application.')
param location string

@description('Existing Microsoft Foundry account.')
param foundryAccountName string

@description('Azure OpenAI deployment name.')
param modelDeploymentName string

@description('Deployment used for weekly and monthly reviews.')
param reviewDeploymentName string = ''

@description('Deployment used for the Ask Coach chat.')
param chatDeploymentName string = ''

@allowed([
  '0'
  '1'
  '2'
])
@description('Maximum OpenAI SDK retries for transient hosted Coach failures.')
param aiMaxRetries string = '2'

@description('Microsoft identity application client ID.')
param aadClientId string

@allowed([
  'false'
  'true'
])
@description('Whether the private landing page may remain anonymously reachable.')
param authReady string

@secure()
@minLength(16)
@description('Private seed for the anonymous beta landing reveal sequence.')
param betaRevealSeed string

@allowed([
  'false'
  'true'
])
@description('Whether Google is configured as an Easy Auth identity provider.')
param googleAuthEnabled string

@description('Google OAuth web client ID.')
@minLength(1)
param googleClientId string

@secure()
@description('Google OAuth web client secret.')
param googleClientSecret string

@allowed([
  '1'
  '2'
  '3'
  '4'
  '5'
])
@description('Maximum active beta members, including the owner.')
param maxUsers string

@description('Immutable Entra object ID allowed to administer the beta.')
param ownerObjectId string

@allowed([
  'false'
  'true'
])
@description('Grant the owner Key Vault Secrets User for break-glass recovery.')
param grantOwnerKeyVaultAccess string = 'false'

@allowed([
  'false'
  'true'
])
@description('Temporarily grant the owner Storage Table Data Reader for diagnostics.')
param grantOwnerStorageDiagnosticAccess string = 'false'

@minLength(1)
@description('Current deployed Container App image, supplied by AZD metadata.')
param currentContainerImage string

@minLength(1)
@description('Current deployed Container App URL, supplied by AZD metadata.')
param currentWebUrl string

var resourceSuffix = take(uniqueString(subscription().id, resourceGroup().id, environmentName), 6)
var tags = {
  'azd-env-name': environmentName
  application: 'irontrail'
  environment: environmentName
}
var serviceTags = union(tags, {
  'azd-service-name': 'web'
})
var identityName = 'id-irontrail-${resourceSuffix}'
var containerRegistryName = replace('crirontrail${resourceSuffix}', '-', '')
var storageAccountName = replace('stirontrail${resourceSuffix}', '-', '')
var keyVaultName = 'kv-irontrail-${resourceSuffix}'
var containerAppsEnvironmentName = 'cae-irontrail-${resourceSuffix}'
var containerAppName = 'ca-irontrail-${resourceSuffix}'
var storageBlobEndpoint = 'https://${storageAccountName}.blob.${environment().suffixes.storage}/'
var storageTableEndpoint = 'https://${storageAccountName}.table.${environment().suffixes.storage}'
var foundryEndpoint = 'https://${foundryAccountName}.cognitiveservices.azure.com/'
var unauthenticatedClientAction = toLower(authReady) == 'true' ? 'AllowAnonymous' : 'Return401'
var googleAuthConfigured = toLower(googleAuthEnabled) == 'true'
var authProviders = googleAuthConfigured ? 'aad,google' : 'aad'
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var storageTableDataReaderRoleId = '76199698-9eea-4c19-bc75-cec21354c6b6'
var revisionSuffix = 'c2-${take(uniqueString(containerAppName, googleAuthEnabled, googleClientId, maxUsers, aiMaxRetries), 8)}'
var googleIdentityProvider = googleAuthConfigured ? {
  google: {
    enabled: true
    login: {
      scopes: [
        'openid'
        'email'
        'profile'
      ]
    }
    registration: {
      clientId: googleClientId
      clientSecretSettingName: 'google-client-secret'
    }
    validation: {
      allowedAudiences: [
        googleClientId
      ]
    }
  }
} : {}

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: identityName
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: containerAppsEnvironmentName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

var keyVaultUri = keyVault.properties.vaultUri

// Break-glass: the vault uses RBAC, so subscription Owner alone cannot read
// these secrets. The patch module treats the vault as existing, so the grant
// is declared here rather than through the vault module's roleAssignments.
// Deterministic name means repeat deployments are idempotent.
resource ownerKeyVaultAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' =
  if (toLower(grantOwnerKeyVaultAccess) == 'true') {
    scope: keyVault
    name: guid(keyVault.id, ownerObjectId, keyVaultSecretsUserRoleId)
    properties: {
      principalId: ownerObjectId
      principalType: 'User'
      roleDefinitionId: subscriptionResourceId(
        'Microsoft.Authorization/roleDefinitions',
        keyVaultSecretsUserRoleId
      )
    }
  }

// Table metadata is sufficient for membership, retention, and usage audits.
// Blob Reader is intentionally excluded so the operator cannot download
// workout files through this diagnostic grant.
resource ownerStorageDiagnosticAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' =
  if (toLower(grantOwnerStorageDiagnosticAccess) == 'true') {
    scope: storageAccount
    name: guid(storageAccount.id, ownerObjectId, storageTableDataReaderRoleId)
    properties: {
      principalId: ownerObjectId
      principalType: 'User'
      roleDefinitionId: subscriptionResourceId(
        'Microsoft.Authorization/roleDefinitions',
        storageTableDataReaderRoleId
      )
    }
  }

resource betaRevealSeedSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'beta-reveal-seed'
  properties: {
    attributes: {
      enabled: true
    }
    contentType: 'Private beta landing reveal seed'
    value: betaRevealSeed
  }
}

resource googleClientSecretResource 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (googleAuthConfigured) {
  parent: keyVault
  name: 'google-client-secret'
  properties: {
    attributes: {
      enabled: true
    }
    contentType: 'Google OAuth web client secret'
    value: googleClientSecret
  }
}

// This resource deliberately mirrors the live owner-beta configuration so the
// Google rollout cannot reset traffic, image, probes, registry, or core settings.
resource stageC2ContainerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  tags: serviceTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  dependsOn: googleAuthConfigured ? [
    betaRevealSeedSecret
    googleClientSecretResource!
  ] : [
    betaRevealSeedSecret
  ]
  properties: {
    managedEnvironmentId: containerAppsEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      maxInactiveRevisions: 0
      ingress: {
        allowInsecure: false
        clientCertificateMode: 'Ignore'
        exposedPort: 0
        external: true
        stickySessions: {
          affinity: 'sticky'
        }
        targetPort: 80
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        transport: 'auto'
      }
      registries: [
        {
          identity: managedIdentity.id
          server: '${containerRegistryName}.azurecr.io'
        }
      ]
      secrets: concat([
        {
          identity: managedIdentity.id
          keyVaultUrl: '${keyVaultUri}secrets/aad-client-secret'
          name: 'aad-client-secret'
        }
        {
          identity: managedIdentity.id
          keyVaultUrl: '${keyVaultUri}secrets/bootstrap-invite-hash'
          name: 'bootstrap-invite-hash'
        }
        {
          identity: managedIdentity.id
          keyVaultUrl: '${keyVaultUri}secrets/appinsights-connection-string'
          name: 'appinsights-connection-string'
        }
        {
          identity: managedIdentity.id
          keyVaultUrl: '${keyVaultUri}secrets/beta-reveal-seed'
          name: 'beta-reveal-seed'
        }
      ], googleAuthConfigured ? [
        {
          identity: managedIdentity.id
          keyVaultUrl: '${keyVaultUri}secrets/google-client-secret'
          name: 'google-client-secret'
        }
      ] : [])
    }
    template: {
      revisionSuffix: revisionSuffix
      containers: [
        {
          env: [
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              secretRef: 'appinsights-connection-string'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: managedIdentity.properties.clientId
            }
            {
              name: 'IRONTRAIL_AUTH_PROVIDERS'
              value: authProviders
            }
            {
              name: 'IRONTRAIL_MAX_USERS'
              value: maxUsers
            }
            {
              name: 'IRONTRAIL_AUTH_REVALIDATE_SECONDS'
              value: '5'
            }
            {
              name: 'IRONTRAIL_OWNER_OBJECT_ID'
              value: ownerObjectId
            }
            {
              name: 'IRONTRAIL_AZURE_OPENAI_DEPLOYMENT'
              value: modelDeploymentName
            }
            {
              name: 'IRONTRAIL_AI_REVIEW_DEPLOYMENT'
              value: reviewDeploymentName
            }
            {
              name: 'IRONTRAIL_AI_CHAT_DEPLOYMENT'
              value: chatDeploymentName
            }
            {
              name: 'IRONTRAIL_AZURE_OPENAI_ENDPOINT'
              value: foundryEndpoint
            }
            {
              name: 'IRONTRAIL_AI_MAX_OUTPUT_TOKENS'
              value: '1200'
            }
            {
              name: 'IRONTRAIL_AI_MAX_RETRIES'
              value: aiMaxRetries
            }
            {
              name: 'IRONTRAIL_AI_REASONING_EFFORT'
              value: 'minimal'
            }
            {
              name: 'IRONTRAIL_BLOB_RECOVERY_DAYS'
              value: '7'
            }
            {
              name: 'IRONTRAIL_BOOTSTRAP_INVITE_HASH'
              secretRef: 'bootstrap-invite-hash'
            }
            {
              name: 'IRONTRAIL_DATA_CONTAINER'
              value: 'datasets'
            }
            {
              name: 'IRONTRAIL_MODE'
              value: 'cloud'
            }
            {
              name: 'IRONTRAIL_STORAGE_BLOB_URL'
              value: storageBlobEndpoint
            }
            {
              name: 'IRONTRAIL_STORAGE_TABLE_URL'
              value: storageTableEndpoint
            }
            {
              name: 'IRONTRAIL_BETA_REVEAL_SEED'
              secretRef: 'beta-reveal-seed'
            }
          ]
          image: currentContainerImage
          name: 'web'
          probes: [
            {
              httpGet: {
                path: '/_stcore/health'
                port: 80
              }
              initialDelaySeconds: 10
              periodSeconds: 30
              type: 'Liveness'
            }
            {
              httpGet: {
                path: '/_stcore/health'
                port: 80
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              type: 'Readiness'
            }
          ]
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
        }
      ]
      scale: {
        maxReplicas: 1
        minReplicas: 0
      }
    }
  }
}

resource stageC2AuthConfig 'Microsoft.App/containerApps/authConfigs@2024-03-01' = {
  parent: stageC2ContainerApp
  name: 'current'
  properties: {
    globalValidation: {
      unauthenticatedClientAction: unauthenticatedClientAction
    }
    httpSettings: {
      requireHttps: true
    }
    identityProviders: union({
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: aadClientId
          clientSecretSettingName: 'aad-client-secret'
          openIdIssuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
        }
      }
    }, googleIdentityProvider)
    platform: {
      enabled: true
    }
  }
}

output containerAppName string = stageC2ContainerApp.name
output containerAppsEnvironmentName string = containerAppsEnvironment.name
output containerRegistryEndpoint string = '${containerRegistryName}.azurecr.io'
output keyVaultName string = keyVault.name
output managedIdentityClientId string = managedIdentity.properties.clientId
output storageBlobUrl string = storageBlobEndpoint
output storageTableUrl string = storageTableEndpoint
output webUrl string = currentWebUrl
