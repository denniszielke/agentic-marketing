---
name: ops
description: >
  Operations runbook for the agentic-marketing (NorthStar Health) repo. USE THIS
  SKILL when the user asks to deploy, build, provision, generate data, index,
  ingest, register, grant permissions, create identities, or clean up any part of
  the project — including infrastructure (azd), container images, Container Apps,
  the product/persona/research/market-insights MCP servers, AI Search indexes
  (products, personas, innovations), Foundry toolboxes (marketing, strategy) and
  the marketing/strategy/web agents. Covers the full lifecycle: provision →
  generate data → create indexes → ingest → build → deploy MCP → identities/auth →
  register toolboxes → deploy agents → deploy web → clean up.
---

# Ops Runbook — agentic-marketing (NorthStar Health)

An agentic product-strategy & market-intelligence demo for the fictional consumer
healthcare company **NorthStar Health** (markets: Germany, UK, Nordics;
categories: Vitamins & Supplements, Gut Health, Weight Management, Home
Diagnostics).

It ships **four MCP servers**, **three Azure AI Search indexes**, **two Foundry
toolboxes** and **three agents**:

- **product_mcp_server** — product catalogue (AI Search `products` index), Container App, port 8093.
- **persona_mcp_server** — customer personas (AI Search `personas` index), Container App, port 8094.
- **research_mcp_server** — innovation/research base (AI Search `innovations` index), Container App, port 8095.
- **market_insights_server** — sales/margin/growth/share/forecast, static JSON in-process, Container App, port 8096.
- **marketing_toolbox** — Foundry toolbox = product + market-insights + persona MCP servers.
- **strategy_toolbox** — Foundry toolbox = product + market-insights + persona + research MCP servers.
- **market_intelligence_agent** — Foundry **hosted agent** (marketing_toolbox).
- **executive_strategy_agent** — Foundry **hosted agent** (strategy_toolbox + marketing_toolbox).
- **web_recommender_agent** — Azure **Container App** + AG-UI web UI (marketing_toolbox), port 8092.

All commands run from the **repo root**. Configuration comes from `./.env`, which
`azd up` writes automatically. Use the project venv:

```bash
source .venv/bin/activate   # or prefix commands with: .venv/bin/python
```

---

## 0. Prerequisites

| Tool | Version | Install |
|---|---|---|
| Azure Developer CLI (`azd`) | latest | https://aka.ms/azd |
| Azure CLI (`az`) | ≥ 2.60 | https://aka.ms/azcli |
| Python | 3.13 + | |

Install Python deps (all services + scripts are consolidated in the root file):
```bash
pip install -r requirements.txt
```

The Foundry azd extension is needed for the agent-identity connections (§6):
```bash
azd ext install microsoft.foundry
```

---

## 1. Provision Infrastructure

Creates the long-lived Azure resources (AI Foundry project, Azure AI Search,
Container Apps environment, ACR, user-assigned managed identity, Application
Insights / Log Analytics) and writes all outputs to `./.env`.

```bash
azd env set AZURE_LOCATION swedencentral
azd env set AZURE_PRINCIPAL_ID $(az ad signed-in-user show --query id -o tsv)
azd env set AZURE_PRINCIPAL_TYPE User
azd env set ENABLE_HOSTED_AGENTS true       # adds ACR for the hosted agents
azd env set SKIP_CONNECTION_CREATION true
azd env set SKIP_ROLE_ASSIGNMENTS true
azd up
```

The bicep exports the marketing index names to `./.env`:
`AZURE_SEARCH_PRODUCTS_INDEX_NAME=products`,
`AZURE_SEARCH_PERSONAS_INDEX_NAME=personas`,
`AZURE_SEARCH_INNOVATIONS_INDEX_NAME=innovations`.

Provision only / deploy only / tear down:
```bash
azd provision
azd deploy
azd down
```

---

## 2. Generate Demo Data

The synthetic datasets are generated deterministically (seeded) and are already
committed under `data/`. Regenerate them only if you change the generator:
`data/products.json` (50 NorthStar + competitor products), `data/personas.json`
(90 personas, 30 per market), `data/research_innovations.json` (innovations),
`data/market_sales_monthly.json` and `data/market_sales_annual.json`.

