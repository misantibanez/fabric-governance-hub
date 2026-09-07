param storageAccountName string
param location string
param appPrincipalId string
param tags object

var tokenContainerName = 'easyauth-token-store'
var storageBlobDataContributorRoleDefinitionId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource storageAccount 'Microsoft.Storage/storageAccounts@2025-06-01' = {
  name: storageAccountName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Disabled'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-06-01' = {
  parent: storageAccount
  name: 'default'
}

resource tokenContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-06-01' = {
  parent: blobService
  name: tokenContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource tokenStoreRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, appPrincipalId, storageBlobDataContributorRoleDefinitionId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleDefinitionId)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output id string = storageAccount.id
output name string = storageAccount.name
output containerName string = tokenContainer.name
output blobContainerUri string = '${storageAccount.properties.primaryEndpoints.blob}${tokenContainer.name}'
