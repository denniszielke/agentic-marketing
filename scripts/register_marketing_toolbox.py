"""Register the **marketing_toolbox** Foundry toolbox.

Creates (or updates) the Foundry toolbox that the ``market_intelligence_agent``
and ``web_recommender_agent`` consume at runtime. It bundles three remote MCP
server Container Apps:

  * ``product-mcp-server``      (product catalogue)
  * ``market-insights-server``  (sales / margin / growth / share / forecast)
  * ``persona-mcp-server``      (customer personas)

Any agent in the project discovers the combined tool surface through the toolbox
MCP endpoint ``{project}/toolboxes/{toolbox}/mcp?api-version=v1``.

Run this after the three MCP server Container Apps are deployed.

Auth: honours ``ENTRA_AUTH_ENABLED``. When on, each server is registered with a
``project_connection_id`` (an agent-identity connection created by
``scripts.create_mcp_agent_identity_connections``) so the toolbox forwards an
authenticated token; when off, the plain server URL is registered.

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT    Foundry project endpoint (required).
  MARKETING_TOOLBOX_NAME       Toolbox name (default: marketing_toolbox).
  AZURE_RESOURCE_GROUP         used to derive MCP URLs from Container App FQDNs.
  PRODUCT_MCP_URL / PERSONA_MCP_URL / MARKET_MCP_URL   explicit MCP URLs (optional).
  PRODUCT_MCP_CONNECTION_ID / PERSONA_MCP_CONNECTION_ID / MARKET_MCP_CONNECTION_ID
                               Foundry agent-identity connection ids (Entra auth).
"""

from __future__ import annotations

import os

from azure.ai.projects.models import MCPToolboxTool

from scripts.agent_deploy_helpers import get_client, get_container_app_fqdn, get_env
from scripts.auth_helpers import entra_auth_enabled

TOOLBOX_NAME = os.getenv("MARKETING_TOOLBOX_NAME", "marketing_toolbox")

# (server_label, url_env, app_name_env, default_app, connection_env, description)
_SERVERS = [
    ("product-data", "PRODUCT_MCP_URL", "PRODUCT_MCP_APP_NAME", "product-mcp-server",
     "PRODUCT_MCP_CONNECTION_ID",
     "NorthStar Health product catalogue (internal and competitor products)."),
    ("market-insights", "MARKET_MCP_URL", "MARKET_MCP_APP_NAME", "market-insights-server",
     "MARKET_MCP_CONNECTION_ID",
     "NorthStar Health market intelligence: sales, margin, growth, market share, forecast."),
    ("persona-data", "PERSONA_MCP_URL", "PERSONA_MCP_APP_NAME", "persona-mcp-server",
     "PERSONA_MCP_CONNECTION_ID",
     "NorthStar Health customer persona segmentation."),
]


def _resolve_mcp_url(url_env: str, app_name_env: str, default_app: str) -> str:
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


def _build_tool(server_label: str, url: str, connection_env: str,
                description: str) -> MCPToolboxTool:
    tool_kwargs: dict = {
        "server_label": server_label,
        "server_url": url,
        "description": description,
        "require_approval": "never",
    }
    if entra_auth_enabled():
        connection_id = os.getenv(connection_env, "").strip()
        if connection_id:
            tool_kwargs["project_connection_id"] = connection_id
            print(f"  {server_label}: Entra auth on, connection {connection_id}")
        else:
            print(
                f"  WARN: ENTRA_AUTH_ENABLED=true but {connection_env} is unset — "
                f"calls to {server_label} will fail with 401 until a Foundry "
                "agent-identity connection is created and its id is set."
            )
    return MCPToolboxTool(**tool_kwargs)


def deploy() -> None:
    if not os.getenv("AZURE_AI_PROJECT_ENDPOINT"):
        print("Skipping toolbox registration: AZURE_AI_PROJECT_ENDPOINT is required.")
        return

    tools = []
    for label, url_env, app_env, default_app, conn_env, desc in _SERVERS:
        url = _resolve_mcp_url(url_env, app_env, default_app)
        if not url:
            print(f"Skipping '{label}': set {url_env} or AZURE_RESOURCE_GROUP so "
                  "the Container App URL can be derived.")
            continue
        print(f"  + {label}: {url}")
        tools.append(_build_tool(label, url, conn_env, desc))

    if not tools:
        print("Skipping toolbox registration: no MCP server URLs resolved.")
        return

    client = get_client()
    version = client.toolboxes.create_version(
        name=TOOLBOX_NAME,
        tools=tools,
        description="Marketing toolbox: product, market-insights and persona MCP servers.",
        metadata={"source": "agentic-marketing"},
    )
    client.toolboxes.update(name=TOOLBOX_NAME, default_version=version.version)

    project_endpoint = get_env("AZURE_AI_PROJECT_ENDPOINT")
    consumer_endpoint = (
        f"{project_endpoint.rstrip('/')}/toolboxes/{TOOLBOX_NAME}/mcp?api-version=v1"
    )
    print(f"Toolbox '{TOOLBOX_NAME}' version '{version.version}' created with {len(tools)} server(s).")
    print(f"  Consumer endpoint: {consumer_endpoint}")


if __name__ == "__main__":
    deploy()
