"""Translate BEA's price-source names (column "Price index source data" in
config/Detail_CPI_PCE_mapping.xlsx, BEA Table 2.4.4U-D) into BLS series IDs.

This file does NOT choose which price feeds a PCE line; the BEA workbook does.
It only says which BLS series each BEA source name refers to.

Entry format:  "BEA source text": [(kind, code, weight), ...]
  kind "cpi"     -> CPI-U U.S. city average; SA or NSA taken from the workbook's
                    "Seasonal Status" for that line (CUSR0000 / CUUR0000 + code)
       "cpi_sa"  -> force CUSR0000 + code     "cpi_nsa" -> force CUUR0000 + code
       "ppi"     -> PPI series id used verbatim; "A|B" = try A, else B
  weight         -> relative weight inside a BEA composite. BEA does not publish
                    composite weights; equal weights are used and flagged.
CPI item codes are from the BLS cu.item list. PPI ids marked VERIFY are best
matches to BEA's description; the app lists any id BLS does not return.
Sources not listed here (BEA input-cost indexes, implicit deflators, USDA,
foreign CPIs, import prices) cannot be nowcast from CPI/PPI and use the
line's own recent trend instead (see the nowcast tab settings).
"""

C = "cpi"

SOURCE_SERIES = {
    # ---------------- motor vehicles
    "CPI New cars": [(C, "SS45011", 1)],
    "CPI New trucks": [(C, "SS45021", 1)],
    "CPI Used cars and trucks": [(C, "SETA02", 1)],
    "CPI Car and truck rental": [(C, "SETA04", 1)],
    "CPI Tires": [(C, "SETC01", 1)],
    "CPI Vehicle parts and equipment other than tires": [(C, "SS48021", 1)],
    "CPI Leased cars and trucks": [(C, "SETA03", 1)],
    "CPI Motor vehicle maintenance and repair": [(C, "SETD", 1)],
    "CPI Parking fees and tolls": [(C, "SS52051", 1)],
    "CPI New motorcycles": [(C, "SS45031", 1)],
    # ---------------- furnishings & household
    "CPI Furniture and bedding": [(C, "SEHJ", 1)],
    "CPI Clocks, lamps, and decorator items": [(C, "SEHL01", 1)],
    "CPI Floor covering": [(C, "SEHH01", 1)],
    "CPI Window coverings": [(C, "SEHH02", 1)],
    "CPI Other linens": [(C, "SEHH03", 1)],
    "CPI Major appliances": [(C, "SEHK01", 1)],
    "CPI Other appliances": [(C, "SEHK02", 1)],
    "CPI Dishes and flatware": [(C, "SEHL03", 1)],
    "CPI Nonelectric cookware and tableware": [(C, "SEHL04", 1)],
    "CPI Tools, hardware, and supplies": [(C, "SEHM01", 1)],
    "CPI Outdoor equipment and supplies": [(C, "SEHM02", 1)],
    "CPI Indoor plants and flowers": [(C, "SEHL02", 1)],
    "CPI Household cleaning products": [(C, "SEHN01", 1)],
    "CPI Household paper products": [(C, "SEHN02", 1)],
    "CPI Miscellaneous household products": [(C, "SEHN03", 1)],
    "CPI Household operations": [(C, "SEHP", 1)],
    "CPI Moving, storage, and freight expenses": [(C, "SEHP03", 1)],
    "CPI Repair of household items": [(C, "SEHP04", 1)],
    "CPIs for Domestic services, for Food at home, and for Laundry and dry cleaning services":
        [("cpi_nsa", "SEHP01", 1), ("cpi_sa", "SAF11", 1), ("cpi_nsa", "SEGD03", 1)],
    # ---------------- recreation goods & services
    "CPI Televisions": [(C, "SERA01", 1)],
    "CPI Other video equipment": [(C, "SERA03", 1)],
    "CPI Audio equipment": [(C, "SERA05", 1)],
    "CPI Recorded music and music subscriptions": [(C, "SERA06", 1)],
    "CPI Video discs and other media": [(C, "SS31022", 1)],
    "CPI Rental of video discs and other media": [(C, "SS62055", 1)],  # BLS now: subscription and rental of video
    "CPI Video and audio": [(C, "SERA", 1)],
    "CPI Cable and satellite television service": [(C, "SERA02", 1)],
    "CPI Photographic equipment": [(C, "SS61023", 1)],
    "CPI Film and photographic supplies": [(C, "SS61021", 1)],
    "CPI Film processing": [(C, "SS62052", 1)],
    "CPI Photographer fees": [(C, "SS62051", 1)],
    "CPI Computers, peripherals, and smart home assistants": [(C, "SEEE01", 1)],
    "CPI Computer software and accessories": [(C, "SEEE02", 1)],
    "CPI Telephone hardware, calculators, and other consumer information items": [(C, "SEEE04", 1)],
    "CPI Sports equipment": [(C, "SERC02", 1)],
    "CPI Sports vehicles including bicycles": [(C, "SERC01", 1)],
    "CPI Sporting goods": [(C, "SERC", 1)],
    "CPI Recreational books": [(C, "SERG02", 1)],
    "CPI Newspapers and magazines": [(C, "SERG01", 1)],
    "CPI Music instruments and accessories": [(C, "SERE03", 1)],
    "CPI Toys": [(C, "SERE01", 1)],
    "CPI Sewing machines, fabrics, and supplies": [(C, "SERE02", 1)],
    "CPI Pets and pet products": [(C, "SERB01", 1)],
    "CPI Pet services including veterinary": [(C, "SERB02", 1)],
    "CPI Club dues and fees for participant sports and group exercises": [(C, "SERF01", 1)],
    "CPI Other recreation services": [(C, "SERF", 1)],
    "CPI Admission to movies, theaters, and concerts": [(C, "SS62031", 1)],
    "CPI Admission to sporting events": [(C, "SS62032", 1)],
    "CPI All Items": [(C, "SA0", 1)],
    # ---------------- other durable / personal goods
    "CPI Jewelry": [(C, "SEAG02", 1)],
    "CPI Watches": [(C, "SEAG01", 1)],
    "CPI Medical equipment and supplies": [(C, "SEMG", 1)],
    "CPI Eyeglasses and eyecare": [(C, "SEMC03", 1)],
    "CPI Educational books and supplies": [(C, "SEEA", 1)],
    "CPI Miscellaneous personal goods": [(C, "SEGE", 1)],
    "CPI Hair, dental, shaving, and miscellaneous personal care products": [(C, "SEGB01", 1)],
    "CPI Cosmetics/perfumes/bath/nail preparations and implements": [(C, "SEGB02", 1)],
    "CPI Tobacco and smoking products": [(C, "SEGA", 1)],
    "CPI Stationery, stationery supplies, and gift wrap": [(C, "SS33032", 1)],
    "CPI Prescription drugs": [(C, "SEMF01", 1)],
    "CPI Nonprescription drugs": [(C, "SEMF02", 1)],
    "CPI Commodities": [(C, "SAC", 1)],
    # ---------------- food & beverages
    "CPI Cereals and cereal products": [(C, "SEFA", 1)],
    "CPI Bakery products": [(C, "SEFB", 1)],
    "CPI Beef and veal": [(C, "SEFC", 1)],
    "CPI Pork": [(C, "SEFD", 1)],
    "CPI Other meats": [(C, "SEFE", 1)],
    "CPI Poultry": [(C, "SEFF", 1)],
    "CPI Fish and seafood": [(C, "SEFG", 1)],
    "CPI Milk": [(C, "SEFJ01", 1)],
    "BEA Composite index of CPIs (Fixed-weighted CPIs for Cheese and related products, for Ice cream and related products, and for Other dairy and related products)":
        [("cpi_nsa", "SEFJ02", 1), ("cpi_sa", "SEFJ03", 1), ("cpi_nsa", "SEFJ04", 1)],
    "CPI Eggs": [(C, "SEFH", 1)],
    "CPI Fats and oils": [(C, "SEFS", 1)],
    "CPI Fresh fruits": [(C, "SEFK", 1)],
    "CPI Fresh vegetables": [(C, "SEFL", 1)],
    "CPI Processed fruits and vegetables": [(C, "SEFM", 1)],
    "CPI Sugar and sweets": [(C, "SEFR", 1)],
    "CPI Beverage materials including coffee and tea": [(C, "SEFP", 1)],
    "CPI Juices and nonalcoholic drinks": [(C, "SEFN", 1)],
    "CPI Distilled spirits at home": [(C, "SEFW02", 1)],
    "CPI Wine at home": [(C, "SEFW03", 1)],
    "CPI Beer, ale, and other malt beverages at home": [(C, "SEFW01", 1)],
    "CPI Food at employee sites and schools": [(C, "SEFV03", 1)],
    "CPI Full service meals and snacks": [(C, "SEFV01", 1)],
    "CPI Limited service meals and snacks": [(C, "SEFV02", 1)],
    "CPI Alcoholic beverages away from home": [(C, "SEFX", 1)],
    # ---------------- clothing
    "CPI Women's and girls' apparel": [(C, "SAA2", 1)],
    "CPI Men's and boys' apparel": [(C, "SAA1", 1)],
    "CPI Infants' and toddlers' apparel": [(C, "SEAF", 1)],
    "CPI Footwear": [(C, "SEAE", 1)],
    "PPI Apparel": [("ppi", "WPU0381", 1)],  # VERIFY
    # ---------------- energy
    "CPI Motor fuel": [(C, "SETB", 1)],
    "CPI Motor oil, coolant, and fluids": [(C, "SS47021", 1)],
    "CPI Fuel oil": [(C, "SEHE01", 1)],
    "CPI Propane, kerosene, and other firewood": [(C, "SEHE02", 1)],
    "CPI Electricity": [(C, "SEHF01", 1)],
    "CPI Utility (piped) gas service": [(C, "SEHF02", 1)],
    # ---------------- housing & utilities
    "CPI Rent of primary residence": [(C, "SEHA", 1)],
    "CPI Owners' equivalent rent of primary residence": [(C, "SEHC01", 1)],
    # Rental value of farm dwellings: BEA says out-months are based on CPI OER
    'Implicit. Quantity extrapolation based on annual real-dollar net stock of farm housing from BEA capital stock estimates. Current-dollar extrapolation based on gross rental value of farm dwellings from USDA. "Out months" based on CPI owners equivalent rent of primary residence.':
        [("cpi_sa", "SEHC01", 1)],
    "CPI Water and sewage maintenance": [(C, "SEHG01", 1)],
    "CPI Garbage and trash collection": [(C, "SEHG02", 1)],
    "CPI Other lodging away from home including hotels and motels": [(C, "SEHB02", 1)],
    "CPI Housing at school, excluding board": [(C, "SEHB01", 1)],
    # ---------------- health
    "CPI Dental services": [(C, "SEMC02", 1)],
    "CPI Services of other medical professionals": [(C, "SEMC04", 1)],
    "CPI Hospital and related services": [(C, "SEMD", 1)],
    "PPI Offices of physicians": [("ppi", "PCU621111621111", 1)],
    "PPI Home health care services": [("ppi", "PCU621610621610|PCU6216--6216--", 1)],
    "PPI Hospitals": [("ppi", "PCU622---622---", 1)],
    "PPI Nursing care facilities": [("ppi", "PCU6231--6231--", 1)],
    "BEA Composite index of fixed-weighted PPIs for Medical laboratories and for Diagnostic imaging centers":
        [("ppi", "PCU621511621511", 1), ("ppi", "PCU621512621512", 1)],
    # ---------------- transportation
    "CPI Other intercity transportation": [(C, "SETG02", 1)],
    "CPI Intracity transportation": [(C, "SETG03", 1)],
    "PPI Domestic scheduled passenger air transportation": [("ppi", "PCU4811114811111|PCU481111481111", 1)],  # VERIFY
    # ---------------- communication, education, personal & other services
    "CPI Land-line telephone services": [(C, "SEED04", 1)],
    "Fixed weighted average of CPI Wireless telephone services and CPI Smartphones":
        [(C, "SEED03", 1), (C, "SSEE041", 1)],
    "CPI Postage": [(C, "SEEC01", 1)],
    "CPI Delivery services": [(C, "SEEC02", 1)],
    "CPI Internet services and electronic information providers": [(C, "SEEE03", 1)],
    "CPI College tuition and fees": [(C, "SEEB01", 1)],
    "CPI Elementary and high school tuition and fixed fees": [(C, "SEEB02", 1)],
    "CPI Day care and nursery school": [(C, "SEEB03", 1)],
    "CPI Child care and nursery school": [(C, "SEEB03", 1)],
    "CPI Technical and business school tuition and fees": [(C, "SEEB04", 1)],
    "CPI Legal services": [(C, "SEGD01", 1)],
    "CPI Tax preparation and other accounting fees": [(C, "SS68023", 1)],
    "CPI Miscellaneous personal services": [(C, "SEGD", 1)],
    "CPI Funeral expenses": [(C, "SEGD02", 1)],
    "CPI Haircuts and other personal care services": [(C, "SEGC01", 1)],
    "CPI Apparel services other than laundry and drycleaning": [(C, "SEGD04", 1)],
    "CPI Laundry and drycleaning services": [(C, "SEGD03", 1)],
    "CPI Checking account and other bank services": [(C, "SS68021", 1)],
    "PPI Employment placement services": [("ppi", "PCU561311561311", 1)],  # VERIFY
    # ---------------- financial (PPI product-level ids not verified; industry fallbacks)
    "PPI Brokerage services, equities and ETFs": [("ppi", "PCU523120523120", 1)],  # VERIFY
    "PPI Brokerage services, all other securities": [("ppi", "PCU523120523120", 1)],  # VERIFY
    "PPI Dealer transactions, equities securities": [("ppi", "PCU523110523110", 1)],  # VERIFY
    "PPI Dealer transactions, debt securities and all other trading": [("ppi", "PCU523110523110", 1)],  # VERIFY
    "PPI Other securities related services including margin lending and mutual fund sales":
        [("ppi", "PCU523120523120", 1)],  # VERIFY
    "Fixed weighted average of PPI Portfolio Management and PPI Investment advice":
        [("ppi", "PCU523920523920", 1), ("ppi", "PCU523930523930", 1)],
    "PPI Commercial bank trust services": [("ppi", "PCU522110522110", 1)],  # VERIFY
    "PPI Homeowner's insurance": [("ppi", "PCU524126524126", 1)],  # VERIFY (industry: P&C insurers)
}

