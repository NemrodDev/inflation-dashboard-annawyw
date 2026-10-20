"""PCE configuration. BEA tables are addressed by line description, not line number,
because BEA renumbers lines when it adds detail. Matching is exact (case-insensitive)
first, then 'startswith', then 'contains', always within the given table.

Tables used (BEA API):
  NIPA T20804 / T20805               monthly price index / nominal PCE by major type
  NIUnderlyingDetail U20404 / U20405 monthly price index / nominal PCE, full detail
"""

MAJOR_PRICE = ("NIPA", "T20804")
MAJOR_NOMINAL = ("NIPA", "T20805")
DETAIL_PRICE = ("NIUnderlyingDetail", "U20404")
DETAIL_NOMINAL = ("NIUnderlyingDetail", "U20405")

HEADLINE = "Personal consumption expenditures (PCE)"
CORE = "PCE excluding food and energy"
SUPERCORE = "PCE services excluding energy and housing"
EX_FEH = "PCE excluding food, energy, and housing"

AGGREGATE_NAMES = [
    HEADLINE, CORE, SUPERCORE, "Goods", "Services", "Housing",
    "Food", "Energy goods and services", "Market-based PCE excluding food and energy",
]


def _t(*names):
    return [(n, 1) for n in names]


# Terms reference line descriptions in the major-type table (T20804/T20805)
CONTRIB_SPECS = {
    "Headline": {
        "Major": [
            {"label": "Food", "terms": _t("Food")},
            {"label": "Energy", "terms": _t("Energy goods and services")},
            {"label": "Core goods", "terms": [("Goods", 1),
                                              ("Food and beverages purchased for off-premises consumption", -1),
                                              ("Gasoline and other energy goods", -1)]},
            {"label": "Housing", "terms": _t("Housing")},
            {"label": "Core services ex housing", "terms": _t(SUPERCORE)},
        ],
    },
    "Core": {
        "Major": [
            {"label": "Core goods", "terms": [("Goods", 1),
                                              ("Food and beverages purchased for off-premises consumption", -1),
                                              ("Gasoline and other energy goods", -1)]},
            {"label": "Housing", "terms": _t("Housing")},
            {"label": "Core services ex housing", "terms": _t(SUPERCORE)},
        ],
        "Detailed": [
            {"label": "Motor vehicles & parts", "terms": _t("Motor vehicles and parts")},
            {"label": "Furnishings & HH equip.", "terms": _t("Furnishings and durable household equipment")},
            {"label": "Recreational goods", "terms": _t("Recreational goods and vehicles")},
            {"label": "Other durable goods", "terms": _t("Other durable goods")},
            {"label": "Clothing & footwear", "terms": _t("Clothing and footwear")},
            {"label": "Other nondurable goods", "terms": _t("Other nondurable goods")},
            {"label": "Housing", "terms": _t("Housing")},
            {"label": "Health care", "terms": _t("Health care")},
            {"label": "Transportation services", "terms": _t("Transportation services")},
            {"label": "Recreation services", "terms": _t("Recreation services")},
            {"label": "Food services & accomm.", "terms": _t("Food services and accommodations")},
            {"label": "Financial svcs & insurance", "terms": _t("Financial services and insurance")},
            {"label": "Other services", "terms": _t("Other services")},
            {"label": "NPISH", "terms": _t("Final consumption expenditures of nonprofit institutions serving households (NPISHs)")},
        ],
    },
}
CONTRIB_SPECS["Headline"]["Detailed"] = [
    {"label": "Food", "terms": _t("Food")},
    {"label": "Energy", "terms": _t("Energy goods and services")},
] + CONTRIB_SPECS["Core"]["Detailed"]

# "AI-exposed" consumer items, analogous to config/cpi.py AI_ITEMS. Lines of the underlying-detail table
# (U20404/U20405), matched by description; label shown on the charts. Weights are PCE's own: each line's
# share of total PCE spending in the previous month. BEA has no separate smartphone line: "Telephone and
# related communication equipment" (mostly smartphones) is the closest, priced by BEA from CPI telephone hardware.
AI_ITEMS = [
    ("Personal computers/tablets and peripheral equipment", "Personal computers/tablets & peripherals"),
    ("Computer software and accessories", "Computer software & accessories"),
    ("Telephone and related communication equipment", "Telephones incl. smartphones"),
    ("Televisions", "Televisions"),
]

# Underlying-detail ancestors that define food / energy for the "core only" diffusion option
FOOD_ANCESTORS = ["Food and beverages purchased for off-premises consumption"]
ENERGY_ANCESTORS = ["Gasoline and other energy goods", "Electricity and gas"]

HEAT_CENTER = 0.165
HEAT_SCALE = 0.4
