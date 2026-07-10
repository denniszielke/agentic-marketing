"""Deploy the **Supervisor** as an Azure AI Foundry **hosted** (container) agent.

This is the *supervisor* half of the agent-to-agent (A2A) demo. The supervisor is
a container-backed Foundry hosted agent (RESPONSES protocol via
``ResponsesHostServer``) that:

  1. triages each incoming question and, when it is a *marketing* question
     (products, personas or market performance), **delegates it to the marketing
     specialist over A2A** — its code calls the specialist's Foundry A2A endpoint
     with the open-source A2A client, authenticating as its own Entra **Agent
     Identity**; and
  2. is itself exposed as an **incoming A2A endpoint** using Foundry's native
     feature (the RESPONSES + A2A + INVOCATIONS protocols + a published agent
     card), so other agents / front ends can call it.
     See https://aka.ms/foundry-enable-a2a-endpoint.

Building it as a hosted agent (rather than a prompt agent + ``A2APreviewTool``)
means the supervisor talks to the specialist through the A2A *client*, which
sidesteps the server-side RemoteA2A connection / agent-card-path plumbing.

What this script sets up (deployment + the permission A2A needs):
  - removes any prior ``supervisor-agent`` (e.g. the earlier prompt-agent form)
    so the name can be recreated as a hosted agent;
  - builds the supervisor image in ACR and creates the hosted agent version with
    the RESPONSES + A2A + INVOCATIONS protocols enabled and its agent card
    published (incoming A2A);
  - grants the supervisor's Entra Agent Identity the **Foundry Agent Consumer**
    role on the project, which is the permission required to call the
    specialist's A2A endpoint.

Prerequisites:
  - The specialist is deployed first: ``python -m scripts.deploy_marketing_specialist_agent``.
  - ``ENABLE_HOSTED_AGENTS true`` at provision time (ACR for hosted agents).
  - ``az login`` with rights to create role assignments.

Run::

    python -m scripts.deploy_supervisor_agent

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT            Foundry project endpoint (required).
  AZURE_CONTAINER_REGISTRY_ENDPOINT    ACR login server for the agent image (required).
  AZURE_AI_PROJECT_ID                  Full ARM resource id of the project (role-assignment scope).
  AZURE_AI_MODEL_DEPLOYMENT_NAME       Model deployment (default: gpt-4.1-mini).
  AZURE_AI_SUPERVISOR_AGENT_NAME       Hosted agent name (default: supervisor-agent).
  AZURE_AI_SPECIALIST_AGENT_NAME       Specialist agent name (default: marketing-specialist-agent).
  AZURE_AI_SPECIALIST_A2A_URL          Explicit specialist A2A base URL (optional; else derived).
  A2A_CALLER_ROLE                      RBAC role for the caller (default: Foundry Agent Consumer).
"""

from __future__ import annotations

import os
import sys

from scripts.agent_deploy_helpers import (
    deploy_hosted_agent,
    get_client,
    get_env,
    load_agent_card,
    resolve_registry,
)
from scripts.prompt_agent_helpers import (
    a2a_base_url,
    assign_project_role,
    discover_agent_identity_object_id,
)

AGENT_CARD = load_agent_card("src/supervisor_agent/agentcard.json")


def _resolve_project_id() -> str:
    """Resolve the ARM resource id of the Foundry project (from env, else derive)."""
    project_id = os.getenv("AZURE_AI_PROJECT_ID", "").strip()
    if project_id:
        return project_id
    subscription = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip()
    resource_group = os.getenv("AZURE_RESOURCE_GROUP", "").strip()
    project_name = os.getenv("AZURE_AI_PROJECT_NAME", "").strip()
    endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip()
    account = endpoint.split("://", 1)[1].split(".", 1)[0] if "://" in endpoint else ""
    if subscription and resource_group and account and project_name:
        return (
            f"/subscriptions/{subscription}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.CognitiveServices/accounts/{account}"
            f"/projects/{project_name}"
        )
    return ""


