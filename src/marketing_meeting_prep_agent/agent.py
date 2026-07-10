"""Marketing Meeting Prep Agent — Foundry hosted agent.

Prepares a decision-ready briefing for the signed-in marketer's upcoming
meetings. It reads the meeting title / agenda / attendees from the user's
Microsoft 365 calendar (via **WorkIQ**) and then grounds the briefing in
NorthStar Health's marketing data — relevant products, market insights and
customer personas.

It is built with the **agent-framework** and hosted in **Azure AI Foundry** as a
hosted agent (served over the RESPONSES protocol by ``ResponsesHostServer``). It
consumes two **Foundry toolboxes**, each published as a single MCP endpoint:

  * ``marketing_toolbox`` — bundles three MCP servers, authenticated with the
    hosted agent's Entra **Agent Identity**:
      - ``product_mcp_server``      — product catalogue (Azure AI Search).
      - ``market_insights_server``  — sales, margin, growth, share, forecast.
      - ``persona_mcp_server``      — customer persona segmentation.
  * ``workiq_toolbox`` — the Microsoft Agent 365 WorkIQ MCP server (calendar),
    authenticated with **OAuth identity passthrough** so the calendar is read in
    the signed-in user's own context and honours Microsoft 365 permissions.

Consuming the servers through toolboxes keeps them published, discovered and
governed centrally. Direct ``*_MCP_URL`` overrides bypass the toolboxes for
local development.

Model calls are routed through Azure AI Foundry using Entra ID (no API keys).

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT             — Foundry project endpoint (required)
  AZURE_OPENAI_CHAT_DEPLOYMENT_NAME     — chat model deployment
  AZURE_AI_MODEL_DEPLOYMENT_NAME        — fallback model deployment
  MARKETING_TOOLBOX_NAME                — toolbox name (default: marketing_toolbox)
  MARKETING_TOOLBOX_MCP_ENDPOINT        — explicit toolbox MCP endpoint (optional)
  MARKETING_MCP_URL                     — direct marketing MCP URL for local dev (optional)
  WORKIQ_TOOLBOX_NAME                   — toolbox name (default: workiq-tools)
  WORKIQ_TOOLBOX_MCP_ENDPOINT           — explicit toolbox MCP endpoint (optional)
  WORKIQ_MCP_URL                        — direct WorkIQ MCP URL for local dev (optional)
  PORT                                  — host port (default: 8088)

Run the hosted agent server locally from the project root:

    python -m src.marketing_meeting_prep_agent.agent
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import httpx
from agent_framework import MCPStreamableHTTPTool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv

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
_MODEL_DEPLOYMENT = (
    os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")
    or os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    or "gpt-4.1-mini"
)


def _toolbox_endpoint(name: str) -> str:
    return f"{_PROJECT_ENDPOINT.rstrip('/')}/toolboxes/{name}/mcp?api-version=v1"


_MARKETING_TOOLBOX_NAME = os.getenv("MARKETING_TOOLBOX_NAME", "marketing_toolbox")
_MARKETING_TOOLBOX_ENDPOINT = os.getenv("MARKETING_TOOLBOX_MCP_ENDPOINT") or _toolbox_endpoint(
    _MARKETING_TOOLBOX_NAME
)
_DIRECT_MARKETING_MCP_URL = os.getenv("MARKETING_MCP_URL", "").strip()

_WORKIQ_TOOLBOX_NAME = os.getenv("WORKIQ_TOOLBOX_NAME", "workiq-tools")
_WORKIQ_TOOLBOX_ENDPOINT = os.getenv("WORKIQ_TOOLBOX_MCP_ENDPOINT") or _toolbox_endpoint(
    _WORKIQ_TOOLBOX_NAME
)
_DIRECT_WORKIQ_MCP_URL = os.getenv("WORKIQ_MCP_URL", "").strip()

_SKILLS_DIR = Path(__file__).parent / "skills"


BASE_INSTRUCTIONS = """\
You are the Marketing Meeting Prep Agent for NorthStar Health, a European
consumer healthcare company operating in Germany, the UK and the Nordics across
four categories: Vitamins & Supplements, Gut Health, Weight Management and Home
Diagnostics.

