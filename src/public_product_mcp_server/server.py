"""Public Product MCP server for the NorthStar Health marketing ecosystem.

Exposes a **public, read-only** view of the NorthStar Health product catalogue
over the Model Context Protocol, backed by the same **Azure AI Search** index
(``products``) as the internal ``product_mcp_server``.

This server is intended for **anonymous public consumption on the internet**, so
it deliberately differs from the internal product server in two ways:

  * **No authentication.** It never builds an Entra JWT verifier — every request
    is served anonymously.
  * **No commercially sensitive fields.** The projection omits ``list_price``
    (actual prices), ``gross_margin`` (margins) and any unit cost. Only public
    information is returned: product name, category, brand, markets, qualitative
    price tier, launch year, competitor flag, claims and the description.

The index is populated by ``scripts/ingest_knowledge.py`` from
``data/products.json``.

Run it with::

    python -m src.public_product_mcp_server.server

It serves the streamable-HTTP MCP transport on ``http://127.0.0.1:8097/mcp`` by
default (override with ``PUBLIC_PRODUCT_MCP_HOST`` / ``PUBLIC_PRODUCT_MCP_PORT``).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

_HOST = os.getenv("PUBLIC_PRODUCT_MCP_HOST", "127.0.0.1")
_PORT = int(os.getenv("PUBLIC_PRODUCT_MCP_PORT", "8097"))

_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT", "").strip()
_SEARCH_API_KEY = os.getenv("AZURE_SEARCH_ADMIN_KEY", "").strip()
_INDEX_NAME = os.getenv("AZURE_SEARCH_PRODUCTS_INDEX_NAME", "products")

# Public projection — intentionally EXCLUDES commercially sensitive fields:
# no ``list_price`` (prices), no ``gross_margin`` (margins) and no unit cost.
# ``price_tier`` is a qualitative band (e.g. "Premium"/"Entry"), not a price.
_FIELDS = [
    "id", "product_name", "category", "brand", "market", "price_tier",
    "launch_year", "is_competitor", "claims", "tags", "description",
]

# Fields that must never leave this server (guards against accidental exposure
# if the index projection ever changes upstream).
_SENSITIVE_FIELDS = frozenset(
    {"list_price", "list_price_currency", "gross_margin", "cost_per_unit", "market_prices"}
)


def _search_client():
    """Create a synchronous Azure AI Search client for the products index."""
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
    """Project a document to the public field set, dropping sensitive fields."""
    return {f: doc.get(f) for f in _FIELDS if f not in _SENSITIVE_FIELDS}


def _escape(value: str) -> str:
    return value.replace("'", "''")


mcp = FastMCP(
    name="public_product_data",
    instructions=(
        "Public NorthStar Health product catalogue (internal and competitor "
        "products) across Vitamins & Supplements, Gut Health, Weight Management "
        "and Home Diagnostics, for the markets Germany, UK and Nordics. Use these "
        "tools to list products by category / market / brand, search products by "
        "free-text need or claim (semantic + vector search over the product "
        "description), retrieve a single product's public metadata, and review "
        "competitor positioning. This is a PUBLIC endpoint: it returns product "
        "names, categories, brands, markets, qualitative price tier, claims and "
        "descriptions only — it does NOT expose list prices, margins or costs."
    ),
    # No authentication — this server is intentionally public/anonymous.
)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_: Request) -> JSONResponse:
    """Readiness probe endpoint — returns 200 OK when the server is up."""
    return JSONResponse({"status": "ok"})


@mcp.tool()
def list_products(category: Optional[str] = None, market: Optional[str] = None,
                  brand: Optional[str] = None, competitor_only: bool = False,
                  top: int = 50) -> list[dict[str, Any]]:
    """List the public product catalogue, optionally filtered.

    Args:
        category: Optional category filter (e.g. "Gut Health").
        market: Optional market filter — "Germany", "UK" or "Nordics".
        brand: Optional brand filter (e.g. "NorthStar Health", "VitaCore Labs").
        competitor_only: When true, return only competitor products.
        top: Maximum number of products to return (default 50).

    Each product includes name, category, brand, markets, qualitative price
    tier, claims and a description. Prices, margins and costs are not exposed.
    """
    client = _search_client()
    if client is None:
        return [{"error": "AZURE_SEARCH_ENDPOINT is not configured."}]
    filters = []
    if category:
        filters.append(f"category eq '{_escape(category)}'")
    if brand:
        filters.append(f"brand eq '{_escape(brand)}'")
    if market:
        filters.append(f"market/any(m: m eq '{_escape(market)}')")
    if competitor_only:
        filters.append("is_competitor eq true")
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
def search_products(query: str, top: int = 10) -> list[dict[str, Any]]:
    """Search the public product catalogue by free-text need, benefit or claim.

    Runs a semantic search over the product descriptions and claims.

    Args:
        query: Free-text query, e.g. "premium probiotic for gut health",
            "GLP-1 companion weight management", "immune support vitamins".
        top: Maximum number of products to return (default 10).
    """
    client = _search_client()
    if client is None:
        return [{"error": "AZURE_SEARCH_ENDPOINT is not configured."}]
    try:
        response = client.search(
            search_text=query,
            query_type="semantic",
            semantic_configuration_name="products-semantic",
            select=",".join(_FIELDS), top=max(1, top),
        )
        return [_project(doc) for doc in response]
    except Exception:
        # Fall back to plain keyword search if semantic ranking is unavailable.
        response = client.search(search_text=query, select=",".join(_FIELDS),
                                 top=max(1, top))
        return [_project(doc) for doc in response]
    finally:
        client.close()


@mcp.tool()
def get_product(product_id: str) -> dict[str, Any]:
    """Get a single product's public metadata by product id (e.g. "VIT-1001").

    Returns the product's public fields, or an ``error`` field if none matches.
    Prices, margins and costs are not exposed.
    """
    client = _search_client()
    if client is None:
        return {"error": "AZURE_SEARCH_ENDPOINT is not configured."}
    try:
        doc = client.get_document(key=product_id.strip())
        return _project(doc)
    except Exception:
        return {"error": f"No product matched '{product_id}'."}
    finally:
        client.close()


@mcp.tool()
def list_categories() -> list[str]:
    """List the distinct product categories in the catalogue."""
    return _facet_values("category")


@mcp.tool()
def list_brands() -> list[str]:
    """List the distinct brands in the catalogue (NorthStar + competitors)."""
    return _facet_values("brand")


@mcp.tool()
def get_positioning(product_id: str) -> dict[str, Any]:
    """Return a product's public competitive positioning summary.

    Includes the product's own qualitative price tier and claims plus the
    competing products in the same category (for comparison). Prices, margins
    and costs are not exposed.

    Args:
        product_id: The product id, e.g. "GUT-2001".
    """
    client = _search_client()
    if client is None:
        return {"error": "AZURE_SEARCH_ENDPOINT is not configured."}
    try:
        try:
            product = _project(client.get_document(key=product_id.strip()))
        except Exception:
            return {"error": f"No product matched '{product_id}'."}
        category = product.get("category")
        competitors: list[dict[str, Any]] = []
        if category:
            response = client.search(
                search_text="*",
                filter=f"category eq '{_escape(category)}' and id ne '{_escape(product_id.strip())}'",
                select="id,product_name,brand,price_tier,is_competitor,claims",
                top=50,
            )
            competitors = [
                {
                    "id": d.get("id"), "product_name": d.get("product_name"),
                    "brand": d.get("brand"), "price_tier": d.get("price_tier"),
                    "is_competitor": d.get("is_competitor"), "claims": d.get("claims"),
                }
                for d in response
            ]
        return {"product": product, "category": category, "competitors": competitors,
                "competitor_count": len(competitors)}
    finally:
        client.close()


def _facet_values(field: str) -> list[str]:
    client = _search_client()
    if client is None:
        return []
    try:
        response = client.search(search_text="*", facets=[f"{field},count:200"], top=0)
        facets = response.get_facets() or {}
        return [f["value"] for f in facets.get(field, [])]
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
    """Entry point — serve the public product data over streamable-HTTP MCP."""
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
