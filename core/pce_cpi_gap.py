"""Which categories make core PCE run above or below core CPI: for each category,
PCE contribution to core PCE m/m minus CPI contribution to core CPI m/m, in percentage points.

PCE: category m/m (BEA Table 2.4.4U) x its share of core PCE nominal spending in the previous month.
CPI: m/m of the mapped CPI items x their relative importance within core CPI (updated for relative
     price change, as BLS does), summed. Categories with no core-CPI counterpart (food services,
     financial services, nonprofits, other durables) have a CPI contribution of 0 — food away from home
     is excluded from core CPI while PCE food services are in core PCE.
Total row = core PCE m/m − core CPI m/m.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# (label, BEA code in Table 2.4.4U, CPI items as [(code, sign)])
CATEGORIES = [
    ("Housing", "DHSGRG", [("SEHA", 1), ("SEHC", 1)]),
    ("Transportation services", "DTRSRG", [("SAS4", 1), ("SETE", -1)]),
    ("Accommodation", "DACCRG", [("SEHB", 1)]),
    ("Health care", "DHLCRG", [("SAM2", 1), ("SEME", -1)]),
    ("Household utilities", "DWRSRG", [("SEHG", 1)]),
    ("Alcoholic beverages", "DAOPRG", [("SAF116", 1)]),
    ("Furnishings and durable household equipment", "DFDHRG", [("SAH31", 1)]),
    ("Clothing and footwear", "DCLORG", [("SAA", 1)]),
    ("Recreation services", "DRCARG", [("SARS", 1)]),
    ("Other nondurable goods", "DONGRG", [("SAGC", 1), ("SAM1", 1)]),
    ("Nonprofits", "DNPIRG", []),
    ("Insurance", "DINSRG", [("SEME", 1), ("SETE", 1)]),
    ("Other durable goods", "DODGRG", []),
    ("Motor vehicles and parts", "DMOTRG", [("SETA01", 1), ("SETA02", 1), ("SETC", 1)]),
    ("Other services", "DOTSRG", [("SAES", 1), ("SAGS", 1), ("SEHP", 1)]),
    ("Food services", "DFSERG", []),
    ("Financial services", "DFNLRG", []),
    ("Recreational goods and vehicles", "DREQRG", [("SARC", 1), ("SAEC", 1)]),
]


def _key(meta, code):
    hit = meta.index[(meta.get("bea_code") == code) & meta.index.str.startswith("U:")] if "bea_code" in meta else []
    return hit[0] if len(hit) else None


def pce_contrib(pce) -> pd.DataFrame:
    """Published PCE contributions to core PCE m/m by category (pp), month x category."""
    nom, idx, meta = pce.extras["nominal"], pce.idx, pce.meta
    core_w = nom[pce.core].shift(1)
    out = {}
    for lab, code, _ in CATEGORIES:
        k = _key(meta, code)
        if k is None or k not in idx:
            continue
        out[lab] = nom[k].shift(1) / core_w * idx[k].pct_change(fill_method=None) * 100
    return pd.DataFrame(out)


def cpi_contrib(cpi) -> pd.DataFrame:
    """CPI contributions to core CPI m/m by category (pp), month x category."""
    w, idx, core = cpi.weights, cpi.idx, cpi.core
    out = {}
    for lab, _, items in CATEGORIES:
        s = pd.Series(0.0, index=idx.index)
        for code, sg in items:
            if code in idx and code in w:
                s = s + sg * (w[code] / w[core]) * idx[code].pct_change(fill_method=None) * 100
        out[lab] = s
    return pd.DataFrame(out)


def leaf_categories(pce, leaf_keys) -> dict:
    """Leaf key -> category label, by walking up BEA's line hierarchy."""
    meta = pce.meta
    by_key = {_key(meta, code): lab for lab, code, _ in CATEGORIES}
    out = {}
    for k in leaf_keys:
        p = k
        while p is not None and p in meta.index:
            if p in by_key:
                out[k] = by_key[p]
                break
            p = meta.loc[p, "parent"] if "parent" in meta else None
            p = None if (p is None or (isinstance(p, float) and np.isnan(p))) else p
    return out


