# Agentic Marketing — NorthStar Health

An agentic product-strategy & market-intelligence demo for the fictional consumer
healthcare company **NorthStar Health** (markets: Germany, UK, Nordics;
categories: Vitamins & Supplements, Gut Health, Weight Management, Home
Diagnostics).

It ships **four MCP servers**, **three Azure AI Search indexes**, **two Foundry
toolboxes** and **three agents**:

| Component | Type | Backing data | Port |
|---|---|---|---|
| `product_mcp_server` | Container App (MCP) | AI Search `products` index | 8093 |
| `persona_mcp_server` | Container App (MCP) | AI Search `personas` index | 8094 |
| `research_mcp_server` | Container App (MCP) | AI Search `innovations` index | 8095 |
| `market_insights_server` | Container App (MCP) | static JSON in-process | 8096 |
| `marketing_toolbox` | Foundry toolbox | product + market-insights + persona | — |
| `strategy_toolbox` | Foundry toolbox | product + market-insights + persona + research | — |
| `market_intelligence_agent` | Foundry hosted agent | `marketing_toolbox` | 8088 |
| `executive_strategy_agent` | Foundry hosted agent | `strategy_toolbox` + `marketing_toolbox` | 8088 |
| `web_recommender_agent` | Container App + AG-UI web UI | `marketing_toolbox` | 8092 |

> All commands run from the **repo root**. Configuration comes from `./.env`,
> which `azd up` writes automatically. Activate the project venv first:
> `source .venv/bin/activate` (or prefix commands with `.venv/bin/python`).

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Azure Developer CLI (`azd`) | latest | https://aka.ms/azd |
| Azure CLI (`az`) | ≥ 2.60 | https://aka.ms/azcli |
| Python | 3.13+ | |

```bash
# Install all Python deps (services + scripts are consolidated in the root file)
pip install -r requirements.txt

# Foundry azd extension — needed for agent-identity connections
azd ext install microsoft.foundry
```

---

## Deployment Overview

The end-to-end lifecycle:

```
provision → generate data → create indexes → ingest → build images →
deploy MCP servers → identities/auth → register toolboxes → deploy agents → deploy web
```

Each numbered section below is a step in that pipeline.

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

The bicep exports the marketing index names to `./.env`
(`AZURE_SEARCH_PRODUCTS_INDEX_NAME=products`,
`AZURE_SEARCH_PERSONAS_INDEX_NAME=personas`,
`AZURE_SEARCH_INNOVATIONS_INDEX_NAME=innovations`).

Granular commands: `azd provision`, `azd deploy`, `azd down`.

---

## 2. Generate Demo Data

Synthetic datasets are generated deterministically (seeded) and are already
committed under `data/`. Regenerate only if you change the generator:

```bash
python -m scripts.generate_datasets
```

Produces `data/products.json`, `data/personas.json`,
`data/research_innovations.json`, `data/market_sales_monthly.json`,
`data/market_sales_annual.json`.

---

## 3. Create & Populate the Search Indexes

Three Azure AI Search indexes — **products**, **personas**, **innovations** —
each with an HNSW vector field and a semantic configuration.

```bash
# create/update the three index schemas
python -m scripts.create_search_indexes

# read the JSON datasets, embed each record's description into
# description_vector (if AZURE_OPENAI_ENDPOINT is set), and upload
python -m scripts.ingest_knowledge
```

Ingestion is embedding-optional: without `AZURE_OPENAI_ENDPOINT`, documents are
pushed without vectors and text/semantic search still works. Run this step
**before** deploying the search-backed MCP servers so their queries return data.

---

## 4. Build the Container Images

Builds all seven images in ACR (no local Docker): the four MCP servers, the two
hosted agents and the web recommender. Only builds — does not deploy.

```bash
python -m scripts.build_containers                 # auto timestamp tag + :latest
python -m scripts.build_containers latest          # explicit tag
python -m scripts.build_containers --env <name>    # override rg-<name>
```

Images: `product-mcp-server`, `persona-mcp-server`, `research-mcp-server`,
`market-insights-server`, `market-intelligence-agent`, `executive-strategy-agent`,
`web-recommender-agent`.

> Each `deploy_*` script also accepts `--build` to build just its own image in
> ACR first, so a full pre-build is optional.

---

## 5. Deploy the MCP Servers

Deploys each MCP server as a Container App via `infra/core/host/app.bicep`. Pass
`--build` to build in ACR first (else deploys `:latest` or the `TAG` env var).

```bash
python -m scripts.deploy_product_mcp_server --build        # products index (8093)
python -m scripts.deploy_persona_mcp_server --build        # personas index (8094)
python -m scripts.deploy_research_mcp_server --build       # innovations index (8095)
python -m scripts.deploy_market_insights_server --build    # static sales data (8096)
```

Each prints the deployed `…/mcp` URL and exposes `/health` as an unauthenticated
readiness route. Per-server overrides use the `PRODUCT_` / `PERSONA_` /
`RESEARCH_` / `MARKET_` prefix (`<PREFIX>_MCP_APP_NAME`, `<PREFIX>_MCP_PORT`,
`<PREFIX>_MCP_EXTERNAL`, `<PREFIX>_MCP_URL`).