```bash
python -m scripts.generate_datasets
```

---

## 3. Create & Populate the Search Indexes

Three Azure AI Search indexes — **products**, **personas** and **innovations** —
each with HNSW vector + a semantic configuration (`products-semantic`,
`personas-semantic`, `innovations-semantic`).

```bash
# create/update the three index schemas
python -m scripts.create_search_indexes

# read the three JSON datasets, embed each record's description (if
# AZURE_OPENAI_ENDPOINT is set) into description_vector, and upload
python -m scripts.ingest_knowledge
```

Ingestion is embedding-optional: without `AZURE_OPENAI_ENDPOINT` the documents are
pushed without vectors and text/semantic search still works. Key overrides:
- `AZURE_SEARCH_PRODUCTS_INDEX_NAME` (products)
- `AZURE_SEARCH_PERSONAS_INDEX_NAME` (personas)
- `AZURE_SEARCH_INNOVATIONS_INDEX_NAME` (innovations)
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME` (text-embedding-3-small)
- `AZURE_OPENAI_EMBEDDING_DIMENSIONS` (1536)

Run §3 **before** deploying the search-backed MCP servers so their queries return data.

---

## 4. Build the Container Images

Builds all seven images in ACR (no local Docker): the four MCP servers, the two
hosted agents and the web recommender. Only builds — does not deploy. The
resource group is read from `./.env` (`AZURE_RESOURCE_GROUP`, or
`rg-<AZURE_ENV_NAME>`); subscription and registry are discovered from it.

Images: `product-mcp-server`, `persona-mcp-server`, `research-mcp-server`,
`market-insights-server`, `market-intelligence-agent`, `executive-strategy-agent`,
`web-recommender-agent`.

```bash
python -m scripts.build_containers                 # auto timestamp tag + :latest
python -m scripts.build_containers latest          # explicit tag
python -m scripts.build_containers --env <name>    # override rg-<name>
```

> Each `deploy_*` script also accepts `--build` to build just its own image in
> ACR first, so a full pre-build is optional.

---

## 5. Deploy the MCP Servers

Deploys each MCP server as a Container App via `infra/core/host/app.bicep`. Pass
`--build` to build in ACR first (else deploys `:latest` or the `TAG` env var).
Unlike the toolbox registration, these scripts do **not** take `--register` —
toolbox registration is a separate step (§7).

```bash
python -m scripts.deploy_product_mcp_server --build        # products index (8093)
python -m scripts.deploy_persona_mcp_server --build        # personas index (8094)
python -m scripts.deploy_research_mcp_server --build       # innovations index (8095)
python -m scripts.deploy_market_insights_server --build    # static sales data (8096)
```

Each prints the deployed `…/mcp` URL. Key overrides per server (prefix
`PRODUCT_` / `PERSONA_` / `RESEARCH_` / `MARKET_`):
- `<PREFIX>_MCP_APP_NAME` — Container App name (defaults `product-mcp-server`,
  `persona-mcp-server`, `research-mcp-server`, `market-insights-server`)
- `<PREFIX>_MCP_PORT` — 8093 / 8094 / 8095 / 8096
- `<PREFIX>_MCP_EXTERNAL` — public ingress (default: true)
- search-backed servers read `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_ADMIN_KEY`
  and their index-name env var; the market-insights server bundles the JSON under
  `/app/data` (`MARKETING_DATA_DIR`).

All four expose `/health` as an unauthenticated readiness route.

---

## 5b. Protect the MCP Servers with Entra ID

The MCP servers validate Entra ID access tokens **natively inside the app** via
FastMCP's `AzureJWTVerifier` + `RemoteAuthProvider` — no Container Apps Easy Auth,
no sidecar, no client secret. Auth is on by default (`ENTRA_AUTH_ENABLED=true`),
so every request must present a valid token. Opt out per deployment for anonymous
ingress:

```bash
azd env set ENTRA_AUTH_ENABLED false   # (or export ENTRA_AUTH_ENABLED=false)
```

With auth enabled (the default), running the MCP deploy scripts (§5) will, for
each server:
- ensure an Entra **app registration** (`<app>-mcp-auth`) with an `Mcp.Invoke`
  app role — the token audience is `api://<appId>`;
