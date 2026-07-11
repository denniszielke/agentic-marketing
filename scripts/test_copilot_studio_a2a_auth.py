"""Verify the **Copilot Studio A2A OAuth credentials** can authenticate to the
marketing specialist's A2A endpoint.

Run this after ``scripts.create_copilot_studio_a2a_auth`` to confirm the app
registration, its client secret and the ``Foundry Agent Consumer`` role grant are
all wired correctly — *before* pasting the parameters into Copilot Studio.

It reuses the **same client id + client secret** you hand to Copilot Studio, but
authenticates with the OAuth 2.0 **client-credentials** flow (app-only) via
``ClientSecretCredential``. That validates everything Copilot Studio's
authorization-code flow also depends on: the secret is valid, the app can mint a
``https://ai.azure.com`` token, and the identity is authorized on the specialist's
A2A endpoint (the app's service principal holds the ``Foundry Agent Consumer``
role granted by the provisioning script). It then fetches the specialist's A2A
agent card and sends it a message, exactly like ``scripts.test_a2a_specialist``.

Install the client deps (one-off)::

    pip install "a2a-sdk==1.0.2" "httpx==0.28.1" "azure-identity>=1.25"

Run (reads ``./.env``; flags override)::

    python -m scripts.test_copilot_studio_a2a_auth \\
        --client-id <CLIENT_ID> --client-secret <CLIENT_SECRET>

    python -m scripts.test_copilot_studio_a2a_auth "Which category grows fastest in the Nordics?"

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT           Foundry project endpoint (required).
  AZURE_AI_SPECIALIST_AGENT_NAME      Target agent name (default: marketing-specialist-agent).
  AZURE_TENANT_ID                     Entra tenant id (else the signed-in az tenant).
  COPILOT_STUDIO_A2A_CLIENT_ID        Client id (when --client-id is omitted).
  COPILOT_STUDIO_A2A_CLIENT_SECRET    Client secret (when --client-secret is omitted).
  A2A_TEST_MESSAGE                    Default message when none is passed on the CLI.

Note: A2A on Foundry is text-only, non-streaming and in preview.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import httpx
from azure.identity import ClientSecretCredential
from dotenv import load_dotenv

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types.a2a_pb2 import Role, SendMessageRequest

from scripts._cli import normalize

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=True)
load_dotenv(override=False)

# Agent card path, relative to the A2A base URL (selects A2A v1.0).
_AGENT_CARD_PATH = "agentCard/v1.0"
# Audience/scope the Foundry A2A endpoint accepts (Azure AI data plane).
_AI_SCOPE = "https://ai.azure.com/.default"


def _a2a_base_url(project_endpoint: str, agent_name: str) -> str:
    return (
        f"{project_endpoint.rstrip('/')}/agents/{agent_name}"
        "/endpoint/protocols/a2a"
    )


def _resolve_tenant_id() -> str:
    tenant = os.getenv("AZURE_TENANT_ID", "").strip()
    if tenant:
        return tenant
    result = subprocess.run(
        normalize(["az", "account", "show", "--query", "tenantId", "-o", "tsv"]),
        check=False, capture_output=True, text=True,
    )
    return result.stdout.strip()


async def _run(base_url: str, message_text: str, credential: ClientSecretCredential) -> int:
    print("==> Acquiring app-only token (client-credentials flow) for "
          f"{_AI_SCOPE}")
    token = credential.get_token(_AI_SCOPE).token
    print("    Token acquired OK.")

    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(120.0),
    ) as httpx_client:
        print(f"\n==> Resolving agent card: {base_url}/{_AGENT_CARD_PATH}")
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=base_url,
            agent_card_path=_AGENT_CARD_PATH,
        )
        agent_card = await resolver.get_agent_card()
        print(f"    Card OK: name={getattr(agent_card, 'name', '?')!r} "
              f"protocolVersion={getattr(agent_card, 'protocol_version', '?')!r}")

        config = ClientConfig(streaming=False, httpx_client=httpx_client)
        client = await create_client(agent=agent_card, client_config=config)

        print(f"\n==> Sending message:\n    {message_text}\n")
        message = new_text_message(message_text, role=Role.ROLE_USER)
        request = SendMessageRequest(message=message)

        got_response = False
        async for response in client.send_message(request):
            got_response = True
            print("---- A2A response ----")
            print(response)
        await client.close()

    if not got_response:
        print("WARN: no response received from the specialist.")
        return 1
    print("\nDone. The Copilot Studio credentials authenticate to the specialist A2A "
          "endpoint successfully.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client-id",
        default=os.getenv("COPILOT_STUDIO_A2A_CLIENT_ID", "").strip(),
        help="App (client) id from create_copilot_studio_a2a_auth.",
    )
    parser.add_argument(
        "--client-secret",
        default=os.getenv("COPILOT_STUDIO_A2A_CLIENT_SECRET", "").strip(),
        help="Client secret from create_copilot_studio_a2a_auth.",
    )
    parser.add_argument(
        "--tenant-id",
        default=_resolve_tenant_id(),
        help="Entra tenant id (defaults to AZURE_TENANT_ID or the signed-in az tenant).",
    )
    parser.add_argument(
        "message", nargs="*",
        help="Message to send to the specialist (optional).",
    )
    args = parser.parse_args(argv)

    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip()
    if not project_endpoint:
        print("ERROR: AZURE_AI_PROJECT_ENDPOINT is required (set it in ./.env).",
              file=sys.stderr)
        return 1
    if not args.client_id or not args.client_secret:
        print(
            "ERROR: a client id and secret are required. Pass --client-id / "
            "--client-secret, or set COPILOT_STUDIO_A2A_CLIENT_ID / "
            "COPILOT_STUDIO_A2A_CLIENT_SECRET in ./.env.",
            file=sys.stderr,
        )
        return 1
    if not args.tenant_id:
        print("ERROR: could not resolve a tenant id. Pass --tenant-id or set "
              "AZURE_TENANT_ID in ./.env.", file=sys.stderr)
        return 1

    agent_name = os.getenv("AZURE_AI_SPECIALIST_AGENT_NAME", "marketing-specialist-agent")
    message_text = (
        " ".join(args.message).strip()
        or os.getenv("A2A_TEST_MESSAGE", "").strip()
        or "What is happening in the German vitamins & supplements market? "
        "Give me the top growth categories and the personas to target."
    )

    base_url = _a2a_base_url(project_endpoint, agent_name)
    print(f"==> Target specialist: {agent_name}")
    print(f"    A2A base path:     {base_url}")
    print(f"    Client id:         {args.client_id}")
    print(f"    Tenant id:         {args.tenant_id}\n")

    credential = ClientSecretCredential(
        tenant_id=args.tenant_id,
        client_id=args.client_id,
        client_secret=args.client_secret,
    )

    try:
        return asyncio.run(_run(base_url, message_text, credential))
    except httpx.HTTPStatusError as exc:
        body = exc.response.text if exc.response is not None else ""
        print(f"\nERROR: HTTP {exc.response.status_code if exc.response else '?'} "
              f"from the A2A endpoint:\n{body[:1500]}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - surface any client error for a local test
        print(f"\nERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
