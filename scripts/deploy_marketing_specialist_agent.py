"""Deploy the **Marketing Specialist** as an Azure AI Foundry **prompt agent**.

This is the *specialist* half of the agent-to-agent (A2A) demo. It is a
server-side prompt agent (no container) that:

  1. grounds every answer in the marketing-toolbox MCP servers (product +
     market-insights + persona) — one MCP tool per server, each authenticated
     with the specialist's agent-identity connection — so it knows NorthStar
     Health's products, customer personas and market performance; and
  2. is exposed as an **incoming A2A endpoint** so the supervisor agent (and any
     other A2A caller) can delegate marketing tasks to it.

Why per-server MCP tools instead of the toolbox gateway endpoint
(``…/toolboxes/marketing_toolbox/mcp``): a prompt agent cannot inject the
``ai.azure.com`` bearer token that the toolbox consumer endpoint requires, so that
hop returns **401**. Wiring the same three servers directly (with their
``*_MCP_CONNECTION_ID`` agent-identity connections) gives identical grounding with
authentication the platform can perform on the agent's behalf.

Docs:
  - Enable incoming A2A: https://aka.ms/foundry-enable-a2a-endpoint
  - Marketing toolbox registration: ``scripts.register_marketing_toolbox``

Prerequisites (see the ops runbook):
  - MCP servers deployed (``deploy_product_mcp_server`` / ``deploy_market_insights_server``
    / ``deploy_persona_mcp_server``) and the toolbox registered
    (``register_marketing_toolbox``).
  - When ``ENTRA_AUTH_ENABLED=true`` (default), the agent-identity connections
    (``create_mcp_agent_identity_connections``) so the toolbox can forward an
    authenticated token to the MCP servers.
  - ``az login`` with rights to create app-role assignments.

Run::

    python -m scripts.deploy_marketing_specialist_agent

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT            Foundry project endpoint (required).
  AZURE_AI_MODEL_DEPLOYMENT_NAME       Model deployment (default: gpt-4.1-mini).
  AZURE_AI_SPECIALIST_AGENT_NAME       Prompt agent name (default: marketing-specialist-agent).
  AZURE_RESOURCE_GROUP                 Used to derive each MCP server URL from its Container App FQDN.
  PRODUCT_MCP_URL / MARKET_MCP_URL / PERSONA_MCP_URL          Explicit MCP URLs (optional).
  PRODUCT_MCP_CONNECTION_ID / MARKET_MCP_CONNECTION_ID / PERSONA_MCP_CONNECTION_ID
                                       Agent-identity connection ids (used when ENTRA_AUTH_ENABLED=true).
"""

from __future__ import annotations

import os
import sys

from azure.ai.projects.models import MCPTool

from scripts.agent_deploy_helpers import (
    get_client,
    get_container_app_fqdn,
    get_env,
    load_agent_card,
)
from scripts.auth_helpers import entra_auth_enabled
from scripts.grant_agent_identity_mcp_role import main as grant_mcp_role_main
from scripts.prompt_agent_helpers import (
    create_prompt_agent_version,
    discover_agent_identity_object_id,
    enable_incoming_a2a,
)

AGENT_CARD = load_agent_card("src/marketing_specialist_agent/agentcard.json")

INSTRUCTIONS = """\
You are the Marketing Specialist for NorthStar Health, a European consumer
healthcare company operating in Germany, the UK and the Nordics across four
categories: Vitamins & Supplements, Gut Health, Weight Management and Home
Diagnostics.

You have grounding tools from the marketing toolbox:
  - product_data tools: the internal and competitor product catalogue (list/search
    products, compare positioning, inspect pricing tiers and metadata);
  - market_insights tools: sales, revenue, gross margin, growth rates, market
    share and 2026-2028 forecasts by market, category, product and brand;
  - persona_data tools: customer persona segmentation (search personas, filter by
    market/category/interest, inspect behaviour and spend).

Operating principles:
  1. Always ground quantitative claims (growth, share, margin, price, sales) in
     a tool result — never invent figures.
  2. Call the marketing tools whenever a question touches products, personas or
     market performance; do not answer marketing questions from memory.
  3. Be concise and decision-ready: lead with the answer, then the supporting
     evidence, then a suggested next step.
  4. You may be called by another agent that hands you a specific task. Treat the
     incoming message as the task, complete it end to end, and return a
     self-contained answer.
"""


# The marketing toolbox is composed of these three MCP servers. A prompt agent
# consumes them directly (each with its agent-identity connection) rather than
# through the toolbox gateway endpoint, which a prompt agent cannot authenticate
# to (that hop returns 401).
# (server_label, url_env, app_name_env, default_app, connection_env)
_SERVERS = [
    ("product_data", "PRODUCT_MCP_URL", "PRODUCT_MCP_APP_NAME",
     "product-mcp-server", "PRODUCT_MCP_CONNECTION_ID"),
    ("market_insights", "MARKET_MCP_URL", "MARKET_MCP_APP_NAME",
     "market-insights-server", "MARKET_MCP_CONNECTION_ID"),
    ("persona_data", "PERSONA_MCP_URL", "PERSONA_MCP_APP_NAME",
     "persona-mcp-server", "PERSONA_MCP_CONNECTION_ID"),
]


