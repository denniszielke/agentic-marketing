"""
NorthStar Health — synthetic dataset generator.

Produces four datasets under ./data:
  - products.json               (>= 50 products per category, 4 categories)
  - personas.json               (>= 50 personas per market, 3 markets)
  - research_innovations.json    (>= 50 innovations mapped to market trends)
  - market_sales_monthly.json    (monthly sales history + forecast, NorthStar portfolio)
  - market_sales_annual.json     (per product/market/year summary with growth & share)

All records include a human-readable `description` so semantic search has
sufficient context. Prices, costs, margins, ages and years are internally
consistent and grounded in the pricing / growth tables in context.md.

Deterministic via a fixed random seed.
"""

import json
import math
import os
import random

random.seed(20260709)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# --------------------------------------------------------------------------
# Shared reference data (grounded in context.md)
# --------------------------------------------------------------------------

CATEGORIES = [
    "Vitamins & Supplements",
    "Gut Health",
    "Weight Management",
    "Home Diagnostics",
]

CATEGORY_PREFIX = {
    "Vitamins & Supplements": "VIT",
    "Gut Health": "GUT",
    "Weight Management": "WGT",
    "Home Diagnostics": "DIA",
}

MARKETS = ["Germany", "UK", "Nordics"]

MARKET_CURRENCY = {"Germany": "EUR", "UK": "GBP", "Nordics": "EUR"}
CURRENCY_SYMBOL = {"EUR": "€", "GBP": "£"}

BRANDS = [
    "NorthStar Health",
    "VitaCore Labs",
    "PurePath Wellness",
    "BioMetric Health",
    "NordicVital",
    "NutriSphere",
]
BRAND_SHORT = {
    "NorthStar Health": "NorthStar",
    "VitaCore Labs": "VitaCore",
    "PurePath Wellness": "PurePath",
    "BioMetric Health": "BioMetric",
    "NordicVital": "NordicVital",
    "NutriSphere": "NutriSphere",
}
# NorthStar (internal) gets the biggest share; the rest are competitors.
BRAND_WEIGHTS = [0.32, 0.15, 0.14, 0.13, 0.13, 0.13]

PRICE_TIERS = ["Entry", "Mid Market", "Premium"]
TIER_WEIGHTS = [0.35, 0.40, 0.25]

# Per-market / category / tier list prices (context.md price distribution).
PRICES = {
    "Germany": {
        "Vitamins & Supplements": {"Entry": 8, "Mid Market": 18, "Premium": 35},
        "Gut Health": {"Entry": 12, "Mid Market": 28, "Premium": 55},
        "Weight Management": {"Entry": 18, "Mid Market": 40, "Premium": 80},
        "Home Diagnostics": {"Entry": 29, "Mid Market": 69, "Premium": 149},
    },
    "UK": {
        "Vitamins & Supplements": {"Entry": 7, "Mid Market": 18, "Premium": 40},
        "Gut Health": {"Entry": 12, "Mid Market": 30, "Premium": 60},
        "Weight Management": {"Entry": 15, "Mid Market": 45, "Premium": 90},
        "Home Diagnostics": {"Entry": 25, "Mid Market": 75, "Premium": 175},
    },
    "Nordics": {
        "Vitamins & Supplements": {"Entry": 10, "Mid Market": 22, "Premium": 45},
        "Gut Health": {"Entry": 15, "Mid Market": 35, "Premium": 70},
        "Weight Management": {"Entry": 20, "Mid Market": 55, "Premium": 100},
        "Home Diagnostics": {"Entry": 35, "Mid Market": 90, "Premium": 199},
    },
}

# Annual category growth rate (%) per market (context.md).
GROWTH = {
    "Germany": {
        "Vitamins & Supplements": 6,
        "Gut Health": 11,
        "Weight Management": 8,
        "Home Diagnostics": 15,
    },
    "UK": {
        "Vitamins & Supplements": 8,
        "Gut Health": 13,
        "Weight Management": 12,
        "Home Diagnostics": 16,
    },
    "Nordics": {
        "Vitamins & Supplements": 7,
        "Gut Health": 14,
        "Weight Management": 10,
        "Home Diagnostics": 18,
    },
}

# --------------------------------------------------------------------------
# Category vocabulary for rich, varied descriptions
# --------------------------------------------------------------------------

