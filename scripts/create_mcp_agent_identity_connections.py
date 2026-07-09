"""Create the Foundry **agent-identity** connections for the marketing MCP toolboxes.

Automates the ``azd ai connection create ... --auth-type agentic-identity`` steps
so the marketing / strategy toolboxes authenticate to their MCP servers with the
hosted agents' **Entra Agent Identity** (no client secret). For each server it
creates a ``remote-tool`` connection whose target is the MCP ``/mcp`` URL and
whose audience is the server's ``api://<appId>``.

The agent identity still needs the ``Mcp.Invoke`` app role on each MCP app
registration — grant it with ``scripts.grant_agent_identity_mcp_role`` (or pass
``--grant`` here to do both in one run).

Prerequisites:
  - ``az login`` and the MCP servers deployed with ``ENTRA_AUTH_ENABLED=true``.
  - The Foundry azd extension: ``azd ext install microsoft.foundry``.

Usage::

    python -m scripts.create_mcp_agent_identity_connections            # all servers
    python -m scripts.create_mcp_agent_identity_connections --grant     # + grant role
    python -m scripts.create_mcp_agent_identity_connections --only product

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT       Foundry project endpoint (required).
  AZURE_RESOURCE_GROUP            Used to derive an MCP URL when *_MCP_URL is unset.
  PRODUCT_MCP_URL / MARKET_MCP_URL / PERSONA_MCP_URL / RESEARCH_MCP_URL   (optional).
  *_MCP_APP_NAME                  Container App names (defaults below).
  *_MCP_CONNECTION_NAME           Connection names to create (defaults below).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from scripts._cli import normalize

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=True)
load_dotenv(override=False)

import os  # noqa: E402  (after dotenv load)

from scripts.agent_deploy_helpers import get_container_app_fqdn  # noqa: E402
from scripts.auth_helpers import entra_auth_enabled, resolve_mcp_audience  # noqa: E402


# label -> (url_env, app_env, app_default, conn_env, conn_default)
_SERVERS = {
    "product": (
        "PRODUCT_MCP_URL", "PRODUCT_MCP_APP_NAME", "product-mcp-server",
        "PRODUCT_MCP_CONNECTION_NAME", "product-mcp-agentid",
    ),
    "market": (
        "MARKET_MCP_URL", "MARKET_MCP_APP_NAME", "market-insights-server",
        "MARKET_MCP_CONNECTION_NAME", "market-mcp-agentid",
    ),
    "persona": (
        "PERSONA_MCP_URL", "PERSONA_MCP_APP_NAME", "persona-mcp-server",
        "PERSONA_MCP_CONNECTION_NAME", "persona-mcp-agentid",
    ),
    "research": (
        "RESEARCH_MCP_URL", "RESEARCH_MCP_APP_NAME", "research-mcp-server",
        "RESEARCH_MCP_CONNECTION_NAME", "research-mcp-agentid",
    ),
}

# label -> the ./.env variable the register scripts read for the connection id.
_CONN_ENV = {
    "product": "PRODUCT_MCP_CONNECTION_ID",
    "market": "MARKET_MCP_CONNECTION_ID",
    "persona": "PERSONA_MCP_CONNECTION_ID",
    "research": "RESEARCH_MCP_CONNECTION_ID",
}


def _resolve_mcp_url(url_env: str, app_env: str, app_default: str) -> str:
    url = os.getenv(url_env, "").strip()
    if url:
        return url
    resource_group = os.getenv("AZURE_RESOURCE_GROUP", "").strip()
    app_name = os.getenv(app_env, app_default)
    if resource_group:
        fqdn = get_container_app_fqdn(resource_group, app_name)
        if fqdn:
            return f"https://{fqdn}/mcp"
    return ""


def _azd(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(normalize(["azd", *args]), check=False, capture_output=True, text=True)


def _ensure_azd() -> bool:
    if shutil.which("azd") is None:
        print(
            "ERROR: the Azure Developer CLI (azd) is not installed. Install it, then "
            "run 'azd ext install microsoft.foundry'.",
            file=sys.stderr,
        )
        return False
    if _azd("ai", "-h").returncode != 0:
        print(
            "ERROR: the Foundry azd extension is missing. Install it with "
            "'azd ext install microsoft.foundry'.",
            file=sys.stderr,
        )
        return False
    return True


def _create_connection(name: str, target: str, audience: str) -> bool:
    print(f"==> Creating connection '{name}' -> {target} (audience {audience})")
    result = _azd(
        "ai", "connection", "create", name,
        "--kind", "remote-tool",
        "--target", target,
        "--auth-type", "agentic-identity",
        "--audience", audience,
        "--no-prompt",
    )
    if result.returncode == 0:
        print(f"  created '{name}'.")
        return True
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if "already exists" in combined or "conflict" in combined:
        print(f"  '{name}' already exists (skipped).")
        return True
    print(f"  ERROR creating '{name}': {(result.stderr or result.stdout).strip()}",
          file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=sorted(_SERVERS), help="Limit to one server.")
    parser.add_argument(
        "--grant", action="store_true",
        help="Also grant the agent identity Mcp.Invoke first "
        "(runs scripts.grant_agent_identity_mcp_role).",
    )
    args = parser.parse_args(argv)

    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip()
    if not project_endpoint:
        print("ERROR: AZURE_AI_PROJECT_ENDPOINT is required.", file=sys.stderr)
        return 1

    if not entra_auth_enabled():
        print(
            "NOTE: ENTRA_AUTH_ENABLED is false — the MCP servers run anonymously, so "
            "the toolboxes need no auth connection. Nothing to do."
        )
        return 0

    if args.grant:
        from scripts.grant_agent_identity_mcp_role import main as grant_main
        print("==> Granting Mcp.Invoke to the agent identities")
        rc = grant_main([])
        if rc != 0:
            print("  WARN: role grant failed; continuing to connection creation.")

    if not _ensure_azd():
        return 1

    print(f"==> azd ai project set {project_endpoint}")
    proj = _azd("ai", "project", "set", project_endpoint)
    if proj.returncode != 0:
        print(f"ERROR: 'azd ai project set' failed: {(proj.stderr or proj.stdout).strip()}",
              file=sys.stderr)
        return 1

    labels = [args.only] if args.only else list(_SERVERS)
    created: list[tuple[str, str]] = []
    failures = 0
    for label in labels:
        url_env, app_env, app_default, conn_env, conn_default = _SERVERS[label]
        app_name = os.getenv(app_env, app_default)
        audience = resolve_mcp_audience(app_name)
        if not audience:
            print(
                f"  WARN: no '{app_name}-mcp-auth' app registration for the {label} "
                "MCP server — deploy it with ENTRA_AUTH_ENABLED=true first. Skipping."
            )
            continue
        target = _resolve_mcp_url(url_env, app_env, app_default)
        if not target:
            print(f"  WARN: could not resolve the {label} MCP URL — set {url_env} or "
                  "AZURE_RESOURCE_GROUP. Skipping.")
            continue
        conn_name = os.getenv(conn_env, conn_default)
        if _create_connection(conn_name, target, audience):
            created.append((label, conn_name))
        else:
            failures += 1

    if created:
        print("\nSet these in ./.env so the toolboxes use the connections:")
        for label, conn_name in created:
            print(f"  {_CONN_ENV[label]}={conn_name}")
        print("\nThen re-register the toolboxes:")
        print("  python -m scripts.register_marketing_toolbox")
        print("  python -m scripts.register_strategy_toolbox")

    print("\nDone." if not failures else f"\nDone with {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
