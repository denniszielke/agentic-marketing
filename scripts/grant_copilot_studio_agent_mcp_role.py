"""Grant the ``Mcp.Invoke`` app role to a **Copilot Studio agent identity** so it
can call the marketing MCP servers (product, persona, market-insights and
research) using its own Entra identity — no client secret.

A Copilot Studio agent authenticates to an MCP server with a token whose
audience is the server's ``api://<appId>``. Entra only issues that token when the
calling identity holds the ``Mcp.Invoke`` app role on the MCP resource. This
script assigns that role, on all four marketing MCP servers, to the Copilot
Studio agent's Entra **service principal**.

Unlike ``grant_agent_identity_mcp_role`` (which auto-discovers the *hosted*
Foundry agents), this script targets an identity **you supply** — the Copilot
Studio agent's object id, application (client) id, or display name.

What it does:
  1. Resolve the Copilot Studio agent's service-principal object id — from
     ``--agent-id`` / ``--app-id`` / ``--agent-name`` /
     ``COPILOT_STUDIO_AGENT_IDS`` (an object id, appId or display name all work).
  2. Resolve the ``api://<appId>`` audience of each MCP server's app
     registration (``<app>-mcp-auth``).
  3. Grant ``Mcp.Invoke`` on each MCP app registration to the agent identity
     (idempotent).

Requires: Azure CLI signed in (``az login``) with rights to create app role
assignments, and the MCP servers deployed with ``ENTRA_AUTH_ENABLED=true``.

Usage::

    # by service-principal object id (repeatable)
    python -m scripts.grant_copilot_studio_agent_mcp_role --agent-id <OBJECT_ID>

    # by application (client) id
    python -m scripts.grant_copilot_studio_agent_mcp_role --app-id <APP_ID>

    # by display name
    python -m scripts.grant_copilot_studio_agent_mcp_role --agent-name "My Copilot Agent"

    # grant on a subset of servers only
    python -m scripts.grant_copilot_studio_agent_mcp_role --agent-id <OBJECT_ID> \\
        --only product --only persona

Environment variables:
  COPILOT_STUDIO_AGENT_IDS            Comma-separated agent identifiers (object
                                      ids, appIds or display names) to grant.
  PRODUCT_MCP_APP_NAME / MARKET_MCP_APP_NAME / PERSONA_MCP_APP_NAME /
  RESEARCH_MCP_APP_NAME               Container App names (defaults below).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from scripts._cli import normalize

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=True)
load_dotenv(override=False)

from scripts.auth_helpers import (  # noqa: E402  (after dotenv load)
    entra_auth_enabled,
    grant_mcp_role_to_principal,
    resolve_mcp_audience,
)

# The four marketing MCP servers a Copilot Studio agent may call. Keys are the
# ``--only`` labels; values are (env var, default Container App name).
_MCP_SERVERS: dict[str, tuple[str, str]] = {
    "product": ("PRODUCT_MCP_APP_NAME", "product-mcp-server"),
    "market": ("MARKET_MCP_APP_NAME", "market-insights-server"),
    "persona": ("PERSONA_MCP_APP_NAME", "persona-mcp-server"),
    "research": ("RESEARCH_MCP_APP_NAME", "research-mcp-server"),
}


def _az(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(normalize(["az", *args]), check=False, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"az {' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def _resolve_sp_object_id(identifier: str) -> str:
    """Resolve a Copilot Studio agent identifier to its service-principal object id.

    ``identifier`` may be a service-principal object id, an application (client)
    id or a display name. Returns "" when nothing matches.
    """
    identifier = identifier.strip()
    if not identifier:
        return ""

    # `az ad sp show --id` accepts an object id, appId or identifier URI.
    result = _az("ad", "sp", "show", "--id", identifier,
                 "--query", "id", "-o", "tsv", check=False)
    obj_id = result.stdout.strip()
    if obj_id:
        return obj_id

    # Fall back to a display-name lookup.
    result = _az("ad", "sp", "list", "--display-name", identifier,
                 "--query", "[0].id", "-o", "tsv", check=False)
    return result.stdout.strip()


def _resolve_agent_object_ids(identifiers: list[str]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for identifier in identifiers:
        obj_id = _resolve_sp_object_id(identifier)
        if not obj_id:
            print(
                f"  WARN: could not resolve a service principal for '{identifier}'. "
                "Pass its object id, application (client) id, or exact display name."
            )
            continue
        if obj_id in seen:
            continue
        seen.add(obj_id)
        if obj_id != identifier:
            print(f"  Resolved '{identifier}' → service principal {obj_id}")
        resolved.append(obj_id)
    return resolved


def _resolve_mcp_apps(labels: list[str]) -> list[tuple[str, str]]:
    apps: list[tuple[str, str]] = []
    for label in labels:
        env_var, default = _MCP_SERVERS[label]
        app_name = os.getenv(env_var, default)
        audience = resolve_mcp_audience(app_name)
        if audience:
            apps.append((label, audience.removeprefix("api://")))
        else:
            print(
                f"  WARN: no '{app_name}-mcp-auth' app registration found for the "
                f"{label} MCP server. Deploy it with ENTRA_AUTH_ENABLED=true first."
            )
    return apps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-id", dest="agent_ids", action="append", default=[],
        metavar="OBJECT_ID",
        help="Copilot Studio agent service-principal object id (repeatable).",
    )
    parser.add_argument(
        "--app-id", dest="app_ids", action="append", default=[],
        metavar="APP_ID",
        help="Copilot Studio agent application (client) id (repeatable).",
    )
    parser.add_argument(
        "--agent-name", dest="agent_names", action="append", default=[],
        metavar="DISPLAY_NAME",
        help="Copilot Studio agent display name to look up (repeatable).",
    )
    parser.add_argument(
        "--only", dest="only", action="append", default=[],
        choices=sorted(_MCP_SERVERS),
        help="Grant on a subset of MCP servers only (repeatable). Default: all four.",
    )
    args = parser.parse_args(argv)

    if not entra_auth_enabled():
        print(
            "NOTE: ENTRA_AUTH_ENABLED is false — the MCP servers run anonymously, "
            "so no Mcp.Invoke grant is required. Continuing anyway."
        )

    env_ids = [
        i.strip()
        for i in os.getenv("COPILOT_STUDIO_AGENT_IDS", "").split(",")
        if i.strip()
    ]
    identifiers = [*args.agent_ids, *args.app_ids, *args.agent_names, *env_ids]
    if not identifiers:
        print(
            "\nERROR: no Copilot Studio agent identity supplied. Pass its object "
            "id (--agent-id), application id (--app-id) or display name "
            "(--agent-name), or set COPILOT_STUDIO_AGENT_IDS in ./.env.",
            file=sys.stderr,
        )
        return 1

    print(f"==> Resolving Copilot Studio agent identities: {', '.join(identifiers)}")
    agent_ids = _resolve_agent_object_ids(identifiers)
    if not agent_ids:
        print(
            "\nERROR: none of the supplied identifiers resolved to a service "
            "principal.",
            file=sys.stderr,
        )
        return 1

    labels = args.only or list(_MCP_SERVERS)
    apps = _resolve_mcp_apps(labels)
    if not apps:
        print(
            "\nERROR: no MCP app registrations resolved. Deploy the MCP servers "
            "with ENTRA_AUTH_ENABLED=true first.",
            file=sys.stderr,
        )
        return 1

    for agent_id in agent_ids:
        print(f"\n==> Granting Mcp.Invoke to Copilot Studio agent {agent_id}")
        for label, app_id in apps:
            print(f"  {label} MCP ({app_id}):")
            grant_mcp_role_to_principal(app_id, agent_id)

    print(
        "\nDone. App role assignments can take 2–5 minutes to propagate. Configure "
        "the Copilot Studio agent to request a token for each MCP server's "
        "api://<appId> audience (or api://<appId>/.default)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