CATEGORY_VOCAB = {
    "Vitamins & Supplements": {
        "noun": "supplement",
        "lines": ["Vita", "Immuno", "Neuro", "Cardio", "Energy", "Flex",
                   "Daily", "Pure", "Bio", "Active", "Omega", "Cellular"],
        "descriptors": ["Complete", "Max", "Plus", "Boost", "Restore", "Guard",
                         "Balance", "Formula", "Advanced", "Core", "Prime", "One"],
        "ingredients": ["vitamin D3 and K2", "chelated magnesium", "zinc and selenium",
                         "a B-complex blend", "marine omega-3", "CoQ10", "ashwagandha",
                         "buffered vitamin C", "iron bisglycinate", "methylated folate",
                         "lutein and zeaxanthin", "curcumin phytosome"],
        "benefits": ["immune resilience", "sustained energy metabolism", "cognitive clarity",
                      "bone and joint strength", "cardiovascular health", "stress adaptation",
                      "restful sleep", "healthy aging", "hormonal balance"],
        "formats": ["once-daily capsules", "vegan softgels", "effervescent tablets",
                     "sugar-free gummies", "single-serve powder sachets", "sublingual drops"],
        "claims_pool": ["Immune Support", "Energy", "Cognitive Health", "Heart Health",
                         "Bone Health", "Stress Relief", "Sleep Support", "Antioxidant",
                         "Vegan", "Clinically Studied Ingredients"],
    },
    "Gut Health": {
        "noun": "gut health product",
        "lines": ["Gut", "MicroBiome", "Flora", "Digest", "Biome", "Balance",
                   "Restore", "Symbio", "Enzyme", "Fibre", "Culture", "Bio"],
        "descriptors": ["Pro", "Daily", "Balance", "Restore", "Complete", "Plus",
                         "Advanced", "Sync", "Guard", "Complex", "Care", "Renew"],
        "ingredients": ["a 12-strain probiotic blend", "Lactobacillus and Bifidobacterium cultures",
                         "prebiotic inulin", "psyllium and acacia fibre", "digestive enzymes",
                         "L-glutamine", "postbiotic butyrate", "spore-forming probiotics",
                         "zinc carnosine", "slippery elm and marshmallow root"],
        "benefits": ["microbiome balance", "digestive comfort", "reduced bloating",
                      "gut barrier integrity", "regularity", "immune modulation via the gut",
                      "improved nutrient absorption"],
        "formats": ["delayed-release capsules", "flavourless drink powder", "daily sachets",
                     "chewable tablets", "shelf-stable capsules"],
        "claims_pool": ["Microbiome Support", "Digestive Comfort", "Bloating Relief",
                         "Gut Barrier", "Regularity", "Immune Support", "Prebiotic",
                         "Live Cultures", "Vegan", "Sugar-Free"],
    },
    "Weight Management": {
        "noun": "weight management product",
        "lines": ["Meta", "Lean", "Slim", "Satiety", "Burn", "Shape", "Trim",
                   "GLP", "Metabolic", "Fuel", "Balance", "Active"],
        "descriptors": ["Pro", "Lean", "Shake", "Boost", "Control", "Companion",
                         "Plus", "Support", "Formula", "Path", "Complete", "Daily"],
        "ingredients": ["glucomannan fibre", "green tea catechins", "L-carnitine",
                         "chromium picolinate", "a whey and pea protein blend",
                         "GLP-1 companion micronutrients", "konjac root", "5-HTP",
                         "capsaicin extract", "branched-chain amino acids"],
        "benefits": ["appetite control", "metabolic support", "lean muscle preservation",
                      "sustained satiety", "steady energy", "balanced blood sugar",
                      "nutritional support during GLP-1 therapy"],
        "formats": ["high-protein meal-replacement shake", "capsules", "pre-meal fibre sachets",
                     "ready-to-mix powder", "chewable appetite tablets"],
        "claims_pool": ["Appetite Control", "Metabolism Support", "High Protein", "Satiety",
                         "Low Sugar", "GLP-1 Companion", "Lean Muscle", "Energy",
                         "Meal Replacement", "Vegan Option"],
    },
    "Home Diagnostics": {
        "noun": "home diagnostic kit",
        "lines": ["Vita", "Cholestro", "Gut", "Hormone", "Metabolic", "Longevity",
                   "Health", "Insight", "Bio", "Cardio", "Immune", "Inflam"],
        "descriptors": ["Scan", "Check", "Track", "Insight", "Index", "Test",
                         "Screen", "Profile", "Monitor", "360", "Panel", "Report"],
        "technologies": ["a finger-prick dried blood spot sample", "a lateral-flow assay",
                          "at-home sampling with certified lab analysis",
                          "a smartphone-read colorimetric test", "a stool sampling kit",
                          "a saliva hormone sample", "a multi-marker blood panel"],
        "measures": ["vitamin D status", "a full cholesterol and lipid panel",
                      "gut microbiome diversity", "key female hormones",
                      "HbA1c and metabolic markers", "inflammation (CRP)",
                      "iron and ferritin levels", "a combined longevity biomarker score"],
        "benefits": ["early detection of deficiencies", "personalised recommendations",
                      "progress tracking over time", "clinically validated results",
                      "actionable lifestyle guidance"],
        "formats": ["single-use test kit", "quarterly subscription kit", "annual screening kit"],
        "claims_pool": ["At-Home Testing", "Lab-Analysed", "Personalised Insights",
                         "Early Detection", "Progress Tracking", "Clinically Validated",
                         "Fast Results", "Subscription", "No Clinic Visit", "GDPR-Compliant"],
    },
}

