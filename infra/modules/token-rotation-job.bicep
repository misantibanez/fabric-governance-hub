param jobName string
param identityName string
param location string
param managedEnvironmentId string
param storageAccountName string
param tokenContainerName string
param targetContainerAppName string
param targetContainerAppIdentityId string
param tags object

var storageBlobDelegatorRoleDefinitionId = 'db58b8e5-c6ad-4a2a-8342-4190687cbf4a'
var storageBlobDataContributorRoleDefinitionId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var containerAppsContributorRoleDefinitionId = '358470bc-b998-42bd-ab17-a7e34c199c0f'
var containerAppsOperatorRoleDefinitionId = 'f3bd1b5c-91fa-40e7-afe7-0c11d331232c'
var managedIdentityOperatorRoleDefinitionId = 'f1a07417-d97a-45cb-824c-7a7467783830'
var rotationScript = '''
set -eu

az login --identity --client-id "$AZURE_CLIENT_ID" --allow-no-subscriptions --output none
az account set --subscription "$AZURE_SUBSCRIPTION_ID"

expiry="$(date -u -d '+6 days' '+%Y-%m-%dT%H:%MZ')"
sas_token="$(az storage container generate-sas \
  --account-name "$STORAGE_ACCOUNT_NAME" \
  --name "$TOKEN_CONTAINER_NAME" \
  --permissions rwdl \
  --expiry "$expiry" \
  --https-only \
  --as-user \
  --auth-mode login \
  --output tsv)"

test -n "$sas_token"
sas_url="https://$STORAGE_ACCOUNT_NAME.blob.$AZURE_STORAGE_DNS_SUFFIX/$TOKEN_CONTAINER_NAME?$sas_token"

az config set extension.use_dynamic_install=no
az extension add --name containerapp --version 1.3.0b5 --only-show-errors
az containerapp secret set \
  --resource-group "$TARGET_RESOURCE_GROUP" \
  --name "$TARGET_CONTAINER_APP_NAME" \
  --secrets "easy-auth-token-store-sas=$sas_url" \
  --only-show-errors \
  --output none

revision="$(az containerapp show \
  --resource-group "$TARGET_RESOURCE_GROUP" \
  --name "$TARGET_CONTAINER_APP_NAME" \
  --query properties.latestRevisionName \
  --output tsv)"

test -n "$revision"
az containerapp revision restart \
  --resource-group "$TARGET_RESOURCE_GROUP" \
  --name "$TARGET_CONTAINER_APP_NAME" \
  --revision "$revision" \
  --only-show-errors \
  --output none

unset sas_token sas_url
printf 'Easy Auth token-store SAS rotated; expiry=%s; revision=%s\n' "$expiry" "$revision"
'''

resource rotationIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: identityName
  location: location
  tags: tags
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2025-06-01' existing = {
  name: storageAccountName
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-06-01' existing = {
  parent: storageAccount
  name: 'default'
}

resource tokenContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-06-01' existing = {
  parent: blobService
  name: tokenContainerName
}

resource targetContainerApp 'Microsoft.App/containerApps@2026-01-01' existing = {
  name: targetContainerAppName
}

resource managedEnvironment 'Microsoft.App/managedEnvironments@2025-07-01' existing = {
  name: last(split(managedEnvironmentId, '/'))
}

resource targetContainerAppIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: last(split(targetContainerAppIdentityId, '/'))
}

resource storageBlobDelegator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, rotationIdentity.id, storageBlobDelegatorRoleDefinitionId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDelegatorRoleDefinitionId)
    principalId: rotationIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(tokenContainer.id, rotationIdentity.id, storageBlobDataContributorRoleDefinitionId)
  scope: tokenContainer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleDefinitionId)
    principalId: rotationIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource targetAppContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(targetContainerApp.id, rotationIdentity.id, containerAppsContributorRoleDefinitionId)
  scope: targetContainerApp
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', containerAppsContributorRoleDefinitionId)
    principalId: rotationIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource environmentOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(managedEnvironment.id, rotationIdentity.id, containerAppsOperatorRoleDefinitionId)
  scope: managedEnvironment
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', containerAppsOperatorRoleDefinitionId)
    principalId: rotationIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource targetIdentityOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(targetContainerAppIdentity.id, rotationIdentity.id, managedIdentityOperatorRoleDefinitionId)
  scope: targetContainerAppIdentity
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', managedIdentityOperatorRoleDefinitionId)
    principalId: rotationIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource rotationJob 'Microsoft.App/jobs@2026-01-01' = {
  name: jobName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${rotationIdentity.id}': {}
    }
  }
  properties: {
    environmentId: managedEnvironmentId
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 600
      replicaRetryLimit: 2
      scheduleTriggerConfig: {
        cronExpression: '15 2 * * *'
        parallelism: 1
        replicaCompletionCount: 1
      }
    }
    template: {
      containers: [
        {
          name: 'token-rotation'
          image: 'mcr.microsoft.com/azure-cli:2.90.0'
          command: [
            '/bin/bash'
            '-c'
          ]
          args: [
            replace(rotationScript, '\r', '')
          ]
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: rotationIdentity.properties.clientId
            }
            {
              name: 'AZURE_SUBSCRIPTION_ID'
              value: subscription().subscriptionId
            }
            {
              name: 'STORAGE_ACCOUNT_NAME'
              value: storageAccountName
            }
            {
              name: 'TOKEN_CONTAINER_NAME'
              value: tokenContainerName
            }
            {
              name: 'AZURE_STORAGE_DNS_SUFFIX'
              value: environment().suffixes.storage
            }
            {
              name: 'TARGET_RESOURCE_GROUP'
              value: resourceGroup().name
            }
            {
              name: 'TARGET_CONTAINER_APP_NAME'
              value: targetContainerAppName
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
    }
  }
  dependsOn: [
    storageBlobDelegator
    storageBlobDataContributor
    targetAppContributor
    environmentOperator
    targetIdentityOperator
  ]
}

output id string = rotationJob.id
output name string = rotationJob.name
output identityPrincipalId string = rotationIdentity.properties.principalId