def _delete_existing(client, agent_name: str) -> None:
    """Best-effort remove an existing agent of the same name (any kind)."""
    for attempt in (
        lambda: client.agents.delete(agent_name=agent_name),
        lambda: client.agents.delete_agent(agent_name=agent_name),
    ):
        try:
            attempt()
            print(f"  Removed existing agent '{agent_name}'.")
            return
        except AttributeError:
            continue
        except Exception as exc:  # noqa: BLE001 - tolerate not-found / API drift
            msg = str(exc).lower()
            if ("not" in msg and "found" in msg) or "doesn't exist" in msg:
                print(f"  No existing agent '{agent_name}' to remove.")
            else:
                print(f"  WARN: could not remove existing agent '{agent_name}': {exc}")
            return


def deploy() -> None:
    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    if not project_endpoint:
        print("Skipping supervisor deployment: AZURE_AI_PROJECT_ENDPOINT is required.")
        return

    registry = resolve_registry()
    client = get_client()

    agent_name = os.getenv("AZURE_AI_SUPERVISOR_AGENT_NAME", "supervisor-agent")
    specialist_name = os.getenv("AZURE_AI_SPECIALIST_AGENT_NAME", "marketing-specialist-agent")
    caller_role = os.getenv("A2A_CALLER_ROLE", "Foundry Agent Consumer")
    specialist_a2a = os.getenv("AZURE_AI_SPECIALIST_A2A_URL", "").strip() or a2a_base_url(
        project_endpoint, specialist_name
    )

    print(f"==> Deploying supervisor hosted agent '{agent_name}'")
    print(f"    Specialist A2A endpoint: {specialist_a2a}")

    # 0. Remove any prior supervisor (e.g. the previous prompt-agent form) so the
    #    name can be recreated as a hosted agent.
    print("==> Removing any prior supervisor agent of the same name")
    _delete_existing(client, agent_name)

    # 1. Build + deploy the hosted supervisor. deploy_hosted_agent builds the
    #    image in ACR, creates the hosted agent version, enables the RESPONSES +
    #    A2A + INVOCATIONS protocols (native incoming A2A) and publishes the card.
    deploy_hosted_agent(
        client,
        agent_name=agent_name,
        description="Supervisor hosted agent that delegates marketing tasks to the specialist over A2A.",
        registry=registry,
        project_endpoint=project_endpoint,
        dockerfile_rel="src/supervisor_agent/Dockerfile",
        extra_env={
            "AZURE_AI_SPECIALIST_AGENT_NAME": specialist_name,
            "AZURE_AI_SPECIALIST_A2A_URL": specialist_a2a,
        },
        agent_card=AGENT_CARD,
    )

    # 2. Permission for the outbound A2A call: the supervisor's Entra Agent
    #    Identity must hold the caller role on the project that hosts the
    #    specialist. (Each deploy can rotate the identity — re-grant idempotently.)
    project_id = _resolve_project_id()
    if not project_id:
        print(
            "\nWARN: could not resolve the Foundry project resource id — skipping the "
            f"'{caller_role}' grant. Set AZURE_AI_PROJECT_ID in ./.env and re-run.",
            file=sys.stderr,
        )
    else:
        print(f"\n==> Granting '{caller_role}' to the supervisor's agent identity on the project")
        obj_id = discover_agent_identity_object_id(agent_name)
        if obj_id:
            print(f"    Agent identity: {obj_id}")
            assign_project_role(principal_object_id=obj_id, role=caller_role, scope=project_id)
        else:
            print(
                "    WARN: could not discover the supervisor's Entra Agent Identity yet. "
                "Re-run the grant manually once it appears:\n"
                f"      az role assignment create --assignee-object-id <object-id> "
                f"--assignee-principal-type ServicePrincipal --role \"{caller_role}\" "
                f"--scope {project_id}"
            )

    supervisor_a2a = a2a_base_url(get_env("AZURE_AI_PROJECT_ENDPOINT"), agent_name)
    print(
        "\nDone. Supervisor hosted agent is live and delegates to the specialist over A2A.\n"
        f"  Supervisor A2A endpoint: {supervisor_a2a}\n"
        f"  Agent card (v1.0):       {supervisor_a2a}/agentCard/v1.0\n"
        "Role assignments can take 2-5 minutes to propagate before the first A2A call succeeds."
    )


if __name__ == "__main__":
    deploy()
