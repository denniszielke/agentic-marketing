"""Register the **WorkIQ MCP server** as a Foundry toolbox.

Creates (or updates) a Foundry toolbox backed by the Microsoft Agent 365 WorkIQ
MCP server. This gives the ``marketing_meeting_prep_agent`` access to the
signed-in marketer's calendar (in their own user context) so it can read an
upcoming meeting's title, agenda and attendees and prepare a briefing.

Run this after ``azd up`` has provisioned the Foundry project and before
deploying the marketing meeting prep agent that consumes WorkIQ.

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT   Foundry project endpoint (required).
  WORKIQ_TOOLBOX_NAME         Toolbox name (default: workiq-tools).
  WORKIQ_MCP_URL              Full WorkIQ MCP server URL. If set it is used
                              verbatim (advanced override); otherwise the URL is
                              built from the base host, tenant id and server name
                              below.
  WORKIQ_MCP_SERVER           WorkIQ MCP server name (default: mcp_CalendarTools).
  WORKIQ_SCOPE                Delegated scope the OAuth connection requests
                              (default: McpServers.Calendar.All).
  WORKIQ_TENANT_ID            Entra tenant id used in the MCP URL path. Falls
                              back to AZURE_TENANT_ID, then to the signed-in
                              ``az account show`` tenant.
  WORKIQ_CONNECTION_ID        Foundry connection ID (or name) that provides the
                              OAuth identity-passthrough token for the WorkIQ MCP
                              server. See scripts/setup_workiq_oauth_app.py.
  WORKIQ_CONNECTION_NAME      Foundry connection name to reference (default:
                              workiq-connection) when WORKIQ_CONNECTION_ID is
                              unset. If neither resolves to an existing
                              connection the toolbox is registered without one
                              (calls will fail auth until a connection is set).
"""

from __future__ import annotations

import os
import subprocess
from scripts._cli import normalize

from azure.ai.projects.models import MCPToolboxTool

from scripts.agent_deploy_helpers import get_client, get_env

# Microsoft Agent 365 WorkIQ MCP server (from the A365 MCP server catalog).
# The Agent 365 tooling gateway requires the tenant id in the URL path:
#   https://agent365.svc.cloud.microsoft/agents/tenants/{tenantId}/servers/{server}
# Omitting the /tenants/{tenantId}/ segment makes the remote server reject
# tools/list with HTTP 400 EndpointInvalid / TenantIdInvalid.
_WORKIQ_HOST = "https://agent365.svc.cloud.microsoft"
# NB: there is no "mcp_WorkIQTools" server / "McpServers.WorkIQ.All" scope — the
# Agent 365 Tools app exposes granular capabilities. Default to Calendar (the
# meeting prep agent reads upcoming meetings); override for Mail/OneDrive/etc.
_DEFAULT_WORKIQ_SERVER = "mcp_CalendarTools"
_WORKIQ_SCOPE = os.getenv("WORKIQ_SCOPE", "McpServers.Calendar.All").strip()

TOOLBOX_NAME = os.getenv("WORKIQ_TOOLBOX_NAME", "workiq-tools")
CONNECTION_NAME = os.getenv("WORKIQ_CONNECTION_NAME", "workiq-connection").strip()


def _resolve_tenant_id() -> str:
    """Resolve the Entra tenant id for the WorkIQ MCP URL path."""
    tenant = (
        os.getenv("WORKIQ_TENANT_ID", "").strip()
        or os.getenv("AZURE_TENANT_ID", "").strip()
    )
    if tenant:
        return tenant
    result = subprocess.run(
        normalize(["az", "account", "show", "--query", "tenantId", "-o", "tsv"]),
        check=False,
        capture_output=True,
        text=True,
    )
    tenant = result.stdout.strip()
    if not tenant:
        raise RuntimeError(
            "Could not resolve the Entra tenant id. Set WORKIQ_TENANT_ID (or "
            "AZURE_TENANT_ID) in ./.env, or sign in with 'az login'."
        )
    return tenant


def _resolve_workiq_url() -> str:
    """Build the tenant-scoped WorkIQ MCP URL (or use WORKIQ_MCP_URL verbatim)."""
    override = os.getenv("WORKIQ_MCP_URL", "").strip()
    if override:
        return override
    tenant = _resolve_tenant_id()
    server = os.getenv("WORKIQ_MCP_SERVER", "").strip() or _DEFAULT_WORKIQ_SERVER
    return f"{_WORKIQ_HOST}/agents/tenants/{tenant}/servers/{server}"


def _resolve_connection_id(client) -> str:
    """Resolve the OAuth connection to reference from the MCP tool.

    Prefers an explicit ``WORKIQ_CONNECTION_ID``. Otherwise looks up the
    connection named ``WORKIQ_CONNECTION_NAME`` (default ``workiq-connection``,
    created via the Foundry OAuth identity-passthrough setup) and returns its id.
    Returns "" when no connection is configured yet.
    """
    explicit = os.getenv("WORKIQ_CONNECTION_ID", "").strip()
    if explicit:
        return explicit
    if not CONNECTION_NAME:
        return ""
    try:
        connection = client.connections.get(name=CONNECTION_NAME)
    except Exception:  # noqa: BLE001 — connection simply not created yet
        return ""
    return getattr(connection, "id", None) or getattr(connection, "name", "") or ""


def deploy() -> None:
    if not os.getenv("AZURE_AI_PROJECT_ENDPOINT"):
        print("Skipping toolbox registration: AZURE_AI_PROJECT_ENDPOINT is required.")
        return

    workiq_url = _resolve_workiq_url()
    client = get_client()
    connection_id = _resolve_connection_id(client)

    tool_kwargs: dict = {
        "server_label": "workiq",
        "server_url": workiq_url,
        "description": (
            "Microsoft Agent 365 WorkIQ MCP server. Provides access to the "
            "signed-in user's calendar in their own user context: list upcoming "
            "meetings and inspect a meeting's subject, agenda and attendees. "
            f"Required OAuth scope: {_WORKIQ_SCOPE}."
        ),
        "require_approval": "never",
    }
    if connection_id:
        tool_kwargs["project_connection_id"] = connection_id

    tool = MCPToolboxTool(**tool_kwargs)

    version = client.toolboxes.create_version(
        name=TOOLBOX_NAME,
        tools=[tool],
        description=(
            "WorkIQ toolbox backed by the Microsoft Agent 365 WorkIQ MCP server. "
            "Exposes calendar capabilities to the marketing meeting prep agent."
        ),
        metadata={"source": "agent365-mcp-workiq", "scope": _WORKIQ_SCOPE},
    )
    client.toolboxes.update(name=TOOLBOX_NAME, default_version=version.version)

    project_endpoint = get_env("AZURE_AI_PROJECT_ENDPOINT")
    consumer_endpoint = (
        f"{project_endpoint.rstrip('/')}/toolboxes/{TOOLBOX_NAME}/mcp?api-version=v1"
    )
    print(f"Toolbox '{TOOLBOX_NAME}' version '{version.version}' created.")
    print(f"  WorkIQ MCP server: {workiq_url}")
    if connection_id:
        print(f"  OAuth connection:  {connection_id}")
    else:
        print(
            "  Note: no WorkIQ OAuth connection resolved. Create one with "
            "OAuth identity passthrough\n"
            "  (see scripts/setup_workiq_oauth_app.py), then re-run with "
            "WORKIQ_CONNECTION_NAME set.\n"
            "  Until then WorkIQ tool calls fail with 401 Unauthorized."
        )
    print(f"  Consumer endpoint: {consumer_endpoint}")


if __name__ == "__main__":
    deploy()
