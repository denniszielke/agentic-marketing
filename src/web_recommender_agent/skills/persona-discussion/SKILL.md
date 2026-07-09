# Persona Discussion

Use this flow when the marketer wants to explore or compare customer personas
and connect them to products or campaigns.

## Steps

1. **Find the persona(s)** — use the persona tools (`search_personas`,
   `list_personas`, `find_personas_by_interest`) to locate the persona(s) the
   marketer is asking about.
2. **Focus the sidebar** — call `update_overview` with the chosen persona and
   any products under discussion BEFORE writing your reply.
3. **Connect to products** — use the product tools (`search_products`,
   `list_products`, `get_positioning`) to surface products that fit the
   persona's interests, preferred categories and income band.
4. **Add market context** — where useful, use the market insights tools
   (`get_growth_rates`, `get_market_share`, `get_sales`) to show how the
   persona's preferred categories are performing in their market.
5. **Summarise** — give a concise, grounded recommendation for how to reach the
   persona (channel, message, product) and keep the sidebar current.

## Reminders
- Always pass the COMPLETE current state to `update_overview`.
- Never invent personas, products or figures — ground every claim in a tool
  result.
