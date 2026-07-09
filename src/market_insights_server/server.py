"""Market Insights MCP server for the NorthStar Health marketing ecosystem.

Provides market intelligence and financial performance information over the
Model Context Protocol, computed **in-process** from two static datasets loaded
at startup (no external data store):

* ``data/market_sales_annual.json``  — annual sales, growth and market share.
* ``data/market_sales_monthly.json`` — monthly sales history and forecast.

Mirrors the ``finance_mcp_server`` pattern (self-contained, computes over loaded
data). Every MCP tool call may be authenticated via Entra ID (FastMCP Azure JWT
verifier), toggled with ``ENTRA_AUTH_ENABLED``.

Run it with::

    python -m src.market_insights_server.server

It serves the streamable-HTTP MCP transport on ``http://127.0.0.1:8096/mcp`` by
default (override with ``MARKET_MCP_HOST`` / ``MARKET_MCP_PORT``).
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

_HOST = os.getenv("MARKET_MCP_HOST", "127.0.0.1")
_PORT = int(os.getenv("MARKET_MCP_PORT", "8096"))


def _data_dir() -> Path:
    """Resolve the shared ``data/`` directory (repo root or ``MARKETING_DATA_DIR``)."""
    override = os.getenv("MARKETING_DATA_DIR")
    if override:
        return Path(override)
    # server.py -> market_insights_server -> src -> <repo root>/data
    return Path(__file__).resolve().parents[2] / "data"


@lru_cache(maxsize=1)
def _annual() -> list[dict[str, Any]]:
    with (_data_dir() / "market_sales_annual.json").open("r", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _monthly() -> list[dict[str, Any]]:
    with (_data_dir() / "market_sales_monthly.json").open("r", encoding="utf-8") as fh:
        return json.load(fh)


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


mcp = FastMCP(
    name="market_insights",
    instructions=(
        "NorthStar Health market intelligence — historical and forecast sales, "
        "revenue, gross margin, growth rates and market share across Germany, UK "
        "and Nordics for Vitamins & Supplements, Gut Health, Weight Management "
        "and Home Diagnostics. History covers 2023-2025 with 2026-2028 "
        "projections (``is_forecast=true``). Use these tools to query sales, "
        "market share, growth rates, margin comparisons, forecasts and "
        "competitor performance. Revenue is in the reporting currency; margins "
        "and growth/share are percentages."
    ),
    auth=_build_auth(),
)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_: Request) -> JSONResponse:
    """Readiness probe endpoint — returns 200 OK when the server is up."""
    return JSONResponse({"status": "ok"})


def _match(row: dict[str, Any], market: Optional[str], category: Optional[str],
           product_id: Optional[str], brand: Optional[str], year: Optional[int]) -> bool:
    if market and row.get("market", "").lower() != market.lower():
        return False
    if category and row.get("category", "").lower() != category.lower():
        return False
    if product_id and row.get("product_id", "").upper() != product_id.upper():
        return False
    if brand and row.get("brand", "").lower() != brand.lower():
        return False
    if year is not None and row.get("year") != year:
        return False
    return True


@mcp.tool()
def get_sales(market: Optional[str] = None, category: Optional[str] = None,
              product_id: Optional[str] = None, brand: Optional[str] = None,
              year: Optional[int] = None, include_forecast: bool = False,
              top: int = 200) -> list[dict[str, Any]]:
    """Query annual sales rows, optionally filtered.

    Args:
        market: Optional market filter — "Germany", "UK" or "Nordics".
        category: Optional category filter.
        product_id: Optional product id filter (e.g. "GUT-2001").
        brand: Optional brand filter.
        year: Optional single year filter.
        include_forecast: When false (default) only historical rows are returned.
        top: Maximum number of rows to return (default 200).

    Each row includes year, market, product, category, brand, units sold,
    revenue, gross margin, growth rate and market share.
    """
    rows = [
        r for r in _annual()
        if _match(r, market, category, product_id, brand, year)
        and (include_forecast or not r.get("is_forecast"))
    ]
    rows.sort(key=lambda r: (r.get("year", 0), -float(r.get("revenue", 0) or 0)))
    return rows[:max(1, top)]


@mcp.tool()
def get_market_share(market: str, category: Optional[str] = None,
                     year: Optional[int] = None) -> dict[str, Any]:
    """Return market-share by brand for a market (and optional category/year).

    Args:
        market: The market — "Germany", "UK" or "Nordics".
        category: Optional category filter.
        year: Optional year (defaults to the latest historical year).
    """
    rows = [r for r in _annual() if not r.get("is_forecast")
            and r.get("market", "").lower() == market.lower()
            and (not category or r.get("category", "").lower() == category.lower())]
    if not rows:
        return {"market": market, "category": category, "shares": []}
    target_year = year if year is not None else max(r["year"] for r in rows)
    rows = [r for r in rows if r.get("year") == target_year]
    by_brand: dict[str, float] = {}
    for r in rows:
        by_brand[r.get("brand", "?")] = by_brand.get(r.get("brand", "?"), 0.0) + float(
            r.get("market_share", 0) or 0)
    shares = sorted(
        ({"brand": b, "market_share": round(s, 2)} for b, s in by_brand.items()),
        key=lambda x: x["market_share"], reverse=True,
    )
    return {"market": market, "category": category, "year": target_year, "shares": shares}


@mcp.tool()
def get_growth_rates(market: Optional[str] = None,
                     category: Optional[str] = None) -> list[dict[str, Any]]:
    """Return average annual growth rates by category (and optional market).

    Args:
        market: Optional market filter.
        category: Optional category filter.
    """
    buckets: dict[tuple[str, str], list[float]] = {}
    for r in _annual():
        if r.get("is_forecast") or r.get("growth_rate") is None:
            continue
        if market and r.get("market", "").lower() != market.lower():
            continue
        if category and r.get("category", "").lower() != category.lower():
            continue
        key = (r.get("market", "?"), r.get("category", "?"))
        buckets.setdefault(key, []).append(float(r["growth_rate"]))
    out = [
        {"market": k[0], "category": k[1],
         "avg_growth_rate": round(sum(v) / len(v), 2)}
        for k, v in buckets.items() if v
    ]
    out.sort(key=lambda x: x["avg_growth_rate"], reverse=True)
    return out


@mcp.tool()
def compare_margins(category: str, markets: Optional[list[str]] = None) -> dict[str, Any]:
    """Compare average gross margin for a category across markets.

    Args:
        category: The product category to compare (e.g. "Weight Management").
        markets: Markets to compare (defaults to Germany, UK, Nordics).
    """
    markets = markets or ["Germany", "UK", "Nordics"]
    result: list[dict[str, Any]] = []
    for m in markets:
        margins = [float(r.get("gross_margin", 0) or 0) for r in _annual()
                   if not r.get("is_forecast")
                   and r.get("category", "").lower() == category.lower()
                   and r.get("market", "").lower() == m.lower()]
        if margins:
            result.append({"market": m, "avg_gross_margin": round(sum(margins) / len(margins), 2)})
    result.sort(key=lambda x: x["avg_gross_margin"], reverse=True)
    return {"category": category, "margins": result}


@mcp.tool()
def get_forecast(market: str, category: Optional[str] = None) -> list[dict[str, Any]]:
    """Return the forecast (projection) rows for a market, aggregated by year.

    Args:
        market: The market — "Germany", "UK" or "Nordics".
        category: Optional category filter.
    """
    by_year: dict[int, dict[str, float]] = {}
    for r in _annual():
        if not r.get("is_forecast"):
            continue
        if r.get("market", "").lower() != market.lower():
            continue
        if category and r.get("category", "").lower() != category.lower():
            continue
        y = r.get("year")
        agg = by_year.setdefault(y, {"revenue": 0.0, "units_sold": 0.0})
        agg["revenue"] += float(r.get("revenue", 0) or 0)
        agg["units_sold"] += float(r.get("units_sold", 0) or 0)
    return [
        {"year": y, "market": market, "category": category,
         "revenue": round(v["revenue"], 2), "units_sold": int(v["units_sold"])}
        for y, v in sorted(by_year.items())
    ]


@mcp.tool()
def competitor_performance(market: Optional[str] = None,
                           brand: Optional[str] = None,
                           year: Optional[int] = None) -> list[dict[str, Any]]:
    """Return brand-level performance (revenue, units, share) for competitors.

    Args:
        market: Optional market filter.
        brand: Optional single brand filter.
        year: Optional year (defaults to the latest historical year).
    """
    hist = [r for r in _annual() if not r.get("is_forecast")]
    if not hist:
        return []
    target_year = year if year is not None else max(r["year"] for r in hist)
    buckets: dict[str, dict[str, float]] = {}
    for r in hist:
        if r.get("year") != target_year:
            continue
        if market and r.get("market", "").lower() != market.lower():
            continue
        if brand and r.get("brand", "").lower() != brand.lower():
            continue
        b = r.get("brand", "?")
        agg = buckets.setdefault(b, {"revenue": 0.0, "units_sold": 0.0, "market_share": 0.0})
        agg["revenue"] += float(r.get("revenue", 0) or 0)
        agg["units_sold"] += float(r.get("units_sold", 0) or 0)
        agg["market_share"] += float(r.get("market_share", 0) or 0)
    out = [
        {"brand": b, "year": target_year,
         "revenue": round(v["revenue"], 2), "units_sold": int(v["units_sold"]),
         "market_share": round(v["market_share"], 2)}
        for b, v in buckets.items()
    ]
    out.sort(key=lambda x: x["revenue"], reverse=True)
    return out


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
    """Entry point — serve the market insights over streamable-HTTP MCP."""
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
