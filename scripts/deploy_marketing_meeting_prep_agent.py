"""Deploy the **Marketing Meeting Prep Agent** as an Azure AI Foundry hosted agent.

The agent consumes two toolboxes:
  * ``marketing_toolbox`` — product + market insights + persona MCP servers
    (authenticated with the hosted agent's Entra Agent Identity).
  * ``workiq-tools``      — the Microsoft Agent 365 WorkIQ calendar MCP server
    (authenticated with OAuth identity passthrough, so the calendar is read in
    the signed-in user's own context).

Run it after the MCP servers are deployed, the marketing toolbox is registered,
and the WorkIQ toolbox + OAuth connection are created:

    python -m scripts.deploy_product_mcp_server --build
    python -m scripts.deploy_market_insights_server --build
    python -m scripts.deploy_persona_mcp_server --build
    python -m scripts.register_marketing_toolbox
    python -m scripts.create_workiq_connection            # WorkIQ conn + toolbox
    python -m scripts.deploy_marketing_meeting_prep_agent

After the agent is deployed, grant its Entra Agent Identity the ``Mcp.Invoke``
role on the marketing MCP servers so the marketing toolbox authenticates:

    python -m scripts.grant_agent_identity_mcp_role

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT             Foundry project endpoint (required).
  AZURE_CONTAINER_REGISTRY_ENDPOINT     ACR login server for the agent image (required).
  AZURE_AI_MEETING_PREP_AGENT_NAME      Hosted agent name (default: marketing-meeting-prep-agent).
  MARKETING_TOOLBOX_NAME                Marketing toolbox (default: marketing_toolbox).
  WORKIQ_TOOLBOX_NAME                   WorkIQ toolbox (default: workiq-tools).
  MARKETING_MCP_URL / WORKIQ_MCP_URL    Direct MCP URL overrides for local dev (optional).
"""

from __future__ import annotations

import os

from scripts.agent_deploy_helpers import (
    deploy_hosted_agent,
    get_client,
    load_agent_card,
    resolve_registry,
)

AGENT_CARD = load_agent_card("src/marketing_meeting_prep_agent/agentcard.json")


def deploy() -> None:
    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    if not project_endpoint:
        print("Skipping marketing meeting prep agent deployment: AZURE_AI_PROJECT_ENDPOINT is required.")
        return
    registry = resolve_registry()

    client = get_client()
    deploy_hosted_agent(
        client,
        agent_name=os.getenv("AZURE_AI_MEETING_PREP_AGENT_NAME", "marketing-meeting-prep-agent"),
        description="Marketing meeting prep hosted agent (marketing toolbox + WorkIQ calendar)",
        registry=registry,
        project_endpoint=project_endpoint,
        dockerfile_rel="src/marketing_meeting_prep_agent/Dockerfile",
        extra_env={
            "MARKETING_TOOLBOX_NAME": os.getenv("MARKETING_TOOLBOX_NAME", "marketing_toolbox"),
            "WORKIQ_TOOLBOX_NAME": os.getenv("WORKIQ_TOOLBOX_NAME", "workiq-tools"),
            # Direct MCP overrides (blank by default → use the toolboxes).
            "MARKETING_MCP_URL": os.getenv("MARKETING_MCP_URL", ""),
            "WORKIQ_MCP_URL": os.getenv("WORKIQ_MCP_URL", ""),
        },
        agent_card=AGENT_CARD,
    )


if __name__ == "__main__":
    deploy()
