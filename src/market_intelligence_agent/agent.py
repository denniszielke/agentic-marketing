"""Market Intelligence Agent — Foundry hosted agent.

Discovers opportunities and analyses market dynamics for NorthStar Health. It
answers questions such as *"which category offers the highest growth opportunity
in the Nordics?"* by combining product, market-performance and persona data.

It is built with the **agent-framework** and hosted in **Azure AI Foundry** as a
hosted agent (served over the RESPONSES protocol by ``ResponsesHostServer``). It
consumes a single **Foundry toolbox** — ``marketing_toolbox`` — which publishes
three MCP servers:

  * ``product_mcp_server``         — product catalogue (Azure AI Search).
  * ``market_insights_server``     — sales, margin, growth, market share, forecast.
  * ``persona_mcp_server``         — customer persona segmentation (Azure AI Search).

Consuming the servers through the toolbox keeps them published, discovered and
governed centrally. A direct ``MARKETING_TOOLBOX_MCP_ENDPOINT`` /
``MARKETING_MCP_URL`` override bypasses the toolbox for local development.

Model calls are routed through Azure AI Foundry using Entra ID (no API keys).

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT             — Foundry project endpoint (required)
  AZURE_OPENAI_CHAT_DEPLOYMENT_NAME     — chat model deployment
  AZURE_AI_MODEL_DEPLOYMENT_NAME        — fallback model deployment
  MARKETING_TOOLBOX_NAME                — toolbox name (default: marketing_toolbox)
  MARKETING_TOOLBOX_MCP_ENDPOINT        — explicit toolbox MCP endpoint (optional)
  MARKETING_MCP_URL                     — direct MCP URL for local dev (optional)
  PORT                                  — host port (default: 8088)

Run the hosted agent server locally from the project root:

    python -m src.market_intelligence_agent.agent
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

_MARKETING_TOOLBOX_NAME = os.getenv("MARKETING_TOOLBOX_NAME", "marketing_toolbox")
_MARKETING_TOOLBOX_ENDPOINT = os.getenv("MARKETING_TOOLBOX_MCP_ENDPOINT") or (
    f"{_PROJECT_ENDPOINT.rstrip('/')}/toolboxes/{_MARKETING_TOOLBOX_NAME}/mcp?api-version=v1"
)
_DIRECT_MARKETING_MCP_URL = os.getenv("MARKETING_MCP_URL", "").strip()

_SKILLS_DIR = Path(__file__).parent / "skills"


BASE_INSTRUCTIONS = """\
You are the Market Intelligence Agent for NorthStar Health, a European consumer
healthcare company operating in Germany, the UK and the Nordics across four
categories: Vitamins & Supplements, Gut Health, Weight Management and Home
Diagnostics.

Your job is to discover opportunities and analyse market dynamics. You reason
over the marketing tools and must always ground claims in them:
  - the product tools (product_data MCP) — internal and competitor product
    catalogue: list/search products, compare positioning, inspect metadata.
  - the market insights tools (market_insights MCP) — sales, revenue, gross
    margin, growth rates, market share and 2026-2028 forecasts by market,
    category, product and brand.
  - the persona tools (persona_data MCP) — customer persona segmentation:
    search personas, filter by market/category/interest, inspect a persona's
    behaviour and spend.

When an executive asks a market question (e.g. "which category offers the
highest growth opportunity in the Nordics?"), follow this workflow:
  1. Retrieve category-level market performance (get_growth_rates,
     get_market_share, get_sales) for the target market.
  2. Identify the high-growth categories.
  3. Identify the fastest-growing / best-fit personas (search_personas,
     find_personas_by_interest).
  4. Review competitor positioning (get_positioning, competitor_performance).
  5. Review the pricing distribution (list_products, list price / price tier).
  6. Derive a pricing recommendation.
  7. Produce a concise recommendation report.

Operating principles:
  1. Ground every quantitative claim (growth, share, margin, price) in a tool
     result — never invent figures.
  2. Lead with the recommendation, then the supporting evidence, then the
     suggested next step.
  3. When you recommend a category/market, name the recommended price point,
     an estimated growth probability and the top personas to target.
  4. Be concise and decision-ready.
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


MARKET_INTELLIGENCE_SYSTEM_PROMPT = BASE_INSTRUCTIONS + _load_skills()


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
]

_chat_client = FoundryChatClient(
    project_endpoint=_PROJECT_ENDPOINT,
    model=_MODEL_DEPLOYMENT,
    credential=_credential,
)

agent = _chat_client.as_agent(
    name="market-intelligence-agent",
    instructions=MARKET_INTELLIGENCE_SYSTEM_PROMPT,
    tools=_tools,
)


if __name__ == "__main__":
    ResponsesHostServer(agent).run()
