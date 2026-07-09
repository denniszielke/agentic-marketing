# Launch Recommendation

Use this flow when asked what product to launch next, or to recommend a launch
market for a concept.

## Steps

1. **Candidate concepts** — call `search_innovations` / `list_innovations` for
   the relevant category or trend; capture each concept's estimated cost,
   estimated sale price, estimated margin, market readiness and expected launch
   year.
2. **Market sizing** — for each candidate's target market, call `get_forecast`,
   `get_growth_rates` and `get_market_share` to size the opportunity.
3. **Competitive gap** — call `get_positioning` / `competitor_performance` to
   confirm there is room (low NorthStar share, high category growth).
4. **Persona demand** — call `search_personas` for the concept's core interests
   and estimate the addressable, high-spend segments.
5. **Economics** — estimate year-1 revenue (addressable demand × price ×
   adoption), gross margin and a projected market-share trajectory. State
   assumptions.
6. **Recommendation** — output: recommended launch, launch market, investment
   required, expected year-1 revenue, expected margin and projected market share.

## Output shape

Lead with the headline recommendation and numbers, then a short rationale and
the key assumptions/risks.