### Protect the MCP servers with Entra ID

The MCP servers validate Entra ID access tokens **natively inside the app** via
FastMCP's `AzureJWTVerifier` + `RemoteAuthProvider` — no Container Apps Easy Auth,
no sidecar, no client secret. Auth is on by default. Opt out per deployment:

```bash
azd env set ENTRA_AUTH_ENABLED false   # anonymous ingress
```

With auth enabled, deploying (§5) will, for each server: ensure an Entra app
registration (`<app>-mcp-auth`) with an `Mcp.Invoke` app role (audience
`api://<appId>`), inject the auth config into the container, and print the
audience callers must request a token for. Anonymous requests get **HTTP 401**.
Requires `az login` with rights to create app registrations and app-role
assignments.

---

## 6. Identities & Permissions (Entra auth on)

When `ENTRA_AUTH_ENABLED=true`, the hosted agents call the MCP servers through the
toolboxes using their **Entra Agent Identity** (no secret). Grant the role and
create the Foundry connections in one helper:

```bash
# grants each agent identity Mcp.Invoke on the MCP apps, then creates a
# remote-tool/agentic-identity connection per server (audience api://<appId>)
python -m scripts.create_mcp_agent_identity_connections --grant
```

It prints the connection-id lines to add to `./.env`
(`PRODUCT_MCP_CONNECTION_ID`, `MARKET_MCP_CONNECTION_ID`,
`PERSONA_MCP_CONNECTION_ID`, `RESEARCH_MCP_CONNECTION_ID`). Without the
connections the toolbox registration warns and tool calls return **401**.

Run for one server only, or grant only:

```bash
python -m scripts.create_mcp_agent_identity_connections --only persona
python -m scripts.grant_agent_identity_mcp_role
python -m scripts.grant_agent_identity_mcp_role --agent-id <agent-identity-object-id>
```

> **IMPORTANT — agent identity rotation.** Each agent republish/redeploy can
> rotate the hosted agent's Entra Agent Identity (new service-principal object
> id). After each deploy, re-run `grant_agent_identity_mcp_role` (it
> auto-discovers), refresh the connections if needed, and re-register the
> toolboxes.

---

## 7. Register the Foundry Toolboxes

Register the two toolboxes after the MCP servers are deployed (idempotent). Each
bundles multiple MCP servers into one toolbox and, when Entra auth is on,
attaches the per-server `*_MCP_CONNECTION_ID` from §6.

```bash
python -m scripts.register_marketing_toolbox    # → marketing_toolbox (product + market + persona)
python -m scripts.register_strategy_toolbox     # → strategy_toolbox  (+ research)
```

Each prints the consumer endpoint
`{project}/toolboxes/{toolbox}/mcp?api-version=v1`.

---

## 8. Deploy the Agents

Prerequisites: MCP servers deployed (§5), indexes created + ingested (§3),
identities/connections created (§6, if auth on) and toolboxes registered (§7).

### Market intelligence agent — Foundry hosted agent (`marketing_toolbox`)

```bash
python -m scripts.deploy_market_intelligence_agent
```

Enables RESPONSES + A2A + INVOCATIONS. Key overrides:
`AZURE_AI_MARKET_AGENT_NAME` (default `market-intelligence-agent`),
`MARKETING_TOOLBOX_NAME`, `MARKETING_MCP_URL` (direct MCP override for local dev).

### Executive strategy agent — Foundry hosted agent (`strategy_toolbox` + `marketing_toolbox`)

```bash
python -m scripts.deploy_executive_strategy_agent
```

Key overrides: `AZURE_AI_STRATEGY_AGENT_NAME` (default
`executive-strategy-agent`), `STRATEGY_TOOLBOX_NAME`, `MARKETING_TOOLBOX_NAME`,
`EXECUTIVE_MARKETING_TOOLBOX_ENABLED` (default true), `STRATEGY_MCP_URL` /
`MARKETING_MCP_URL`.

### Web recommender agent — Container App + AG-UI web UI (`marketing_toolbox`)

```bash
python -m scripts.deploy_web_recommender_agent --build
```

An AG-UI marketing assistant that talks to `marketing_toolbox` through a custom
UI. Prints the public web-UI URL. Readiness probe `/healthz`, port 8092. Key
overrides: `WEB_RECOMMENDER_APP_NAME`, `WEB_RECOMMENDER_PORT` (8092),
`WEB_RECOMMENDER_EXTERNAL` (true), `MARKETING_TOOLBOX_NAME`, `MARKETING_MCP_URL`,
`AZURE_AI_MODEL_DEPLOYMENT_NAME` (gpt-4.1-mini). Uses the container's managed
identity by default; OBO is optional via `WEB_RECOMMENDER_CLIENT_ID` /
`WEB_RECOMMENDER_CLIENT_SECRET` / `WEB_RECOMMENDER_TENANT_ID`.

### Grant Agent 365 observability permissions (hosted agents)