- inject the auth config into the container (`ENTRA_AUTH_ENABLED`,
  `MCP_AUTH_CLIENT_ID`, `AZURE_TENANT_ID`, `MCP_PUBLIC_BASE_URL`) so the app
  verifies each token's **issuer**
  (`https://login.microsoftonline.com/<tenant>/v2.0`), **audience** and **JWKS
  signature**; anonymous requests get **HTTP 401**. No required scope, so
  delegated (user) and app-only (managed identity) tokens are both accepted;
- print the audience callers must request a token for.

Requires `az login` with rights to create app registrations and app-role
assignments. Turn auth off by setting `ENTRA_AUTH_ENABLED=false` and re-deploying.

---

## 6. Identities & Permissions (Entra auth on)

When `ENTRA_AUTH_ENABLED=true`, the hosted agents call the MCP servers through the
toolboxes using their **Entra Agent Identity** (no secret). Grant the role and
create the Foundry connections. One helper does both (needs the Foundry azd
extension: `azd ext install microsoft.foundry`):

```bash
# grants each agent identity Mcp.Invoke on the product/persona/research/market
# MCP apps, then creates a remote-tool/agentic-identity connection per server
# (audience api://<appId>)
python -m scripts.create_mcp_agent_identity_connections --grant
```

It prints the connection-id lines to add to `./.env`:
`PRODUCT_MCP_CONNECTION_ID`, `MARKET_MCP_CONNECTION_ID`,
`PERSONA_MCP_CONNECTION_ID`, `RESEARCH_MCP_CONNECTION_ID`. Under the hood it runs
`python -m scripts.grant_agent_identity_mcp_role` (auto-discovers the
`market-intelligence-agent` / `executive-strategy-agent` identities) +
`azd ai connection create <name> --kind remote-tool --auth-type agentic-identity
--audience api://<appId>`. Without the connections the toolbox registration warns
and tool calls return **401**.

Run for one server only, or grant only:
```bash
python -m scripts.create_mcp_agent_identity_connections --only persona
python -m scripts.grant_agent_identity_mcp_role
python -m scripts.grant_agent_identity_mcp_role --agent-id <agent-identity-object-id>
```

> **IMPORTANT — agent identity rotation.** Each agent **republish/redeploy can
> rotate the hosted agent's Entra Agent Identity** (new service-principal object
> id). After each deploy, re-run `grant_agent_identity_mcp_role` for the new
> identity (it auto-discovers), refresh the connections if needed, and re-register
> the toolboxes.

---

## 7. Register the Foundry Toolboxes

Register the two toolboxes after the MCP servers are deployed (idempotent,
re-runnable). Each bundles multiple MCP servers into one toolbox and, when Entra
auth is on, attaches the per-server `*_MCP_CONNECTION_ID` from §6.

```bash
python -m scripts.register_marketing_toolbox    # → marketing_toolbox (product + market + persona)
python -m scripts.register_strategy_toolbox     # → strategy_toolbox  (+ research)
```

Each prints the consumer endpoint
`{project}/toolboxes/{toolbox}/mcp?api-version=v1`. Key overrides:
- `MARKETING_TOOLBOX_NAME` (marketing_toolbox) / `STRATEGY_TOOLBOX_NAME` (strategy_toolbox)
- `PRODUCT_MCP_URL` / `PERSONA_MCP_URL` / `RESEARCH_MCP_URL` / `MARKET_MCP_URL` —
  explicit MCP URLs (else derived from each Container App FQDN via `AZURE_RESOURCE_GROUP`)
- `PRODUCT_MCP_CONNECTION_ID` / `PERSONA_MCP_CONNECTION_ID` /
  `RESEARCH_MCP_CONNECTION_ID` / `MARKET_MCP_CONNECTION_ID` — agent-identity
  connection ids used when `ENTRA_AUTH_ENABLED=true`

---

## 8. Deploy the Agents

Prerequisites: MCP servers deployed (§5), indexes created + ingested (§3),
identities/connections created (§6, if auth on) and toolboxes registered (§7).

