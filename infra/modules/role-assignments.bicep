param registryName string
param keyVaultName string
param configurationStoreName string
param appPrincipalId string
param deployerObjectId string

var acrPullRoleDefinitionId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var keyVaultSecretsUserRoleDefinitionId = '4633458b-17de-408a-b874-0445c86b69e6'
var keyVaultSecretsOfficerRoleDefinitionId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
var appConfigurationDataOwnerRoleDefinitionId = '5ae67dd6-50cb-40e7-96ff-dc2bfa4b606b'

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' existing = {
  name: registryName
}

resource keyVault 'Microsoft.KeyVault/vaults@2026-02-01' existing = {
  name: keyVaultName
}

resource configurationStore 'Microsoft.AppConfiguration/configurationStores@2024-05-01' existing = {
  name: configurationStoreName
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, appPrincipalId, acrPullRoleDefinitionId)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleDefinitionId)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource keyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, appPrincipalId, keyVaultSecretsUserRoleDefinitionId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleDefinitionId)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource appConfigurationDataOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(configurationStore.id, appPrincipalId, appConfigurationDataOwnerRoleDefinitionId)
  scope: configurationStore
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', appConfigurationDataOwnerRoleDefinitionId)
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource keyVaultSecretsOfficer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, deployerObjectId, keyVaultSecretsOfficerRoleDefinitionId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsOfficerRoleDefinitionId)
    principalId: deployerObjectId
    principalType: 'User'
  }
}