TARGET_AUDIENCE = [
    "health-conscious professionals", "active retirees", "biohackers and self-optimisers",
    "busy parents", "endurance and fitness enthusiasts", "wellness-focused women",
    "preventive-health adopters", "value-seeking everyday shoppers",
    "consumers on GLP-1 therapy", "longevity-minded consumers",
]

DIFFERENTIATORS = [
    "clean-label sourcing and full ingredient transparency",
    "clinically studied dosages", "a subscription model with adaptive refills",
    "sustainable, recyclable packaging", "third-party purity testing",
    "app-connected tracking and coaching", "Nordic-sourced sustainable ingredients",
    "pharmacy-grade quality certification", "affordable everyday pricing",
    "premium bioavailable formulations",
]


def money(x):
    return round(x + 0.0, 2)


def article(word):
    return "an" if word[:1].lower() in "aeiou" else "a"


def gen_products():
    products = []
    for category in CATEGORIES:
        vocab = CATEGORY_VOCAB[category]
        used_names = set()
        count = 0
        prefix = CATEGORY_PREFIX[category]
        while count < 56:
            brand = random.choices(BRANDS, weights=BRAND_WEIGHTS, k=1)[0]
            line = random.choice(vocab["lines"])
            desc = random.choice(vocab["descriptors"])
            name = f"{BRAND_SHORT[brand]} {line}{desc}"
            if name in used_names:
                continue
            used_names.add(name)
            count += 1
            pid = f"{prefix}-{1000 + count}"

            tier = random.choices(PRICE_TIERS, weights=TIER_WEIGHTS, k=1)[0]

            # Markets: every product in at least one, most in several.
            n_markets = random.choices([1, 2, 3], weights=[0.2, 0.35, 0.45], k=1)[0]
            markets = sorted(random.sample(MARKETS, n_markets), key=MARKETS.index)

            # Base list price = Germany price for tier/category (EUR reference).
            base_market = markets[0]
            list_price = money(PRICES[base_market][category][tier])
            market_prices = {
                m: {"price": money(PRICES[m][category][tier]),
                    "currency": MARKET_CURRENCY[m]}
                for m in markets
            }

            # Gross margin by tier (Premium ~20-40% higher than Mid).
            if tier == "Entry":
                margin = random.randint(42, 52)
            elif tier == "Mid Market":
                margin = random.randint(56, 65)
            else:
                margin = random.randint(70, 82)
            # Germany-only products lean toward higher margins.
            if markets == ["Germany"]:
                margin = min(margin + 3, 85)
            cost_per_unit = money(list_price * (1 - margin / 100))

            launch_year = random.choices(
                [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025],
                weights=[0.06, 0.08, 0.1, 0.12, 0.14, 0.16, 0.18, 0.16],
                k=1,
            )[0]

            claims = random.sample(vocab["claims_pool"], k=random.randint(3, 4))

            audience = random.choice(TARGET_AUDIENCE)
            differentiator = random.choice(DIFFERENTIATORS)
            benefit = random.choice(vocab["benefits"])
            benefit2 = random.choice([b for b in vocab["benefits"] if b != benefit])
            fmt = random.choice(vocab["formats"])

            if category == "Home Diagnostics":
                tech = random.choice(vocab["technologies"])
                measure = random.choice(vocab["measures"])
                description = (
                    f"{name} is a {tier.lower()}-tier {vocab['noun']} from {brand} that uses "
                    f"{tech} to assess {measure}. It delivers {benefit} and {benefit2}, "
                    f"supplied as a {fmt}. Aimed at {audience} in "
                    f"{', '.join(markets)}, it differentiates through {differentiator}. "
                    f"Key claims: {', '.join(claims)}."
                )
            else:
                ingredient = random.choice(vocab["ingredients"])
                description = (
                    f"{name} is a {tier.lower()}-tier {vocab['noun']} from {brand}, "
                    f"formulated with {ingredient} to support {benefit} and {benefit2}. "
                    f"Delivered as {fmt}, it targets {audience} across "
                    f"{', '.join(markets)} and stands out through {differentiator}. "
                    f"Key claims: {', '.join(claims)}."
                )

            products.append({
                "product_id": pid,
                "product_name": name,
                "category": category,
                "brand": brand,
                "is_competitor": brand != "NorthStar Health",
                "market": markets,
                "price_tier": tier,
                "launch_year": launch_year,
                "cost_per_unit": cost_per_unit,
                "list_price": list_price,
                "list_price_currency": MARKET_CURRENCY[base_market],
                "market_prices": market_prices,
                "gross_margin": margin,
                "claims": claims,
                "description": description,
            })
    return products


# --------------------------------------------------------------------------
# Personas
# --------------------------------------------------------------------------

