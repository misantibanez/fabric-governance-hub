param containerAppName string
param location string
param managedEnvironmentId string
param managedIdentityId string
param registryLoginServer string
@secure()
param tokenStoreSasUrl string
param applicationInsightsConnectionString string
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param appPort int = 5000
param fabricTenantId string
param entraWebClientId string
@secure()
param entraWebClientSecret string
param dataGatewayClientId string
@secure()
param dataGatewayClientSecret string
param allowedAdminGroupObjectId string
@secure()
param flaskSecretKey string
param enableGitHubPat bool = false
@secure()
param githubPat string = ''
param tags object

var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var isPlaceholder = containerImage == placeholderImage
var effectivePort = isPlaceholder ? 80 : appPort
var plainEnvironmentVariables = [
  {
    name: 'PORT'
    value: string(effectivePort)
  }
  {
    name: 'FABRIC_TENANT_ID'
    value: fabricTenantId
  }
  {
    name: 'ENTRA_WEB_CLIENT_ID'
    value: entraWebClientId
  }
  {
    name: 'DATA_GATEWAY_CLIENT_ID'
    value: dataGatewayClientId
  }
  {
    name: 'ALLOWED_ADMIN_GROUP_OBJECT_ID'
    value: allowedAdminGroupObjectId
  }
  {
    name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
    value: applicationInsightsConnectionString
  }
]
var requiredSecretEnvironmentVariables = [
  {
    name: 'FLASK_SECRET_KEY'
    secretRef: 'flask-secret-key'
  }
  {
    name: 'ENTRA_WEB_CLIENT_SECRET'
    secretRef: 'entra-web-client-secret'
  }
  {
    name: 'DATA_GATEWAY_CLIENT_SECRET'
    secretRef: 'data-gateway-client-secret'
  }
]
var githubSecretEnvironmentVariables = enableGitHubPat ? [
  {
    name: 'GITHUB_PAT'
    secretRef: 'github-pat'
  }
] : []
var requiredSecrets = [
  {
    name: 'flask-secret-key'
    value: flaskSecretKey
  }
  {
    name: 'entra-web-client-secret'
    value: entraWebClientSecret
  }
  {
    name: 'data-gateway-client-secret'
    value: dataGatewayClientSecret
  }
  {
    name: 'easy-auth-token-store-sas'
    value: tokenStoreSasUrl
  }
]
var githubSecrets = enableGitHubPat ? [
  {
    name: 'github-pat'
    value: githubPat
  }
] : []

resource containerApp 'Microsoft.App/containerApps@2026-01-01' = {
  name: containerAppName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: managedEnvironmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: !isPlaceholder
        targetPort: effectivePort
        transport: 'auto'
        allowInsecure: false
      }
      registries: isPlaceholder ? [] : [
        {
          server: registryLoginServer
          identity: managedIdentityId
        }
      ]
      secrets: isPlaceholder ? [] : concat(requiredSecrets, githubSecrets)
    }
    template: {
      containers: [
        {
          name: 'fabric-governance-hub'
          image: containerImage
          env: isPlaceholder ? [
            {
              name: 'PORT'
              value: string(effectivePort)
            }
          ] : concat(plainEnvironmentVariables, requiredSecretEnvironmentVariables, githubSecretEnvironmentVariables)
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/'
                port: effectivePort
                scheme: 'HTTP'
              }
              initialDelaySeconds: 20
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/'
                port: effectivePort
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 6
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

resource authConfig 'Microsoft.App/containerApps/authConfigs@2026-01-01' = if (!isPlaceholder) {
  parent: containerApp
  name: 'current'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
    }
    login: {
      tokenStore: {
        enabled: true
        azureBlobStorage: {
          sasUrlSettingName: 'easy-auth-token-store-sas'
        }
      }
    }
    identityProviders: {
      azureActiveDirectory: {
        registration: {
          openIdIssuer: '${environment().authentication.loginEndpoint}${fabricTenantId}/v2.0'
          clientId: entraWebClientId
          clientSecretSettingName: 'entra-web-client-secret'
        }
        login: {
          loginParameters: [
            'scope=openid profile email offline_access api://${entraWebClientId}/user_impersonation'
          ]
        }
        validation: {
          allowedAudiences: [
            'api://${entraWebClientId}'
          ]
          defaultAuthorizationPolicy: {
            allowedPrincipals: {
              groups: [
                allowedAdminGroupObjectId
              ]
            }
          }
        }
      }
    }
  }
}

output id string = containerApp.id
output name string = containerApp.name
output fqdn string = isPlaceholder ? '' : containerApp.properties.configuration.ingress.fqdn
