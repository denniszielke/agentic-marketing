# Opportunity Analysis

Use this flow when an executive or marketer asks which category, market or
product represents the best growth opportunity, or asks for a pricing
recommendation.

## Steps

1. **Frame the question** — identify the target market(s) and, if given, the
   category or time horizon. Default to comparing all four categories
   (Vitamins & Supplements, Gut Health, Weight Management, Home Diagnostics).
2. **Market performance** — call `get_growth_rates` and `get_market_share` for
   the target market; call `get_sales` for the recent historical revenue and
   `get_forecast` for the 2026-2028 projection.
3. **Rank categories** — order by growth rate and forecast revenue; note where
   NorthStar's share is low but growth is high (the opportunity zone).
4. **Competitor check** — call `competitor_performance` and `get_positioning`
   for the leading products in the target category to understand pricing and
   claims.
5. **Persona demand** — call `search_personas` / `find_personas_by_interest`
   for the category's core interests; identify the top 2-3 personas.
6. **Pricing** — inspect `list_products` price tiers in the category and market;
   propose a price point consistent with the target personas' income band and
   the competitor distribution.
7. **Recommendation** — output the recommended category, target market,
   recommended price, an estimated growth probability (0-100) and the top
   personas.

## Output shape

Lead with a one-line recommendation, then a short evidence table (growth,
share, competitor price band, persona fit), then the recommended price and
target personas.