Your job is to prepare a decision-ready briefing for the signed-in marketer's
upcoming meetings. You have two tool surfaces and must always ground claims in
them:
  - the WorkIQ calendar tools (workiq MCP) — read the signed-in user's Microsoft
    365 calendar in their own user context: list upcoming events, and inspect a
    meeting's subject/title, agenda/body and attendees. Never fabricate a
    meeting; only report what the calendar returns.
  - the marketing tools (marketing toolbox MCP):
      - the product tools (product_data) — internal and competitor product
        catalogue: list/search products, compare positioning, inspect metadata.
      - the market insights tools (market_insights) — sales, revenue, gross
        margin, growth rates, market share and 2026-2028 forecasts by market,
        category, product and brand.
      - the persona tools (persona_data) — customer persona segmentation:
        search personas, filter by market/category/interest, inspect a
        persona's behaviour and spend.

When asked to prepare for a meeting, follow this workflow:
  1. Resolve the meeting. If the user names a meeting, find it on their
     calendar; otherwise take the next upcoming meeting. Extract the title,
     agenda/body, date/time and attendees from WorkIQ.
  2. Derive the relevant markets, categories, products, brands or personas from
     the meeting title and agenda text.
  3. Pull the relevant product details (list_products / search_products /
     get_positioning) for the derived products or categories.
  4. Pull the relevant market insights (get_sales, get_growth_rates,
     get_market_share, get_forecast) for the derived market(s) and category(ies).
  5. Pull the relevant persona briefings (search_personas,
     find_personas_by_interest) for the derived audience.
  6. Assemble a concise briefing.

Operating principles:
  1. Ground every quantitative claim (growth, share, margin, price) in a tool
     result — never invent figures — and attribute calendar facts to WorkIQ.
  2. If the calendar has no matching meeting, say so and ask the user to name
     the meeting or date rather than guessing.
  3. Lead with the meeting header (title, date/time, attendees), then the
     briefing (products, market, personas), then 2-3 suggested talking points.
  4. Be concise and decision-ready. Respect Microsoft 365 permissions — you only
     see what the signed-in user can see.
"""


def _load_skills() -> str:
    """Concatenate every SKILL.md under ``skills/`` into the system prompt."""
    if not _SKILLS_DIR.exists():
        return ""
    parts: list[str] = []
    for skill_file in sorted(_SKILLS_DIR.glob("*/SKILL.md")):
        parts.append(skill_file.read_text(encoding="utf-8").strip())
    if not parts:
        return ""
    return "\n\n---\n\n# Domain skills\n\n" + "\n\n---\n\n".join(parts)


MEETING_PREP_SYSTEM_PROMPT = BASE_INSTRUCTIONS + _load_skills()


# ---------------------------------------------------------------------------
# Identity / credential
# ---------------------------------------------------------------------------

_credential = DefaultAzureCredential()
_toolbox_token_provider = get_bearer_token_provider(
    _credential, "https://ai.azure.com/.default"
)


class _ToolboxAuth(httpx.Auth):
    """Inject a fresh Entra token on every Foundry toolbox MCP request."""

    def __init__(self, token_provider):
        self._get_token = token_provider

    def auth_flow(self, request):
        request.headers["Authorization"] = "Bearer " + self._get_token()
        yield request


def _toolbox_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        auth=_ToolboxAuth(_toolbox_token_provider),
        headers={"Foundry-Features": "Toolboxes=V1Preview"},
        timeout=120.0,
    )


def _build_mcp_tool(name: str, toolbox_endpoint: str, direct_url: str) -> MCPStreamableHTTPTool:
    """Build an MCP tool, preferring a direct URL for local dev over the toolbox."""
    if direct_url:
        logger.info("Using direct %s MCP endpoint %s", name, direct_url)
        return MCPStreamableHTTPTool(name=name, url=direct_url, load_prompts=False)
    logger.info("Using Foundry toolbox %s endpoint %s", name, toolbox_endpoint)
    return MCPStreamableHTTPTool(
        name=name,
        url=toolbox_endpoint,
        http_client=_toolbox_http_client(),
        load_prompts=False,
    )


# ---------------------------------------------------------------------------
# Agent assembly
# ---------------------------------------------------------------------------

_tools: list = [
    _build_mcp_tool("marketing", _MARKETING_TOOLBOX_ENDPOINT, _DIRECT_MARKETING_MCP_URL),
    _build_mcp_tool("workiq", _WORKIQ_TOOLBOX_ENDPOINT, _DIRECT_WORKIQ_MCP_URL),
]

_chat_client = FoundryChatClient(
    project_endpoint=_PROJECT_ENDPOINT,
    model=_MODEL_DEPLOYMENT,
    credential=_credential,
)

agent = _chat_client.as_agent(
    name="marketing-meeting-prep-agent",
    instructions=MEETING_PREP_SYSTEM_PROMPT,
    tools=_tools,
)


if __name__ == "__main__":
    ResponsesHostServer(agent).run()
