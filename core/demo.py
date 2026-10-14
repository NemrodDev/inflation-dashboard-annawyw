"""Synthetic data with the same structure as the live sources, so the whole app can
be explored (and tested) without API keys. Numbers are random but shaped like the
2021-22 inflation surge and its unwind. Clearly labelled as DEMO in the UI."""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import cpi as CPI, ppi as PPI, pce as PCE
from core.builders import build_cpi, build_ppi, build_pce

START = "2014-01-01"


def _dates(end):
    return pd.date_range(START, end, freq="MS")


def _regime(dates):
    t = np.arange(len(dates))
    peak = np.argmin(np.abs(dates - pd.Timestamp("2022-06-01")))
    start = np.argmin(np.abs(dates - pd.Timestamp("2021-03-01")))
    f = np.ones(len(dates))
    up = (t >= start) & (t <= peak)
    f[up] = 1 + 2.2 * (t[up] - start) / max(peak - start, 1)
    down = t > peak
    f[down] = 1.3 + 1.9 * np.exp(-(t[down] - peak) / 10)
    return f


def _leaf_mom(rng, n, drift, vol, f, seasonal_noise=0.0):
    return drift * f + rng.normal(0, vol, n) * np.sqrt(f) + seasonal_noise


def _tree_children(rows):
    """rows: list of (code, level). children by indentation."""
    ch = {}
    for i, (c, lv) in enumerate(rows):
        ch[c] = []
        for j in range(i + 1, len(rows)):
            c2, lv2 = rows[j]
            if lv2 <= lv:
                break
            if lv2 == lv + 1:
                ch[c].append(c2)
    return ch


def _aggregate(moms: dict, ri: dict, children: dict, order):
    for c in reversed(order):
        kids = [k for k in children.get(c, []) if k in moms]
        if kids:
            w = np.array([ri[k] for k in kids])
            moms[c] = sum(ri[k] * moms[k] for k in kids) / w.sum()
    return moms


def _to_index(moms: dict, dates):
    return pd.DataFrame({k: 100 * np.cumprod(1 + v / 100) for k, v in moms.items()}, index=dates)


# ------------------------------------------------------------------ CPI
def demo_cpi(end) -> object:
    rng = np.random.default_rng(1)
    dates = _dates(end)
    n, f = len(dates), _regime(dates)
    rows = CPI.RELEASE_TABLE
    ri = {c: w for c, _, _, w in rows}
    group = {}
    cur = None
    for c, _, lv, _ in rows:
        if lv == 1:
            cur = c
        group[c] = cur
    children = _tree_children([(c, lv) for c, _, lv, _ in rows])
    codes = [r[0] for r in rows]
    core_goods = set(codes[codes.index("SACL1E") + 1: codes.index("SASLE")])
    moms = {}
    for c, name, lv, _ in rows:
        if children[c]:
            continue
        g = group[c]
        if g == "SAF1":
            moms[c] = _leaf_mom(rng, n, 0.18, 0.25, f)
        elif g == "SA0E":
            moms[c] = _leaf_mom(rng, n, 0.15, 2.4, f)
        elif c in ("SEHA", "SEHC"):
            sh = 0.28 + 0.25 * np.clip(f - 1, 0, None) / 2.2 + rng.normal(0, 0.05, n)
            moms[c] = sh
        elif c == "SETA02":
            moms[c] = _leaf_mom(rng, n, 0.0, 1.4, f ** 2)
        elif c in ("SETE",):
            moms[c] = _leaf_mom(rng, n, 0.45, 0.6, f)
        elif c in ("SETG01", "SEHB"):
            moms[c] = _leaf_mom(rng, n, 0.1, 2.5, f)
        elif c in core_goods:
            moms[c] = _leaf_mom(rng, n, 0.02, 0.35, f)
        else:
            moms[c] = _leaf_mom(rng, n, 0.27, 0.22, f)  # core services
    moms = _aggregate(moms, ri, children, [r[0] for r in rows])
    # extras
    moms["SAC"] = (ri["SAF11"] * moms["SAF11"] + ri["SACE"] * moms["SACE"] + ri["SACL1E"] * moms["SACL1E"]) / (
        ri["SAF11"] + ri["SACE"] + ri["SACL1E"])
    moms["SAS"] = (ri["SASLE"] * moms["SASLE"] + ri["SEHF"] * moms["SEHF"] + ri["SEFV"] * moms["SEFV"]) / (
        ri["SASLE"] + ri["SEHF"] + ri["SEFV"])
    moms["SASL2RS"] = moms["SAS"] - 0.05
    moms["SAE1"] = _leaf_mom(rng, n, 0.2, 0.2, f)
    moms["SAE2"] = _leaf_mom(rng, n, 0.0, 0.4, f)
    for c, _, _ in CPI.AI_ITEMS:
        moms[c] = _leaf_mom(rng, n, -0.4 if c != "SEEE02" else -0.1, 1.2, np.ones(n))
    extra = []
    for k in range(80):
        code = f"DEMO{k:03d}"
        moms[code] = _leaf_mom(rng, n, rng.uniform(-0.1, 0.4), rng.uniform(0.2, 1.2), f)
        extra.append(code)
    idx = _to_index(moms, dates)
    idx.loc[pd.Timestamp("2025-10-01")] = np.nan  # mimic the Oct-2025 publication gap
    names = {c: f"Demo item {c[-3:]}" for c in extra}
    diff = list(CPI.DIFFUSION_FALLBACK) + extra
    ds = build_cpi(idx, names, ["DEMO DATA — synthetic, for layout only."], None, diff)
    ds.extras["ai_codes"] = [c for c, _, _ in CPI.AI_ITEMS]
    return ds


