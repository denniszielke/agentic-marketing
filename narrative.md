# Detailed Functional Specification for Coding Agents

This scenario is intended to demonstrate a fully agentic product strategy and market intelligence platform for a fictional consumer healthcare company called NorthStar Health. The objective is to show how agents can continuously analyse market conditions, monitor competitors, understand customer needs, evaluate product opportunities and generate executive recommendations.

The environment should simulate realistic healthcare consumer markets while using entirely synthetic data.

## Business Scenario

NorthStar Health operates in three key markets:

- Germany
- United Kingdom
- Nordics

The company offers products across four strategic healthcare categories:

- Vitamins & Supplements
- Gut Health
- Weight Management
- Home Diagnostics

The company faces increasing competition and must constantly answer strategic questions such as:

- Which products should be launched next?
- Which markets offer the highest growth potential?
- How should pricing differ between Germany, the UK and the Nordics?
- Which customer personas are showing increased interest?
- Which competitors are winning market share?
- What innovations are expected to emerge over the next 12-24 months?

To address these questions the organisation uses a collection of MCP servers and AI agents.

## MCP Server Specifications

### product_mcp_server

The Product MCP Server acts as the primary source of product information within the organisation.

The server stores all internal and competitor products and provides structured access to product metadata.

**Core Functions**

The Product MCP Server should be able to:

- Retrieve product details by product identifier.
- Search products by category.
- Search products by market.
- Search products by competitor.
- Return metadata for products.
- Return product lifecycle information.
- Return product launch history.
- Return product positioning information.

**Example Product Metadata**

```json
{
  "product_id": "VIT-1001",
  "product_name": "NorthStar VitaComplete",
  "category": "Vitamins & Supplements",
  "brand": "NorthStar Health",
  "market": ["Germany", "UK", "Nordics"],
  "price_tier": "Premium",
  "launch_year": 2024,
  "cost_per_unit": 8.50,
  "list_price": 29.99,
  "gross_margin": 72,
  "claims": [
    "Immune Support",
    "Energy",
    "Cognitive Health"
  ]
}
```

**Expected Dataset Size**

For demo purposes generate:

- 50 products
- 5 brands
- 4 categories
- 3 markets

### market_insights_server

The Market Insights MCP Server provides market intelligence and financial performance information.

The server contains historical and forecast market performance.

**Core Functions**

The server should return:

- Product pricing
- Product margin
- Units sold
- Revenue
- Market share
- Growth rates
- Competitor performance
- Forecasts

**Example Queries**

The server should support questions such as:

- Show all probiotics sold in Germany.
- Which products grew most in the Nordics during 2025?
- Compare margins for weight management products between Germany and the UK.
- Which competitors increased prices in the last year?

**Example Data Model**

```json
{
  "year": 2025,
  "market": "Germany",
  "product_id": "GUT-2001",
  "units_sold": 185000,
  "revenue": 6700000,
  "gross_margin": 63,
  "growth_rate": 18,
  "market_share": 7.2
}
```

**Expected Dataset Size**

Generate:

- Six years of history (2020-2025)
- Monthly sales
- Market-level forecasts
- 2026-2028 projections

### ### research_mcp_server

The Research MCP Server functions as a healthcare innovation knowledge repository.

This server contains synthetic analyst reports and future healthcare concepts.

The purpose is to support innovation and strategic planning.

**Core Functions**

The server should provide:

- Emerging market trends
- Innovation opportunities
- Competitor launches
- Future product categories
- Estimated production costs
- Estimated retail pricing

**Example Research Objects**

```json
{
  "innovation_name": "MicroBiome Twin",
  "category": "Gut Health",
  "technology": "Continuous Gut Monitoring",
  "estimated_cost": 35,
  "estimated_sale_price": 129,
  "market_readiness": "Medium",
  "target_market": "Nordics",
  "expected_launch_year": 2027
}
```

**Example Innovation Themes**

| Category | Themes |
| --- | --- |
| Gut Health | Continuous microbiome monitoring; AI nutrition coaching; Biological gut-age scoring |
| Weight Management | GLP-1 companion programmes; Metabolic digital twins; Personalised appetite optimisation |
| Diagnostics | Multi-marker testing; Home blood analysis; Preventive longevity scoring |
| Vitamins | Adaptive supplements; Diagnostic-driven supplements; AI-generated supplement plans |

### persona_mcp_server

The Persona MCP Server provides customer segmentation context.

Every persona should contain behavioural, demographic and commercial information.

**Core Functions**

The server should allow:

- Lookup by market
- Lookup by category
- Lookup by age group
- Lookup by income
- Lookup by health objective

