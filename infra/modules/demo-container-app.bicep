param containerAppName string
param location string
param managedEnvironmentId string
param containerImage string
param appPort int = 5000
param demoUsername string = 'demo'
@secure()
param demoPasswordHash string
@secure()
param flaskSecretKey string
param tags object

resource containerApp 'Microsoft.App/containerApps@2026-01-01' = {
  name: containerAppName
  location: location
  tags: union(tags, {
    workload: 'demo'
  })
  properties: {
    managedEnvironmentId: managedEnvironmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: appPort
        transport: 'auto'
        allowInsecure: false
      }
      secrets: [
        {
          name: 'demo-password-hash'
          value: demoPasswordHash
        }
        {
          name: 'flask-secret-key'
          value: flaskSecretKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'fabric-governance-hub-demo'
          image: containerImage
          env: [
            {
              name: 'PORT'
              value: string(appPort)
            }
            {
              name: 'DEMO_MODE'
              value: 'true'
            }
            {
              name: 'DEMO_USERNAME'
              value: demoUsername
            }
            {
              name: 'DEMO_PASSWORD_HASH'
              secretRef: 'demo-password-hash'
            }
            {
              name: 'FLASK_SECRET_KEY'
              secretRef: 'flask-secret-key'
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/demo/login'
                port: appPort
                scheme: 'HTTP'
              }
              initialDelaySeconds: 15
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/demo/login'
                port: appPort
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

output name string = containerApp.name
output fqdn string = containerApp.properties.configuration.ingress.fqdn
