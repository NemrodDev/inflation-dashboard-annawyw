"""CPI configuration: release-table layout, relative importance, contribution specs.

Keys are BLS CPI item codes (e.g. "SA0L1E"). Series IDs are built as
CUSR0000<code> (seasonally adjusted) and CUUR0000<code> (not seasonally adjusted).

RELATIVE IMPORTANCE
-------------------
The values below are APPROXIMATE December relative importances (share of
all-items CPI-U, %). BLS updates them every January. Replace them with the
current vintage from https://www.bls.gov/cpi/tables/relative-importance/
(or drop a CSV at config/cpi_relative_importance.csv with columns
item_code,relative_importance and it will override these values).
"""

SA_PREFIX = "CUSR0000"
NSA_PREFIX = "CUUR0000"

# (item_code, display name, indent level, approx. relative importance)
RELEASE_TABLE = [
    ("SA0", "All items", 0, 100.0),
    ("SAF1", "Food", 1, 13.6),
    ("SAF11", "Food at home", 2, 8.0),
    ("SAF111", "Cereals and bakery products", 3, 1.1),
    ("SAF112", "Meats, poultry, fish, and eggs", 3, 1.7),
    ("SEFJ", "Dairy and related products", 3, 0.75),
    ("SAF113", "Fruits and vegetables", 3, 1.4),
    ("SAF114", "Nonalcoholic beverages", 3, 0.95),
    ("SAF115", "Other food at home", 3, 2.1),
    ("SEFV", "Food away from home", 2, 5.6),
    ("SA0E", "Energy", 1, 6.4),
    ("SACE", "Energy commodities", 2, 3.4),
    ("SEHE01", "Fuel oil", 3, 0.1),
    ("SETB01", "Gasoline (all types)", 3, 3.1),
    ("SEHF", "Energy services", 2, 3.0),
    ("SEHF01", "Electricity", 3, 2.4),
    ("SEHF02", "Utility (piped) gas service", 3, 0.6),
    ("SA0L1E", "All items less food and energy", 1, 80.0),
    ("SACL1E", "Commodities less food and energy commodities", 2, 19.4),
    ("SAH31", "Household furnishings and supplies", 3, 3.4),
    ("SAA", "Apparel", 3, 2.5),
    ("SETA01", "New vehicles", 3, 4.3),
    ("SETA02", "Used cars and trucks", 3, 1.9),
    ("SETC", "Motor vehicle parts and equipment", 3, 0.4),
    ("SAM1", "Medical care commodities", 3, 1.5),
    ("SARC", "Recreation commodities", 3, 2.0),
    ("SAEC", "Education and communication commodities", 3, 0.9),
    ("SAF116", "Alcoholic beverages", 3, 0.85),
    ("SAGC", "Other goods", 3, 1.65),
    ("SASLE", "Services less energy services", 2, 60.6),
    ("SAH1", "Shelter", 3, 35.5),
    ("SEHA", "Rent of primary residence", 4, 7.5),
    ("SEHC", "Owners' equivalent rent of residences", 4, 26.2),
    ("SEHB", "Lodging away from home", 4, 1.4),
    ("SEHG", "Water and sewer and trash collection", 3, 1.1),
    ("SEHP", "Household operations", 3, 1.0),
    ("SAM2", "Medical care services", 3, 6.8),
    ("SEMC01", "Physicians' services", 4, 1.8),
    ("SEMD01", "Hospital services", 4, 1.9),
    ("SEME", "Health insurance", 4, 0.6),
    ("SAS4", "Transportation services", 3, 6.3),
    ("SETD", "Motor vehicle maintenance and repair", 4, 1.4),
    ("SETE", "Motor vehicle insurance", 4, 2.8),
    ("SETG01", "Airline fares", 4, 0.85),
    ("SARS", "Recreation services", 3, 3.3),
    ("SAES", "Education and communication services", 3, 5.1),
    ("SAGS", "Other personal services", 3, 1.5),
]

# Extra series fetched for the CPI tab and the nowcast (not in the release table)
EXTRA_SERIES = [
    ("SAC", "Commodities", 1, 36.5),
    ("SAS", "Services", 1, 63.5),
    ("SASL2RS", "Services less rent of shelter", 1, 28.6),
    ("SAE1", "Education", 1, 2.5),
    ("SAE2", "Communication", 1, 3.3),
]