FIRST_NAMES = {
    "Germany": {
        "male": ["Thomas", "Lukas", "Daniel", "Michael", "Sven", "Martin", "Andreas",
                  "Stefan", "Jonas", "Felix", "Matthias", "Klaus", "Jan", "Tobias",
                  "Sebastian", "Florian", "Maximilian", "Niklas"],
        "female": ["Anna", "Petra", "Claudia", "Heike", "Julia", "Sabine", "Katrin",
                    "Nadine", "Birgit", "Ursula", "Franziska", "Lena", "Sophie",
                    "Melanie", "Ingrid", "Karin", "Monika", "Vanessa"],
        "last": ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Wagner",
                  "Becker", "Hoffmann", "Schäfer", "Koch", "Bauer", "Richter",
                  "Klein", "Wolf", "Neumann", "Schwarz", "Zimmermann", "Braun"],
    },
    "UK": {
        "male": ["James", "Liam", "Chris", "Jacob", "Oliver", "Harry", "George",
                  "Jack", "Charlie", "Thomas", "Daniel", "Ryan", "Ben", "Aaron",
                  "Ethan", "Nathan", "Callum", "Joseph"],
        "female": ["Sarah", "Olivia", "Emma", "Sophie", "Amelia", "Barbara", "Grace",
                    "Chloe", "Hannah", "Lucy", "Ella", "Charlotte", "Isla", "Freya",
                    "Poppy", "Alice", "Megan", "Rebecca"],
        "last": ["Smith", "Jones", "Taylor", "Brown", "Williams", "Wilson", "Evans",
                  "Thomas", "Roberts", "Walker", "Wright", "Robinson", "Thompson",
                  "White", "Hughes", "Edwards", "Green", "Hall"],
    },
    "Nordics": {
        "male": ["Erik", "Andreas", "Magnus", "Henrik", "Johan", "Lars", "Oskar",
                  "Emil", "Mikael", "Anders", "Nils", "Gustav", "Aksel", "Elias",
                  "Fredrik", "Bjørn", "Kasper", "Rasmus"],
        "female": ["Sara", "Lena", "Ella", "Ingrid", "Freja", "Astrid", "Maja",
                    "Sofia", "Elin", "Nora", "Sanna", "Linnea", "Ida", "Amalie",
                    "Signe", "Tuva", "Frida", "Karin"],
        "last": ["Andersson", "Johansson", "Nielsen", "Hansen", "Larsen", "Berg",
                  "Lindqvist", "Nyström", "Virtanen", "Korhonen", "Dahl", "Eriksen",
                  "Holm", "Lund", "Sørensen", "Bergström", "Aho", "Moe"],
    },
}

