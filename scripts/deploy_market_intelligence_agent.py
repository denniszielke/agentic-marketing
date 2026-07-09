"""Deploy the **Market Intelligence Agent** as an Azure AI Foundry hosted agent.

The agent consumes the ``marketing_toolbox`` (product + market insights +
persona MCP servers). Run it after the MCP servers are deployed and the toolbox
is registered:

    python -m scripts.deploy_product_mcp_server --build
    python -m scripts.deploy_market_insights_server --build
    python -m scripts.deploy_persona_mcp_server --build
    python -m scripts.register_marketing_toolbox

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT             Foundry project endpoint (required).
  AZURE_CONTAINER_REGISTRY_ENDPOINT     ACR login server for the agent image (required).
  AZURE_AI_MARKET_AGENT_NAME            Hosted agent name (default: market-intelligence-agent).
  MARKETING_TOOLBOX_NAME                Marketing toolbox (default: marketing_toolbox).
  MARKETING_MCP_URL                     Direct MCP URL override for local dev (optional).
"""

from __future__ import annotations

import os

from scripts.agent_deploy_helpers import (
    deploy_hosted_agent,
    get_client,
    load_agent_card,
    resolve_registry,
)

AGENT_CARD = load_agent_card("src/market_intelligence_agent/agentcard.json")


def deploy() -> None:
    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    if not project_endpoint:
        print("Skipping market intelligence agent deployment: AZURE_AI_PROJECT_ENDPOINT is required.")
        return
    registry = resolve_registry()

    client = get_client()
    deploy_hosted_agent(
        client,
        agent_name=os.getenv("AZURE_AI_MARKET_AGENT_NAME", "market-intelligence-agent"),
        description="Market intelligence hosted agent (marketing toolbox)",
        registry=registry,
        project_endpoint=project_endpoint,
        dockerfile_rel="src/market_intelligence_agent/Dockerfile",
        extra_env={
            "MARKETING_TOOLBOX_NAME": os.getenv("MARKETING_TOOLBOX_NAME", "marketing_toolbox"),
            # Direct MCP override (blank by default → use the toolbox).
            "MARKETING_MCP_URL": os.getenv("MARKETING_MCP_URL", ""),
        },
        agent_card=AGENT_CARD,
    )


if __name__ == "__main__":
    deploy()
