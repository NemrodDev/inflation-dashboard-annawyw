"""Default CPI/PPI -> core PCE mapping for the nowcast tab.

Each row maps a slice of core PCE to a source price series. Weights are
APPROXIMATE shares of core PCE (%). They are editable in the app, and the
'Residual' row absorbs whatever is not mapped (imputed financial services,
insurance, NPISH, etc.), proxied by core CPI by default.

source:  "cpi"   -> CPI item code (seasonally adjusted, from the CPI tab data)
         "ppi"   -> PPI key (FD-ID code or PCU industry id, from the PPI tab data)
         "blend" -> "cpi:SEHA*0.27+cpi:SEHC*0.73" weighted blend of series
"""

DEFAULT_MAPPING = [
    # PCE component, weight (% of core PCE), source, series, note
    ("New motor vehicles", 2.6, "cpi", "SETA01", "CPI new vehicles"),
    ("Used motor vehicles (net)", 1.0, "cpi", "SETA02", "CPI used cars & trucks"),
    ("Motor vehicle parts", 0.5, "cpi", "SETC", ""),
    ("Furnishings & household equipment", 3.2, "cpi", "SAH3", ""),
    ("Recreational goods & vehicles", 3.8, "cpi", "SARC", "PCE weight > CPI weight"),
    ("Clothing & footwear", 2.9, "cpi", "SAA", ""),
    ("Pharma & other medical products", 4.3, "cpi", "SAM1", "BEA blends CPI and PPI drugs"),
    ("Other nondurable / durable goods", 5.5, "cpi", "SAGC", "personal care, tobacco, misc"),
    ("Housing (rent + imputed rent)", 15.5, "blend", "cpi:SEHA*0.27+cpi:SEHC*0.73",
     "PCE housing weight is roughly half of CPI's"),
    ("Physician services", 4.4, "ppi", "PCU621111621111", "PPI physician offices"),
    ("Hospitals", 9.0, "ppi", "PCU622---622---", "PPI hospitals"),
    ("Nursing homes", 1.2, "ppi", "PCU6231--6231--", "PPI nursing care facilities"),
    ("Home health care", 0.8, "ppi", "PCU6216--6216--", ""),
    ("Dental & other outpatient", 2.7, "cpi", "SAM2", ""),
    ("Motor vehicle maint. & repair", 1.8, "cpi", "SETD", ""),
    ("Motor vehicle insurance (net)", 0.6, "cpi", "SETE", "much smaller weight than CPI"),
    ("Air transportation", 0.7, "ppi", "PCU481111481111", "PPI airline passenger, not CPI fares"),
    ("Other transportation services", 0.9, "cpi", "SAS4", ""),
    ("Recreation services", 4.6, "cpi", "SARS", ""),
    ("Food services", 7.0, "cpi", "SEFV", "in core PCE (not in CPI core ex food)"),
    ("Accommodations", 1.2, "cpi", "SEHB", ""),
    ("Portfolio mgmt & investment advice", 1.9, "ppi", "PCU523920523920", "tracks equity prices"),
    ("Securities commissions", 0.4, "ppi", "PCU523120523120", ""),
    ("Health insurance", 1.4, "ppi", "PCU524114524114", ""),
    ("Communication", 2.5, "cpi", "SAE2", ""),
    ("Education", 2.3, "cpi", "SAE1", ""),
    ("Personal care, social & other services", 3.5, "cpi", "SAGS", ""),
]
RESIDUAL_SOURCE = ("cpi", "SA0L1E")  # proxy for the unmapped share

# Headline PCE = core share * core + food share * food + energy share * energy
DEFAULT_HEADLINE_SHARES = {"core": 88.3, "food": 7.6, "energy": 4.1}
HEADLINE_PROXIES = {"food": ("cpi", "SAF11"), "energy": ("cpi", "SA0E")}