# ------------------------------------------------------------------ PPI
def demo_ppi(end):
    rng = np.random.default_rng(2)
    dates = _dates(end)
    n, f = len(dates), _regime(dates)
    rows = [r for r in PPI.RELEASE_TABLE if not r[0].startswith("FD491")]
    ri = {c: w for c, _, _, w in PPI.RELEASE_TABLE}
    children = _tree_children([(c, lv) for c, _, lv, _ in rows])
    # FD421 children (FD4211) are a subset; give the remainder its own leaf
    moms = {}
    for c, _, _, _ in rows:
        if children[c]:
            continue
        vol = {"FD411": 1.2, "FD412": 3.0, "FD423": 0.9, "FD4221": 2.0}.get(c, 0.3)
        drift = {"FD412": 0.1, "FD413": 0.12}.get(c, 0.22)
        moms[c] = _leaf_mom(rng, n, drift, vol, f)
    moms = _aggregate(moms, ri, children, [r[0] for r in rows])
    comb = lambda ks: sum(ri[k] * moms[k] for k in ks) / sum(ri[k] for k in ks)  # noqa: E731
    moms["FD49104"] = comb(["FD413", "FD42", "FD43"])
    moms["FD49116"] = comb(["FD413", "FD422", "FD421", "FD43"])
    moms["FD49108"] = comb(["FD41", "FD422", "FD421", "FD43"])
    for k in PPI.PCE_INPUTS:
        moms[k] = _leaf_mom(rng, n, 0.22, 0.35 if "523" not in k else 2.0, f)
    extra = []
    for k in range(120):
        code = f"DEMO{k:03d}"
        moms[code] = _leaf_mom(rng, n, rng.uniform(-0.1, 0.4), rng.uniform(0.3, 2.0), f)
        extra.append(code)
    idx = _to_index(moms, dates)
    names = {c: f"Demo commodity {c[-3:]}" for c in extra}
    return build_ppi(idx, names, ["DEMO DATA — synthetic, for layout only."], extra)


# ------------------------------------------------------------------ PCE
# (name, level, share, in_major_table, flag)
_PCE = [
    ("Personal consumption expenditures (PCE)", 0, None, True, ""),
    ("Goods", 1, None, True, ""),
    ("Durable goods", 2, None, True, ""),
    ("Motor vehicles and parts", 3, .035, True, "g"),
    ("Furnishings and durable household equipment", 3, .025, True, "g"),
    ("Recreational goods and vehicles", 3, .035, True, "g"),
    ("Other durable goods", 3, .017, True, "g"),
    ("Nondurable goods", 2, None, True, ""),
    ("Food and beverages purchased for off-premises consumption", 3, .075, True, "food"),
    ("Clothing and footwear", 3, .022, True, "g"),
    ("Gasoline and other energy goods", 3, .022, True, "energy"),
    ("Other nondurable goods", 3, .09, True, "g"),
    ("Services", 1, None, True, ""),
    ("Household consumption expenditures (for services)", 2, None, True, ""),
    ("Housing and utilities", 3, None, True, ""),
    ("Housing", 4, .158, False, "housing"),
    ("Water supply and sanitation", 4, .006, False, "s"),
    ("Electricity and gas", 4, .016, False, "energy"),
    ("Health care", 3, None, True, ""),
    ("Physician services", 4, .045, False, "s"),
    ("Hospitals", 4, .09, False, "s"),
    ("Other health care", 4, .03, False, "s"),
    ("Transportation services", 3, .035, True, "s"),
    ("Recreation services", 3, .04, True, "s"),
    ("Food services and accommodations", 3, .07, True, "s"),
    ("Financial services and insurance", 3, .085, True, "s"),
    ("Other services", 3, .075, True, "s"),
    ("Final consumption expenditures of nonprofit institutions serving households (NPISHs)", 2, None, True, ""),
    ("Gross output of nonprofit institutions", 3, .08, True, "s"),
    ("Less: Receipts from sales of goods and services by nonprofit institutions", 3, .06, True, "s"),
]