# ---------------------------------------------------------------------------
# BEA 2026 annual update (blog, 2026-08-17): three changes to PCE price sources.
# Applied on top of the workbook when "Apply BEA 2026 method changes" is on.
# Keyed by the workbook's PCE component name (matched case-insensitively).
# ---------------------------------------------------------------------------
BEA_2026_CHANGES = {
    "Portfolio management and investment advice services": {
        "series": [],  # quantity from a BLS CES-based extrapolator -> implicit price
        "kind": "implicit",
        "note": "BEA 2026: no longer deflated with the PPI; quantity extrapolated with "
                "BLS CES employment for the industry, so the price is implicit. "
                "Not observable from CPI/PPI: uses the line's own trend (or your override).",
    },
    "Legal services": {
        "series": [("ppi", "PCU541110541110", 1)],  # VERIFY: BEA composite of detailed legal-services PPIs
        "kind": "ppi",
        "start": "2024-01-01",
        "note": "BEA 2026: CPI legal services replaced from 2024 by a BEA composite of detailed "
                "PPIs for legal services bought by households. BEA does not name the PPIs; "
                "PPI Offices of lawyers is used as the stand-in.",
    },
    "Computer software and accessories": {
        "series": [("cpi", "SEEE02", 1),
                   ("ppi", "PCU513210513210|PCU511210511210", 1),   # VERIFY: game software publishing
                   ("ppi", "PCU518210518210", 1)],                   # VERIFY: hosting, ASP, IT infrastructure
        "kind": "mixed",
        "note": "BEA 2026: composite of CPI computer software & accessories, PPI game software "
                "publishing and PPI hosting/ASP/IT infrastructure. Weights not published (equal); "
                "industry-level PPIs used where the product-level ids are not verified.",
    },
}