Hosted agents export OpenTelemetry spans to the Agent 365 ingestion service using
their Entra Agent Identity, which must hold the
`Agent365.Observability.OtelWrite` app role (otherwise export fails with HTTP
403). Run once per hosted agent **after** deploy (idempotent):

```bash
python -m scripts.grant_observability_permissions
# or target explicit agent identity object ids:
python -m scripts.grant_observability_permissions \
    --agent-id <agent-identity-object-id> --agent-id <agent-identity-object-id>
```

Requires `az login` as Global Administrator or Application Administrator.
Assignments can take 2–5 minutes to propagate.

---

## 9. Run Services Locally

MCP servers (streamable-HTTP MCP on `/mcp`). Search-backed servers need
`AZURE_SEARCH_ENDPOINT`; set `ENTRA_AUTH_ENABLED=false` for anonymous local access.

```bash
export AZURE_SEARCH_ENDPOINT="https://<search>.search.windows.net"
export ENTRA_AUTH_ENABLED=false

python -m src.product_mcp_server.server        # http://127.0.0.1:8093/mcp
python -m src.persona_mcp_server.server        # http://127.0.0.1:8094/mcp
python -m src.research_mcp_server.server        # http://127.0.0.1:8095/mcp
python -m src.market_insights_server.server     # http://127.0.0.1:8096/mcp
```

Agents (RESPONSES host, port 8088) — use a direct `*_MCP_URL` to bypass the toolbox:

```bash
export AZURE_AI_PROJECT_ENDPOINT="https://<project>.services.ai.azure.com/api/projects/<name>"

export MARKETING_MCP_URL="http://127.0.0.1:8093/mcp"
python -m src.market_intelligence_agent.agent

export STRATEGY_MCP_URL="http://127.0.0.1:8095/mcp"
python -m src.executive_strategy_agent.agent
```

Web recommender agent (AG-UI web UI, port 8092):

```bash
export AZURE_AI_PROJECT_ENDPOINT="https://<project>.services.ai.azure.com/api/projects/<name>"
export MARKETING_MCP_URL="http://127.0.0.1:8093/mcp"
python -m src.web_recommender_agent.server
# open http://localhost:8092
```

---

## 10. Cleanup

```bash
# Foundry hosted agents (market intelligence, executive strategy)
python -m scripts.delete_agents
python -m scripts.delete_agents --toolboxes            # also delete the two toolboxes

# Container Apps (4 MCP servers + web recommender agent)
python -m scripts.delete_container_apps
python -m scripts.delete_container_apps --purge-auth   # also delete <app>-mcp-auth app regs

# the three Azure AI Search indexes (schema + data)
python -m scripts.delete_search_indexes

# tear down all Azure resources
azd down
```

---

## Conventions

- Run all scripts from the **repo root** as modules: `python -m scripts.<name>`.
- Scripts read `./.env` via `python-dotenv`; source it before manual CLI work.
- Image builds use `az acr build` (no local Docker). Both `:<timestamp>` and
  `:latest` tags are pushed on every build.
- Hosted agents speak **RESPONSES + A2A + INVOCATIONS** on port `8088`; the web
  recommender serves the AG-UI web UI on port `8092`.
- MCP server ports: product `8093`, persona `8094`, research `8095`,
  market-insights `8096`.
- Agents reach MCP servers through **Foundry toolboxes** by default; a direct
  `*_MCP_URL` override bypasses the toolbox for local dev.
- MCP deploy scripts do **not** take `--register`; toolbox registration is a
  separate step (§7).
- All Python packages are consolidated in the root `requirements.txt`.

---

## Key Environment Variables

Most variables are written to `./.env` by `azd up`.

| Variable | Source | Used by |
|---|---|---|
| `AZURE_RESOURCE_GROUP` | azd | all deploy scripts |
| `AZURE_REGISTRY` / `AZURE_CONTAINER_REGISTRY_ENDPOINT` | azd | build, deploy |
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
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | azd | agent chat model (default: `gpt-4.1-mini`) |
| `ENTRA_AUTH_ENABLED` | manual | validate Entra JWT in-app on MCP servers (default: true) |
| `PRODUCT_MCP_CONNECTION_ID` / `PERSONA_MCP_CONNECTION_ID` / `RESEARCH_MCP_CONNECTION_ID` / `MARKET_MCP_CONNECTION_ID` | manual | agent-identity connection ids the toolboxes use |
| `MARKETING_TOOLBOX_NAME` / `STRATEGY_TOOLBOX_NAME` | manual | defaults: `marketing_toolbox` / `strategy_toolbox` |
| `AZURE_AI_MARKET_AGENT_NAME` / `AZURE_AI_STRATEGY_AGENT_NAME` | manual | hosted agent names |
| `WEB_RECOMMENDER_APP_NAME` / `WEB_RECOMMENDER_PORT` | manual | web UI app name / `8092` |
| `TAG` | manual | image tag for deploy (default: `latest`) |

For the full variable reference and deeper operational detail, see the ops
runbook at [.github/skills/ops/SKILL.md](.github/skills/ops/SKILL.md).