def nowcast_contrib(res, leaves, pce, target) -> pd.Series:
    """Nowcast PCE contributions to core PCE m/m by category for the target month (from line values)."""
    W = res["weights"].loc[target]
    V = res["values"].loc[target]
    core = leaves.loc[~leaves["fe"].isin(["food", "energy"])]
    ok = [ln for ln in core["line"] if pd.notna(W.get(ln)) and pd.notna(V.get(ln))]
    tot = W[ok].sum()
    cat = leaf_categories(pce, core.set_index("line").loc[ok, "key"].tolist())
    key_of = core.set_index("line")["key"]
    s = pd.Series(0.0, index=[c[0] for c in CATEGORIES])
    for ln in ok:
        c = cat.get(key_of[ln])
        if c is not None:
            s[c] += W[ln] * V[ln] / tot          # share of core x m/m % = pp
    return s


def gap(pce_c: pd.DataFrame | pd.Series, cpi_c: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return pce_c - cpi_c.reindex_like(pce_c).fillna(0)


# ------------------------------------------------------------------ 12-month (y/y) version
def _yy(level: pd.Series, d) -> float:
    """12-month % change by calendar month (a missing month stays missing)."""
    a, b = level.get(d, np.nan), level.get(d - pd.DateOffset(months=12), np.nan)
    return (a / b - 1) * 100


def nowcast_cat_mm(res, leaves, pce, target) -> pd.Series:
    """Nowcast m/m % of each category for the target month (spending-weighted average of its lines)."""
    W, V = res["weights"].loc[target], res["values"].loc[target]
    core = leaves.loc[~leaves["fe"].isin(["food", "energy"])]
    key_of = core.set_index("line")["key"]
    cat = leaf_categories(pce, key_of.tolist())
    num, den = {}, {}
    for ln, k in key_of.items():
        c = cat.get(k)
        if c is None or pd.isna(W.get(ln)) or pd.isna(V.get(ln)):
            continue
        num[c] = num.get(c, 0.0) + W[ln] * V[ln]
        den[c] = den.get(c, 0.0) + W[ln]
    return pd.Series({c: num[c] / den[c] for c in num if den[c]})


def yy_gap(pce, cpi, month, pce_total_yy: float, cpi_total_yy: float,
           nowcast_mm: pd.Series | None = None) -> pd.Series:
    """Contribution of each category to (core PCE y/y − core CPI y/y), pp, for `month`.
    Category y/y × its weight 12 months earlier (PCE: share of core spending in month−12;
    CPI: relative importance within core CPI for month−11, i.e. priced at month−12).
    If nowcast_mm is given, PCE categories for `month` use it on top of last month's published level.
    'Residual' = the part of the published gap the category approximation doesn't capture
    (chaining, changing weights, CPI items not mapped); 'Total' = the gap itself."""
    nom, idx, meta = pce.extras["nominal"], pce.idx, pce.meta
    b12 = month - pd.DateOffset(months=12)
    m11 = month - pd.DateOffset(months=11)
    core_w = nom[pce.core].get(b12, np.nan)
    out = {}
    for lab, code, items in CATEGORIES:
        k = _key(meta, code)
        p = 0.0
        if k is not None and k in idx:
            lvl = idx[k]
            if nowcast_mm is not None and lab in nowcast_mm.index:
                prev = lvl.get(month - pd.DateOffset(months=1), np.nan)
                yy = (prev * (1 + nowcast_mm[lab] / 100) / lvl.get(b12, np.nan) - 1) * 100
            else:
                yy = _yy(lvl, month)
            p = nom[k].get(b12, np.nan) / core_w * yy
        c = 0.0
        for icode, sg in items:
            if icode in cpi.idx and icode in cpi.weights:
                w = cpi.weights[icode].get(m11, np.nan) / cpi.weights[cpi.core].get(m11, np.nan)
                v = sg * w * _yy(cpi.idx[icode], month)
                c += 0.0 if pd.isna(v) else v
        out[lab] = (0.0 if pd.isna(p) else p) - c
    s = pd.Series(out)
    total = pce_total_yy - cpi_total_yy
    s["Residual"] = total - s.sum()
    s["Total"] = total
    return s