### Market intelligence agent (Foundry hosted agent — marketing_toolbox)
```bash
python -m scripts.deploy_market_intelligence_agent
```
Consumes `marketing_toolbox`. Enables RESPONSES + A2A + INVOCATIONS. Key
overrides: `AZURE_AI_MARKET_AGENT_NAME` (market-intelligence-agent),
`MARKETING_TOOLBOX_NAME` (marketing_toolbox), `MARKETING_MCP_URL` (direct MCP
override for local dev).

### Executive strategy agent (Foundry hosted agent — strategy + marketing)
```bash
python -m scripts.deploy_executive_strategy_agent
```
Consumes `strategy_toolbox` **and** `marketing_toolbox`. Key overrides:
`AZURE_AI_STRATEGY_AGENT_NAME` (executive-strategy-agent),
`STRATEGY_TOOLBOX_NAME` (strategy_toolbox), `MARKETING_TOOLBOX_NAME`,
`EXECUTIVE_MARKETING_TOOLBOX_ENABLED` (true), `STRATEGY_MCP_URL` /
`MARKETING_MCP_URL` (direct overrides).

### Web recommender agent (Container App + AG-UI web UI)
```bash
python -m scripts.deploy_web_recommender_agent --build
```
An AG-UI marketing assistant that talks to `marketing_toolbox` and lets a marketer
discuss personas and products through a custom UI. Prints the public web-UI URL.
Readiness probe `/healthz`, port 8092. Key overrides: `WEB_RECOMMENDER_APP_NAME`
(web-recommender-agent), `WEB_RECOMMENDER_PORT` (8092),
`WEB_RECOMMENDER_EXTERNAL` (true), `MARKETING_TOOLBOX_NAME`, `MARKETING_MCP_URL`,
`AZURE_AI_MODEL_DEPLOYMENT_NAME` (gpt-4.1-mini). It uses the container's managed
identity by default; OBO is optional via `WEB_RECOMMENDER_CLIENT_ID` /
`WEB_RECOMMENDER_CLIENT_SECRET` / `WEB_RECOMMENDER_TENANT_ID`.

### Grant Agent 365 observability permissions (hosted agents)
The Foundry hosted agents export OpenTelemetry spans to the Agent 365 ingestion
service using their **Entra Agent Identity**, which must hold the
`Agent365.Observability.OtelWrite` app role, otherwise export fails with
`HTTP 403 … missing the required 'Agent365.Observability.OtelWrite' app role`.
Run once per hosted agent **after** deploy (idempotent):

```bash
# auto-discover the market-intelligence + executive-strategy agent identities
python -m scripts.grant_observability_permissions

# or target explicit agent identity object ids (from the 403 message / portal)
python -m scripts.grant_observability_permissions \
    --agent-id <agent-identity-object-id> --agent-id <agent-identity-object-id>
```

Requires `az login` as **Global Administrator** or **Application
Administrator**. Key overrides: `A365_OBSERVABILITY_AGENT_IDS` (comma-separated
object ids, overrides discovery), `AZURE_AI_MARKET_AGENT_NAME` /
`AZURE_AI_STRATEGY_AGENT_NAME` (names used for auto-discovery). Assignments can
take 2–5 minutes to propagate. See https://aka.ms/foundry-grant-agent-365-permissions.

---

## 9. Run Services Locally

MCP servers (serve streamable-HTTP MCP on `/mcp`). The three search-backed servers
need `AZURE_SEARCH_ENDPOINT` (+ optionally `AZURE_SEARCH_ADMIN_KEY`); set
`ENTRA_AUTH_ENABLED=false` for anonymous local access.

```bash
export AZURE_SEARCH_ENDPOINT="https://<search>.search.windows.net"
export ENTRA_AUTH_ENABLED=false

python -m src.product_mcp_server.server        # http://127.0.0.1:8093/mcp
python -m src.persona_mcp_server.server        # http://127.0.0.1:8094/mcp
python -m src.research_mcp_server.server        # http://127.0.0.1:8095/mcp
python -m src.market_insights_server.server     # http://127.0.0.1:8096/mcp  (no search; reads data/)
```

