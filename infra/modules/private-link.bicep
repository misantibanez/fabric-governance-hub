param location string
param virtualNetworkId string
param adminVirtualNetworkId string = ''
param privateEndpointsSubnetId string
param containerRegistryId string
param keyVaultId string
param appConfigurationId string
param tokenStorageAccountId string
param logAnalyticsWorkspaceId string
param applicationInsightsId string
param tags object

resource acrPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.azurecr.io'
  location: 'global'
  tags: tags
}

resource keyVaultPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.vaultcore.azure.net'
  location: 'global'
  tags: tags
}

resource appConfigurationPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.azconfig.io'
  location: 'global'
  tags: tags
}

resource monitorPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.monitor.azure.com'
  location: 'global'
  tags: tags
}

resource omsPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.oms.opinsights.azure.com'
  location: 'global'
  tags: tags
}

resource odsPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.ods.opinsights.azure.com'
  location: 'global'
  tags: tags
}

resource automationAgentPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.agentsvc.azure-automation.net'
  location: 'global'
  tags: tags
}

resource monitorBlobPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  #disable-next-line no-hardcoded-env-urls
  name: 'privatelink.blob.core.windows.net'
  location: 'global'
  tags: tags
}

resource acrVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: acrPrivateDnsZone
  name: 'link-fabric-governance-vnet'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource keyVaultVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: keyVaultPrivateDnsZone
  name: 'link-fabric-governance-vnet'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource appConfigurationVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: appConfigurationPrivateDnsZone
  name: 'link-fabric-governance-vnet'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource appConfigurationAdminVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!empty(adminVirtualNetworkId)) {
  parent: appConfigurationPrivateDnsZone
  name: 'link-fabric-governance-admin-vnet'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: adminVirtualNetworkId
    }
  }
}

resource monitorVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: monitorPrivateDnsZone
  name: 'link-fabric-governance-vnet'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource omsVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: omsPrivateDnsZone
  name: 'link-fabric-governance-vnet'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource odsVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: odsPrivateDnsZone
  name: 'link-fabric-governance-vnet'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource automationAgentVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: automationAgentPrivateDnsZone
  name: 'link-fabric-governance-vnet'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource monitorBlobVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: monitorBlobPrivateDnsZone
  name: 'link-fabric-governance-vnet'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource acrPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-cr-fabric-gov-dev-3d9c'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'acr'
        properties: {
          privateLinkServiceId: containerRegistryId
          groupIds: [
            'registry'
          ]
        }
      }
    ]
  }
}

resource acrPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: acrPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'acr'
        properties: {
          privateDnsZoneId: acrPrivateDnsZone.id
        }
      }
    ]
  }
}

resource keyVaultPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-kv-fabric-gov-dev-3d9c'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'vault'
        properties: {
          privateLinkServiceId: keyVaultId
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

resource keyVaultPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: keyVaultPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'vault'
        properties: {
          privateDnsZoneId: keyVaultPrivateDnsZone.id
        }
      }
    ]
  }
}

resource appConfigurationPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-appcs-fabric-gov-dev-3d9c'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'configuration-store'
        properties: {
          privateLinkServiceId: appConfigurationId
          groupIds: [
            'configurationStores'
          ]
        }
      }
    ]
  }
}

resource appConfigurationPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: appConfigurationPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'configuration-store'
        properties: {
          privateDnsZoneId: appConfigurationPrivateDnsZone.id
        }
      }
    ]
  }
}

resource tokenStoragePrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-st-fabric-gov-dev-3d9c'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'blob'
        properties: {
          privateLinkServiceId: tokenStorageAccountId
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

resource tokenStoragePrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: tokenStoragePrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob'
        properties: {
          privateDnsZoneId: monitorBlobPrivateDnsZone.id
        }
      }
    ]
  }
}

resource monitorPrivateLinkScope 'Microsoft.Insights/privateLinkScopes@2021-07-01-preview' = {
  name: 'ampls-fabric-gov-dev-3d9c'
  location: 'global'
  tags: tags
  properties: {
    accessModeSettings: {
      ingestionAccessMode: 'PrivateOnly'
      queryAccessMode: 'PrivateOnly'
    }
  }
}

resource logAnalyticsScopedResource 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-07-01-preview' = {
  parent: monitorPrivateLinkScope
  name: 'log-analytics'
  properties: {
    linkedResourceId: logAnalyticsWorkspaceId
  }
}

resource applicationInsightsScopedResource 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-07-01-preview' = {
  parent: monitorPrivateLinkScope
  name: 'application-insights'
  properties: {
    linkedResourceId: applicationInsightsId
  }
}

resource monitorPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-ampls-fabric-gov-dev-3d9c'
  location: location
  tags: tags
  dependsOn: [
    logAnalyticsScopedResource
    applicationInsightsScopedResource
  ]
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'azuremonitor'
        properties: {
          privateLinkServiceId: monitorPrivateLinkScope.id
          groupIds: [
            'azuremonitor'
          ]
        }
      }
    ]
  }
}

resource monitorPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: monitorPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'monitor'
        properties: {
          privateDnsZoneId: monitorPrivateDnsZone.id
        }
      }
      {
        name: 'oms'
        properties: {
          privateDnsZoneId: omsPrivateDnsZone.id
        }
      }
      {
        name: 'ods'
        properties: {
          privateDnsZoneId: odsPrivateDnsZone.id
        }
      }
      {
        name: 'automation-agent'
        properties: {
          privateDnsZoneId: automationAgentPrivateDnsZone.id
        }
      }
      {
        name: 'monitor-blob'
        properties: {
          privateDnsZoneId: monitorBlobPrivateDnsZone.id
        }
      }
    ]
  }
}

output monitorPrivateLinkScopeId string = monitorPrivateLinkScope.id
