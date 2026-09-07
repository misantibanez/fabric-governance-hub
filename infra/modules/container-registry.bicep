param registryName string
param location string
param publicNetworkAccess string
param tags object

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' = {
  name: registryName
  location: location
  tags: tags
  sku: {
    name: 'Premium'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: publicNetworkAccess
    networkRuleBypassOptions: 'AzureServices'
  }
}

output id string = registry.id
output name string = registry.name
output loginServer string = registry.properties.loginServer
