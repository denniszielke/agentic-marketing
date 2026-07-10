# Sample Prompts — NorthStar Health

Copy-paste prompts to demo the agents and the underlying MCP tools. Every prompt
is grounded in the real datasets (markets: **Germany, UK, Nordics**; categories:
**Vitamins & Supplements, Gut Health, Weight Management, Home Diagnostics**) and
the real personas shipped in `data/personas.json`.

Send agent prompts to the RESPONSES endpoint (port 8088) or the web recommender
UI (port 8092), depending on the agent.

---

## By agent

### Market Intelligence Agent (`marketing_toolbox`: product + market-insights + persona)

Best at market dynamics, growth, share, pricing and persona targeting.

1. "Which category offers the highest growth opportunity in the **Nordics** over 2026-2028, and what price point should we set?"
2. "Compare **gross margins** for **Gut Health** across Germany, the UK and the Nordics — where is it most profitable?"
3. "Show me **market share** for **Weight Management** in the **UK** and name the competitors winning share."
4. "Which **personas** show the strongest interest in **Home Diagnostics** in Germany, and what do they spend annually?"
5. "We want to grow **Vitamins & Supplements** in the UK. Give me the top 3 target personas, a recommended price tier, and the supporting growth and share numbers."
6. "How do our **NorthStar Health** products stack up against competitor positioning in **Gut Health**? Recommend a repositioning."
7. "Rank all four categories in **Germany** by 2027 forecast revenue and flag the fastest riser."

### Executive Strategy Agent (`strategy_toolbox` + `marketing_toolbox`: research + market-insights + product + persona)

Best at board-level launch, investment and ROI decisions grounded in the
innovation knowledge base.

1. "**What product should we launch next?** Give me the top candidate from the innovation base, its estimated economics, the best launch market, and expected year-1 revenue and margin."
2. "Where should we invest **EUR 20m** for the highest ROI across our three markets? Prioritise by return and strategic fit."
3. "Which **innovation** best fits the **Nordics** Home Diagnostics opportunity, and which personas would we target first?"
4. "Give me a 24-month launch roadmap for **Weight Management** — candidate innovations, launch markets, investment required and projected market share."
5. "Summarise the emerging **trends** likely to reshape Gut Health, and recommend one bet with its cost, retail price and readiness."
6. "Build the board case for launching in the **UK** first vs. Germany first — headline numbers and the honest risks."
7. "Which innovation has the best margin-to-readiness trade-off, and what's the go/no-go recommendation?"

### Web Recommender Agent (AG-UI, `marketing_toolbox`)

Best for interactive persona exploration and campaign shaping; it keeps a live
sidebar via `update_overview`.

1. "Find me the **busy parent** personas in Germany and show the products that fit them."
2. "Explore **Grace Walker** (GBR-002) — what does she care about, and which 3 products should a campaign lead with?"
3. "Build a campaign idea for **weight-management seekers** in the UK: target persona, product bundle, and channel."
4. "Show all **biohacker / self-optimiser** personas and the premium products that match their interests."
5. "Compare **Vitamins & Supplements** products for a **sustainability-focused buyer** and recommend one hero SKU."

---

## By persona

Each persona prompt shows a realistic question and the agent best suited to
answer it. Persona ids match `data/personas.json`.

### Daniel Fischer — active retiree, Germany (GER-001)
- *Web / Market:* "**Daniel Fischer** is a conservative, low-digital 70-year-old who trusts pharmacists. Which **Vitamins & Supplements** and **Home Diagnostics** products should we recommend, and through which channel?"
- *Strategy:* "What upcoming **innovation** would resonate with active retirees like Daniel in Germany, and is it worth launching?"

### Andreas Weber — time-poor executive, Germany (GER-002)
- *Web / Market:* "**Andreas Weber** pays a premium for convenience and measurable results (Sleep, Energy, Cognitive Performance). Recommend a premium subscription bundle and justify the price tier."
- *Market:* "How large is the high-income executive segment in Germany, and what do they spend? Size the opportunity."

### Anna Klein — fitness professional, Germany (GER-004)
- *Web:* "Find products matching **Anna Klein**'s interests (Performance Nutrition, Energy, Lean Muscle) and lead with the most transparent, high-dosage formulas."
- *Market:* "Which **Weight Management** products fit fitness professionals, and how is that category growing in Germany?"

### Sophie Koch — biohacker / self-optimiser, Germany (GER-007)
- *Strategy:* "Which **innovations** would a biohacker like **Sophie Koch** adopt early? Recommend one bet with cost, retail price and readiness."
- *Web:* "Show the most cutting-edge products for self-optimisers and explain the claims."

### Heike Becker — weight-management seeker, Germany (GER-009)
- *Web / Market:* "Build a **Weight Management** recommendation for **Heike Becker** — target product, price point, and the growth/share evidence behind it."

### Chris Taylor — active retiree, UK (GBR-001)
- *Market:* "**Chris Taylor** is a high-income UK retiree focused on Preventative Care and Heart Health. Which **Home Diagnostics** products fit, and how is that category performing in the UK?"
- *Strategy:* "Is there a launch-worthy innovation for affluent UK retirees? Give the ROI case."

### Grace Walker — time-poor executive, UK (GBR-002)
- *Web / Market:* "Explore **Grace Walker** (GBR-002) and recommend a convenience-first product bundle for time-poor UK executives, with the price tier justified."

### Astrid Bergström — active retiree, Nordics (NOR-001)
- *Market:* "**Astrid Bergström** cares about Longevity, Heart Health and Preventative Care in the Nordics. Which categories are growing fastest there, and what should we recommend to her segment?"
- *Strategy:* "Which innovation best serves longevity-focused Nordic retirees, and what's the expected margin?"

### Cross-persona / segment prompts
- "Compare the **active retiree** segment across Germany, the UK and the Nordics — spend, interests and the best-fit products in each market."
- "Which **market + persona** combination is the most attractive for a new **Gut Health** launch? Justify with growth, share and spend."
- "Find every persona interested in **Immune Health** and group them by market and preferred channel."

---

## Tool-coverage cheat sheet

| Prompt theme | Tools exercised |
|---|---|
| Growth / share / margins / forecast | `get_sales`, `get_growth_rates`, `get_market_share`, `compare_margins`, `get_forecast`, `competitor_performance` |
| Product catalogue & positioning | `list_products`, `search_products`, `get_product`, `list_categories`, `list_brands`, `get_positioning` |
| Persona segmentation | `list_personas`, `search_personas`, `get_persona`, `find_personas_by_interest` |
| Innovation / launch decisions | `list_innovations`, `search_innovations`, `get_innovation`, `list_trends` |
