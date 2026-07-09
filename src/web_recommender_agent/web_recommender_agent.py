"""Web Recommender Agent — AG-UI NorthStar Health marketing assistant.

Agent logic and tool definitions for the ``web_recommender_agent`` AG-UI server.
It is a marketing-facing assistant that lets a marketer discuss customer
**personas** and explore **products** and **market performance** through a custom
web UI, backed by the Foundry ``marketing_toolbox`` (product + market insights +
persona MCP servers).

Tools:
  - update_overview          AG-UI sidebar push (focus persona, products, note)
  - marketing toolbox        product / market / persona MCP tools (via toolbox)

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT      Foundry project endpoint (required).
  AZURE_OPENAI_CHAT_DEPLOYMENT_NAME / AZURE_AI_MODEL_DEPLOYMENT_NAME
  MARKETING_TOOLBOX_NAME         Foundry toolbox name (default: marketing_toolbox).
  MARKETING_TOOLBOX_MCP_ENDPOINT explicit toolbox MCP endpoint (optional).
  MARKETING_MCP_URL              direct marketing MCP URL for local dev (optional).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

import httpx
from agent_framework import Agent, Content, MCPStreamableHTTPTool, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_ag_ui import state_update
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent / "skills"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_PROJECT_ENDPOINT = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
_MODEL = (
    os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")
    or os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    or "gpt-4.1-mini"
)

_MARKETING_TOOLBOX_NAME = os.getenv("MARKETING_TOOLBOX_NAME", "marketing_toolbox")
_MARKETING_TOOLBOX_ENDPOINT = os.getenv("MARKETING_TOOLBOX_MCP_ENDPOINT") or (
    f"{_PROJECT_ENDPOINT.rstrip('/')}/toolboxes/{_MARKETING_TOOLBOX_NAME}/mcp?api-version=v1"
)
_DIRECT_MARKETING_MCP_URL = os.getenv("MARKETING_MCP_URL", "").strip()

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

BASE_INSTRUCTIONS = """\
You are the NorthStar Health marketing assistant. You help a marketer explore
customer personas, products and market performance, and shape campaign and
launch ideas for a European consumer healthcare company operating in Germany,
the UK and the Nordics across Vitamins & Supplements, Gut Health, Weight
Management and Home Diagnostics.

## Your capabilities
- You have access to the **marketing toolbox** with product, market-insights and
  persona tools. Use them for every question that needs real data — never invent
  numbers, personas or products.
  - persona tools: search personas, filter by market/category/interest, inspect
    a persona's behaviour, interests and spend.
  - product tools: list/search products, compare competitor positioning.
  - market insights tools: sales, growth rates, market share, margins, forecasts.

## Keep the sidebar current (MANDATORY)
- Call `update_overview` whenever you focus on a persona or surface a set of
  products — ALWAYS before you write the chat reply. Pass the COMPLETE current
  state each time.

## Style
- Answer in English, friendly, concise and precise.
- Present personas and product lists in a readable way (short lists or tables).
- Ground every claim in a tool result and be explicit about assumptions.
"""


def _load_skills() -> str:
    if not _SKILLS_DIR.exists():
        return ""
    parts: list[str] = []
    for skill_file in sorted(_SKILLS_DIR.glob("*/SKILL.md")):
        parts.append(skill_file.read_text(encoding="utf-8").strip())
    if not parts:
        return ""
    return "\n\n---\n\n# Domain skills\n\n" + "\n\n---\n\n".join(parts)


SYSTEM_PROMPT = BASE_INSTRUCTIONS + _load_skills()


# ---------------------------------------------------------------------------
# AG-UI sidebar state schema
# ---------------------------------------------------------------------------

class PersonaCard(BaseModel):
    persona_id: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    market: Optional[str] = Field(default=None)
    archetype: Optional[str] = Field(default=None)


class ProductRow(BaseModel):
    product_id: str
    product_name: str
    category: Optional[str] = Field(default=None)
    price_tier: Optional[str] = Field(default=None)
    list_price: Optional[float] = Field(default=None)


class FocusNote(BaseModel):
    topic: Optional[str] = Field(default=None)
    summary: Optional[str] = Field(default=None)


@tool
def update_overview(
    persona: PersonaCard,
    products: List[ProductRow],
    note: FocusNote,
) -> Content:
    """Refresh the live sidebar (focus persona, products, note).

    Call this whenever you focus on a persona or surface a set of products.
    Always pass the COMPLETE current state. Call BEFORE writing the chat reply.
    """
    return state_update(
        text="Overview updated.",
        state={
            "persona": PersonaCard.model_validate(persona).model_dump(),
            "products": [ProductRow.model_validate(p).model_dump() for p in products],
            "note": FocusNote.model_validate(note).model_dump(),
        },
    )


# ---------------------------------------------------------------------------
# Toolbox auth helper
# ---------------------------------------------------------------------------

class _ToolboxAuth(httpx.Auth):
    def __init__(self, token_provider):
        self._get_token = token_provider

    def auth_flow(self, request):
        request.headers["Authorization"] = "Bearer " + self._get_token()
        yield request


# ---------------------------------------------------------------------------
# Factory functions (called once at server startup)
# ---------------------------------------------------------------------------

def make_marketing_tool(credential: DefaultAzureCredential) -> MCPStreamableHTTPTool:
    """Build the marketing toolbox MCP tool (direct URL for local dev, else toolbox)."""
    if _DIRECT_MARKETING_MCP_URL:
        logger.info("Using direct marketing MCP endpoint %s", _DIRECT_MARKETING_MCP_URL)
        return MCPStreamableHTTPTool(
            name="marketing", url=_DIRECT_MARKETING_MCP_URL, load_prompts=False
        )
    token_provider = get_bearer_token_provider(credential, "https://ai.azure.com/.default")
    http_client = httpx.AsyncClient(
        auth=_ToolboxAuth(token_provider),
        headers={"Foundry-Features": "Toolboxes=V1Preview"},
        timeout=120.0,
    )
    logger.info("Using Foundry toolbox marketing endpoint %s", _MARKETING_TOOLBOX_ENDPOINT)
    return MCPStreamableHTTPTool(
        name="marketing",
        url=_MARKETING_TOOLBOX_ENDPOINT,
        http_client=http_client,
        load_prompts=False,
    )


def make_chat_client(credential: DefaultAzureCredential) -> FoundryChatClient:
    return FoundryChatClient(
        project_endpoint=_PROJECT_ENDPOINT,
        model=_MODEL,
        credential=credential,
    )


def make_agent(
    foundry_client: "FoundryChatClient",
    marketing_tool: MCPStreamableHTTPTool,
) -> "Agent":
    """Assemble and return the web recommender agent."""
    tools = [update_overview, marketing_tool]
    return foundry_client.as_agent(
        name="WebRecommenderAgent",
        instructions=SYSTEM_PROMPT,
        tools=tools,
    )
