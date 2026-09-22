targetScope = 'resourceGroup'

param location string = resourceGroup().location
param managedEnvironmentId string
@description('Publicly accessible image containing the Fabric Governance Hub application.')
param containerImage string
param containerAppName string = 'ca-fabric-governance-hub-demo'
param demoUsername string = 'demo'
@secure()
param demoPasswordHash string
@secure()
param flaskSecretKey string

var tags = {
  application: 'fabric-governance-hub'
  environment: 'demo'
  isolation: 'sample-data-only'
}

module demoContainerApp './modules/demo-container-app.bicep' = {
  name: 'demo-container-app'
  params: {
    containerAppName: containerAppName
    location: location
    managedEnvironmentId: managedEnvironmentId
    containerImage: containerImage
    appPort: 5000
    demoUsername: demoUsername
    demoPasswordHash: demoPasswordHash
    flaskSecretKey: flaskSecretKey
    tags: tags
  }
}

output containerAppName string = demoContainerApp.outputs.name
output containerAppFqdn string = demoContainerApp.outputs.fqdn
