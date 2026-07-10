"""Supervisor Agent — Foundry **hosted** agent (container) with A2A delegation.

This is the *supervisor* half of the agent-to-agent (A2A) demo, built as a
container-backed Foundry **hosted agent** (served over the RESPONSES protocol by
``ResponsesHostServer``). It:

  1. triages each incoming question and decides whether it is a *marketing*
     question (products, customer personas or market performance); and
  2. when it is, **delegates the task to the marketing specialist over A2A** —
     it calls the specialist's Foundry A2A endpoint directly with the
     open-source A2A client (``a2a-sdk``), authenticating with the container's
     managed identity (its Entra **Agent Identity**), and returns the
     specialist's grounded answer.

Because the supervisor is a hosted agent that runs its own code, it calls the
specialist through the A2A **client** (not the server-side ``A2APreviewTool``),
which avoids the prompt-agent connection/card-path plumbing entirely.

Incoming A2A is enabled on this agent natively by the deploy script
(``deploy_hosted_agent`` turns on the RESPONSES + A2A + INVOCATIONS protocols and
publishes the agent card), so other agents can also call the supervisor.

Model calls are routed through Azure AI Foundry using Entra ID (no API keys).

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT        Foundry project endpoint (required).
  AZURE_OPENAI_CHAT_DEPLOYMENT_NAME / AZURE_AI_MODEL_DEPLOYMENT_NAME  chat model.
  AZURE_AI_SPECIALIST_AGENT_NAME   Specialist agent name (default: marketing-specialist-agent).
  AZURE_AI_SPECIALIST_A2A_URL      Explicit specialist A2A base URL (optional; else derived).
  PORT                             host port (default: 8088).

Run the hosted agent server locally from the project root:

    python -m src.supervisor_agent.agent
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import httpx
from agent_framework import tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types.a2a_pb2 import Role, SendMessageRequest

# Allow standalone execution from the project root.
_src_root = Path(__file__).resolve().parents[2]
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_env_path if _env_path.exists() else None)

logging.basicConfig(level=logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_PROJECT_ENDPOINT = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
_MODEL = (
    os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")
    or os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    or "gpt-4.1-mini"
)
_SPECIALIST_NAME = os.getenv("AZURE_AI_SPECIALIST_AGENT_NAME", "marketing-specialist-agent")
_SPECIALIST_A2A_URL = os.getenv("AZURE_AI_SPECIALIST_A2A_URL", "").strip() or (
    f"{_PROJECT_ENDPOINT.rstrip('/')}/agents/{_SPECIALIST_NAME}/endpoint/protocols/a2a"
)
# Foundry serves the agent card at agentCard/v1.0 (not /.well-known/agent-card.json).
_AGENT_CARD_PATH = "agentCard/v1.0"

SUPERVISOR_SYSTEM_PROMPT = """\
You are the Supervisor agent for NorthStar Health, a European consumer healthcare
company operating in Germany, the UK and the Nordics across four categories:
Vitamins & Supplements, Gut Health, Weight Management and Home Diagnostics.

You have one tool, `ask_marketing_specialist`, which delegates a task to the
marketing specialist over A2A. The specialist is an expert on NorthStar Health's
products, customer personas and market performance (sales, revenue, gross margin,
growth rates, market share and forecasts), grounded in the marketing data.

For every incoming question:
  1. Decide whether it is a MARKETING question — i.e. it is about products,
     product positioning or pricing, customer personas/segments, or market
     performance (sales, growth, margin, share, forecasts) for NorthStar Health.
  2. If it IS a marketing question, call `ask_marketing_specialist` with a clear,
     self-contained task describing exactly what to find or produce, then return
     the specialist's answer to the user (you may briefly frame it, but do not
     invent or alter its facts).
  3. If it is NOT a marketing question, answer it yourself if it is trivial, or
     politely explain that it is out of scope for this marketing supervisor and
     that you can only help with product, persona and market questions.

Principles:
  - Never fabricate marketing figures yourself — always obtain them from the
    marketing specialist via the tool.
  - Be concise. Prefer delegating a single well-scoped task over many small ones.
"""


# ---------------------------------------------------------------------------
# A2A delegation
# ---------------------------------------------------------------------------
def _extract_text(response: object) -> str:
    """Pull any text parts out of an A2A send_message response (task or message)."""
    texts: list[str] = []
    candidates = response if isinstance(response, tuple) else (response,)
    for cand in candidates:
        if cand is None:
            continue
        task = getattr(cand, "task", None)
        if task is not None:
            for artifact in getattr(task, "artifacts", []) or []:
                for part in getattr(artifact, "parts", []) or []:
                    text = getattr(part, "text", "")
                    if text:
                        texts.append(text)
        message = getattr(cand, "msg", None) or getattr(cand, "message", None)
        if message is not None:
            parts = getattr(message, "content", None) or getattr(message, "parts", []) or []
            for part in parts:
                text = getattr(part, "text", "")
                if text:
                    texts.append(text)
    return "\n".join(texts).strip()


async def _call_specialist_a2a(task_text: str) -> str:
    """Send a task to the marketing specialist's A2A endpoint and return its reply."""
    credential = DefaultAzureCredential()
    token = credential.get_token("https://ai.azure.com/.default").token
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(120.0),
    ) as httpx_client:
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=_SPECIALIST_A2A_URL,
            agent_card_path=_AGENT_CARD_PATH,
        )
        agent_card = await resolver.get_agent_card()
        client = await create_client(
            agent=agent_card,
            client_config=ClientConfig(streaming=False, httpx_client=httpx_client),
        )
        request = SendMessageRequest(message=new_text_message(task_text, role=Role.ROLE_USER))
        chunks: list[str] = []
        async for response in client.send_message(request):
            chunks.append(_extract_text(response))
        await client.close()
    answer = "\n".join(c for c in chunks if c).strip()
    return answer or "(the marketing specialist returned no content)"


@tool
async def ask_marketing_specialist(task: str) -> str:
    """Delegate a marketing task to the NorthStar Health marketing specialist over A2A.

    Use this for any question about NorthStar Health products, product positioning
    or pricing, customer personas/segments, or market performance (sales, growth,
    gross margin, market share, forecasts). Pass a clear, self-contained task
    describing exactly what to find or produce. Returns the specialist's grounded
    answer verbatim.
    """
    logger.info("Delegating to specialist over A2A: %s", _SPECIALIST_A2A_URL)
    try:
        return await _call_specialist_a2a(task)
    except Exception as exc:  # noqa: BLE001 - surface delegation failures to the model
        logger.exception("A2A delegation failed")
        return f"ERROR delegating to the marketing specialist over A2A: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Agent assembly
# ---------------------------------------------------------------------------
_credential = DefaultAzureCredential()
_chat_client = FoundryChatClient(
    project_endpoint=_PROJECT_ENDPOINT,
    model=_MODEL,
    credential=_credential,
)

agent = _chat_client.as_agent(
    name="supervisor-agent",
    instructions=SUPERVISOR_SYSTEM_PROMPT,
    tools=[ask_marketing_specialist],
)


if __name__ == "__main__":
    ResponsesHostServer(agent).run()