PERSONA_ARCHETYPES = [
    {
        "label": "active retiree", "age": (62, 76), "income": ["Middle", "High"],
        "digital": ["Low", "Medium"], "risk": "Conservative", "spend": (600, 1200),
        "interests": ["Longevity", "Heart Health", "Healthy Aging", "Preventative Care"],
        "categories": ["Vitamins & Supplements", "Home Diagnostics"],
        "channel": "pharmacies and trusted health retailers",
        "motivation": "wants to stay independent and physically active well into later life",
        "behavior": "prefers proven, clinically backed products and values pharmacist advice",
    },
    {
        "label": "time-poor executive", "age": (38, 55), "income": ["High", "Affluent"],
        "digital": ["Medium", "High"], "risk": "Moderate", "spend": (900, 2200),
        "interests": ["Stress Management", "Cognitive Performance", "Energy", "Sleep"],
        "categories": ["Vitamins & Supplements", "Home Diagnostics"],
        "channel": "premium online subscriptions",
        "motivation": "seeks to sustain high performance and manage stress under pressure",
        "behavior": "willing to pay a premium for convenience and measurable results",
    },
    {
        "label": "pharmacy-loyal shopper", "age": (45, 70), "income": ["Low", "Middle"],
        "digital": ["Low"], "risk": "Conservative", "spend": (300, 700),
        "interests": ["Immune Health", "Bone Health", "Everyday Wellness"],
        "categories": ["Vitamins & Supplements"],
        "channel": "local pharmacies",
        "motivation": "relies on familiar brands and professional recommendations",
        "behavior": "rarely experiments and prioritises trust and safety over novelty",
    },
    {
        "label": "fitness professional", "age": (24, 40), "income": ["Middle", "High"],
        "digital": ["Medium", "High"], "risk": "Moderate", "spend": (700, 1600),
        "interests": ["Performance Nutrition", "Recovery", "Lean Muscle", "Energy"],
        "categories": ["Vitamins & Supplements", "Weight Management"],
        "channel": "specialist sports-nutrition retailers and online",
        "motivation": "optimises training, recovery and body composition",
        "behavior": "reads labels closely and favours high-dosage, transparent formulas",
    },
    {
        "label": "busy parent", "age": (30, 45), "income": ["Middle"],
        "digital": ["Medium"], "risk": "Conservative", "spend": (400, 900),
        "interests": ["Family Wellness", "Immune Health", "Convenience"],
        "categories": ["Vitamins & Supplements", "Gut Health"],
        "channel": "supermarkets and convenient online delivery",
        "motivation": "wants simple, reliable wellness for the whole family",
        "behavior": "values convenience, bundles and easy reordering",
    },
    {
        "label": "preventive-health adopter", "age": (35, 58), "income": ["Middle", "High"],
        "digital": ["Medium", "High"], "risk": "Moderate", "spend": (700, 1500),
        "interests": ["Preventative Care", "Early Detection", "Metabolic Health"],
        "categories": ["Home Diagnostics", "Vitamins & Supplements"],
        "channel": "online diagnostics platforms",
        "motivation": "monitors health markers regularly to catch issues early",
        "behavior": "data-driven and comfortable with at-home testing",
    },
    {
        "label": "biohacker and self-optimiser", "age": (26, 44), "income": ["High", "Affluent"],
        "digital": ["High"], "risk": "Adventurous", "spend": (1200, 2500),
        "interests": ["Longevity", "Cognitive Performance", "Metabolic Health", "Sleep"],
        "categories": ["Home Diagnostics", "Vitamins & Supplements", "Gut Health"],
        "channel": "cutting-edge D2C brands and subscriptions",
        "motivation": "treats health as a measurable system to continuously optimise",
        "behavior": "an early adopter who combines wearables, diagnostics and personalised stacks",
    },
    {
        "label": "subscription-first consumer", "age": (25, 40), "income": ["Middle", "High"],
        "digital": ["High"], "risk": "Moderate", "spend": (500, 1300),
        "interests": ["Convenience", "Personalisation", "Everyday Wellness"],
        "categories": ["Vitamins & Supplements", "Gut Health"],
        "channel": "monthly online subscriptions",
        "motivation": "prefers set-and-forget wellness that arrives automatically",
        "behavior": "loyal to brands offering personalisation and easy management",
    },
    {
        "label": "social-led wellness enthusiast", "age": (21, 35), "income": ["Low", "Middle"],
        "digital": ["High"], "risk": "Adventurous", "spend": (350, 900),
        "interests": ["Trending Wellness", "Gut Health", "Skin & Beauty", "Energy"],
        "categories": ["Gut Health", "Vitamins & Supplements", "Weight Management"],
        "channel": "influencer-driven social commerce",
        "motivation": "discovers products through social media and community trends",
        "behavior": "adopts new trends quickly and shares experiences online",
    },
    {
        "label": "weight-management seeker", "age": (28, 52), "income": ["Middle", "High"],
        "digital": ["Medium", "High"], "risk": "Moderate", "spend": (600, 1600),
        "interests": ["Weight Loss", "Appetite Control", "Metabolic Health"],
        "categories": ["Weight Management", "Home Diagnostics"],
        "channel": "online programmes and pharmacies",
        "motivation": "pursues sustainable weight goals, sometimes alongside GLP-1 therapy",
        "behavior": "tracks progress closely and values nutritional support and coaching",
    },
    {
        "label": "sustainability-focused buyer", "age": (27, 48), "income": ["Middle", "High"],
        "digital": ["Medium", "High"], "risk": "Moderate", "spend": (500, 1300),
        "interests": ["Sustainability", "Clean Ingredients", "Healthy Aging"],
        "categories": ["Vitamins & Supplements", "Gut Health"],
        "channel": "eco-conscious premium brands",
        "motivation": "chooses products aligned with environmental and ethical values",
        "behavior": "scrutinises sourcing, packaging and clean-label credentials",
    },
    {
        "label": "chronic-condition monitor", "age": (48, 72), "income": ["Middle"],
        "digital": ["Low", "Medium"], "risk": "Conservative", "spend": (500, 1100),
        "interests": ["Cholesterol", "Blood Sugar", "Heart Health", "Early Detection"],
        "categories": ["Home Diagnostics", "Vitamins & Supplements"],
        "channel": "pharmacies and healthcare providers",
        "motivation": "manages ongoing risk factors and tracks them between GP visits",
        "behavior": "adheres to routine testing and doctor-aligned supplementation",
    },
    {
        "label": "digital-native decision maker", "age": (22, 33), "income": ["Low", "Middle"],
        "digital": ["High"], "risk": "Adventurous", "spend": (300, 800),
        "interests": ["Convenience", "Energy", "Gut Health", "Personalisation"],
        "categories": ["Gut Health", "Vitamins & Supplements"],
        "channel": "mobile-first apps and marketplaces",
        "motivation": "relies on apps and reviews to guide every purchase",
        "behavior": "compares options rapidly and expects seamless digital experiences",
    },
    {
        "label": "longevity innovator", "age": (40, 60), "income": ["Affluent"],
        "digital": ["High"], "risk": "Adventurous", "spend": (1500, 2500),
        "interests": ["Longevity", "Biological Age", "Metabolic Health", "Preventative Care"],
        "categories": ["Home Diagnostics", "Vitamins & Supplements"],
        "channel": "clinical-grade wellness programmes",
        "motivation": "invests heavily in extending healthspan and measuring biological age",
        "behavior": "participates in advanced testing and personalised longevity protocols",
    },
]


