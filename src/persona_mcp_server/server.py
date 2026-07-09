"""Persona MCP server for the NorthStar Health marketing ecosystem.

Exposes the customer **persona segmentation** over the Model Context Protocol,
backed by an **Azure AI Search** index (``personas``). The marketing agents use
it to look up personas by market / category / age / income / interest and to
search personas semantically by their behavioural backstory.

The index is populated by ``scripts/ingest_knowledge.py`` from
``data/personas.json``. Every MCP tool call may be authenticated via Entra ID
(FastMCP Azure JWT verifier), toggled with ``ENTRA_AUTH_ENABLED``.

Run it with::

    python -m src.persona_mcp_server.server

It serves the streamable-HTTP MCP transport on ``http://127.0.0.1:8094/mcp`` by
default (override with ``PERSONA_MCP_HOST`` / ``PERSONA_MCP_PORT``).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

_HOST = os.getenv("PERSONA_MCP_HOST", "127.0.0.1")
_PORT = int(os.getenv("PERSONA_MCP_PORT", "8094"))

_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT", "").strip()
_SEARCH_API_KEY = os.getenv("AZURE_SEARCH_ADMIN_KEY", "").strip()
_INDEX_NAME = os.getenv("AZURE_SEARCH_PERSONAS_INDEX_NAME", "personas")

_FIELDS = [
    "id", "name", "market", "archetype", "age", "gender", "income_band",
    "risk_tolerance", "digital_maturity", "interests", "preferred_categories",
    "preferred_channel", "annual_spend", "description",
]


def _build_auth():
    """Build the FastMCP Microsoft Entra ID JWT auth provider, or ``None``."""
    enabled = os.getenv("ENTRA_AUTH_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
    client_id = os.getenv("MCP_AUTH_CLIENT_ID", "").strip()
    tenant_id = os.getenv("AZURE_TENANT_ID", "").strip()
    if not (enabled and client_id and tenant_id):
        return None
    from fastmcp.server.auth import RemoteAuthProvider
    from fastmcp.server.auth.providers.azure import AzureJWTVerifier
    from pydantic import AnyHttpUrl

    base_url = os.getenv("MCP_PUBLIC_BASE_URL", "").strip() or f"http://{_HOST}:{_PORT}"
    verifier = AzureJWTVerifier(client_id=client_id, tenant_id=tenant_id)
    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[
            AnyHttpUrl(f"https://login.microsoftonline.com/{tenant_id}/v2.0")
        ],
        base_url=base_url,
    )


def _search_client():
    """Create a synchronous Azure AI Search client for the personas index."""
    if not _SEARCH_ENDPOINT:
        return None
    from azure.search.documents import SearchClient

    if _SEARCH_API_KEY:
        from azure.core.credentials import AzureKeyCredential

        credential: Any = AzureKeyCredential(_SEARCH_API_KEY)
    else:
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
    return SearchClient(endpoint=_SEARCH_ENDPOINT, index_name=_INDEX_NAME,
                        credential=credential)


def _project(doc: dict[str, Any]) -> dict[str, Any]:
    return {f: doc.get(f) for f in _FIELDS}


def _escape(value: str) -> str:
    return value.replace("'", "''")


mcp = FastMCP(
    name="persona_data",
    instructions=(
        "NorthStar Health customer personas across Germany, UK and Nordics. Each "
        "persona carries demographics (age, gender, income band), behaviour "
        "(risk tolerance, digital maturity), health interests, preferred product "
        "categories, preferred channel and annual spend, plus a narrative "
        "backstory. Use these tools to look up personas by market / category / "
        "age group / income band / interest, retrieve a single persona, or "
        "search personas semantically by their needs and behaviour."
    ),
    auth=_build_auth(),
)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_: Request) -> JSONResponse:
    """Readiness probe endpoint — returns 200 OK when the server is up."""
    return JSONResponse({"status": "ok"})


@mcp.tool()
def list_personas(market: Optional[str] = None, category: Optional[str] = None,
                  age_group: Optional[str] = None, income_band: Optional[str] = None,
                  top: int = 50) -> list[dict[str, Any]]:
    """List personas, optionally filtered.

    Args:
        market: Optional market filter — "Germany", "UK" or "Nordics".
        category: Optional preferred-category filter (e.g. "Home Diagnostics").
        age_group: Optional age band — "young" (<35), "mid" (35-54) or
            "senior" (55+).
        income_band: Optional income band — "Low", "Middle", "High" or "Affluent".
        top: Maximum number of personas to return (default 50).
    """
    client = _search_client()
    if client is None:
        return [{"error": "AZURE_SEARCH_ENDPOINT is not configured."}]
    filters = []
    if market:
        filters.append(f"market eq '{_escape(market)}'")
    if income_band:
        filters.append(f"income_band eq '{_escape(income_band)}'")
    if category:
        filters.append(f"preferred_categories/any(c: c eq '{_escape(category)}')")
    if age_group:
        ranges = {"young": "age lt 35", "mid": "age ge 35 and age lt 55",
                  "senior": "age ge 55"}
        clause = ranges.get(age_group.strip().lower())
        if clause:
            filters.append(f"({clause})")
    filter_expr = " and ".join(filters) if filters else None
    try:
        response = client.search(
            search_text="*", filter=filter_expr,
            select=",".join(_FIELDS), top=max(1, top),
        )
        return [_project(doc) for doc in response]
    finally:
        client.close()


@mcp.tool()
def search_personas(query: str, top: int = 10) -> list[dict[str, Any]]:
    """Search personas semantically by need, motivation or behaviour.

    Args:
        query: Free-text query, e.g. "biohacker interested in longevity",
            "budget-conscious pharmacy shopper", "GLP-1 weight management user".
        top: Maximum number of personas to return (default 10).
    """
    client = _search_client()
    if client is None:
        return [{"error": "AZURE_SEARCH_ENDPOINT is not configured."}]
    try:
        response = client.search(
            search_text=query,
            query_type="semantic",
            semantic_configuration_name="personas-semantic",
            select=",".join(_FIELDS), top=max(1, top),
        )
        return [_project(doc) for doc in response]
    except Exception:
        response = client.search(search_text=query, select=",".join(_FIELDS),
                                 top=max(1, top))
        return [_project(doc) for doc in response]
    finally:
        client.close()


@mcp.tool()
def get_persona(persona_id: str) -> dict[str, Any]:
    """Get a single persona's full profile by id (e.g. "GER-001").

    Returns the persona's fields, or an ``error`` field if none matches.
    """
    client = _search_client()
    if client is None:
        return {"error": "AZURE_SEARCH_ENDPOINT is not configured."}
    try:
        doc = client.get_document(key=persona_id.strip())
        return _project(doc)
    except Exception:
        return {"error": f"No persona matched '{persona_id}'."}
    finally:
        client.close()


@mcp.tool()
def find_personas_by_interest(interest: str, top: int = 20) -> list[dict[str, Any]]:
    """Find personas whose health interests match a topic.

    Args:
        interest: A health interest, e.g. "Heart Health", "Sleep",
            "Cognitive Performance", "Longevity".
        top: Maximum number of personas to return (default 20).
    """
    client = _search_client()
    if client is None:
        return [{"error": "AZURE_SEARCH_ENDPOINT is not configured."}]
    try:
        response = client.search(
            search_text=interest,
            search_fields="interests",
            select=",".join(_FIELDS), top=max(1, top),
        )
        return [_project(doc) for doc in response]
    finally:
        client.close()


def _configure_telemetry() -> None:
    """Wire OpenTelemetry to Application Insights when configured."""
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection_string:
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(connection_string=connection_string)
        logging.getLogger(__name__).info("Application Insights telemetry enabled.")
    except Exception as exc:  # pragma: no cover - best effort
        logging.getLogger(__name__).warning("Telemetry not configured: %s", exc)


def main() -> None:
    """Entry point — serve the persona data over streamable-HTTP MCP."""
    logging.basicConfig(level=os.environ.get("MCP_LOG_LEVEL", "INFO"))
    _configure_telemetry()
    mcp.run(
        transport="http",
        host=_HOST,
        port=_PORT,
        host_origin_protection=False,
    )


if __name__ == "__main__":
    main()
