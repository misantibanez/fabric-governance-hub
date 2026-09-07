targetScope = 'subscription'

@minLength(1)
@maxLength(64)
param environmentName string

@minLength(1)
param location string

@minLength(1)
param resourceGroupLocation string = 'centralus'

param sessionId string
param deployedBy string
param createdAt string
param deployerObjectId string
param resourceGroupName string = 'rg-fb-governance-app'
param adminVirtualNetworkId string = ''
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param fabricTenantId string = tenant().tenantId
param entraWebClientId string = ''
@secure()
param entraWebClientSecret string
param dataGatewayClientId string = ''
@secure()
param dataGatewayClientSecret string
param allowedAdminGroupObjectId string = ''
@secure()
param flaskSecretKey string
@secure()
param tokenStoreSasUrl string
param enableGitHubPat bool = false
@secure()
param githubPat string = ''

@description('Disable public access to ACR and Azure Monitor only after the VNet-integrated app is healthy.')
param lockDownPrivateServices bool = false

var tags = {
  'app-onboard-skill': 'true'
  'app-onboard-session-id': sessionId
  'created-at': createdAt
  environment: environmentName
  'deployed-by': deployedBy
}

resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {
  name: resourceGroupName
  location: resourceGroupLocation
  tags: tags
}

module managedIdentity './modules/managed-identity.bicep' = {
  name: 'managed-identity'
  scope: rg
  params: {
    identityName: 'id-fabric-gov-dev-3d9c'
    location: location
    tags: tags
  }
}

module containerRegistry './modules/container-registry.bicep' = {
  name: 'container-registry'
  scope: rg
  params: {
    registryName: 'crfabricgovdev3d9c'
    location: location
    publicNetworkAccess: lockDownPrivateServices ? 'Disabled' : 'Enabled'
    tags: tags
  }
}

module logAnalytics './modules/log-analytics.bicep' = {
  name: 'log-analytics'
  scope: rg
  params: {
    workspaceName: 'log-fabric-gov-dev-3d9c'
    location: location
    publicNetworkAccess: lockDownPrivateServices ? 'Disabled' : 'Enabled'
    tags: tags
  }
}

module applicationInsights './modules/application-insights.bicep' = {
  name: 'application-insights'
  scope: rg
  params: {
    applicationInsightsName: 'appi-fabric-gov-dev-3d9c'
    location: location
    workspaceResourceId: logAnalytics.outputs.id
    publicNetworkAccess: lockDownPrivateServices ? 'Disabled' : 'Enabled'
    tags: tags
  }
}

module keyVault './modules/key-vault.bicep' = {
  name: 'key-vault'
  scope: rg
  params: {
    keyVaultName: 'kv-fabric-gov-dev-3d9c'
    location: location
    tags: tags
  }
}

module appConfiguration './modules/app-configuration.bicep' = {
  name: 'app-configuration'
  scope: rg
  params: {
    configurationStoreName: 'appcs-fabric-gov-dev-3d9c'
    location: location
    publicNetworkAccess: 'Disabled'
    tags: tags
  }
}

module tokenStorage './modules/token-storage.bicep' = {
  name: 'token-storage'
  scope: rg
  params: {
    storageAccountName: 'stfabricgovdev3d9c'
    location: location
    appPrincipalId: managedIdentity.outputs.principalId
    tags: tags
  }
}

module virtualNetwork './modules/virtual-network.bicep' = {
  name: 'virtual-network'
  scope: rg
  params: {
    virtualNetworkName: 'vnet-fabric-gov-dev-3d9c'
    location: location
    tags: tags
  }
}

module containerEnvironment './modules/container-app-environment.bicep' = {
  name: 'container-app-environment'
  scope: rg
  params: {
    environmentName: 'cae-fabric-gov-dev-3d9c-vnet'
    location: location
    workspaceName: 'log-fabric-gov-dev-3d9c'
    workspaceCustomerId: logAnalytics.outputs.customerId
    infrastructureSubnetId: virtualNetwork.outputs.containerAppsSubnetId
    tags: tags
  }
}