Agents (RESPONSES host, port 8088) — use a direct `*_MCP_URL` to bypass the toolbox:
```bash
export AZURE_AI_PROJECT_ENDPOINT="https://<project>.services.ai.azure.com/api/projects/<name>"

# market intelligence agent
export MARKETING_MCP_URL="http://127.0.0.1:8093/mcp"   # or the toolbox endpoint
python -m src.market_intelligence_agent.agent

# executive strategy agent
export STRATEGY_MCP_URL="http://127.0.0.1:8095/mcp"
python -m src.executive_strategy_agent.agent
```

Web recommender agent (AG-UI web UI, port 8092):
```bash
export AZURE_AI_PROJECT_ENDPOINT="https://<project>.services.ai.azure.com/api/projects/<name>"
export MARKETING_MCP_URL="http://127.0.0.1:8093/mcp"   # or the marketing_toolbox endpoint
python -m src.web_recommender_agent.server
# open http://localhost:8092
```

---

## 10. Cleanup

```bash
# Foundry hosted agents (market intelligence, executive strategy)
python -m scripts.delete_agents
python -m scripts.delete_agents --toolboxes   # also delete marketing_toolbox + strategy_toolbox

# Container Apps (4 MCP servers + web recommender agent)
python -m scripts.delete_container_apps
python -m scripts.delete_container_apps --purge-auth   # also delete the
                                                      # <app>-mcp-auth Entra
                                                      # app registrations

# the three Azure AI Search indexes (schema + data)
python -m scripts.delete_search_indexes

# tear down all Azure resources
azd down
```

---

## 11. Environment Variable Reference

Most variables are written to `./.env` by `azd up`.

| Variable | Source | Used by |
|---|---|---|
| `AZURE_RESOURCE_GROUP` | azd | all deploy scripts |
| `AZURE_REGISTRY` / `AZURE_CONTAINER_REGISTRY_ENDPOINT` | azd | build, deploy, hosted agents |
| `AZURE_CONTAINER_APPS_ENVIRONMENT_NAME` | azd | container-app deploy |
| `AZURE_IDENTITY_NAME` | azd | container-app deploy (managed identity) |
| `AZURE_AI_PROJECT_ENDPOINT` | azd | agents, toolboxes, connections |
| `AZURE_SEARCH_ENDPOINT` | azd | indexing, ingestion, search MCP servers |
| `AZURE_SEARCH_ADMIN_KEY` | azd | indexing (optional; falls back to DefaultAzureCredential) |
| `AZURE_SEARCH_PRODUCTS_INDEX_NAME` | azd | default: `products` |
| `AZURE_SEARCH_PERSONAS_INDEX_NAME` | azd | default: `personas` |
| `AZURE_SEARCH_INNOVATIONS_INDEX_NAME` | azd | default: `innovations` |
| `AZURE_OPENAI_ENDPOINT` | azd | embedding calls (ingest) |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME` | azd | default: `text-embedding-3-small` |
| `AZURE_OPENAI_EMBEDDING_DIMENSIONS` | manual | default: `1536` |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | azd | agent chat model (default: `gpt-4.1-mini`) |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` | azd | agent chat model override |
| `OPENAI_API_VERSION` | azd | default: `2024-05-01-preview` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | azd | telemetry (MCP servers + web agent) |
| `TAG` | manual | image tag for deploy (default: `latest`) |
| `PRODUCT_MCP_APP_NAME` / `PERSONA_MCP_APP_NAME` / `RESEARCH_MCP_APP_NAME` / `MARKET_MCP_APP_NAME` | manual | MCP Container App names |
| `PRODUCT_MCP_PORT` / `PERSONA_MCP_PORT` / `RESEARCH_MCP_PORT` / `MARKET_MCP_PORT` | manual | `8093` / `8094` / `8095` / `8096` |
| `PRODUCT_MCP_EXTERNAL` / `PERSONA_MCP_EXTERNAL` / `RESEARCH_MCP_EXTERNAL` / `MARKET_MCP_EXTERNAL` | manual | public ingress (default: true) |
| `PRODUCT_MCP_URL` / `PERSONA_MCP_URL` / `RESEARCH_MCP_URL` / `MARKET_MCP_URL` | manual | direct MCP URL (local dev / toolbox derive) |
| `MARKETING_DATA_DIR` | manual | market-insights data dir in container (`/app/data`) |
| `ENTRA_AUTH_ENABLED` | manual | validate Entra JWT in-app on MCP servers (default: true) |
| `PRODUCT_MCP_CONNECTION_ID` / `PERSONA_MCP_CONNECTION_ID` / `RESEARCH_MCP_CONNECTION_ID` / `MARKET_MCP_CONNECTION_ID` | manual | agent-identity Foundry connection ids the toolboxes use to reach each MCP server |
| `AGENT_IDENTITY_MCP_IDS` | manual | Entra Agent Identity object ids to grant `Mcp.Invoke` (overrides auto-discovery) |
| `MARKETING_TOOLBOX_NAME` | manual | default: `marketing_toolbox` |
| `STRATEGY_TOOLBOX_NAME` | manual | default: `strategy_toolbox` |
| `MARKETING_MCP_URL` / `STRATEGY_MCP_URL` | manual | direct toolbox MCP overrides for agents (local dev) |
| `EXECUTIVE_MARKETING_TOOLBOX_ENABLED` | manual | attach marketing_toolbox to the strategy agent (default: true) |
| `AZURE_AI_MARKET_AGENT_NAME` | manual | default: `market-intelligence-agent` |
| `AZURE_AI_STRATEGY_AGENT_NAME` | manual | default: `executive-strategy-agent` |
| `A365_OBSERVABILITY_AGENT_IDS` | manual | agent identity object ids to grant OtelWrite (overrides discovery) |
| `WEB_RECOMMENDER_APP_NAME` | manual | default: `web-recommender-agent` |
| `WEB_RECOMMENDER_PORT` / `WEB_RECOMMENDER_EXTERNAL` | manual | `8092` / public (true) |
| `WEB_RECOMMENDER_CLIENT_ID` / `WEB_RECOMMENDER_CLIENT_SECRET` / `WEB_RECOMMENDER_TENANT_ID` | manual | optional OBO for the web UI |

