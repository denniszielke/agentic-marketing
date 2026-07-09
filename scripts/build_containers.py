"""Build the NorthStar Health marketing container images using Azure Container Registry.

This script **only builds** the images (the four MCP servers, the two hosted
agents and the web recommender agent) in ACR — it does not deploy anything.
Deploy separately with the ``scripts/deploy_*`` helpers.

The target resource group is loaded automatically from ``./.env`` (written by
``azd up``): ``AZURE_RESOURCE_GROUP`` is used directly, otherwise it is derived
from ``AZURE_ENV_NAME`` as ``rg-<AZURE_ENV_NAME>``. The subscription and
container registry are then discovered from that resource group.

Usage::

    # build with an auto-generated timestamp tag (env from ./.env)
    python -m scripts.build_containers

    # build with an explicit tag
    python -m scripts.build_containers 20240608120000

    # override the environment name (resource group rg-<name>)
    python -m scripts.build_containers --env myenv
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from scripts._cli import normalize

load_dotenv(override=True)

REPO_ROOT = Path(__file__).resolve().parents[1]

# image name -> Dockerfile path (relative to REPO_ROOT)
IMAGES: dict[str, str] = {
    "product-mcp-server": "src/product_mcp_server/Dockerfile",
    "persona-mcp-server": "src/persona_mcp_server/Dockerfile",
    "research-mcp-server": "src/research_mcp_server/Dockerfile",
    "market-insights-server": "src/market_insights_server/Dockerfile",
    "market-intelligence-agent": "src/market_intelligence_agent/Dockerfile",
    "executive-strategy-agent": "src/executive_strategy_agent/Dockerfile",
    "web-recommender-agent": "src/web_recommender_agent/Dockerfile",
}


def _run(cmd: list[str], capture: bool = False) -> str:
    result = subprocess.run(normalize(cmd), check=True, text=True,
                            capture_output=capture)
    return (result.stdout or "").strip() if capture else ""


def _group_exists(resource_group: str) -> bool:
    out = _run(["az", "group", "exists", "--name", resource_group], capture=True)
    return out.lower() == "true"


def _subscription_id() -> str:
    return _run(["az", "account", "show", "--query", "id", "-o", "tsv"], capture=True)


def _registry_name(resource_group: str) -> str:
    login_server = (
        os.getenv("AZURE_REGISTRY")
        or os.getenv("AZURE_CONTAINER_REGISTRY_ENDPOINT")
        or ""
    ).strip()
    if login_server:
        return login_server.removesuffix(".azurecr.io")
    return _run(
        ["az", "acr", "list", "-g", resource_group, "--query", "[0].name", "-o", "tsv"],
        capture=True,
    )


def build_image(subscription_id: str, registry: str, name: str,
                dockerfile: str, tag: str) -> None:
    """Build ``name:tag`` and ``name:latest`` in ACR from the repo root context."""
    print(f"==> Building {name}:{tag} (and :latest) from {dockerfile}")
    _run(
        [
            "az", "acr", "build",
            "--subscription", subscription_id,
            "--registry", registry,
            "--image", f"{name}:{tag}",
            "--image", f"{name}:latest",
            "--platform", "linux/amd64",
            "--file", dockerfile,
            str(REPO_ROOT),
        ]
    )


def _resolve_resource_group(env_override: str | None) -> str | None:
    if env_override:
        return f"rg-{env_override}"
    resource_group = os.getenv("AZURE_RESOURCE_GROUP")
    if resource_group:
        return resource_group
    env_name = os.getenv("AZURE_ENV_NAME")
    if env_name:
        return f"rg-{env_name}"
    return None


def main(argv: list[str]) -> int:
    env_override: str | None = None
    positionals: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--env", "-e"):
            if i + 1 >= len(argv):
                print("ERROR: --env requires a value", file=sys.stderr)
                return 1
            env_override = argv[i + 1]
            i += 2
            continue
        positionals.append(arg)
        i += 1

    tag = positionals[0] if positionals else datetime.now().strftime("%Y%m%d%H%M%S")

    resource_group = _resolve_resource_group(env_override)
    if not resource_group:
        print("ERROR: could not resolve the resource group. Set AZURE_RESOURCE_GROUP "
              "or AZURE_ENV_NAME in ./.env, or pass --env <AZURE_ENV_NAME>.",
              file=sys.stderr)
        return 1

    if not _group_exists(resource_group):
        print(f"ERROR: resource group {resource_group} does not exist - aborting",
              file=sys.stderr)
        return 1

    subscription_id = _subscription_id()
    registry = _registry_name(resource_group)
    if not registry:
        print(f"ERROR: No container registry found in resource group "
              f"{resource_group} - aborting", file=sys.stderr)
        return 1

    print(f"==> Using registry: {registry}, tag: {tag}")

    for name, dockerfile in IMAGES.items():
        build_image(subscription_id, registry, name, dockerfile, tag)

    print("All images built successfully.")
    print(f"Registry: {registry}.azurecr.io, Tag: {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
