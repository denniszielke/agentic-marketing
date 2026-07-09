"""Ingest the NorthStar Health marketing datasets into Azure AI Search.

Reads the three generated JSON datasets under ``data/``, optionally embeds the
``description`` text with Azure OpenAI, and uploads them to their indexes:

  * **products**     from ``data/products.json``
  * **personas**     from ``data/personas.json``
  * **innovations**  from ``data/research_innovations.json``

Each record already ships a readable ``description`` (persona backstory / product
& innovation narrative). That text is embedded into ``description_vector`` so the
agents can run vector / semantic / hybrid search over it.

Run ``python -m scripts.create_search_indexes`` first to create the schemas.

Embeddings are optional: if ``AZURE_OPENAI_ENDPOINT`` and the embedding
deployment are configured, ``description_vector`` is populated; otherwise the
documents are pushed without vectors and text/semantic search still works.

Environment variables:
  AZURE_SEARCH_ENDPOINT                   required
  AZURE_SEARCH_ADMIN_KEY                  admin key; falls back to DefaultAzureCredential
  AZURE_SEARCH_PRODUCTS_INDEX_NAME        default: products
  AZURE_SEARCH_PERSONAS_INDEX_NAME        default: personas
  AZURE_SEARCH_INNOVATIONS_INDEX_NAME     default: innovations
  AZURE_OPENAI_ENDPOINT                   Azure OpenAI endpoint for embeddings (optional)
  AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME  default: text-embedding-3-small
  OPENAI_API_VERSION                      default: 2024-05-01-preview
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from dotenv import load_dotenv

load_dotenv(override=True)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _REPO_ROOT / "data"

PRODUCTS_INDEX_NAME = os.getenv("AZURE_SEARCH_PRODUCTS_INDEX_NAME", "products")
PERSONAS_INDEX_NAME = os.getenv("AZURE_SEARCH_PERSONAS_INDEX_NAME", "personas")
INNOVATIONS_INDEX_NAME = os.getenv("AZURE_SEARCH_INNOVATIONS_INDEX_NAME", "innovations")


# ---------------------------------------------------------------------------
# Document builders — map dataset records to search documents
# ---------------------------------------------------------------------------

def _load_json(name: str) -> list[dict[str, Any]]:
    path = _DATA_DIR / name
    if not path.exists():
        print(f"Dataset not found: {path}")
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _build_product_docs() -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for p in _load_json("products.json"):
        docs.append({
            "id": p["product_id"],
            "product_name": p.get("product_name", ""),
            "category": p.get("category", ""),
            "brand": p.get("brand", ""),
            "market": p.get("market", []) or [],
            "price_tier": p.get("price_tier", ""),
            "list_price": float(p.get("list_price", 0) or 0),
            "gross_margin": float(p.get("gross_margin", 0) or 0),
            "launch_year": int(p.get("launch_year", 0) or 0),
            "is_competitor": bool(p.get("is_competitor", False)),
            "claims": p.get("claims", []) or [],
            "tags": [t for t in [p.get("category", ""), p.get("brand", ""),
                                 p.get("price_tier", "")] if t],
            "description": p.get("description", ""),
        })
    return docs


def _build_persona_docs() -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for p in _load_json("personas.json"):
        docs.append({
            "id": p["persona_id"],
            "name": p.get("name", ""),
            "market": p.get("market", ""),
            "archetype": p.get("archetype", ""),
            "age": int(p.get("age", 0) or 0),
            "gender": p.get("gender", ""),
            "income_band": p.get("income_band", ""),
            "risk_tolerance": p.get("risk_tolerance", ""),
            "digital_maturity": p.get("digital_maturity", ""),
            "interests": p.get("interests", []) or [],
            "preferred_categories": p.get("preferred_categories", []) or [],
            "preferred_channel": p.get("preferred_channel", ""),
            "annual_spend": float(p.get("annual_spend", 0) or 0),
            "description": p.get("description", ""),
        })
    return docs


def _build_innovation_docs() -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for i in _load_json("research_innovations.json"):
        docs.append({
            "id": i["innovation_id"],
            "innovation_name": i.get("innovation_name", ""),
            "category": i.get("category", ""),
            "technology": i.get("technology", ""),
            "concept": i.get("concept", ""),
            "trends_addressed": i.get("trends_addressed", []) or [],
            "estimated_cost": float(i.get("estimated_cost", 0) or 0),
            "estimated_sale_price": float(i.get("estimated_sale_price", 0) or 0),
            "estimated_gross_margin": float(i.get("estimated_gross_margin", 0) or 0),
            "market_readiness": i.get("market_readiness", ""),
            "target_market": i.get("target_market", ""),
            "expected_launch_year": int(i.get("expected_launch_year", 0) or 0),
            "tags": [t for t in [i.get("category", ""), i.get("technology", ""),
                                 i.get("market_readiness", "")] if t],
            "description": i.get("description", ""),
        })
    return docs


# ---------------------------------------------------------------------------
# Embeddings (optional)
# ---------------------------------------------------------------------------

class _Embedder:
    """Thin Azure OpenAI embedding wrapper; disabled if not configured."""

    def __init__(self) -> None:
        self._client = None
        self._model = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        if not endpoint:
            print("No AZURE_OPENAI_ENDPOINT — uploading without vectors.")
            return
        try:
            from openai import AzureOpenAI
        except ImportError:
            print("openai package not installed — uploading without vectors.")
            return
        api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
        api_version = os.getenv("OPENAI_API_VERSION", "2024-05-01-preview")
        if api_key:
            self._client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)
        else:
            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
            )
            self._client = AzureOpenAI(
                azure_endpoint=endpoint,
                azure_ad_token_provider=token_provider,
                api_version=api_version,
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._client is None:
            return [[] for _ in texts]
        vectors: list[list[float]] = []
        for i in range(0, len(texts), 16):
            batch = [t[:8000] for t in texts[i : i + 16]]
            resp = self._client.embeddings.create(model=self._model, input=batch)
            vectors.extend([d.embedding for d in resp.data])
        return vectors


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def _search_client(index_name: str) -> SearchClient:
    endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    if not endpoint:
        raise RuntimeError("AZURE_SEARCH_ENDPOINT is required")
    api_key = os.getenv("AZURE_SEARCH_ADMIN_KEY", "").strip()
    credential = AzureKeyCredential(api_key) if api_key else DefaultAzureCredential()
    return SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)


def _embed_descriptions(embedder: _Embedder, docs: list[dict[str, Any]]) -> None:
    if not (embedder.enabled and docs):
        return
    vectors = embedder.embed([d.get("description", "") for d in docs])
    for doc, vec in zip(docs, vectors):
        if vec:
            doc["description_vector"] = vec


def _upload(index_name: str, docs: list[dict[str, Any]]) -> None:
    if not docs:
        print(f"No documents to upload to '{index_name}'.")
        return
    client = _search_client(index_name)
    for i in range(0, len(docs), 500):
        batch = docs[i : i + 500]
        client.upload_documents(documents=batch)
    print(f"Uploaded {len(docs)} documents to '{index_name}'.")


def ingest() -> None:
    embedder = _Embedder()

    product_docs = _build_product_docs()
    _embed_descriptions(embedder, product_docs)
    _upload(PRODUCTS_INDEX_NAME, product_docs)

    persona_docs = _build_persona_docs()
    _embed_descriptions(embedder, persona_docs)
    _upload(PERSONAS_INDEX_NAME, persona_docs)

    innovation_docs = _build_innovation_docs()
    _embed_descriptions(embedder, innovation_docs)
    _upload(INNOVATIONS_INDEX_NAME, innovation_docs)


if __name__ == "__main__":
    ingest()
