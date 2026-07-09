"""Deploy the **Web Recommender Agent** as an Azure Container App.

The NorthStar Health marketing assistant — an AG-UI web agent that lets a
marketer discuss customer personas and explore products and market performance
through a custom web UI, backed by the Foundry ``marketing_toolbox``.

Run it after ``azd up`` and after the marketing toolbox is registered:

    python -m scripts.register_marketing_toolbox

Usage::

    python -m scripts.deploy_web_recommender_agent --build   # build + deploy
    python -m scripts.deploy_web_recommender_agent           # deploy existing image

Environment variables (populated from ``.env`` by ``azd up``):
  AZURE_RESOURCE_GROUP                   target resource group (required)
  AZURE_CONTAINER_APPS_ENVIRONMENT_NAME  Container Apps environment (required)
  AZURE_IDENTITY_NAME                    user-assigned managed identity (required)
  AZURE_AI_PROJECT_ENDPOINT              Foundry project endpoint (required)
  MARKETING_TOOLBOX_NAME                 marketing toolbox (default: marketing_toolbox)
  MARKETING_MCP_URL                      direct marketing MCP URL override (optional)
  AZURE_AI_MODEL_DEPLOYMENT_NAME         chat model deployment (default: gpt-4.1-mini)
  APPLICATIONINSIGHTS_CONNECTION_STRING  telemetry sink (optional)
  WEB_RECOMMENDER_APP_NAME               Container App name (default: web-recommender-agent)
  WEB_RECOMMENDER_PORT                   container port (default: 8092)
  WEB_RECOMMENDER_EXTERNAL               "true" for public ingress (default: true)
  TAG                                    image tag to deploy (default: latest)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from scripts.deploy_helpers import (
    build_image,
    deploy_container_app,
    get_env,
    resolve_registry,
)

APP_NAME = os.getenv("WEB_RECOMMENDER_APP_NAME", "web-recommender-agent")
IMAGE_NAME = "web-recommender-agent"
PORT = int(os.getenv("WEB_RECOMMENDER_PORT", "8092"))
_DOCKERFILE = "src/web_recommender_agent/Dockerfile"


def build() -> str:
    registry = resolve_registry()
    source_path = Path(__file__).resolve().parents[1]
    dockerfile = str(source_path / _DOCKERFILE)
    return build_image(registry, IMAGE_NAME, source_path, dockerfile=dockerfile)


def deploy(tag: str | None = None) -> str | None:
    external = os.getenv("WEB_RECOMMENDER_EXTERNAL", "true").strip().lower() == "true"

    env_vars = {
        "AZURE_AI_PROJECT_ENDPOINT": get_env("AZURE_AI_PROJECT_ENDPOINT"),
        "MARKETING_TOOLBOX_NAME": os.getenv("MARKETING_TOOLBOX_NAME", "marketing_toolbox"),
        "MARKETING_MCP_URL": os.getenv("MARKETING_MCP_URL", ""),
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini"),
        "AZURE_OPENAI_CHAT_DEPLOYMENT_NAME": os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", ""),
        # Optional OBO settings (blank by default → uses managed identity).
        "WEB_RECOMMENDER_CLIENT_ID": os.getenv("WEB_RECOMMENDER_CLIENT_ID", ""),
        "WEB_RECOMMENDER_CLIENT_SECRET": os.getenv("WEB_RECOMMENDER_CLIENT_SECRET", ""),
        "WEB_RECOMMENDER_TENANT_ID": os.getenv(
            "WEB_RECOMMENDER_TENANT_ID", os.getenv("AZURE_TENANT_ID", "")
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
        readiness_probe_path="/healthz",
    )

    if fqdn:
        print(f"\nWeb Recommender Agent deployed: https://{fqdn}/")
    else:
        print(
            "\nWeb Recommender Agent deployed, but no ingress FQDN returned. "
            "Set WEB_RECOMMENDER_EXTERNAL=true or check the ingress."
        )
    return fqdn


if __name__ == "__main__":
    do_build = "--build" in sys.argv
    built_tag: str | None = None
    if do_build:
        built_tag = build()
    deploy(tag=built_tag)
