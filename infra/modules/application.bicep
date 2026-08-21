targetScope = 'resourceGroup'

@description('AZD environment name.')
param environmentName string

@description('Location for new application resources.')
param location string

@description('Existing Microsoft Foundry account name.')
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

@secure()
@description('Microsoft identity application client secret.')
param aadClientSecret string

@secure()
@description('SHA-256 hash of the bootstrap administrator invite.')
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
@description('Grant the owner Key Vault Secrets User for break-glass recovery.')
param grantOwnerKeyVaultAccess string = 'false'

@allowed([
  'false'
  'true'
])
@description('Temporarily grant the owner Storage Table Data Reader for diagnostics.')
param grantOwnerStorageDiagnosticAccess string = 'false'

@description('Current deployed image retained when reconciling an existing beta.')
param currentContainerImage string = ''

@allowed([
  'false'
  'true'
])
@description('Whether the verified login landing page may accept anonymous requests.')
param authReady string

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
@description('Maximum number of active beta members, including the owner.')
param maxUsers string

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
var logAnalyticsName = 'log-irontrail-${resourceSuffix}'
var applicationInsightsName = 'appi-irontrail-${resourceSuffix}'
var containerAppsEnvironmentName = 'cae-irontrail-${resourceSuffix}'
var containerAppName = 'ca-irontrail-${resourceSuffix}'
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var unauthenticatedClientAction = toLower(authReady) == 'true' ? 'AllowAnonymous' : 'Return401'
var tableEndpoint = 'https://${storageAccountName}.table.${environment().suffixes.storage}'
var foundryEndpoint = 'https://${foundryAccountName}.cognitiveservices.azure.com/'
var googleAuthConfigured = toLower(googleAuthEnabled) == 'true'
var authProviders = googleAuthConfigured ? 'aad,google' : 'aad'

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var storageBlobContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageTableContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
var storageTableDataReaderRoleId = '76199698-9eea-4c19-bc75-cec21354c6b6'
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var cognitiveServicesOpenAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

module managedIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.6.0' = {
  name: 'managedIdentity'
  params: {
    enableTelemetry: false
    location: location
    name: identityName
    tags: tags
  }
}

module logAnalytics 'br/public:avm/res/operational-insights/workspace:0.15.1' = {
  name: 'logAnalytics'
  params: {
    dailyQuotaGb: '0.25'
    dataRetention: 30
    enableTelemetry: false
    location: location
    name: logAnalyticsName
    tags: tags
  }
}

module applicationInsights 'br/public:avm/res/insights/component:0.7.2' = {
  name: 'applicationInsights'
  params: {
    disableIpMasking: false
    disableLocalAuth: true
    enableTelemetry: false
    immediatePurgeDataOn30Days: true
    location: location
    name: applicationInsightsName
    tags: tags
    workspaceResourceId: logAnalytics.outputs.resourceId
  }
}

module containerRegistry 'br/public:avm/res/container-registry/registry:0.9.3' = {
  name: 'containerRegistry'
  params: {
    acrAdminUserEnabled: false
    acrSku: 'Basic'
    enableTelemetry: false
    location: location
    name: containerRegistryName
    roleAssignments: [
      {
        principalId: managedIdentity.outputs.principalId
        principalType: 'ServicePrincipal'
        roleDefinitionIdOrName: acrPullRoleId
      }
    ]
    tags: tags
  }
}

