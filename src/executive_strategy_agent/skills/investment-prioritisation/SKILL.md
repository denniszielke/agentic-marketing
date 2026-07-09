# Investment Prioritisation

Use this flow when asked where to invest a given budget (e.g. "where should we
invest EUR 20m?") or which market/category delivers the highest ROI.

## Steps

1. **Define the options** — enumerate the candidate markets × categories in
   scope. Default to all three markets and four categories.
2. **Return drivers** — for each option, gather growth rate (`get_growth_rates`),
   forecast revenue (`get_forecast`), current share (`get_market_share`) and
   average margin (`compare_margins`).
3. **Score ROI** — rank options by expected margin-weighted revenue growth per
   unit of investment; note strategic fit (share headroom, persona demand,
   innovation pipeline readiness).
4. **Allocate** — split the budget across the top options, keeping a clear
   rationale for each allocation.
5. **Summarise** — produce a board-ready allocation with expected returns.

## Output shape

A short allocation table (option, allocation, expected return, rationale) with a
one-line overall recommendation on top.