---

## 12. Conventions

- Run all scripts from the **repo root** as modules: `python -m scripts.<name>`.
- Scripts read `./.env` via `python-dotenv` — source it before manual CLI work.
- Image builds use `az acr build` (no local Docker). Both `:<timestamp>` and
  `:latest` tags are pushed on every build.
- Hosted agents (market intelligence, executive strategy) speak **RESPONSES + A2A
  + INVOCATIONS** on port `8088`; the web recommender Container App serves the
  AG-UI web UI on port `8092`.
- MCP server ports: product `8093`, persona `8094`, research `8095`,
  market-insights `8096`.
- Agents reach MCP servers through **Foundry toolboxes** by default; a direct
  `*_MCP_URL` override bypasses the toolbox for local dev.
- The MCP deploy scripts do **not** take `--register`; toolbox registration is a
  separate step (`register_marketing_toolbox` / `register_strategy_toolbox`).
- Each agent loads its domain flows from a `skills/` subfolder that ships inside
  its container image.
- All Python packages (services + scripts) are consolidated in the root
  `requirements.txt`; per-service `requirements.txt` files mirror the subset each
  Dockerfile installs.

---

## 13. End-to-End Sequence (happy path)

```bash
azd up
python -m scripts.generate_datasets          # data already committed; optional refresh
python -m scripts.create_search_indexes
python -m scripts.ingest_knowledge
python -m scripts.build_containers
python -m scripts.deploy_product_mcp_server
python -m scripts.deploy_persona_mcp_server
python -m scripts.deploy_research_mcp_server
python -m scripts.deploy_market_insights_server
python -m scripts.create_mcp_agent_identity_connections --grant   # Entra auth on
python -m scripts.grant_observability_permissions
python -m scripts.register_marketing_toolbox
python -m scripts.register_strategy_toolbox
python -m scripts.deploy_market_intelligence_agent
python -m scripts.deploy_executive_strategy_agent
python -m scripts.deploy_web_recommender_agent
# teardown
python -m scripts.delete_agents --toolboxes
python -m scripts.delete_container_apps --purge-auth
python -m scripts.delete_search_indexes
```
