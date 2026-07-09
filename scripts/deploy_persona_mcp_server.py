"""Deploy the **persona MCP server** as an Azure Container App.

The NorthStar Health customer persona segmentation (Azure AI Search backed) that
the marketing and strategy agents reach through a Foundry toolbox. Run it after
``azd up`` and after the ``personas`` search index has been created and ingested.

Usage::

    python -m scripts.deploy_persona_mcp_server --build            # build + deploy
    python -m scripts.deploy_persona_mcp_server                    # deploy only

Environment variables (populated automatically from ``.env`` after ``azd up``):
  AZURE_RESOURCE_GROUP, AZURE_REGISTRY, AZURE_CONTAINER_APPS_ENVIRONMENT_NAME,
  AZURE_IDENTITY_NAME, AZURE_SEARCH_ENDPOINT (required)
  AZURE_SEARCH_ADMIN_KEY                 optional; else DefaultAzureCredential
  AZURE_SEARCH_PERSONAS_INDEX_NAME       default: personas
  PERSONA_MCP_EXTERNAL                   "true" for public ingress (default: true)
  ENTRA_AUTH_ENABLED                     "true" to protect with Entra JWT (default: true)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from scripts.auth_helpers import (
    ensure_mcp_app_registration,
    entra_auth_enabled,
    resolve_tenant_id,
)
from scripts.deploy_helpers import (
    build_image,
    deploy_container_app,
    get_containerapp_env_default_domain,
    get_env,
    resolve_registry,
)

APP_NAME = os.getenv("PERSONA_MCP_APP_NAME", "persona-mcp-server")
IMAGE_NAME = "persona-mcp-server"
PORT = int(os.getenv("PERSONA_MCP_PORT", "8094"))
_DOCKERFILE = "src/persona_mcp_server/Dockerfile"


def build() -> str:
    registry = resolve_registry()
    source_path = Path(__file__).resolve().parents[1]
    dockerfile = str(source_path / _DOCKERFILE)
    return build_image(registry, IMAGE_NAME, source_path, dockerfile=dockerfile)


def deploy(tag: str | None = None) -> str:
    external = os.getenv("PERSONA_MCP_EXTERNAL", "true").strip().lower() == "true"
    env_vars = {
        "PERSONA_MCP_HOST": "0.0.0.0",
        "PERSONA_MCP_PORT": str(PORT),
        "AZURE_SEARCH_ENDPOINT": os.getenv("AZURE_SEARCH_ENDPOINT", ""),
        "AZURE_SEARCH_ADMIN_KEY": os.getenv("AZURE_SEARCH_ADMIN_KEY", ""),
        "AZURE_SEARCH_PERSONAS_INDEX_NAME": os.getenv(
            "AZURE_SEARCH_PERSONAS_INDEX_NAME", "personas"
        ),
        "APPLICATIONINSIGHTS_CONNECTION_STRING": os.getenv(
            "APPLICATIONINSIGHTS_CONNECTION_STRING", ""
        ),
    }
    env_vars.update(_auth_env_vars())

    fqdn = deploy_container_app(
        app_name=APP_NAME,
        image_name=IMAGE_NAME,
        port=PORT,
        external=external,
        env_vars=env_vars,
        tag=tag,
        readiness_probe_path="/health",
    )
    if fqdn:
        print(f"\nPersona MCP server deployed: https://{fqdn}/mcp")
    else:
        print("\nPersona MCP server deployed, but no ingress FQDN was returned.")
    return fqdn


def _auth_env_vars() -> dict[str, str]:
    if not entra_auth_enabled():
        print("\n==> ENTRA_AUTH_ENABLED=false — MCP server runs without authentication")
        return {"ENTRA_AUTH_ENABLED": "false"}

    print("\n==> ENTRA_AUTH_ENABLED=true — protecting the MCP server with FastMCP Entra JWT auth")
    app_id, audience = ensure_mcp_app_registration(APP_NAME)
    tenant_id = resolve_tenant_id()
    resource_group = get_env("AZURE_RESOURCE_GROUP")
    environment_name = get_env("AZURE_CONTAINER_APPS_ENVIRONMENT_NAME")
    default_domain = get_containerapp_env_default_domain(resource_group, environment_name)
    base_url = f"https://{APP_NAME}.{default_domain}" if default_domain else ""
    print(f"  Callers must request a token for audience '{audience}/.default'.")
    return {
        "ENTRA_AUTH_ENABLED": "true",
        "MCP_AUTH_CLIENT_ID": app_id,
        "AZURE_TENANT_ID": tenant_id,
        "MCP_PUBLIC_BASE_URL": base_url,
    }


if __name__ == "__main__":
    do_build = "--build" in sys.argv
    built_tag: str | None = None
    if do_build:
        built_tag = build()
    deploy(tag=built_tag)
