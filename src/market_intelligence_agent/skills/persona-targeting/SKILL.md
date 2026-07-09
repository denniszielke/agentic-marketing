# Persona Targeting

Use this flow when asked which customers to target for a category, product or
campaign, or which personas are showing increased interest.

## Steps

1. **Identify the theme** — the category or health interest in question
   (e.g. "gut health", "longevity", "GLP-1 weight management").
2. **Search personas** — call `search_personas` with the theme, and
   `find_personas_by_interest` for the specific interest keyword.
3. **Filter** — narrow by `market`, `preferred category`, `age group` and
   `income band` using `list_personas` when the request is market-specific.
4. **Qualify** — for each candidate persona, note their annual spend, preferred
   channel, digital maturity and risk tolerance to judge campaign fit.
5. **Rank** — order personas by fit (interest overlap × spend × channel match).

## Output shape

List the top personas with market, archetype, why they fit, and the channel to
reach them. Keep it to the 2-3 strongest matches unless more are requested.
