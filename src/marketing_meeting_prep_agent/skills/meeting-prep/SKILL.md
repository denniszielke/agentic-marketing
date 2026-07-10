# Meeting Briefing

Use this flow when the marketer asks you to prepare for, brief them on, or get
them ready for an upcoming meeting.

## Steps

1. **Resolve the meeting (WorkIQ).** If the user names a meeting or gives a date,
   find it on their calendar; otherwise take the next upcoming event. Read the
   subject/title, agenda/body, start time and attendees. If nothing matches,
   say so and ask the user to name the meeting or date — never invent one.
2. **Derive the topics.** From the title and agenda text, extract the relevant
   market(s) (Germany, UK, Nordics), category(ies) (Vitamins & Supplements, Gut
   Health, Weight Management, Home Diagnostics), and any named products, brands
   or audiences.
3. **Product details.** Call `list_products` / `search_products` /
   `get_positioning` for the derived products or categories to summarise the
   relevant internal and competitor products.
4. **Market insights.** Call `get_sales`, `get_growth_rates`,
   `get_market_share` and `get_forecast` for the derived market(s) and
   category(ies) to summarise recent performance and the 2026-2028 outlook.
5. **Persona briefings.** Call `search_personas` /
   `find_personas_by_interest` for the derived audience; identify the top 2-3
   personas and why they matter for this meeting.
6. **Assemble the briefing.**

## Output shape

Lead with a meeting header (title, date/time, attendees — attributed to
WorkIQ), then a short briefing with three sections (Products, Market, Personas),
then 2-3 suggested talking points tailored to the agenda. Ground every figure in
a tool result.
