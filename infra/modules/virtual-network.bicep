param virtualNetworkName string
param location string
param tags object

param addressPrefix string = '10.40.0.0/16'
param containerAppsSubnetPrefix string = '10.40.0.0/23'
param privateEndpointsSubnetPrefix string = '10.40.2.0/24'

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: virtualNetworkName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        addressPrefix
      ]
    }
    subnets: [
      {
        name: 'snet-container-apps'
        properties: {
          addressPrefix: containerAppsSubnetPrefix
          delegations: [
            {
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: privateEndpointsSubnetPrefix
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

output id string = virtualNetwork.id
output containerAppsSubnetId string = '${virtualNetwork.id}/subnets/snet-container-apps'
output privateEndpointsSubnetId string = '${virtualNetwork.id}/subnets/snet-private-endpoints'
