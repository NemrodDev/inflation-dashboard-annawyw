"""Alternative / summary core inflation measures, all as 12-month % changes.

Published:   core PCE (BEA), core CPI (BLS), market-based core PCE (BEA Table 2.4.4U, DPCXRG),
             Dallas Fed trimmed mean PCE 24/31 (FRED PCETRIM12M159SFRBDAL).
Derived exactly from BEA lines (nominal-weighted removal of a component, chained):
             market-based core PCE excluding housing  = DPCXRG less DHSMRG (market-based housing)
             core services excluding housing          = IA000063 (services ex energy) less DHSGRG (housing)
Computed from BEA's detailed PCE lines (each line's previous-month share of nominal spending):
             trimmed means (24/31 and 19/20 trims of the monthly price-change distribution),
             median PCE (weighted median), chained into indexes and taken 12 months apart;
             bias-adjusted trimmed mean = 24/31 trimmed mean less its average gap to headline PCE
             (trailing 10 years, y/y), so it is centred on headline over long periods.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DALLAS_TM = "PCETRIM12M159SFRBDAL"
CODES = {"core_services": "IA000063", "housing": "DHSGRG", "mkt_core": "DPCXRG", "mkt_housing": "DHSMRG"}


def yoy(index: pd.Series) -> pd.Series:
    """12-month % change by calendar month (a missing month, e.g. Oct 2025 CPI, stays a gap
    instead of shifting the comparison to 13 months back)."""
    i = index.dropna()
    prior = index.reindex(i.index - pd.DateOffset(months=12))
    return pd.Series((i.values / prior.values - 1) * 100, index=i.index)


def chain(mm: pd.Series, base=100.0) -> pd.Series:
    mm = mm.dropna()
    return base * (1 + mm / 100).cumprod()


def key_for(meta: pd.DataFrame, code: str, prefix="U:"):
    if "bea_code" not in meta:
        return None
    hit = meta.index[(meta["bea_code"] == code) & meta.index.str.startswith(prefix)]
    return hit[0] if len(hit) else None


def excluding(idx_a: pd.Series, nom_a: pd.Series, idx_b: pd.Series, nom_b: pd.Series) -> pd.Series:
    """Price index of aggregate A without component B: monthly change
    (W_A m_A − W_B m_B) / (W_A − W_B) with previous-month nominal weights, chained."""
    ma, mb = idx_a.pct_change(fill_method=None) * 100, idx_b.pct_change(fill_method=None) * 100
    wa, wb = nom_a.shift(1), nom_b.shift(1)
    mm = (wa * ma - wb * mb) / (wa - wb)
    return chain(mm)


def trimmed_mm(mm: pd.DataFrame, w: pd.DataFrame, lo: float, hi: float) -> pd.Series:
    """Weighted trimmed mean of each month's component changes: drop the lowest `lo` and highest `hi`
    shares of expenditure weight (partial weights at the cut points). lo = hi = 0.5 gives the
    weighted median."""
    out = {}
    for d in mm.index:
        x, ww = mm.loc[d], w.loc[d]
        ok = x.notna() & ww.notna() & (ww > 0)
        if ok.sum() < 20:
            continue
        x, ww = x[ok].values, ww[ok].values
        o = np.argsort(x, kind="mergesort")
        x, ww = x[o], ww[o] / ww.sum()
        c1 = np.cumsum(ww)
        c0 = c1 - ww
        if lo >= 0.5 and hi >= 0.5:                       # weighted median
            out[d] = float(x[np.searchsorted(c1, 0.5)])
            continue
        inc = np.clip(np.minimum(c1, 1 - hi) - np.maximum(c0, lo), 0, None)
        out[d] = float((x * inc).sum() / inc.sum()) if inc.sum() > 0 else np.nan
    return pd.Series(out)


def compute(pce, cpi, dallas_yy: pd.Series | None = None) -> tuple[pd.DataFrame, dict]:
    """All measures as y/y %. Returns (frame, notes)."""
    notes = {}
    idx, nom, meta = pce.idx, pce.extras["nominal"], pce.meta
    out = {"Core PCE": yoy(idx[pce.core]), "Core CPI": yoy(cpi.idx[cpi.core]) if cpi is not None else None}

    # trimmed means / median from detailed lines
    keys = [k for k in pce.diffusion_keys if k in idx and k in nom]
    mm = idx[keys].pct_change(fill_method=None) * 100
    w = nom[keys].shift(1)
    tm2431 = yoy(chain(trimmed_mm(mm, w, 0.24, 0.31)))
    out["Trimmed Mean PCE (24/31)"] = tm2431
    if dallas_yy is not None and len(dallas_yy.dropna()):
        d = dallas_yy.dropna()
        both = pd.DataFrame({"ours": tm2431, "dallas": d}).dropna()
        if len(both) > 12:
            notes["tm_check"] = (float((both["ours"] - both["dallas"]).abs().mean()), len(both))
        out["Trimmed Mean PCE (24/31)"] = d
        notes["tm_source"] = "Dallas Fed (FRED)"
    else:
        notes["tm_source"] = "computed from BEA detail"
    head = yoy(idx[pce.headline])
    gap = (out["Trimmed Mean PCE (24/31)"] - head).dropna()
    bias = gap.shift(1).rolling(120, min_periods=36).mean()
    out["Bias-Adjusted Trimmed Mean (24/31)"] = (out["Trimmed Mean PCE (24/31)"] - bias).dropna()
    out["Alternative Trimmed Mean (19/20)"] = yoy(chain(trimmed_mm(mm, w, 0.19, 0.20)))
    out["Median PCE"] = yoy(chain(trimmed_mm(mm, w, 0.5, 0.5)))
    notes["n_components"] = len(keys)

    k = {n: key_for(meta, c) for n, c in CODES.items()}
    if k["mkt_core"]:
        out["Market-Based Core PCE"] = yoy(idx[k["mkt_core"]])
        if k["mkt_housing"]:
            out["Market-Based Core PCE Excluding Housing"] = yoy(excluding(
                idx[k["mkt_core"]], nom[k["mkt_core"]], idx[k["mkt_housing"]], nom[k["mkt_housing"]]))
    if k["core_services"] and k["housing"]:
        out["Core Services Excluding Housing"] = yoy(excluding(
            idx[k["core_services"]], nom[k["core_services"]], idx[k["housing"]], nom[k["housing"]]))
    df = pd.DataFrame({n: s for n, s in out.items() if s is not None})
    return df, notes
