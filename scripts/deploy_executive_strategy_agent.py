"""Deploy the **Executive Strategy Agent** as an Azure AI Foundry hosted agent.

The virtual Chief Strategy Officer. It consumes the ``strategy_toolbox``
(product + market insights + persona + research MCP servers) and also the
``marketing_toolbox``. Run it after the MCP servers are deployed and both
toolboxes are registered:

    python -m scripts.register_marketing_toolbox
    python -m scripts.register_strategy_toolbox

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT             Foundry project endpoint (required).
  AZURE_CONTAINER_REGISTRY_ENDPOINT     ACR login server for the agent image (required).
  AZURE_AI_STRATEGY_AGENT_NAME          Hosted agent name (default: executive-strategy-agent).
  STRATEGY_TOOLBOX_NAME                 Strategy toolbox (default: strategy_toolbox).
  MARKETING_TOOLBOX_NAME                Marketing toolbox (default: marketing_toolbox).
  EXECUTIVE_MARKETING_TOOLBOX_ENABLED   Attach the marketing toolbox (default: true).
  STRATEGY_MCP_URL / MARKETING_MCP_URL  Direct MCP URL overrides for local dev (optional).
"""

from __future__ import annotations

import os

from scripts.agent_deploy_helpers import (
    deploy_hosted_agent,
    get_client,
    load_agent_card,
    resolve_registry,
)

AGENT_CARD = load_agent_card("src/executive_strategy_agent/agentcard.json")


def deploy() -> None:
    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    if not project_endpoint:
        print("Skipping executive strategy agent deployment: AZURE_AI_PROJECT_ENDPOINT is required.")
        return
    registry = resolve_registry()

    client = get_client()
    deploy_hosted_agent(
        client,
        agent_name=os.getenv("AZURE_AI_STRATEGY_AGENT_NAME", "executive-strategy-agent"),
        description="Executive strategy hosted agent (strategy + marketing toolboxes)",
        registry=registry,
        project_endpoint=project_endpoint,
        dockerfile_rel="src/executive_strategy_agent/Dockerfile",
        extra_env={
            "STRATEGY_TOOLBOX_NAME": os.getenv("STRATEGY_TOOLBOX_NAME", "strategy_toolbox"),
            "MARKETING_TOOLBOX_NAME": os.getenv("MARKETING_TOOLBOX_NAME", "marketing_toolbox"),
            "EXECUTIVE_MARKETING_TOOLBOX_ENABLED": os.getenv(
                "EXECUTIVE_MARKETING_TOOLBOX_ENABLED", "true"
            ),
            # Direct MCP overrides (blank by default → use the toolboxes).
            "STRATEGY_MCP_URL": os.getenv("STRATEGY_MCP_URL", ""),
            "MARKETING_MCP_URL": os.getenv("MARKETING_MCP_URL", ""),
        },
        agent_card=AGENT_CARD,
    )


if __name__ == "__main__":
    deploy()
