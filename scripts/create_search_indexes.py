"""Create (or update) the three NorthStar Health marketing Azure AI Search indexes.

Defined in ``narrative.md`` / ``plan.md``:

  1. **products** — internal & competitor product catalogue: product name,
     category, brand, market, price tier, list price, gross margin, claims and a
     ``description_vector`` for vector search over the product description.

  2. **personas** — customer segmentation: name, market, archetype, age, income
     band, risk tolerance, digital maturity, interests, preferred categories and
     a ``description_vector`` for vector search over the persona backstory.

  3. **innovations** — healthcare innovation knowledge base: innovation name,
     category, technology, concept, trends addressed, estimated cost/price,
     market readiness, target market and a ``description_vector`` for vector
     search over the innovation description.

All indexes are created with HNSW vector search and a semantic configuration so
the agents can run vector, semantic or hybrid queries. Populate them afterwards
with ``python -m scripts.ingest_knowledge``.

Environment variables:
  AZURE_SEARCH_ENDPOINT                  e.g. https://<service>.search.windows.net (required)
  AZURE_SEARCH_ADMIN_KEY                 admin key; falls back to DefaultAzureCredential
  AZURE_SEARCH_PRODUCTS_INDEX_NAME       default: products
  AZURE_SEARCH_PERSONAS_INDEX_NAME       default: personas
  AZURE_SEARCH_INNOVATIONS_INDEX_NAME    default: innovations
  AZURE_OPENAI_EMBEDDING_DIMENSIONS      embedding vector size (default: 1536)
"""

from __future__ import annotations

import os

from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    VectorSearch,
    VectorSearchProfile,
)
from dotenv import load_dotenv

load_dotenv(override=True)

