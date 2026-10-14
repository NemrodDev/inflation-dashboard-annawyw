"""PPI configuration (Final Demand-Intermediate Demand system).

Keys are FD-ID codes (e.g. "FD49104") or full series IDs for industry series
(e.g. "PCU622---622---"). SA series id = "WPS" + code, NSA = "WPU" + code.

Relative importances are APPROXIMATE (December weights, % of final demand).
Update from the PPI detailed report (Table 1) each February.
"""

SA_PREFIX = "WPS"
NSA_PREFIX = "WPU"

# (code, name, level, approx RI)
RELEASE_TABLE = [
    ("FD4", "Final demand", 0, 100.0),
    ("FD41", "Final demand goods", 1, 32.5),
    ("FD411", "Foods", 2, 5.5),
    ("FD412", "Energy", 2, 5.6),
    ("FD413", "Goods less foods and energy", 2, 21.4),
    ("FD42", "Final demand services", 1, 65.5),
    ("FD423", "Trade services", 2, 20.3),
    ("FD422", "Transportation and warehousing", 2, 4.9),
    ("FD4221", "Transportation of passengers", 3, 1.6),
    ("FD4222", "Transportation & warehousing of goods", 3, 3.3),
    ("FD421", "Services less trade, transp. & warehousing", 2, 40.3),
    ("FD4211", "Finished services less TTW", 3, 37.0),
    ("FD42111", "Finished consumer services less TTW", 4, 26.0),
    ("FD42112", "Private capital investment services less TTW", 4, 5.5),
    ("FD43", "Final demand construction", 1, 2.0),
    ("FD49104", "Final demand less foods and energy", 0, 88.9),
    ("FD49116", "Final demand less foods, energy, and trade", 0, 68.6),
    ("FD49108", "Final demand less trade services", 0, 79.7),
]

HEADLINE = "FD4"
CORE = "FD49104"
CORE_CORE = "FD49116"

AGGREGATES = ["FD4", "FD49104", "FD49116", "FD41", "FD413", "FD42", "FD423", "FD421"]

# PPI components that feed the PCE price index (industry PPIs, NSA, "PCU" ids used verbatim).
# key -> (series_id, label)
PCE_INPUTS = {
    "PCU621111621111": "Physician offices",
    "PCU622---622---": "Hospitals",
    "PCU6231--6231--": "Nursing care facilities",
    "PCU6216--6216--": "Home health care",
    "PCU621210621210": "Dentists' offices",
    "PCU481111481111": "Scheduled passenger air transportation",
    "PCU523920523920": "Portfolio management",
    "PCU523120523120": "Securities brokerage",
    "PCU524114524114": "Direct health & medical insurance carriers",
}


def _t(*codes):
    return [(c, 1) for c in codes]


CONTRIB_SPECS = {
    "Headline": {
        "Major": [
            {"label": "Foods", "terms": _t("FD411")},
            {"label": "Energy", "terms": _t("FD412")},
            {"label": "Core goods", "terms": _t("FD413")},
            {"label": "Trade services", "terms": _t("FD423")},
            {"label": "Transp. & warehousing", "terms": _t("FD422")},
            {"label": "Other services", "terms": _t("FD421")},
            {"label": "Construction", "terms": _t("FD43")},
        ],
    },
    "Core": {
        "Major": [
            {"label": "Core goods", "terms": _t("FD413")},
            {"label": "Trade services", "terms": _t("FD423")},
            {"label": "Transp. & warehousing", "terms": _t("FD422")},
            {"label": "Other services", "terms": _t("FD421")},
            {"label": "Construction", "terms": _t("FD43")},
        ],
    },
}
CONTRIB_SPECS["Headline"]["Detailed"] = [
    {"label": "Foods", "terms": _t("FD411")},
    {"label": "Energy", "terms": _t("FD412")},
    {"label": "Core goods", "terms": _t("FD413")},
    {"label": "Trade services", "terms": _t("FD423")},
    {"label": "Passenger transport", "terms": _t("FD4221")},
    {"label": "Freight & warehousing", "terms": _t("FD4222")},
    {"label": "Consumer services ex TTW", "terms": _t("FD42111")},
    {"label": "Other services ex TTW", "terms": [("FD421", 1), ("FD42111", -1)]},
    {"label": "Construction", "terms": _t("FD43")},
]
CONTRIB_SPECS["Core"]["Detailed"] = CONTRIB_SPECS["Headline"]["Detailed"][2:]

HEAT_CENTER = 0.165
HEAT_SCALE = 0.6

# Cap on SA commodity indexes pulled for the diffusion universe (API quota)
DIFFUSION_MAX_SERIES = 300
