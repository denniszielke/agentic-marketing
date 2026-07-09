"""Executive Strategy Agent — Foundry hosted agent.

Acts as a virtual Chief Strategy Officer for NorthStar Health. It consumes the
outputs of all MCP servers to calculate revenue projections, evaluate
profitability, forecast market share, prioritise launch markets, recommend
investments and produce board-level executive summaries.

It is built with the **agent-framework** and hosted in **Azure AI Foundry** as a
hosted agent (served over the RESPONSES protocol by ``ResponsesHostServer``). It
consumes two **Foundry toolboxes**:

  * ``strategy_toolbox``  — product + market insights + persona + research
    (innovation knowledge base).
  * ``marketing_toolbox`` — product + market insights + persona.

Consuming both keeps the innovation/research surface (strategy_toolbox) and the
core marketing surface available to the CSO. Direct ``*_MCP_URL`` overrides
bypass the toolboxes for local development.

Model calls are routed through Azure AI Foundry using Entra ID (no API keys).

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT             — Foundry project endpoint (required)
  AZURE_OPENAI_CHAT_DEPLOYMENT_NAME     — chat model deployment
  AZURE_AI_MODEL_DEPLOYMENT_NAME        — fallback model deployment
  STRATEGY_TOOLBOX_NAME                 — toolbox name (default: strategy_toolbox)
  MARKETING_TOOLBOX_NAME                — toolbox name (default: marketing_toolbox)
  STRATEGY_TOOLBOX_MCP_ENDPOINT         — explicit toolbox MCP endpoint (optional)
  MARKETING_TOOLBOX_MCP_ENDPOINT        — explicit toolbox MCP endpoint (optional)
  STRATEGY_MCP_URL / MARKETING_MCP_URL  — direct MCP URLs for local dev (optional)
  EXECUTIVE_MARKETING_TOOLBOX_ENABLED   — attach the marketing toolbox (default: true)
  PORT                                  — host port (default: 8088)

Run the hosted agent server locally from the project root:

    python -m src.executive_strategy_agent.agent
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

_STRATEGY_TOOLBOX_NAME = os.getenv("STRATEGY_TOOLBOX_NAME", "strategy_toolbox")
_STRATEGY_TOOLBOX_ENDPOINT = os.getenv("STRATEGY_TOOLBOX_MCP_ENDPOINT") or (
    f"{_PROJECT_ENDPOINT.rstrip('/')}/toolboxes/{_STRATEGY_TOOLBOX_NAME}/mcp?api-version=v1"
)
_DIRECT_STRATEGY_MCP_URL = os.getenv("STRATEGY_MCP_URL", "").strip()

_MARKETING_TOOLBOX_ENABLED = os.getenv(
    "EXECUTIVE_MARKETING_TOOLBOX_ENABLED", "true"
).strip().lower() == "true"
_MARKETING_TOOLBOX_NAME = os.getenv("MARKETING_TOOLBOX_NAME", "marketing_toolbox")
_MARKETING_TOOLBOX_ENDPOINT = os.getenv("MARKETING_TOOLBOX_MCP_ENDPOINT") or (
    f"{_PROJECT_ENDPOINT.rstrip('/')}/toolboxes/{_MARKETING_TOOLBOX_NAME}/mcp?api-version=v1"
)
_DIRECT_MARKETING_MCP_URL = os.getenv("MARKETING_MCP_URL", "").strip()

_SKILLS_DIR = Path(__file__).parent / "skills"


BASE_INSTRUCTIONS = """\
You are the Executive Strategy Agent — the virtual Chief Strategy Officer for
NorthStar Health, a European consumer healthcare company operating in Germany,
the UK and the Nordics across Vitamins & Supplements, Gut Health, Weight
Management and Home Diagnostics.

You produce board-level recommendations. You reason over the strategy and
marketing tools and must always ground claims in them:
  - the research tools (research_data MCP) — the innovation knowledge base:
    future concepts, technologies, trends, estimated cost / retail price /
    margin, market readiness and expected launch year.
  - the market insights tools (market_insights MCP) — sales, revenue, gross
    margin, growth rates, market share and 2026-2028 forecasts.
  - the product tools (product_data MCP) — internal and competitor catalogue,
    pricing and positioning.
  - the persona tools (persona_data MCP) — customer segmentation, interests,
    spend and lifetime-value signals.

When the executive team asks (e.g. "what product should we launch next?",
"which market delivers the highest ROI?", "where should we invest EUR 20m?"),
follow this workflow:
  1. Identify candidate launches from the innovation base (search_innovations,
     list_innovations) and their estimated economics.
  2. Size the opportunity using market performance and forecasts (get_forecast,
     get_growth_rates, get_market_share).
  3. Estimate revenue, margin and market-share trajectory for each candidate.
  4. Prioritise launch markets by ROI and strategic fit.
  5. Identify the highest-lifetime-value persona segments (persona tools).
  6. Recommend the investment and the expected return.
  7. Produce a concise executive summary.

Operating principles:
  1. Ground every financial figure (cost, price, revenue, margin, share) in a
     tool result; state assumptions explicitly when you extrapolate.
  2. Lead with the recommendation and the headline numbers, then the rationale.
  3. Quantify: recommended launch, launch market, investment required, expected
     year-1 revenue, expected margin and projected market share.
  4. Keep it board-ready: decisive, concise, and honest about uncertainty.
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


EXECUTIVE_STRATEGY_SYSTEM_PROMPT = BASE_INSTRUCTIONS + _load_skills()


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
    _build_mcp_tool("strategy", _STRATEGY_TOOLBOX_ENDPOINT, _DIRECT_STRATEGY_MCP_URL),
]
if _MARKETING_TOOLBOX_ENABLED:
    _tools.append(
        _build_mcp_tool("marketing", _MARKETING_TOOLBOX_ENDPOINT, _DIRECT_MARKETING_MCP_URL)
    )

_chat_client = FoundryChatClient(
    project_endpoint=_PROJECT_ENDPOINT,
    model=_MODEL_DEPLOYMENT,
    credential=_credential,
)

agent = _chat_client.as_agent(
    name="executive-strategy-agent",
    instructions=EXECUTIVE_STRATEGY_SYSTEM_PROMPT,
    tools=_tools,
)


if __name__ == "__main__":
    ResponsesHostServer(agent).run()