module storageAccount 'br/public:avm/res/storage/storage-account:0.32.1' = {
  name: 'storageAccount'
  params: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    blobServices: {
      containers: [
        {
          name: 'datasets'
          publicAccess: 'None'
        }
      ]
      containerDeleteRetentionPolicyDays: 7
      containerDeleteRetentionPolicyEnabled: true
      deleteRetentionPolicyDays: 7
      deleteRetentionPolicyEnabled: true
    }
    defaultToOAuthAuthentication: true
    enableTelemetry: false
    kind: 'StorageV2'
    location: location
    managementPolicyRules: [
      {
        definition: {
          actions: {
            baseBlob: {
              delete: {
                daysAfterModificationGreaterThan: 30
              }
            }
          }
          filters: {
            blobTypes: [
              'blockBlob'
            ]
            prefixMatch: [
              'datasets/raw/'
            ]
          }
        }
        enabled: true
        name: 'delete-raw-after-30-days'
        type: 'Lifecycle'
      }
      {
        definition: {
          actions: {
            baseBlob: {
              delete: {
                daysAfterModificationGreaterThan: 60
              }
            }
          }
          filters: {
            blobTypes: [
              'blockBlob'
            ]
            prefixMatch: [
              'datasets/normalized/'
            ]
          }
        }
        enabled: true
        name: 'delete-normalized-after-60-days'
        type: 'Lifecycle'
      }
    ]
    minimumTlsVersion: 'TLS1_2'
    name: storageAccountName
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
    publicNetworkAccess: 'Enabled'
    roleAssignments: concat(
      [
        {
          principalId: managedIdentity.outputs.principalId
          principalType: 'ServicePrincipal'
          roleDefinitionIdOrName: storageBlobContributorRoleId
        }
        {
          principalId: managedIdentity.outputs.principalId
          principalType: 'ServicePrincipal'
          roleDefinitionIdOrName: storageTableContributorRoleId
        }
      ],
      toLower(grantOwnerStorageDiagnosticAccess) == 'true'
        ? [
            {
              principalId: ownerObjectId
              principalType: 'User'
              roleDefinitionIdOrName: storageTableDataReaderRoleId
            }
          ]
        : []
    )
    skuName: 'Standard_LRS'
    supportsHttpsTrafficOnly: true
    tableServices: {
      tables: [
        {
          name: 'IronTrailAuth'
        }
        {
          name: 'IronTrailData'
        }
        {
          name: 'IronTrailUsage'
        }
      ]
    }
    tags: tags
  }
}

module keyVault 'br/public:avm/res/key-vault/vault:0.13.3' = {
  name: 'keyVault'
  params: {
    enablePurgeProtection: false
    enableRbacAuthorization: true
    enableTelemetry: false
    location: location
    name: keyVaultName
    publicNetworkAccess: 'Enabled'
    roleAssignments: concat(
      [
        {
          principalId: managedIdentity.outputs.principalId
          principalType: 'ServicePrincipal'
          roleDefinitionIdOrName: keyVaultSecretsUserRoleId
        }
      ],
      // Break-glass: the vault uses RBAC, so subscription Owner alone cannot
      // read these secrets. Declaring the grant keeps it auditable instead of
      // being applied by hand during a recovery.
      toLower(grantOwnerKeyVaultAccess) == 'true'
        ? [
            {
              principalId: ownerObjectId
              principalType: 'User'
              roleDefinitionIdOrName: keyVaultSecretsUserRoleId
            }
          ]
        : []
    )
    secrets: concat([
      {
        contentType: 'Container Apps Easy Auth client secret'
        name: 'aad-client-secret'
        value: aadClientSecret
      }
      {
        contentType: 'SHA-256 bootstrap invite hash'
        name: 'bootstrap-invite-hash'
        value: bootstrapInviteHash
      }
      {
        contentType: 'Application Insights connection string'
        name: 'appinsights-connection-string'
        value: applicationInsights.outputs.connectionString
      }
      {
        contentType: 'Private beta landing reveal seed'
        name: 'beta-reveal-seed'
        value: betaRevealSeed
      }
    ], googleAuthConfigured ? [
      {
        contentType: 'Google OAuth web client secret'
        name: 'google-client-secret'
        value: googleClientSecret
      }
    ] : [])
    sku: 'standard'
    softDeleteRetentionInDays: 7
    tags: tags
  }
}

module containerAppsEnvironment 'br/public:avm/res/app/managed-environment:0.13.3' = {
  name: 'containerAppsEnvironment'
  params: {
    appInsightsConnectionString: applicationInsights.outputs.connectionString
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsWorkspaceResourceId: logAnalytics.outputs.resourceId
    }
    enableTelemetry: false
    location: location
    name: containerAppsEnvironmentName
    publicNetworkAccess: 'Enabled'
    tags: tags
    zoneRedundant: false
  }
}