def gen_personas():
    personas = []
    for market in MARKETS:
        code = {"Germany": "GER", "UK": "GBR", "Nordics": "NOR"}[market]
        names_pool = FIRST_NAMES[market]
        used = set()
        for i in range(1, 51):
            arche = PERSONA_ARCHETYPES[(i - 1) % len(PERSONA_ARCHETYPES)]
            gender = random.choice(["male", "female"])
            # unique first+last
            for _ in range(50):
                first = random.choice(names_pool[gender])
                last = random.choice(names_pool["last"])
                full = f"{first} {last}"
                if full not in used:
                    used.add(full)
                    break
            pid = f"{code}-{i:03d}"
            age = random.randint(*arche["age"])
            income = random.choice(arche["income"])
            digital = random.choice(arche["digital"])
            spend = int(round(random.randint(*arche["spend"]) / 10.0) * 10)
            interests = random.sample(arche["interests"], k=min(3, len(arche["interests"])))
            categories = arche["categories"]
            pronoun = {"male": ("He", "his"), "female": ("She", "her")}[gender]

            product_pref_terms = {
                "Vitamins & Supplements": "daily supplements",
                "Gut Health": "probiotics and gut support",
                "Weight Management": "weight-management and metabolic products",
                "Home Diagnostics": "at-home diagnostic kits",
            }
            prefs = [product_pref_terms[c] for c in categories]

            description = (
                f"{full} is a {age}-year-old {arche['label']} in {market} who "
                f"{arche['motivation']}. With a {income.lower()} income and "
                f"{digital.lower()} digital fluency, {pronoun[0].lower()} {arche['behavior']}. "
                f"Health priorities include {', '.join(interests)}. "
                f"{pronoun[0]} prefers {', '.join(prefs)}, shops mainly via "
                f"{arche['channel']}, and spends roughly {spend} per year. "
                f"Risk tolerance toward new products is {arche['risk'].lower()}."
            )

            personas.append({
                "persona_id": pid,
                "name": full,
                "market": market,
                "archetype": arche["label"],
                "age": age,
                "gender": gender,
                "income_band": income,
                "risk_tolerance": arche["risk"],
                "digital_maturity": digital,
                "interests": interests,
                "preferred_categories": categories,
                "preferred_channel": arche["channel"],
                "annual_spend": spend,
                "annual_spend_currency": MARKET_CURRENCY[market],
                "description": description,
            })
    return personas


# --------------------------------------------------------------------------
# Research innovations
# --------------------------------------------------------------------------

TRENDS = [
    "personalised nutrition", "longevity and healthy aging", "microbiome science",
    "GLP-1 and metabolic health", "at-home diagnostics", "preventive healthcare",
    "AI health coaching", "wearable and continuous monitoring", "sustainability and clean labels",
    "women's health", "cognitive performance", "sleep optimisation", "immune resilience",
    "gut-brain axis", "precision supplementation",
]

INNOVATION_SEEDS = {
    "Vitamins & Supplements": [
        ("NeuroFocus AI", "AI-guided cognitive supplement", ["cognitive performance", "AI health coaching", "personalised nutrition"]),
        ("Adaptive Vitamin Pack", "diagnostic-driven adaptive formulation", ["personalised nutrition", "precision supplementation", "at-home diagnostics"]),
        ("ChronoDose", "circadian-timed nutrient delivery", ["sleep optimisation", "precision supplementation"]),
        ("CellRenew NAD+", "NAD+ precursor longevity stack", ["longevity and healthy aging", "precision supplementation"]),
        ("ImmunoSense", "wearable-linked immune support", ["immune resilience", "wearable and continuous monitoring"]),
    ],
    "Gut Health": [
        ("MicroBiome Twin", "continuous microbiome monitoring with probiotics", ["microbiome science", "wearable and continuous monitoring", "personalised nutrition"]),
        ("Gut Age Score", "biological gut-age scoring", ["microbiome science", "longevity and healthy aging"]),
        ("PsychoBiotic Calm", "gut-brain axis mood support", ["gut-brain axis", "microbiome science"]),
        ("Precision Postbiotics", "targeted postbiotic therapeutics", ["microbiome science", "precision supplementation"]),
        ("FloraSync AI", "AI nutrition coach for the microbiome", ["AI health coaching", "microbiome science", "personalised nutrition"]),
    ],
    "Weight Management": [
        ("GLP Companion Plus", "nutrition system for GLP-1 users", ["GLP-1 and metabolic health", "personalised nutrition"]),
        ("Metabolic Digital Twin", "personalised metabolic simulation model", ["GLP-1 and metabolic health", "AI health coaching", "wearable and continuous monitoring"]),
        ("Satiety Sense CGM", "appetite coaching linked to glucose monitoring", ["GLP-1 and metabolic health", "wearable and continuous monitoring"]),
        ("LeanProtein Precision", "DNA-informed protein optimisation", ["personalised nutrition", "precision supplementation"]),
        ("AppetiteReset", "personalised appetite optimisation programme", ["GLP-1 and metabolic health", "AI health coaching"]),
    ],
    "Home Diagnostics": [
        ("Health Insight 360", "integrated multi-marker subscription panel", ["at-home diagnostics", "preventive healthcare", "personalised nutrition"]),
        ("Longevity Index", "biological age scoring kit", ["longevity and healthy aging", "at-home diagnostics", "preventive healthcare"]),
        ("HormoneTrack Fem", "continuous female hormone tracking", ["women's health", "at-home diagnostics"]),
        ("CardioEarly", "at-home cardiovascular risk panel", ["preventive healthcare", "at-home diagnostics"]),
        ("InflammoScan", "chronic inflammation monitoring", ["preventive healthcare", "at-home diagnostics", "longevity and healthy aging"]),
    ],
}

