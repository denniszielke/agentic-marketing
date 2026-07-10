"""Shared helpers for deploying **Foundry prompt agents** with A2A.

The agent-to-agent (A2A) demo hosts two *prompt* agents (server-side, declarative
— no container image):

* ``marketing-specialist-agent`` — a marketing specialist grounded in the
  ``marketing_toolbox`` (product + market-insights + persona MCP servers). It is
  exposed as an **incoming A2A endpoint** so other agents can delegate to it.
* ``supervisor-agent`` — a supervisor that inspects the incoming question and,
  when it is a marketing question, **calls the specialist over A2A** (via the
  ``A2APreviewTool`` + a ``RemoteA2A`` project connection) and returns its answer.

Unlike the hosted agents in :mod:`scripts.agent_deploy_helpers`, prompt agents
are created with :class:`~azure.ai.projects.models.PromptAgentDefinition` and need
no ACR image. This module centralises the create/patch/enable-A2A plumbing and
the Entra **Agent Identity** discovery both deploy scripts share.

All configuration is sourced from ``./.env`` (written by ``azd up``).
"""

from __future__ import annotations

import json
import subprocess
import time
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    A2AProtocolConfiguration,
    AgentCard,
    AgentEndpointConfig,
    PromptAgentDefinition,
    ProtocolConfiguration,
    ResponsesProtocolConfiguration,
)

from scripts._cli import normalize
from scripts.agent_deploy_helpers import patch_agent_card_via_rest

_GRAPH = "https://graph.microsoft.com"

__all__ = [
    "a2a_base_url",
    "agent_card_url",
    "create_prompt_agent_version",
    "enable_incoming_a2a",
    "discover_agent_identity_object_id",
    "assign_project_role",
]


# ---------------------------------------------------------------------------
# A2A endpoint URLs
# ---------------------------------------------------------------------------
def a2a_base_url(project_endpoint: str, agent_name: str) -> str:
    """Return the A2A base path for a Foundry agent's incoming endpoint."""
    return (
        f"{project_endpoint.rstrip('/')}/agents/{agent_name}"
        "/endpoint/protocols/a2a"
    )


def agent_card_url(project_endpoint: str, agent_name: str, version: str = "v1.0") -> str:
    """Return the versioned agent-card discovery URL for a Foundry A2A agent."""
    return f"{a2a_base_url(project_endpoint, agent_name)}/agentCard/{version}"


# ---------------------------------------------------------------------------
# Prompt agent create / A2A enable
# ---------------------------------------------------------------------------
def create_prompt_agent_version(
    client: AIProjectClient,
    *,
    agent_name: str,
    description: str,
    model: str,
    instructions: str,
    tools: list[Any] | None = None,
) -> Any:
    """Create (or add a new version to) a Foundry **prompt agent**.

    Returns the created agent-version object.
    """
    definition = PromptAgentDefinition(
        model=model,
        instructions=instructions,
        tools=tools or [],
    )
    version = client.agents.create_version(
        agent_name=agent_name,
        description=description,
        definition=definition,
    )
    print(f"Prompt agent '{agent_name}' version '{getattr(version, 'version', '?')}' created.")
    return version


def enable_incoming_a2a(
    client: AIProjectClient,
    *,
    project_endpoint: str,
    agent_name: str,
    agent_card: AgentCard,
) -> str:
    """Enable the incoming **A2A** protocol on a prompt agent's endpoint.

    Turns on the ``responses`` + ``a2a`` protocols and publishes the agent card
    so other agents can discover and call it. Returns the A2A base URL.
    """
    endpoint_config = AgentEndpointConfig(
        protocol_configuration=ProtocolConfiguration(
            responses=ResponsesProtocolConfiguration(),
            a2a=A2AProtocolConfiguration(),
        ),
    )
    client.agents.update_details(agent_name=agent_name, agent_endpoint=endpoint_config)

    # The Python SDK does not yet persist the agent card via update_details, so
    # patch it (and the protocol list) through the REST API.
    patch_agent_card_via_rest(
        project_endpoint=project_endpoint,
        agent_name=agent_name,
        agent_card=agent_card,
        protocols=["responses", "a2a"],
    )

    base = a2a_base_url(project_endpoint, agent_name)
    print(f"  Incoming A2A enabled for '{agent_name}'.")
    print(f"    A2A base path: {base}")
    print(f"    Agent card (v1.0): {base}/agentCard/v1.0")
    return base


# ---------------------------------------------------------------------------
# Entra Agent Identity discovery + role assignment
# ---------------------------------------------------------------------------
def _az(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        normalize(["az", *args]), check=False, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"az {' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def discover_agent_identity_object_id(agent_name: str, *, retries: int = 12, delay: float = 5.0) -> str:
    """Return the Entra **Agent Identity** service-principal object id for a Foundry agent.

    Foundry provisions an ``agentIdentity`` service principal per agent whose
    display name contains the agent name. The identity can take a short while to
    appear after ``create_version``, so this polls up to ``retries`` times. Returns
    the object id, or "" if it never becomes discoverable.
    """
    uri = (
        f"{_GRAPH}/beta/servicePrincipals/microsoft.graph.agentIdentity"
        "?$select=id,appId,displayName"
    )
    wanted = agent_name.lower()
    for attempt in range(1, retries + 1):
        result = _az("rest", "--method", "GET", "--uri", uri,
                     "--headers", "Content-Type=application/json")
        if result.returncode != 0:
            print(f"  WARN: could not enumerate agent identities via Graph: "
                  f"{(result.stderr or result.stdout).strip()}")
            return ""
        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            data = {}
        for identity in data.get("value", []):
            if wanted in (identity.get("displayName") or "").lower():
                return identity.get("id", "")
        if attempt < retries:
            print(f"  agent identity for '{agent_name}' not visible yet "
                  f"(attempt {attempt}/{retries}); waiting {delay:.0f}s...")
            time.sleep(delay)
    return ""


def assign_project_role(
    *,
    principal_object_id: str,
    role: str,
    scope: str,
) -> bool:
    """Assign an Azure RBAC role to a service principal at a resource scope.

    Idempotent — "already exists" is treated as success. Uses
    ``--assignee-object-id`` + ``ServicePrincipal`` so no Graph lookup (or its
    propagation delay) is required for the assignee.
    """
    if not principal_object_id or not scope:
        return False
    result = _az(
        "role", "assignment", "create",
        "--assignee-object-id", principal_object_id,
        "--assignee-principal-type", "ServicePrincipal",
        "--role", role,
        "--scope", scope,
    )
    if result.returncode == 0:
        print(f"  Granted '{role}' to {principal_object_id} on {scope}")
        return True
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if "already exists" in combined or "roleassignmentexists" in combined:
        print(f"  '{role}' already assigned to {principal_object_id} (skipped).")
        return True
    print(f"  WARN: could not assign '{role}': {(result.stderr or result.stdout).strip()}")
    return False