**Example Persona**

```json
{
  "persona_id": "GER-001",
  "name": "Active Retiree Anna",
  "market": "Germany",
  "age": 67,
  "income_band": "Middle",
  "interests": [
    "Longevity",
    "Heart Health",
    "Preventative Care"
  ],
  "preferred_categories": [
    "Vitamins",
    "Diagnostics"
  ],
  "annual_spend": 900
}
```

**Dataset Guidance**

Generate:

- 30 personas per market
- 90 total personas

Each persona should contain:

- Age
- Gender
- Income
- Health interests
- Risk tolerance
- Annual spend
- Digital maturity
- Product preferences

## Agent Specifications

### market_intelligence_agent

The Market Intelligence Agent is responsible for discovering opportunities and analysing market dynamics.

**Data Sources**

The agent can access:

- product_mcp_server
- market_insights_server
- persona_mcp_server

**Responsibilities**

The agent continuously evaluates:

- Product performance
- Market performance
- Market growth
- Competitor pricing
- Customer demand
- Persona shifts

**Example Workflow**

The agent starts when an executive requests:

> "Which category offers the highest growth opportunity in the Nordics?"

The agent performs the following steps:

1. Retrieves category-level market performance.
2. Identifies high-growth categories.
3. Identifies fastest-growing personas.
4. Reviews competitor positioning.
5. Reviews pricing distribution.
6. Calculates pricing recommendations.
7. Produces recommendation report.

**Output Example**

```json
{
  "recommended_category": "Gut Health",
  "target_market": "Nordics",
  "recommended_price": 42.99,
  "growth_probability": 86,
  "top_personas": [
    "Biohacker Erik",
    "Health Optimiser Andreas"
  ]
}
```

### executive_strategy_agent

The Executive Strategy Agent acts as a virtual Chief Strategy Officer.

The agent consumes outputs from all MCP servers and subordinate agents.

**Responsibilities**

The Executive Strategy Agent should:

- Calculate revenue projections.
- Evaluate profitability.
- Forecast market share.
- Prioritise launch markets.
- Recommend investments.
- Produce executive summaries.

**Example Questions**

The Executive Team may ask:

- What product should be launched next?
- Which market delivers the highest ROI?
- Where should we invest €20 million?
- Which persona segment generates the highest lifetime value?

**Example Output**

```json
{
  "recommended_launch": "MicroBiome Twin",
  "launch_market": "Nordics",
  "investment_required": 12000000,
  "expected_revenue_year1": 35000000,
  "expected_margin": 67,
  "projected_market_share": 4.8
}
```

## User Personas

### Researcher Persona

The Researcher is responsible for understanding healthcare trends and future innovations.

The Researcher primarily interacts with the Research MCP Server.

Typical questions include:

- Which innovations are emerging in gut health?
- How are competitors approaching longevity solutions?
- Which future products have the highest commercial potential?
- Which technologies are expected to become mainstream?

The Researcher consumes strategic reports rather than operational data.

### Marketing Persona

The Marketeer focuses on demand generation, campaign planning and market performance.

The Marketeer primarily works with:

- Market Intelligence Agent
- Product MCP Server
- Market Insights Server

Typical questions include:

- Which products generate the strongest growth?
- Which personas are responding to our campaigns?
- Which price points drive maximum conversion?
- Which market is most attractive for launch?

The Marketeer requires dashboards, segmentation reports and campaign recommendations.

### Executive Persona

The Executive is focused on financial performance and strategic investment decisions.

The Executive primarily interacts with:

- Executive Strategy Agent

Typical questions include:

- Which products generate the highest margin?
- Which category should receive investment?
- Which market should be prioritised?
- How much revenue can be generated next year?

Executives consume board-level recommendations rather than detailed operational metrics.

## Sample Data Generation Guidance

To make the demo realistic, create approximately:

| Entity | Records |
| --- | --- |
| Products | 50 |
| Competitor Products | 150 |
| Personas | 90 |
| Monthly Sales Records | 10,800+ |
| Market Reports | 500 |
| Innovation Reports | 250 |

Generate trends that appear realistic:

- Gut Health should grow fastest in the Nordics.
- Home Diagnostics should grow strongly in all markets.
- Germany should have the highest average margins.
- UK should demonstrate strongest pricing competition.
- Nordics should demonstrate strongest innovation adoption.
- Weight Management should accelerate due to GLP-1 related products.
- Premium products should deliver 20-40% higher margins than mid-tier products.

This dataset is sufficiently rich to support natural-language queries, forecasting demonstrations, pricing optimisation, executive reporting, market intelligence scenarios and multi-agent orchestration demonstrations.