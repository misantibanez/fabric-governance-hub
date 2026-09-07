param keyVaultName string

@secure()
param flaskSecretKey string

@secure()
param entraWebClientSecret string

@secure()
param dataGatewayClientSecret string

param enableGitHubPat bool = false

@secure()
param githubPat string = ''

resource keyVault 'Microsoft.KeyVault/vaults@2026-02-01' existing = {
  name: keyVaultName
}

resource flaskSecret 'Microsoft.KeyVault/vaults/secrets@2026-02-01' = {
  parent: keyVault
  name: 'flask-secret-key'
  properties: {
    value: flaskSecretKey
  }
}

resource entraWebClientSecretResource 'Microsoft.KeyVault/vaults/secrets@2026-02-01' = {
  parent: keyVault
  name: 'entra-web-client-secret'
  properties: {
    value: entraWebClientSecret
  }
}

resource dataGatewayClientSecretResource 'Microsoft.KeyVault/vaults/secrets@2026-02-01' = {
  parent: keyVault
  name: 'data-gateway-client-secret'
  properties: {
    value: dataGatewayClientSecret
  }
}

resource githubPatSecret 'Microsoft.KeyVault/vaults/secrets@2026-02-01' = if (enableGitHubPat) {
  parent: keyVault
  name: 'github-pat'
  properties: {
    value: githubPat
  }
}