def demo_pce(end):
    rng = np.random.default_rng(3)
    dates = _dates(end)
    n, f = len(dates), _regime(dates)
    names = [r[0] for r in _PCE]
    children = _tree_children([(r[0], r[1]) for r in _PCE])
    price_m, nom = {}, {}
    for nm, lv, sh, _, flag in _PCE:
        if children[nm]:
            continue
        drift, vol = {"food": (0.18, 0.3), "energy": (0.15, 2.5), "g": (0.02, 0.35),
                      "housing": (0.3, 0.06)}.get(flag, (0.24, 0.2))
        m = _leaf_mom(rng, n, drift, vol, f)
        price_m[nm] = m
        nom[nm] = sh * 1.6e7 * np.cumprod((1 + m / 100) * 1.0015)
    sign = {nm: (-1 if nm.startswith("Less") else 1) for nm in names}
    for nm in reversed(names):
        kids = children[nm]
        if not kids:
            continue
        nom[nm] = sum(sign[k] * nom[k] for k in kids)
        prev = {k: np.r_[nom[k][0], nom[k][:-1]] for k in kids}
        price_m[nm] = sum(sign[k] * prev[k] * price_m[k] for k in kids) / sum(sign[k] * prev[k] for k in kids)

    def combo(plus, minus=()):
        p_n = sum(nom[k] for k in plus) - sum(nom[k] for k in minus)
        prev = lambda k: np.r_[nom[k][0], nom[k][:-1]]  # noqa: E731
        num = sum(prev(k) * price_m[k] for k in plus) - sum(prev(k) * price_m[k] for k in minus)
        den = sum(prev(k) for k in plus) - sum(prev(k) for k in minus)
        return p_n, num / den

    food = ["Food and beverages purchased for off-premises consumption"]
    energy = ["Gasoline and other energy goods", "Electricity and gas"]
    head = "Personal consumption expenditures (PCE)"
    addenda = {
        "PCE excluding food and energy": combo([head], food + energy),
        "Food": combo(food),
        "Energy goods and services": combo(energy),
        "Housing": combo(["Housing"]),
        "PCE services excluding energy and housing": combo(["Services"], ["Electricity and gas", "Housing"]),
        "PCE excluding food, energy, and housing": combo([head], food + energy + ["Housing"]),
        "Market-based PCE excluding food and energy": combo([head], food + energy),
    }

    def table(major_only):
        lines = [r for r in _PCE if (r[3] or not major_only)]
        lines_names = [r[0] for r in lines]
        if major_only:
            lines_names += ["Addenda:"] + list(addenda)
        keys = [f"L{i + 1:03d}" for i in range(len(lines_names))]
        p, q = {}, {}
        for k, nm in zip(keys, lines_names):
            if nm == "Addenda:":
                p[k] = np.full(n, np.nan)
                q[k] = np.full(n, np.nan)
                continue
            if nm in addenda and major_only and lines_names.index(nm) > lines_names.index("Addenda:"):
                q[k], m = addenda[nm]
            else:
                q[k], m = nom[nm], price_m[nm]
            p[k] = 100 * np.cumprod(1 + m / 100)
        meta = pd.DataFrame({"name": lines_names, "line": range(1, len(keys) + 1)}, index=keys)
        return pd.DataFrame(p, index=dates), pd.DataFrame(q, index=dates), meta

    maj_p, maj_n, maj_meta = table(True)
    det_p, det_n, det_meta = table(False)
    # mimic BEA timing: PCE lags CPI by ~1 month
    maj_p, maj_n, det_p, det_n = (x.iloc[:-1] for x in (maj_p, maj_n, det_p, det_n))
    return build_pce(maj_p, maj_n, maj_meta, det_p, det_n, det_meta,
                     ["DEMO DATA — synthetic, for layout only."])