module foundryRoleAssignment 'br/public:avm/ptn/authorization/resource-role-assignment:0.1.2' = {
  name: 'foundryRoleAssignment'
  params: {
    description: 'Allow the IronTrail container identity to invoke the configured model.'
    enableTelemetry: false
    principalId: managedIdentity.outputs.principalId
    principalType: 'ServicePrincipal'
    resourceId: resourceId('Microsoft.CognitiveServices/accounts', foundryAccountName)
    roleDefinitionId: cognitiveServicesOpenAiUserRoleId
    roleName: 'Cognitive Services OpenAI User'
  }
}

module containerApp 'br/public:avm/res/app/container-app:0.23.0' = {
  name: 'containerApp'
  dependsOn: [
    foundryRoleAssignment
  ]
  params: {
    activeRevisionsMode: 'Single'
    authConfig: {
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
      }, googleAuthConfigured ? {
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
      } : {})
      platform: {
        enabled: true
      }
    }
    containers: [
      {
        env: [
          {
            name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
            secretRef: 'appinsights-connection-string'
          }
          {
            name: 'AZURE_CLIENT_ID'
            value: managedIdentity.outputs.clientId
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
            name: 'IRONTRAIL_BETA_REVEAL_SEED'
            secretRef: 'beta-reveal-seed'
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
            value: storageAccount.outputs.primaryBlobEndpoint
          }
          {
            name: 'IRONTRAIL_STORAGE_TABLE_URL'
            value: tableEndpoint
          }
        ]
        image: currentContainerImage == '' ? placeholderImage : currentContainerImage
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
    enableTelemetry: false
    environmentResourceId: containerAppsEnvironment.outputs.resourceId
    ingressAllowInsecure: false
    ingressExternal: true
    ingressTargetPort: 80
    ingressTransport: 'auto'
    location: location
    managedIdentities: {
      userAssignedResourceIds: [
        managedIdentity.outputs.resourceId
      ]
    }
    name: containerAppName
    registries: [
      {
        identity: managedIdentity.outputs.resourceId
        server: containerRegistry.outputs.loginServer
      }
    ]
    scaleSettings: {
      maxReplicas: 1
      minReplicas: 0
    }
    secrets: concat([
      {
        identity: managedIdentity.outputs.resourceId
        keyVaultUrl: '${keyVault.outputs.uri}secrets/aad-client-secret'
        name: 'aad-client-secret'
      }
      {
        identity: managedIdentity.outputs.resourceId
        keyVaultUrl: '${keyVault.outputs.uri}secrets/bootstrap-invite-hash'
        name: 'bootstrap-invite-hash'
      }
      {
        identity: managedIdentity.outputs.resourceId
        keyVaultUrl: '${keyVault.outputs.uri}secrets/appinsights-connection-string'
        name: 'appinsights-connection-string'
      }
      {
        identity: managedIdentity.outputs.resourceId
        keyVaultUrl: '${keyVault.outputs.uri}secrets/beta-reveal-seed'
        name: 'beta-reveal-seed'
      }
    ], googleAuthConfigured ? [
      {
        identity: managedIdentity.outputs.resourceId
        keyVaultUrl: '${keyVault.outputs.uri}secrets/google-client-secret'
        name: 'google-client-secret'
      }
    ] : [])
    stickySessionsAffinity: 'sticky'
    tags: serviceTags
  }
}

output containerAppName string = containerApp.outputs.name
output containerAppsEnvironmentName string = containerAppsEnvironment.outputs.name
output containerRegistryEndpoint string = containerRegistry.outputs.loginServer
output keyVaultName string = keyVault.outputs.name
output managedIdentityClientId string = managedIdentity.outputs.clientId
output storageBlobUrl string = storageAccount.outputs.primaryBlobEndpoint
output storageTableUrl string = tableEndpoint
output webUrl string = 'https://${containerApp.outputs.fqdn}'
