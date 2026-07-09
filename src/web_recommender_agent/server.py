"""AG-UI server for the Web Recommender Agent (NorthStar Health marketing assistant).

Hosts the marketing recommender agent behind the AG-UI protocol (Server-Sent
Events) and serves a streaming single-page marketing web UI from the same
container.

Authentication
--------------
By default the server uses ``DefaultAzureCredential`` (the container's managed
identity in Azure, or ``az login`` locally) to obtain Foundry / toolbox tokens.
If OBO env vars are configured and the frontend sends a delegated Entra token in
the ``Authorization`` header, the server exchanges it for a downstream token so
calls run under the signed-in user's identity.

Optional env vars for OBO:
  WEB_RECOMMENDER_CLIENT_ID        app registration client id
  WEB_RECOMMENDER_CLIENT_SECRET    client secret for OBO token exchange
  WEB_RECOMMENDER_TENANT_ID        Entra tenant id

Endpoints:
  GET  /          — the chat web UI
  POST /agent     — the AG-UI protocol endpoint (SSE stream)
  GET  /healthz   — liveness probe

Environment: see ``web_recommender_agent.py``. Additionally honours ``HOST``
and ``PORT`` (default 0.0.0.0:8092) and ``APPLICATIONINSIGHTS_CONNECTION_STRING``.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from agent_framework_ag_ui import add_agent_framework_fastapi_endpoint
from azure.identity import DefaultAzureCredential
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

_src_root = Path(__file__).resolve().parents[2]
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_env_path if _env_path.exists() else None)

from src.web_recommender_agent.web_recommender_agent import (  # noqa: E402
    make_agent,
    make_chat_client,
    make_marketing_tool,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("azure").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# ---------------------------------------------------------------------------
# AG-UI sidebar state defaults
# ---------------------------------------------------------------------------

DEFAULT_STATE: dict = {
    "persona": {"persona_id": None, "name": None, "market": None, "archetype": None},
    "products": [],
    "note": {"topic": None, "summary": None},
}

STATE_SCHEMA: dict = {
    "persona": {"type": "object"},
    "products": {"type": "array"},
    "note": {"type": "object"},
}

# ---------------------------------------------------------------------------
# Telemetry (Application Insights)
# ---------------------------------------------------------------------------

def _configure_telemetry() -> None:
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection_string:
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(connection_string=connection_string)
        logger.info("Application Insights telemetry enabled.")
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Telemetry not configured: %s", exc)


_configure_telemetry()

# ---------------------------------------------------------------------------
# Credential + agent factory
# ---------------------------------------------------------------------------

_credential = DefaultAzureCredential()
_marketing_tool = make_marketing_tool(_credential)
_chat_client = make_chat_client(_credential)
_agent = make_agent(_chat_client, _marketing_tool)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(_marketing_tool)
        await stack.enter_async_context(_agent)
        logger.info("Web Recommender Agent ready.")
        yield


app = FastAPI(title="Web Recommender Agent — AG-UI", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return (_TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


add_agent_framework_fastapi_endpoint(
    app=app,
    agent=_agent,
    path="/agent",
    state_schema=STATE_SCHEMA,
    default_state=DEFAULT_STATE,
)


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8092"))
    logger.info("Starting Web Recommender Agent on http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
