param botName string
param displayName string
param msaAppId string
param endpoint string
param botServiceSku string = 'F0'

// Bot Service resource — relays Microsoft 365 (Teams, Outlook, etc.)
// interactions to the agent's activityProtocol endpoint. The appId is the
// agent's blueprint client id.
resource botService 'Microsoft.BotService/botServices@2022-09-15' = {
  name: botName
  kind: 'azurebot'
  location: 'global'
  sku: {
    name: botServiceSku
  }
  properties: {
    displayName: displayName
    endpoint: endpoint
    msaAppId: msaAppId
    msaAppTenantId: tenant().tenantId
    msaAppType: 'SingleTenant'
  }
}

// Connect the bot service to Microsoft Teams.
resource botServiceMsTeamsChannel 'Microsoft.BotService/botServices/channels@2021-03-01' = {
  parent: botService
  location: 'global'
  name: 'MsTeamsChannel'
  properties: {
    channelName: 'MsTeamsChannel'
  }
}

// Connect the bot to the Microsoft 365 Extensions channel — required to publish
// and hire the agent as an Agent 365 digital worker in Teams / M365 Copilot
// (see the hosted-agent-permissions "Azure Bot Service setup" doc, which calls
// for configuring the Teams AND Microsoft 365 Extensions channels).
resource botServiceM365ExtensionsChannel 'Microsoft.BotService/botServices/channels@2022-09-15' = {
  parent: botService
  location: 'global'
  name: 'M365Extensions'
  properties: {
    channelName: 'M365Extensions'
  }
}

output botName string = botService.name