module privateLink './modules/private-link.bicep' = {
  name: 'private-link'
  scope: rg
  params: {
    location: location
    virtualNetworkId: virtualNetwork.outputs.id
    adminVirtualNetworkId: adminVirtualNetworkId
    privateEndpointsSubnetId: virtualNetwork.outputs.privateEndpointsSubnetId
    containerRegistryId: containerRegistry.outputs.id
    keyVaultId: keyVault.outputs.id
    appConfigurationId: appConfiguration.outputs.id
    tokenStorageAccountId: tokenStorage.outputs.id
    logAnalyticsWorkspaceId: logAnalytics.outputs.id
    applicationInsightsId: applicationInsights.outputs.id
    tags: tags
  }
}

module containerApp './modules/container-app.bicep' = {
  name: 'container-app'
  scope: rg
  dependsOn: [
    keyVaultSecrets
    privateLink
    roleAssignments
  ]
  params: {
    containerAppName: 'ca-fabric-gov-dev-3d9c-vnet'
    location: location
    managedEnvironmentId: containerEnvironment.outputs.id
    managedIdentityId: managedIdentity.outputs.id
    managedIdentityClientId: managedIdentity.outputs.clientId
    registryLoginServer: containerRegistry.outputs.loginServer
    appConfigurationEndpoint: appConfiguration.outputs.endpoint
    appConfigurationLabel: environmentName
    tokenStoreSasUrl: tokenStoreSasUrl
    applicationInsightsConnectionString: applicationInsights.outputs.connectionString
    containerImage: containerImage
    appPort: 5000
    fabricTenantId: fabricTenantId
    entraWebClientId: entraWebClientId
    entraWebClientSecret: entraWebClientSecret
    dataGatewayClientId: dataGatewayClientId
    dataGatewayClientSecret: dataGatewayClientSecret
    allowedAdminGroupObjectId: allowedAdminGroupObjectId
    flaskSecretKey: flaskSecretKey
    enableGitHubPat: enableGitHubPat
    githubPat: githubPat
    tags: tags
  }
}

module roleAssignments './modules/role-assignments.bicep' = {
  name: 'role-assignments'
  scope: rg
  dependsOn: [
    containerRegistry
    keyVault
  ]
  params: {
    registryName: 'crfabricgovdev3d9c'
    keyVaultName: 'kv-fabric-gov-dev-3d9c'
    configurationStoreName: appConfiguration.outputs.name
    appPrincipalId: managedIdentity.outputs.principalId
    deployerObjectId: deployerObjectId
  }
}

module tokenRotationJob './modules/token-rotation-job.bicep' = {
  name: 'token-rotation-job'
  scope: rg
  params: {
    jobName: 'job-fgov-sas-rotate-dev-3d9c'
    identityName: 'id-fabric-gov-token-rotation-dev-3d9c'
    location: location
    managedEnvironmentId: containerEnvironment.outputs.id
    storageAccountName: tokenStorage.outputs.name
    tokenContainerName: tokenStorage.outputs.containerName
    targetContainerAppName: containerApp.outputs.name
    targetContainerAppIdentityId: managedIdentity.outputs.id
    tags: tags
  }
}

module keyVaultSecrets './modules/key-vault-secrets.bicep' = {
  name: 'key-vault-secrets'
  scope: rg
  dependsOn: [
    roleAssignments
  ]
  params: {
    keyVaultName: 'kv-fabric-gov-dev-3d9c'
    flaskSecretKey: flaskSecretKey
    entraWebClientSecret: entraWebClientSecret
    dataGatewayClientSecret: dataGatewayClientSecret
    enableGitHubPat: enableGitHubPat
    githubPat: githubPat
  }
}

output containerAppName string = containerApp.outputs.name
output containerAppFqdn string = containerApp.outputs.fqdn
output containerRegistryName string = containerRegistry.outputs.name
output keyVaultName string = keyVault.outputs.name
output managedIdentityClientId string = managedIdentity.outputs.clientId
output virtualNetworkId string = virtualNetwork.outputs.id
output monitorPrivateLinkScopeId string = privateLink.outputs.monitorPrivateLinkScopeId
output tokenRotationJobName string = tokenRotationJob.outputs.name
