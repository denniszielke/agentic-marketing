"""Delete the marketing **Container Apps** (MCP servers + web recommender agent).

Removes the Container Apps created for the marketing demo:
  * ``product-mcp-server``       — product catalogue MCP server
  * ``persona-mcp-server``       — persona segmentation MCP server
  * ``research-mcp-server``      — innovation/research MCP server
  * ``market-insights-server``   — market intelligence MCP server (static file)
  * ``web-recommender-agent``    — the AG-UI marketing web agent

Foundry hosted agents (market intelligence, executive strategy) are removed
separately by ``scripts/delete_agents.py``.

Usage::

    python -m scripts.delete_container_apps
    python -m scripts.delete_container_apps --purge-auth   # also delete the
                                                           # <app>-mcp-auth Entra
                                                           # app registrations

Environment variables:
  AZURE_RESOURCE_GROUP        resource group containing the container apps (required)
  PRODUCT_MCP_APP_NAME        default: product-mcp-server
  PERSONA_MCP_APP_NAME        default: persona-mcp-server
  RESEARCH_MCP_APP_NAME       default: research-mcp-server
  MARKET_MCP_APP_NAME         default: market-insights-server
  WEB_RECOMMENDER_APP_NAME    default: web-recommender-agent
"""

from __future__ import annotations

import os
import subprocess
import sys

from dotenv import load_dotenv

from scripts._cli import normalize

load_dotenv(override=True)

RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP")

PRODUCT_MCP_APP = os.getenv("PRODUCT_MCP_APP_NAME", "product-mcp-server")
PERSONA_MCP_APP = os.getenv("PERSONA_MCP_APP_NAME", "persona-mcp-server")
RESEARCH_MCP_APP = os.getenv("RESEARCH_MCP_APP_NAME", "research-mcp-server")
MARKET_MCP_APP = os.getenv("MARKET_MCP_APP_NAME", "market-insights-server")
WEB_RECOMMENDER_APP = os.getenv("WEB_RECOMMENDER_APP_NAME", "web-recommender-agent")

APP_NAMES = [
    PRODUCT_MCP_APP, PERSONA_MCP_APP, RESEARCH_MCP_APP, MARKET_MCP_APP,
    WEB_RECOMMENDER_APP,
]
# MCP servers whose Entra auth app registrations can be purged with --purge-auth.
MCP_APP_NAMES = [PRODUCT_MCP_APP, PERSONA_MCP_APP, RESEARCH_MCP_APP, MARKET_MCP_APP]


def run(cmd: list[str]) -> None:
    normalized = normalize(cmd)
    print(f"$ {' '.join(normalized)}")
    subprocess.run(normalized, check=False)


def delete_all(purge_auth: bool = False) -> None:
    if not RESOURCE_GROUP:
        print("ERROR: AZURE_RESOURCE_GROUP must be set.", file=sys.stderr)
        sys.exit(1)

    for name in APP_NAMES:
        print(f"\n==> Deleting container app '{name}'")
        run([
            "az", "containerapp", "delete",
            "--name", name,
            "--resource-group", RESOURCE_GROUP,
            "--yes",
        ])

    if purge_auth:
        from scripts.auth_helpers import delete_mcp_app_registration

        print("\n==> Purging MCP Entra auth app registrations")
        for name in MCP_APP_NAMES:
            delete_mcp_app_registration(name)

    print("\nAll marketing container apps deleted.")


if __name__ == "__main__":
    delete_all(purge_auth="--purge-auth" in sys.argv)