# "AI-exposed" consumer items. code -> label. RI values are approximate.
# SEEE01 is BLS's current name ("Computers, peripherals, and smart home assistants") for
# personal computers and peripheral equipment; it is also the CPI BEA uses for that PCE line.
AI_ITEMS = [
    ("SEEE01", "Personal computers and peripheral equipment", 0.30),
    ("SEEE02", "Computer software and accessories", 0.03),
    ("SSEE041", "Smartphones", 0.30),
    ("SERA01", "Televisions", 0.18),
]

HEADLINE = "SA0"
CORE = "SA0L1E"
CORE_GOODS = "SACL1E"
CORE_SERVICES = "SASLE"
SHELTER = "SAH1"

AGGREGATES = ["SA0", "SA0L1E", "SAF1", "SA0E", "SACL1E", "SASLE", "SAH1", "SUPERCORE"]

def _t(*codes):
    return [(c, 1) for c in codes]

CONTRIB_SPECS = {
    "Headline": {
        "Major": [
            {"label": "Food", "terms": _t("SAF1")},
            {"label": "Energy", "terms": _t("SA0E")},
            {"label": "Core goods", "terms": _t("SACL1E")},
            {"label": "Shelter", "terms": _t("SAH1")},
            {"label": "Core services ex shelter", "terms": [("SASLE", 1), ("SAH1", -1)]},
        ],
        "Detailed": [
            {"label": "Food at home", "terms": _t("SAF11")},
            {"label": "Food away from home", "terms": _t("SEFV")},
            {"label": "Energy commodities", "terms": _t("SACE")},
            {"label": "Energy services", "terms": _t("SEHF")},
        ],  # + core detailed (appended below)
    },
    "Core": {
        "Major": [
            {"label": "Core goods", "terms": _t("SACL1E")},
            {"label": "Shelter", "terms": _t("SAH1")},
            {"label": "Core services ex shelter", "terms": [("SASLE", 1), ("SAH1", -1)]},
        ],
        "Detailed": [
            {"label": "New vehicles", "terms": _t("SETA01")},
            {"label": "Used cars & trucks", "terms": _t("SETA02")},
            {"label": "Apparel", "terms": _t("SAA")},
            {"label": "Household furnishings", "terms": _t("SAH31")},
            {"label": "Medical commodities", "terms": _t("SAM1")},
            {"label": "Recreation commodities", "terms": _t("SARC")},
            {"label": "Other core goods", "terms": _t("SETC", "SAEC", "SAF116", "SAGC")},
            {"label": "Rent", "terms": _t("SEHA")},
            {"label": "OER", "terms": _t("SEHC")},
            {"label": "Lodging away from home", "terms": _t("SEHB")},
            {"label": "Medical services", "terms": _t("SAM2")},
            {"label": "Motor vehicle insurance", "terms": _t("SETE")},
            {"label": "Motor vehicle maint. & repair", "terms": _t("SETD")},
            {"label": "Airline fares", "terms": _t("SETG01")},
            {"label": "Other transportation svcs", "terms": [("SAS4", 1), ("SETE", -1), ("SETD", -1), ("SETG01", -1)]},
            {"label": "Recreation services", "terms": _t("SARS")},
            {"label": "Educ. & comm. services", "terms": _t("SAES")},
            {"label": "Other core services", "terms": _t("SAGS", "SEHP", "SEHG")},
        ],
    },
}
CONTRIB_SPECS["Headline"]["Detailed"] = CONTRIB_SPECS["Headline"]["Detailed"] + CONTRIB_SPECS["Core"]["Detailed"]

# Supercore (core services ex shelter) components, for the supercore section
SUPERCORE_SPECS = [
    {"label": "Medical care services", "terms": _t("SAM2")},
    {"label": "Transportation services", "terms": _t("SAS4")},
    {"label": "Recreation services", "terms": _t("SARS")},
    {"label": "Educ. & comm. services", "terms": _t("SAES")},
    {"label": "Other personal services", "terms": _t("SAGS")},
    {"label": "Household ops + water/trash", "terms": _t("SEHP", "SEHG")},
]

# Curated fallback universe for diffusion when the BLS item catalog cannot be downloaded
DIFFUSION_FALLBACK = [
    c for c, _, lvl, _ in RELEASE_TABLE if lvl >= 3
] + ["SEFV", "SEHF01", "SEHF02"]

# Heat-map centre for monthly % changes (2% annualised ~= 0.165% m/m)
HEAT_CENTER = 0.165
HEAT_SCALE = 0.5