INNOVATION_TECH = {
    "Vitamins & Supplements": ["AI recommendation engine", "adaptive micro-dosing", "time-released delivery",
                                "nutrigenomic personalisation", "biomarker-linked formulation"],
    "Gut Health": ["continuous microbiome monitoring", "metagenomic sequencing", "engineered probiotics",
                    "postbiotic bioactives", "AI nutrition coaching"],
    "Weight Management": ["continuous glucose monitoring", "metabolic digital twin modelling",
                           "GLP-1 companion nutrition", "AI appetite coaching", "DNA-informed protein design"],
    "Home Diagnostics": ["multiplex biomarker assay", "dried blood spot sampling", "smartphone spectrometry",
                          "cloud-based longevity scoring", "subscription multi-marker panel"],
}

READINESS = ["Low", "Medium", "High"]


def gen_innovations():
    innovations = []
    idx = 0
    # Ensure at least 50: 4 categories x ~13 = 52
    per_category = 13
    for category in CATEGORIES:
        seeds = INNOVATION_SEEDS[category]
        vocab = CATEGORY_VOCAB[category]
        for j in range(per_category):
            idx += 1
            iid = f"INN-{idx:03d}"
            if j < len(seeds):
                name, concept, trends = seeds[j]
                trends = list(trends)
            else:
                # Derive additional concepts from lines/descriptors + trends.
                line = random.choice(vocab["lines"])
                desc = random.choice(vocab["descriptors"])
                name = f"{line}{desc} {random.choice(['AI', 'Precision', 'Next', 'Bio', 'Continuous'])}"
                concept = f"{random.choice(INNOVATION_TECH[category]).split('(')[0]} concept"
                trends = random.sample(TRENDS, k=random.randint(2, 3))

            technology = random.choice(INNOVATION_TECH[category])
            readiness = random.choices(READINESS, weights=[0.35, 0.45, 0.20], k=1)[0]
            target_market = random.choices(
                MARKETS + ["All markets"], weights=[0.25, 0.25, 0.3, 0.2], k=1)[0]

            # Economics: cost and retail depend on category, sensible margin.
            if category == "Home Diagnostics":
                cost = random.randint(18, 60)
                price = int(round(cost * random.uniform(2.6, 4.2)))
            elif category == "Weight Management":
                cost = random.randint(10, 35)
                price = int(round(cost * random.uniform(2.4, 3.8)))
            elif category == "Gut Health":
                cost = random.randint(8, 40)
                price = int(round(cost * random.uniform(2.6, 4.0)))
            else:  # Vitamins
                cost = random.randint(5, 22)
                price = int(round(cost * random.uniform(2.6, 4.5)))

            # Later launch for lower readiness.
            base_year = {"High": 2026, "Medium": 2027, "Low": 2028}[readiness]
            expected_launch_year = base_year + random.choice([0, 0, 1])
            est_margin = round((price - cost) / price * 100, 1)

            markets_phrase = "all markets" if target_market == "All markets" else target_market
            benefit = random.choice(vocab["benefits"])
            description = (
                f"{name} is a {readiness.lower()}-readiness {category} innovation built on "
                f"{article(technology)} {technology}. As {article(concept)} {concept}, it addresses "
                f"{', '.join(trends)}, and is designed to deliver {benefit}. Targeted at "
                f"{markets_phrase}, it is expected to launch in {expected_launch_year} at an "
                f"estimated retail price of {price} (production cost ~{cost}, roughly "
                f"{est_margin}% gross margin). It fits consumers seeking data-driven, "
                f"personalised health outcomes."
            )

            innovations.append({
                "innovation_id": iid,
                "innovation_name": name,
                "category": category,
                "technology": technology,
                "concept": concept,
                "trends_addressed": trends,
                "estimated_cost": cost,
                "estimated_sale_price": price,
                "estimated_gross_margin": est_margin,
                "market_readiness": readiness,
                "target_market": target_market,
                "expected_launch_year": expected_launch_year,
                "description": description,
            })
    return innovations


# --------------------------------------------------------------------------
# Market sales (monthly history + forecast) for the NorthStar portfolio
# --------------------------------------------------------------------------

TIER_BASE_UNITS = {
    "Vitamins & Supplements": {"Entry": 12000, "Mid Market": 6000, "Premium": 2600},
    "Gut Health": {"Entry": 8000, "Mid Market": 4200, "Premium": 1900},
    "Weight Management": {"Entry": 7000, "Mid Market": 3600, "Premium": 1600},
    "Home Diagnostics": {"Entry": 2600, "Mid Market": 1300, "Premium": 560},
}
MARKET_SIZE = {"Germany": 1.2, "UK": 1.0, "Nordics": 0.6}
# Winter-peaking categories (immune/gut); diagnostics peak in Jan (new-year health).
SEASONAL_AMP = {
    "Vitamins & Supplements": 0.18,
    "Gut Health": 0.10,
    "Weight Management": 0.14,
    "Home Diagnostics": 0.16,
}


