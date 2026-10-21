// Gantry on Azure Container Apps: one container serves the page, its API, the live match feed and the MCP endpoint.
// The app signs in to Microsoft Foundry and Azure AI Speech with its own managed identity: no keys anywhere.
//
//   az deployment group create -g rg-gantry -f infra/main.bicep -p foundryName=<your Foundry resource>
//   (scripts/deploy.ps1 builds the image and does the rest)

@description('Where everything runs')
param location string = resourceGroup().location

@description('Name stem for the resources')
param name string = 'gantry'

@description('The existing Microsoft Foundry (AIServices) resource the crew uses, in this resource group')
param foundryName string

@description('The Foundry project inside it')
param projectName string = 'gantry'

@description('Container image, e.g. <registry>.azurecr.io/gantry:1')
param image string = ''

@description('Azure AI Speech region of the Foundry resource')
param speechRegion string = location

@description('Keep one copy always running during judging, so nobody waits for a cold start')
param minReplicas int = 1

var registryName = toLower(replace('${name}${uniqueString(resourceGroup().id)}', '-', ''))

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${name}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: json('0.5') }
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${name}-insights'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${name}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryName
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        // a viewer's WebSocket stays on the copy that holds its broadcast
        stickySessions: { affinity: 'sticky' }
      }
      registries: [
        { server: registry.properties.loginServer, identity: 'system' }
      ]
    }
    template: {
      containers: [
        {
          name: 'gantry'
          image: empty(image) ? 'mcr.microsoft.com/k8se/quickstart:latest' : image
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'GANTRY_PUBLIC', value: '1' }
            { name: 'AZURE_AI_ENDPOINT', value: foundry.properties.endpoint }
            { name: 'AZURE_AI_PROJECT_ENDPOINT', value: 'https://${foundryName}.services.ai.azure.com/api/projects/${projectName}' }
            { name: 'AZURE_SPEECH_REGION', value: speechRegion }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
          ]
          probes: [
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 30 }
            { type: 'Readiness', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 10 }
          ]
        }
      ]
      // one copy: a broadcast's live state lives in memory
      scale: { minReplicas: minReplicas, maxReplicas: 1 }
    }
  }
}

// the app's identity may call the models and the voices, and pull its own image; nothing else
resource foundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, app.id, 'foundry-user')
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource cognitiveUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, app.id, 'cognitive-services-user')
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, app.id, 'acr-pull')
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output url string = 'https://${app.properties.configuration.ingress.fqdn}'
output registry string = registry.properties.loginServer
