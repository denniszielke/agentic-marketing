"""Deploy the **public product MCP server** as an Azure Container App.

A **public, anonymous** view of the NorthStar Health product catalogue (Azure AI
Search backed) for internet consumption. Unlike ``deploy_product_mcp_server``,
this server is **never** protected with Entra auth and it exposes only public
fields — no list prices, margins or costs.

Run it after ``azd up`` has provisioned the infrastructure and the ``products``
search index has been created and ingested.

Usage::

    python -m scripts.deploy_public_product_mcp_server --build     # build + deploy
    python -m scripts.deploy_public_product_mcp_server             # deploy only

Environment variables (populated automatically from ``.env`` after ``azd up``):
  AZURE_RESOURCE_GROUP                   target resource group (required)
  AZURE_REGISTRY                         ACR login server (required)
  AZURE_CONTAINER_APPS_ENVIRONMENT_NAME  Container Apps environment (required)
  AZURE_IDENTITY_NAME                    user-assigned managed identity (required)
  AZURE_SEARCH_ENDPOINT                  AI Search endpoint (required)
  AZURE_SEARCH_ADMIN_KEY                 optional; else DefaultAzureCredential
  AZURE_SEARCH_PRODUCTS_INDEX_NAME       default: products
  TAG                                    image tag to deploy (default: latest)
  PUBLIC_PRODUCT_MCP_APP_NAME            Container App name (default: public-product-mcp-server)
  PUBLIC_PRODUCT_MCP_PORT                container port (default: 8097)
  PUBLIC_PRODUCT_MCP_EXTERNAL            "true" for public ingress (default: true)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from scripts.deploy_helpers import (
    build_image,
    deploy_container_app,
    resolve_registry,
)

APP_NAME = os.getenv("PUBLIC_PRODUCT_MCP_APP_NAME", "public-product-mcp-server")
IMAGE_NAME = "public-product-mcp-server"
PORT = int(os.getenv("PUBLIC_PRODUCT_MCP_PORT", "8097"))
_DOCKERFILE = "src/public_product_mcp_server/Dockerfile"
_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src" / "public_product_mcp_server" / "register-external-mcp-server.json"
)
_GENERATED_PATH = (
    Path(__file__).resolve().parents[1]
    / "src" / "public_product_mcp_server"
    / "register-external-mcp-server.generated.json"
)


def build() -> str:
    registry = resolve_registry()
    source_path = Path(__file__).resolve().parents[1]
    dockerfile = str(source_path / _DOCKERFILE)
    return build_image(registry, IMAGE_NAME, source_path, dockerfile=dockerfile)


def deploy(tag: str | None = None) -> str:
    external = os.getenv("PUBLIC_PRODUCT_MCP_EXTERNAL", "true").strip().lower() == "true"
    # This server is intentionally public — no Entra auth is ever configured.
    print("\n==> Public product MCP server — deployed WITHOUT authentication (anonymous)")
    env_vars = {
        "PUBLIC_PRODUCT_MCP_HOST": "0.0.0.0",
        "PUBLIC_PRODUCT_MCP_PORT": str(PORT),
        "AZURE_SEARCH_ENDPOINT": os.getenv("AZURE_SEARCH_ENDPOINT", ""),
        "AZURE_SEARCH_ADMIN_KEY": os.getenv("AZURE_SEARCH_ADMIN_KEY", ""),
        "AZURE_SEARCH_PRODUCTS_INDEX_NAME": os.getenv(
            "AZURE_SEARCH_PRODUCTS_INDEX_NAME", "products"
        ),
        "APPLICATIONINSIGHTS_CONNECTION_STRING": os.getenv(
            "APPLICATIONINSIGHTS_CONNECTION_STRING", ""
        ),
    }

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
        print(f"\nPublic product MCP server deployed: https://{fqdn}/mcp")
        _persist_server_url(fqdn)
    else:
        print("\nPublic product MCP server deployed, but no ingress FQDN was returned.")
    return fqdn


def _persist_server_url(fqdn: str) -> None:
    """Write the git-ignored generated manifest with the deployed ``/mcp`` URL.

    Fills the committed ``register-external-mcp-server.json`` template with the
    real ``https://<fqdn>/mcp`` URL and writes it to the git-ignored
    ``register-external-mcp-server.generated.json`` (never checked in).
    """
    url = f"https://{fqdn}/mcp"
    try:
        manifest = json.loads(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  WARN: could not generate {_GENERATED_PATH.name}: {exc}")
        return
    manifest["serverUrl"] = url
    _GENERATED_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"==> Wrote {_GENERATED_PATH.name} (serverUrl -> {url})")


if __name__ == "__main__":
    do_build = "--build" in sys.argv
    built_tag: str | None = None
    if do_build:
        built_tag = build()
    deploy(tag=built_tag)