EMBEDDING_DIMENSIONS = int(os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536"))

PRODUCTS_INDEX_NAME = os.getenv("AZURE_SEARCH_PRODUCTS_INDEX_NAME", "products")
PERSONAS_INDEX_NAME = os.getenv("AZURE_SEARCH_PERSONAS_INDEX_NAME", "personas")
INNOVATIONS_INDEX_NAME = os.getenv("AZURE_SEARCH_INNOVATIONS_INDEX_NAME", "innovations")


def _get_index_client() -> SearchIndexClient:
    endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    if not endpoint:
        raise RuntimeError("AZURE_SEARCH_ENDPOINT is required")
    api_key = os.getenv("AZURE_SEARCH_ADMIN_KEY", "").strip()
    credential = AzureKeyCredential(api_key) if api_key else DefaultAzureCredential()
    return SearchIndexClient(endpoint=endpoint, credential=credential)


def _vector_search() -> VectorSearch:
    return VectorSearch(
        profiles=[VectorSearchProfile(name="hnsw", algorithm_configuration_name="hnsw")],
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
    )


def _vector_field(name: str) -> SearchField:
    return SearchField(
        name=name,
        type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
        searchable=True,
        vector_search_dimensions=EMBEDDING_DIMENSIONS,
        vector_search_profile_name="hnsw",
    )


def _str(name: str, *, searchable: bool = False, filterable: bool = False,
         facetable: bool = False) -> SearchField:
    return SearchField(
        name=name,
        type=SearchFieldDataType.String,
        searchable=searchable,
        filterable=filterable,
        facetable=facetable,
    )


def _coll(name: str, *, searchable: bool = True, filterable: bool = True,
          facetable: bool = True) -> SearchField:
    return SearchField(
        name=name,
        type=SearchFieldDataType.Collection(SearchFieldDataType.String),
        searchable=searchable,
        filterable=filterable,
        facetable=facetable,
    )


def _products_fields() -> list[SearchField]:
    """Product catalogue index fields (NorthStar + competitor products)."""
    return [
        SearchField(name="id", type=SearchFieldDataType.String, key=True),
        _str("product_name", searchable=True, filterable=True),
        _str("category", searchable=True, filterable=True, facetable=True),
        _str("brand", searchable=True, filterable=True, facetable=True),
        _coll("market"),
        _str("price_tier", searchable=True, filterable=True, facetable=True),
        SearchField(name="list_price", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SearchField(name="gross_margin", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SearchField(name="launch_year", type=SearchFieldDataType.Int32, filterable=True, sortable=True, facetable=True),
        SearchField(name="is_competitor", type=SearchFieldDataType.Boolean, filterable=True, facetable=True),
        _coll("claims"),
        _coll("tags"),
        SearchField(name="description", type=SearchFieldDataType.String, searchable=True),
        _vector_field("description_vector"),
    ]


def _personas_fields() -> list[SearchField]:
    """Persona segmentation index fields."""
    return [
        SearchField(name="id", type=SearchFieldDataType.String, key=True),
        _str("name", searchable=True, filterable=True),
        _str("market", searchable=True, filterable=True, facetable=True),
        _str("archetype", searchable=True, filterable=True, facetable=True),
        SearchField(name="age", type=SearchFieldDataType.Int32, filterable=True, sortable=True, facetable=True),
        _str("gender", searchable=True, filterable=True, facetable=True),
        _str("income_band", searchable=True, filterable=True, facetable=True),
        _str("risk_tolerance", searchable=True, filterable=True, facetable=True),
        _str("digital_maturity", searchable=True, filterable=True, facetable=True),
        _coll("interests"),
        _coll("preferred_categories"),
        _str("preferred_channel", searchable=True, filterable=True),
        SearchField(name="annual_spend", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SearchField(name="description", type=SearchFieldDataType.String, searchable=True),
        _vector_field("description_vector"),
    ]


def _innovations_fields() -> list[SearchField]:
    """Healthcare innovation knowledge base index fields."""
    return [
        SearchField(name="id", type=SearchFieldDataType.String, key=True),
        _str("innovation_name", searchable=True, filterable=True),
        _str("category", searchable=True, filterable=True, facetable=True),
        _str("technology", searchable=True, filterable=True, facetable=True),
        _str("concept", searchable=True),
        _coll("trends_addressed"),
        SearchField(name="estimated_cost", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SearchField(name="estimated_sale_price", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SearchField(name="estimated_gross_margin", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        _str("market_readiness", searchable=True, filterable=True, facetable=True),
        _str("target_market", searchable=True, filterable=True, facetable=True),
        SearchField(name="expected_launch_year", type=SearchFieldDataType.Int32, filterable=True, sortable=True, facetable=True),
        _coll("tags"),
        SearchField(name="description", type=SearchFieldDataType.String, searchable=True),
        _vector_field("description_vector"),
    ]


def _semantic(config_name: str, title_field: str, content_fields: list[str],
              keyword_fields: list[str]) -> SemanticSearch:
    return SemanticSearch(
        default_configuration_name=config_name,
        configurations=[
            SemanticConfiguration(
                name=config_name,
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name=title_field),
                    content_fields=[SemanticField(field_name=f) for f in content_fields],
                    keywords_fields=[SemanticField(field_name=f) for f in keyword_fields],
                ),
            )
        ],
    )


def create_or_update_indexes() -> None:
    client = _get_index_client()

    products_index = SearchIndex(
        name=PRODUCTS_INDEX_NAME,
        fields=_products_fields(),
        vector_search=_vector_search(),
        semantic_search=_semantic(
            "products-semantic", "product_name", ["description"], ["claims", "tags"]
        ),
    )
    result = client.create_or_update_index(products_index)
    print(f"Index '{result.name}' created/updated.")

    personas_index = SearchIndex(
        name=PERSONAS_INDEX_NAME,
        fields=_personas_fields(),
        vector_search=_vector_search(),
        semantic_search=_semantic(
            "personas-semantic", "name", ["description"], ["interests"]
        ),
    )
    result = client.create_or_update_index(personas_index)
    print(f"Index '{result.name}' created/updated.")

    innovations_index = SearchIndex(
        name=INNOVATIONS_INDEX_NAME,
        fields=_innovations_fields(),
        vector_search=_vector_search(),
        semantic_search=_semantic(
            "innovations-semantic", "innovation_name", ["description"],
            ["trends_addressed", "tags"],
        ),
    )
    result = client.create_or_update_index(innovations_index)
    print(f"Index '{result.name}' created/updated.")


if __name__ == "__main__":
    create_or_update_indexes()