def _resolve_mcp_url(url_env: str, app_name_env: str, default_app: str) -> str:
    """Resolve an MCP server URL (explicit env, else derived from its Container App FQDN)."""
    url = os.getenv(url_env, "").strip()
    if url:
        return url
    resource_group = os.getenv("AZURE_RESOURCE_GROUP", "").strip()
    app_name = os.getenv(app_name_env, default_app)
    if resource_group:
        fqdn = get_container_app_fqdn(resource_group, app_name)
        if fqdn:
            return f"https://{fqdn}/mcp"
    return ""


def _resolve_connection_id(client, connection_env: str) -> str:
    """Resolve a ``*_MCP_CONNECTION_ID`` (a connection name) to its full resource id."""
    name = os.getenv(connection_env, "").strip()
    if not name:
        return ""
    try:
        return client.connections.get(name).id or name
    except Exception:
        return name


def _build_marketing_tools(client) -> list[MCPTool]:
    """Build one MCP tool per marketing-toolbox server (product, market, persona)."""
    auth_on = entra_auth_enabled()
    tools: list[MCPTool] = []
    for label, url_env, app_env, default_app, conn_env in _SERVERS:
        url = _resolve_mcp_url(url_env, app_env, default_app)
        if not url:
            print(f"  skip '{label}': set {url_env} or AZURE_RESOURCE_GROUP so the "
                  "Container App URL can be derived.")
            continue
        kwargs: dict = {
            "server_label": label,
            "server_url": url,
            "require_approval": "never",
        }
        if auth_on:
            conn_id = _resolve_connection_id(client, conn_env)
            if conn_id:
                kwargs["project_connection_id"] = conn_id
                print(f"  + {label}: {url} (connection {os.getenv(conn_env)})")
            else:
                print(f"  WARN: ENTRA_AUTH_ENABLED=true but {conn_env} is unset — calls "
                      f"to {label} will 401. Run "
                      "scripts.create_mcp_agent_identity_connections first.")
        else:
            print(f"  + {label}: {url} (anonymous)")
        tools.append(MCPTool(**kwargs))
    return tools


def deploy() -> None:
    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    if not project_endpoint:
        print("Skipping specialist deployment: AZURE_AI_PROJECT_ENDPOINT is required.")
        return

    model = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")
    agent_name = os.getenv("AZURE_AI_SPECIALIST_AGENT_NAME", "marketing-specialist-agent")

    print(f"==> Deploying marketing specialist prompt agent '{agent_name}'")
    print(f"    Model: {model}")
    print("    Grounding (marketing toolbox servers):")

    client = get_client()
    tools = _build_marketing_tools(client)
    if not tools:
        print("ERROR: no marketing MCP servers resolved; cannot ground the specialist.",
              file=sys.stderr)
        sys.exit(1)

    create_prompt_agent_version(
        client,
        agent_name=agent_name,
        description="Marketing specialist prompt agent grounded in the marketing toolbox servers.",
        model=model,
        instructions=INSTRUCTIONS,
        tools=tools,
    )

    # Expose the specialist as an incoming A2A endpoint so the supervisor can call it.
    enable_incoming_a2a(
        client,
        project_endpoint=project_endpoint,
        agent_name=agent_name,
        agent_card=AGENT_CARD,
    )

    # When the MCP servers enforce Entra auth, the toolbox forwards a token minted
    # for THIS agent's Entra Agent Identity, so that identity needs Mcp.Invoke on
    # each MCP app registration. (Each deploy can rotate the identity — re-run.)
    if entra_auth_enabled():
        print("\n==> Granting the specialist's agent identity Mcp.Invoke on the MCP servers")
        obj_id = discover_agent_identity_object_id(agent_name)
        if obj_id:
            print(f"    Agent identity: {obj_id}")
            grant_mcp_role_main(["--agent-id", obj_id])
        else:
            print(
                "    WARN: could not discover the specialist's Entra Agent Identity yet. "
                "It can take a moment to appear. Re-run:\n"
                "      python -m scripts.grant_agent_identity_mcp_role --agent-id <object-id>\n"
                "    (find the object id in the Foundry portal or the 401 error detail)."
            )
    else:
        print("\nENTRA_AUTH_ENABLED=false — MCP servers are anonymous; no Mcp.Invoke grant needed.")

    print(
        f"\nDone. The supervisor can now connect to this specialist's A2A endpoint:\n"
        f"  {get_env('AZURE_AI_PROJECT_ENDPOINT').rstrip('/')}/agents/{agent_name}"
        "/endpoint/protocols/a2a\n"
        "Next: python -m scripts.deploy_supervisor_agent"
    )


if __name__ == "__main__":
    deploy()
