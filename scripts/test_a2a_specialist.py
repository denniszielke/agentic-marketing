"""Local test client for the **marketing specialist**'s A2A endpoint.

Connects to the specialist Foundry prompt agent over the **A2A protocol** (the
same way the supervisor does) and sends it a message, so you can verify the
specialist's incoming A2A endpoint and its marketing grounding independently of
the supervisor.

It uses the open-source Python A2A SDK. Because the Foundry agent card requires
Entra auth and lives at a custom path (``agentCard/v1.0`` rather than the default
``/.well-known/agent-card.json``), the ``httpx`` client is configured with a
bearer token and the resolver is pointed at the custom card path — which makes
the SDK negotiate A2A **v1.0** end to end.

Install the client deps (one-off)::

    pip install "a2a-sdk==1.0.2" "httpx==0.28.1" "azure-identity>=1.25"

Run (reads ``./.env``)::

    python -m scripts.test_a2a_specialist
    python -m scripts.test_a2a_specialist "Which category has the highest growth in the Nordics?"

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT       Foundry project endpoint (required).
  AZURE_AI_SPECIALIST_AGENT_NAME  Target agent name (default: marketing-specialist-agent).
  A2A_TEST_MESSAGE                 Default message when none is passed on the CLI.

Note: the calling identity (your ``az login`` user, via ``DefaultAzureCredential``)
must hold the **Foundry User** role on the project to read the card and call the
endpoint. A2A on Foundry is text-only, non-streaming and in preview.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types.a2a_pb2 import Role, SendMessageRequest

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=True)
load_dotenv(override=False)

# Agent card path, relative to the A2A base URL (selects A2A v1.0).
_AGENT_CARD_PATH = "agentCard/v1.0"


def _a2a_base_url(project_endpoint: str, agent_name: str) -> str:
    return (
        f"{project_endpoint.rstrip('/')}/agents/{agent_name}"
        "/endpoint/protocols/a2a"
    )


async def _run(base_url: str, message_text: str) -> int:
    credential = DefaultAzureCredential()
    token = credential.get_token("https://ai.azure.com/.default").token

    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(120.0),
    ) as httpx_client:
        print(f"==> Resolving agent card: {base_url}/{_AGENT_CARD_PATH}")
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
    print("\nDone.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip()
    if not project_endpoint:
        print("ERROR: AZURE_AI_PROJECT_ENDPOINT is required (set it in ./.env).",
              file=sys.stderr)
        return 1

    agent_name = os.getenv("AZURE_AI_SPECIALIST_AGENT_NAME", "marketing-specialist-agent")
    message_text = (
        " ".join(argv).strip()
        or os.getenv("A2A_TEST_MESSAGE", "").strip()
        or "What is happening in the German vitamins & supplements market? "
        "Give me the top growth categories and the personas to target."
    )

    base_url = _a2a_base_url(project_endpoint, agent_name)
    print(f"==> Target specialist: {agent_name}")
    print(f"    A2A base path: {base_url}\n")

    try:
        return asyncio.run(_run(base_url, message_text))
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
