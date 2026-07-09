"""Delete the three marketing Azure AI Search indexes (schema + data).

Removes ``products``, ``personas`` and ``innovations`` entirely. To clear only
the documents but keep the schemas, re-run
``python -m scripts.create_search_indexes`` after deleting.

Environment variables:
  AZURE_SEARCH_ENDPOINT                 required
  AZURE_SEARCH_ADMIN_KEY                admin key; falls back to DefaultAzureCredential
  AZURE_SEARCH_PRODUCTS_INDEX_NAME      default: products
  AZURE_SEARCH_PERSONAS_INDEX_NAME      default: personas
  AZURE_SEARCH_INNOVATIONS_INDEX_NAME   default: innovations
"""

from __future__ import annotations

import os

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient
from dotenv import load_dotenv

load_dotenv(override=True)

INDEXES = [
    os.getenv("AZURE_SEARCH_PRODUCTS_INDEX_NAME", "products"),
    os.getenv("AZURE_SEARCH_PERSONAS_INDEX_NAME", "personas"),
    os.getenv("AZURE_SEARCH_INNOVATIONS_INDEX_NAME", "innovations"),
]


def _get_index_client() -> SearchIndexClient:
    endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    if not endpoint:
        raise RuntimeError("AZURE_SEARCH_ENDPOINT is required")
    api_key = os.getenv("AZURE_SEARCH_ADMIN_KEY", "").strip()
    credential = AzureKeyCredential(api_key) if api_key else DefaultAzureCredential()
    return SearchIndexClient(endpoint=endpoint, credential=credential)


def delete_indexes() -> None:
    client = _get_index_client()
    for name in INDEXES:
        try:
            client.delete_index(name)
            print(f"Deleted index '{name}'.")
        except ResourceNotFoundError:
            print(f"Index '{name}' does not exist — skipping.")


if __name__ == "__main__":
    delete_indexes()
