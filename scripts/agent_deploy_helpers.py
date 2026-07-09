"""Shared helpers for deploying the marketing **Foundry hosted agents**.

The marketing demo hosts two agents as Azure AI Foundry hosted agents (RESPONSES
protocol, container-backed):

* ``market_intelligence_agent`` — discovers opportunities and analyses market
  dynamics (marketing_toolbox: products + market insights + personas).
* ``executive_strategy_agent`` — virtual Chief Strategy Officer (strategy_toolbox
  which also includes research, plus the marketing_toolbox).

Both are built from a Dockerfile, pushed to ACR and registered as a hosted agent
version with A2A + Responses + Invocations protocols enabled. This module is
kept separate from ``deploy_helpers.py`` (which the MCP-server deployment scripts
use) so those scripts never need ``azure-ai-projects`` installed.

All configuration is sourced from ``./.env`` (written by ``azd up``).
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from scripts._cli import normalize

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import AgentCard, AgentCardSkill
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

# Load the repository-root .env explicitly so the scripts work regardless of the
# current working directory (azd writes it there via the postdeploy hook).
_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=True)
load_dotenv(override=False)

__all__ = [
    "AgentCard",
    "AgentCardSkill",
    "get_env",
    "get_client",
    "resolve_registry",
    "get_container_app_fqdn",
    "load_agent_card",
    "shared_agent_env",
    "deploy_hosted_agent",
    "patch_agent_card_via_rest",
]


def get_env(name: str, required: bool = True, default: str | None = None) -> str:
    """Read an environment variable, raising if a required one is missing."""
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value or ""


def get_client() -> AIProjectClient:
    """Return a Foundry project client."""
    return AIProjectClient(
        endpoint=get_env("AZURE_AI_PROJECT_ENDPOINT"),
        credential=DefaultAzureCredential(),
    )


def load_agent_card(path: str | Path) -> AgentCard:
    """Load an :class:`AgentCard` from an ``agentcard.json`` file.

    Relative paths are resolved against the repository root. The JSON shape is
    ``{"version", "description", "skills": [{"id", "name", "description"}]}``.
    """
    card_path = Path(path)
    if not card_path.is_absolute():
        card_path = _REPO_ROOT / card_path
    data = json.loads(card_path.read_text(encoding="utf-8"))
    skills = [
        AgentCardSkill(
            id=skill["id"],
            name=skill["name"],
            description=skill.get("description"),
        )
        for skill in data.get("skills", [])
    ]
    return AgentCard(
        version=data.get("version"),
        description=data.get("description"),
        skills=skills,
    )


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
    """Resolve the ACR login server (e.g. ``myacr.azurecr.io``)."""
    registry = os.getenv("AZURE_CONTAINER_REGISTRY_ENDPOINT") or os.getenv("AZURE_REGISTRY")
    if registry:
        return registry
    resource_group = get_env("AZURE_RESOURCE_GROUP")
    registry = _discover_registry(resource_group)
    if not registry:
        raise RuntimeError(
            "Could not resolve a container registry. Set "
            "AZURE_CONTAINER_REGISTRY_ENDPOINT in ./.env or ensure an Azure "
            f"Container Registry exists in {resource_group}."
        )
    print(f"==> Resolved container registry: {registry}")
    return registry


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
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _build_image(registry: str, image_name: str, context_path: Path,
                 dockerfile: str) -> str:
    """Build an image in ACR with a timestamped tag **and** ``:latest``.

    Returns the fully-qualified timestamped image reference so callers can pin
    the exact build when creating a hosted agent version.
    """
    registry_name = registry.removesuffix(".azurecr.io")
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
    dockerfile_path = Path(dockerfile)
    try:
        rel = dockerfile_path.relative_to(context_path)
    except ValueError:
        rel = dockerfile_path
    cmd += ["--file", str(rel), str(context_path)]
    subprocess.run(normalize(cmd), check=True)
    print(f"==> Built {image_tag} (also tagged :latest)")
    return image_tag


# ---------------------------------------------------------------------------
# TEMPORARY WORKAROUND — remove once azure-ai-projects supports persisting the
# A2A agent card via ``client.agents.update_details(agent_card=...)``.
# ---------------------------------------------------------------------------
def _agent_card_to_payload(agent_card: AgentCard) -> dict:
    """Serialise an ``AgentCard`` to the REST ``agent_card`` request shape."""
    skills = []
    for skill in agent_card.skills or []:
        skills.append(
            {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
            }
        )
    return {
        "description": agent_card.description,
        "version": agent_card.version,
        "skills": skills,
    }


def patch_agent_card_via_rest(
    *,
    project_endpoint: str,
    agent_name: str,
    agent_card: AgentCard,
    protocols: list[str],
) -> None:
    """PATCH the agent card + endpoint protocols via the Foundry REST API.

    Stopgap until the Python SDK persists ``agent_card`` on ``update_details``.
    """
    import json
    import urllib.error
    import urllib.request

    token = DefaultAzureCredential().get_token("https://ai.azure.com/.default").token
    url = f"{project_endpoint.rstrip('/')}/agents/{agent_name}?api-version=v1"
    payload = {
        "agent_card": _agent_card_to_payload(agent_card),
        "agent_endpoint": {"protocols": protocols},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="PATCH",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            response.read()
        print(f"  Agent card patched via REST for '{agent_name}'.")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Failed to patch agent card for '{agent_name}' "
            f"({error.code} {error.reason}): {detail}"
        ) from error


def shared_agent_env(project_endpoint: str) -> dict[str, str]:
    """Environment variables common to every marketing Foundry hosted agent."""
    model_deployment_name = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")
    # Experimental GenAI tracing is OFF by default. When enabled it turns on the
    # azure-ai-projects Responses instrumentor, which breaks the streaming path
    # in agent-framework-openai. Set AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true
    # in ./.env to enable.
    genai_tracing = (
        os.getenv("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "false").strip().lower()
        == "true"
    )
    tracing_value = "true" if genai_tracing else "false"
    return {
        "AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING": tracing_value,
        "AZURE_TRACING_GEN_AI_INSTRUMENT_RESPONSES_API": tracing_value,
        "AZURE_SEARCH_ENDPOINT": os.getenv("AZURE_SEARCH_ENDPOINT", ""),
        "AZURE_SEARCH_ADMIN_KEY": os.getenv("AZURE_SEARCH_ADMIN_KEY", ""),
        "AZURE_SEARCH_PRODUCTS_INDEX_NAME": os.getenv(
            "AZURE_SEARCH_PRODUCTS_INDEX_NAME", "products"
        ),
        "AZURE_SEARCH_PERSONAS_INDEX_NAME": os.getenv(
            "AZURE_SEARCH_PERSONAS_INDEX_NAME", "personas"
        ),
        "AZURE_SEARCH_INNOVATIONS_INDEX_NAME": os.getenv(
            "AZURE_SEARCH_INNOVATIONS_INDEX_NAME", "innovations"
        ),
        # APPLICATIONINSIGHTS_CONNECTION_STRING is reserved by the Foundry
        # platform and must NOT be passed in environment_variables — the
        # platform injects it automatically.
        "AZURE_AI_PROJECT_ENDPOINT": project_endpoint,
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": model_deployment_name,
        "AZURE_OPENAI_CHAT_DEPLOYMENT_NAME": os.getenv(
            "AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", model_deployment_name
        ),
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME": os.getenv(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small"
        ),
        "AZURE_OPENAI_ENDPOINT": os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        "OPENAI_API_VERSION": os.getenv("OPENAI_API_VERSION", "2024-05-01-preview"),
    }


def deploy_hosted_agent(
    client: AIProjectClient,
    *,
    agent_name: str,
    description: str,
    registry: str,
    project_endpoint: str,
    dockerfile_rel: str,
    extra_env: dict[str, str] | None = None,
    agent_card: AgentCard | None = None,
    cpu: str = "1",
    memory: str = "2Gi",
) -> None:
    """Build the agent image and create/patch a Foundry hosted agent version.

    Enables the RESPONSES, A2A and INVOCATIONS endpoint protocols so the agent
    can be consumed both by front ends (Responses API) and by other agents
    (A2A hand-offs, including cross-organisation).
    """
    from azure.ai.projects.models import (
        A2AProtocolConfiguration,
        AgentEndpointConfig,
        AgentEndpointProtocol,
        ContainerConfiguration,
        HostedAgentDefinition,
        InvocationsProtocolConfiguration,
        ProtocolConfiguration,
        ProtocolVersionRecord,
        ResponsesProtocolConfiguration,
    )

    source_path = Path(__file__).resolve().parents[1]
    dockerfile = str(source_path / dockerfile_rel)
    full_image_ref = _build_image(registry, agent_name, source_path, dockerfile)

    env_vars = {**shared_agent_env(project_endpoint), **(extra_env or {})}
    env_vars = {k: v for k, v in env_vars.items() if v}

    protocols = [
        ProtocolVersionRecord(protocol=AgentEndpointProtocol.RESPONSES, version="1.0.0"),
    ]
    client.agents.create_version(
        agent_name=agent_name,
        description=description,
        definition=HostedAgentDefinition(
            protocol_versions=protocols,
            cpu=cpu,
            memory=memory,
            container_configuration=ContainerConfiguration(image=full_image_ref),
            environment_variables=env_vars,
        ),
    )

    endpoint_config = AgentEndpointConfig(
        protocol_configuration=ProtocolConfiguration(
            responses=ResponsesProtocolConfiguration(),
            a2a=A2AProtocolConfiguration(),
            invocations=InvocationsProtocolConfiguration(),
        ),
    )
    client.agents.update_details(agent_name=agent_name, agent_endpoint=endpoint_config)

    if agent_card is not None:
        patch_agent_card_via_rest(
            project_endpoint=project_endpoint,
            agent_name=agent_name,
            agent_card=agent_card,
            protocols=["responses", "a2a", "invocations"],
        )

        a2a_base = f"{project_endpoint.rstrip('/')}/agents/{agent_name}/endpoint/protocols/a2a"
        print(f"  A2A enabled — cards: {a2a_base}/agentCard/v0.3 and {a2a_base}/agentCard/v1.0")
    print(f"Hosted agent '{agent_name}' deployed from source.")