def seasonal_factor(category, month):
    amp = SEASONAL_AMP[category]
    if category == "Weight Management":
        peak_month = 1  # January resolutions
    elif category == "Home Diagnostics":
        peak_month = 1
    else:
        peak_month = 12  # winter immune season
    # cosine peaking at peak_month
    return 1 + amp * math.cos(2 * math.pi * (month - peak_month) / 12)


def gen_sales(products):
    monthly = []
    annual = []
    northstar = [p for p in products if p["brand"] == "NorthStar Health"]
    for p in northstar:
        category = p["category"]
        tier = p["price_tier"]
        for market in p["market"]:
            g = GROWTH[market][category] / 100.0
            base = TIER_BASE_UNITS[category][tier] * MARKET_SIZE[market]
            # per-product idiosyncratic scale
            base *= random.uniform(0.7, 1.3)
            price = p["market_prices"][market]["price"]
            currency = p["market_prices"][market]["currency"]
            start_year = max(p["launch_year"], 2020)
            launch_month = 1 if p["launch_year"] < 2020 else random.randint(1, 12)
            # baseline market share for this product within its category-market
            share = round(random.uniform(1.5, 9.0), 1)

            per_year_units = {}
            per_year_revenue = {}
            full_year = {}
            for year in range(start_year, 2029):
                for month in range(1, 13):
                    if year == start_year and year == p["launch_year"] and month < launch_month:
                        continue
                    t = (year - start_year) + (month - 1) / 12.0
                    trend = (1 + g) ** t
                    seasonal = seasonal_factor(category, month)
                    noise = random.uniform(0.9, 1.1)
                    units = int(round(base * trend * seasonal * noise))
                    revenue = money(units * price)
                    is_forecast = year >= 2026
                    monthly.append({
                        "year": year,
                        "month": month,
                        "market": market,
                        "product_id": p["product_id"],
                        "product_name": p["product_name"],
                        "category": category,
                        "brand": p["brand"],
                        "price_tier": tier,
                        "unit_price": price,
                        "currency": currency,
                        "units_sold": units,
                        "revenue": revenue,
                        "gross_margin": p["gross_margin"],
                        "is_forecast": is_forecast,
                    })
                    per_year_units[year] = per_year_units.get(year, 0) + units
                    per_year_revenue[year] = per_year_revenue.get(year, 0.0) + revenue
                # a "full" year has all 12 months of data
                full_year[year] = not (year == p["launch_year"] and launch_month > 1)

            prev_year = None
            for year in sorted(per_year_units):
                units_y = per_year_units[year]
                revenue_y = money(per_year_revenue[year])
                # only compute YoY between two consecutive full years
                if (prev_year is not None and full_year[year] and full_year[prev_year]
                        and prev_year == year - 1):
                    growth_rate = round(
                        (units_y - per_year_units[prev_year]) / per_year_units[prev_year] * 100, 1)
                else:
                    growth_rate = None
                prev_year = year
                # share drifts slightly with category momentum
                share = round(min(max(share + random.uniform(-0.3, 0.5), 0.5), 18.0), 1)
                annual.append({
                    "year": year,
                    "market": market,
                    "product_id": p["product_id"],
                    "product_name": p["product_name"],
                    "category": category,
                    "brand": p["brand"],
                    "units_sold": units_y,
                    "revenue": revenue_y,
                    "gross_margin": p["gross_margin"],
                    "growth_rate": growth_rate,
                    "market_share": share,
                    "is_forecast": year >= 2026,
                })
    return monthly, annual


def write_json(name, obj):
    path = os.path.join(DATA_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return path


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    products = gen_products()
    personas = gen_personas()
    innovations = gen_innovations()
    monthly, annual = gen_sales(products)

    write_json("products.json", products)
    write_json("personas.json", personas)
    write_json("research_innovations.json", innovations)
    write_json("market_sales_monthly.json", monthly)
    write_json("market_sales_annual.json", annual)

    print(f"products:            {len(products)}")
    for c in CATEGORIES:
        print(f"  - {c:<26} {sum(1 for p in products if p['category'] == c)}")
    print(f"  - NorthStar (internal)      {sum(1 for p in products if p['brand'] == 'NorthStar Health')}")
    print(f"  - competitor products       {sum(1 for p in products if p['is_competitor'])}")
    print(f"personas:            {len(personas)}")
    for m in MARKETS:
        print(f"  - {m:<26} {sum(1 for p in personas if p['market'] == m)}")
    print(f"innovations:         {len(innovations)}")
    print(f"monthly sales rows:  {len(monthly)}")
    print(f"annual sales rows:   {len(annual)}")


if __name__ == "__main__":
    main()
