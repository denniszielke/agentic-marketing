"""Research MCP server for the NorthStar Health marketing ecosystem.

Exposes the healthcare **innovation knowledge repository** over the Model Context
Protocol, backed by an **Azure AI Search** index (``innovations``). The strategy
agent uses it to explore emerging trends, innovation opportunities, future
product categories and their estimated economics.

The index is populated by ``scripts/ingest_knowledge.py`` from
``data/research_innovations.json``. Every MCP tool call may be authenticated via
Entra ID (FastMCP Azure JWT verifier), toggled with ``ENTRA_AUTH_ENABLED``.

Run it with::

    python -m src.research_mcp_server.server

It serves the streamable-HTTP MCP transport on ``http://127.0.0.1:8095/mcp`` by
default (override with ``RESEARCH_MCP_HOST`` / ``RESEARCH_MCP_PORT``).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

_HOST = os.getenv("RESEARCH_MCP_HOST", "127.0.0.1")
_PORT = int(os.getenv("RESEARCH_MCP_PORT", "8095"))

_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT", "").strip()
_SEARCH_API_KEY = os.getenv("AZURE_SEARCH_ADMIN_KEY", "").strip()
_INDEX_NAME = os.getenv("AZURE_SEARCH_INNOVATIONS_INDEX_NAME", "innovations")

_FIELDS = [
    "id", "innovation_name", "category", "technology", "concept",
    "trends_addressed", "estimated_cost", "estimated_sale_price",
    "estimated_gross_margin", "market_readiness", "target_market",
    "expected_launch_year", "tags", "description",
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
    """Create a synchronous Azure AI Search client for the innovations index."""
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
    name="research_data",
    instructions=(
        "NorthStar Health innovation and research knowledge base — synthetic "
        "analyst concepts for future consumer-healthcare products across Gut "
        "Health, Weight Management, Home Diagnostics and Vitamins. Each "
        "innovation carries its technology, concept, trends addressed, estimated "
        "cost / retail price / margin, market readiness, target market and "
        "expected launch year, plus a narrative description. Use these tools to "
        "search innovations semantically, list them with filters, retrieve a "
        "single innovation and enumerate the emerging trends."
    ),
    auth=_build_auth(),
)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_: Request) -> JSONResponse:
    """Readiness probe endpoint — returns 200 OK when the server is up."""
    return JSONResponse({"status": "ok"})


@mcp.tool()
def list_innovations(category: Optional[str] = None, target_market: Optional[str] = None,
                     market_readiness: Optional[str] = None,
                     max_launch_year: Optional[int] = None,
                     top: int = 50) -> list[dict[str, Any]]:
    """List innovations, optionally filtered.

    Args:
        category: Optional category filter (e.g. "Gut Health").
        target_market: Optional target-market filter — "Germany", "UK",
            "Nordics" or "All markets". A specific market also returns
            innovations flagged for "All markets".
        market_readiness: Optional readiness filter — "Low", "Medium" or "High".
        max_launch_year: Only return innovations expected to launch on or before
            this year.
        top: Maximum number of innovations to return (default 50).
    """
    client = _search_client()
    if client is None:
        return [{"error": "AZURE_SEARCH_ENDPOINT is not configured."}]
    filters = []
    if category:
        filters.append(f"category eq '{_escape(category)}'")
    if target_market:
        # Market-specific concepts plus those flagged for "All markets".
        needle = _escape(target_market)
        if needle.lower() == "all markets":
            filters.append(f"target_market eq '{needle}'")
        else:
            filters.append(
                f"(target_market eq '{needle}' or target_market eq 'All markets')"
            )
    if market_readiness:
        filters.append(f"market_readiness eq '{_escape(market_readiness)}'")
    if max_launch_year:
        filters.append(f"expected_launch_year le {int(max_launch_year)}")
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
def search_innovations(query: str, top: int = 10) -> list[dict[str, Any]]:
    """Search innovations semantically by concept, technology or trend.

    Args:
        query: Free-text query, e.g. "continuous microbiome monitoring",
            "GLP-1 companion programme", "home blood analysis longevity".
        top: Maximum number of innovations to return (default 10).
    """
    client = _search_client()
    if client is None:
        return [{"error": "AZURE_SEARCH_ENDPOINT is not configured."}]
    try:
        response = client.search(
            search_text=query,
            query_type="semantic",
            semantic_configuration_name="innovations-semantic",
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
def get_innovation(innovation_id: str) -> dict[str, Any]:
    """Get a single innovation's full record by id (e.g. "INN-001").

    Returns the innovation's fields, or an ``error`` field if none matches.
    """
    client = _search_client()
    if client is None:
        return {"error": "AZURE_SEARCH_ENDPOINT is not configured."}
    try:
        doc = client.get_document(key=innovation_id.strip())
        return _project(doc)
    except Exception:
        return {"error": f"No innovation matched '{innovation_id}'."}
    finally:
        client.close()


@mcp.tool()
def list_trends() -> list[dict[str, Any]]:
    """List the emerging trends addressed across the innovation base, with counts."""
    client = _search_client()
    if client is None:
        return [{"error": "AZURE_SEARCH_ENDPOINT is not configured."}]
    try:
        response = client.search(
            search_text="*", facets=["trends_addressed,count:200"], top=0
        )
        facets = response.get_facets() or {}
        return [
            {"trend": f["value"], "count": f["count"]}
            for f in facets.get("trends_addressed", [])
        ]
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
    """Entry point — serve the research data over streamable-HTTP MCP."""
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
