param configurationStoreName string
param location string
param publicNetworkAccess string = 'Enabled'
param tags object

resource configurationStore 'Microsoft.AppConfiguration/configurationStores@2024-05-01' = {
  name: configurationStoreName
  location: location
  tags: tags
  sku: {
    name: 'standard'
  }
  properties: {
    disableLocalAuth: true
    enablePurgeProtection: true
    publicNetworkAccess: publicNetworkAccess
  }
}

output id string = configurationStore.id
output endpoint string = configurationStore.properties.endpoint
output name string = configurationStore.name
