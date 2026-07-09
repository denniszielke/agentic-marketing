"""Shared helpers for building and deploying the marketing MCP servers.

Focused on what the MCP-server deployment scripts need: reading configuration
from the environment, building an image in Azure Container Registry (ACR) and
deploying it as a Container App via ``infra/core/host/app.bicep``.

All configuration is sourced from ``./.env`` (written by ``azd up``).
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from scripts._cli import normalize

# Load the repository-root .env explicitly so the scripts work regardless of the
# current working directory (azd writes it there via the postdeploy hook).
_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=True)
# Also load any .env discovered from the current working directory as a fallback.
load_dotenv(override=False)


def get_env(name: str, required: bool = True, default: str | None = None) -> str:
    """Read an environment variable, raising if a required one is missing."""
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value or ""


def _registry_name(login_server: str) -> str:
    """Strip the ``.azurecr.io`` suffix to get the bare ACR resource name."""
    return login_server.removesuffix(".azurecr.io")


def _discover_registry(resource_group: str) -> str:
    """Find the first ACR login server in the resource group (empty if none)."""
    result = subprocess.run(
        normalize([
            "az", "acr", "list",
            "-g", resource_group,
            "--query", "[0].loginServer",
            "-o", "tsv",
        ]),
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def resolve_registry() -> str:
    """Resolve the ACR login server (e.g. ``myacr.azurecr.io``).

    Precedence: ``AZURE_REGISTRY`` > ``AZURE_CONTAINER_REGISTRY_ENDPOINT`` >
    discovery from the resource group.
    """
    registry = os.getenv("AZURE_REGISTRY") or os.getenv("AZURE_CONTAINER_REGISTRY_ENDPOINT")
    if registry:
        return registry
    resource_group = get_env("AZURE_RESOURCE_GROUP")
    registry = _discover_registry(resource_group)
    if not registry:
        raise RuntimeError(
            "Could not resolve a container registry. Set AZURE_REGISTRY in ./.env "
            f"or ensure an Azure Container Registry exists in {resource_group}."
        )
    print(f"==> Resolved container registry: {registry}")
    return registry


def build_image(
    registry: str,
    image_name: str,
    context_path: Path,
    dockerfile: str | None = None,
) -> str:
    """Build an image in ACR with a timestamped tag **and** ``:latest``.

    Returns the timestamp tag so callers can pass it straight to
    :func:`deploy_container_app` (which builds the full image reference itself).
    """
    registry_name = _registry_name(registry)
    build_tag = datetime.now().strftime("%Y%m%d%H%M%S")
    image_tag = f"{registry}/{image_name}:{build_tag}"
    latest_tag = f"{registry}/{image_name}:latest"
    cmd = [
        "az", "acr", "build",
        "--registry", registry_name,
        "--image", image_tag,
        "--image", latest_tag,
        "--platform", "linux/amd64",
    ]
    if dockerfile:
        dockerfile_path = Path(dockerfile)
        try:
            rel = dockerfile_path.relative_to(context_path)
        except ValueError:
            rel = dockerfile_path
        cmd += ["--file", str(rel)]
    cmd.append(str(context_path))
    subprocess.run(normalize(cmd), check=True)
    print(f"==> Built {image_tag} (also tagged :latest)")
    return build_tag


def get_container_app_fqdn(resource_group: str, app_name: str) -> str:
    """Return the ingress FQDN of a deployed Container App (empty if none)."""
    result = subprocess.run(
        normalize([
            "az", "containerapp", "show",
            "--resource-group", resource_group,
            "--name", app_name,
            "--query", "properties.configuration.ingress.fqdn",
            "--output", "tsv",
        ]),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def get_containerapp_env_default_domain(resource_group: str, environment_name: str) -> str:
    """Return the Container Apps environment default domain (empty if none).

    The public FQDN of an external Container App is ``<app-name>.<default-domain>``.
    Resolving the domain up front lets a deploy set the app's own public base URL
    as an env var *before* the container starts (needed by FastMCP's OAuth
    protected-resource metadata).
    """
    result = subprocess.run(
        normalize([
            "az", "containerapp", "env", "show",
            "--resource-group", resource_group,
            "--name", environment_name,
            "--query", "properties.defaultDomain",
            "--output", "tsv",
        ]),
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def deploy_container_app(
    *,
    app_name: str,
    image_name: str,
    port: int,
    external: bool,
    env_vars: dict[str, str],
    tag: str | None = None,
    readiness_probe_path: str = "",
    min_replicas: int = 0,
    max_replicas: int = 10,
) -> str:
    """Deploy a single Container App via ``app.bicep`` and return its FQDN.

    Reads ``AZURE_RESOURCE_GROUP``, ``AZURE_REGISTRY``,
    ``AZURE_CONTAINER_APPS_ENVIRONMENT_NAME`` and ``AZURE_IDENTITY_NAME`` from
    the environment. ``tag`` defaults to the ``TAG`` env var or ``latest``.
    """
    resource_group = get_env("AZURE_RESOURCE_GROUP")
    registry = resolve_registry()
    environment_name = get_env("AZURE_CONTAINER_APPS_ENVIRONMENT_NAME")
    identity_name = get_env("AZURE_IDENTITY_NAME")
    tag = tag or os.getenv("TAG", "latest")
    app_bicep = Path(__file__).resolve().parents[1] / "infra" / "core" / "host" / "app.bicep"

    image_ref = f"{registry}/{image_name}:{tag}"
    env_json = json.dumps(
        [{"name": k, "value": v} for k, v in env_vars.items() if v]
    )

    params = [
        f"name={app_name}",
        f"containerAppsEnvironmentName={environment_name}",
        f"containerRegistryName={_registry_name(registry)}",
        f"identityName={identity_name}",
        f"imageName={image_ref}",
        f"targetPort={port}",
        f"external={'true' if external else 'false'}",
        f"envJson={env_json}",
        f"minReplicas={min_replicas}",
        f"maxReplicas={max_replicas}",
    ]
    if readiness_probe_path:
        params.append(f"readinessProbePath={readiness_probe_path}")

    print(f"==> Deploying Container App '{app_name}' with image {image_ref}")
    subprocess.run(
        normalize([
            "az", "deployment", "group", "create",
            "--resource-group", resource_group,
            "--template-file", str(app_bicep),
            "--parameters", *params,
        ]),
        check=True,
    )
    return get_container_app_fqdn(resource_group, app_name)
