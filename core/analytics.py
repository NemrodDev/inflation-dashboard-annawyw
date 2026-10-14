"""Transformations shared by every tab."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Dataset:
    """A price measure: SA index levels + metadata + contribution weights.

    idx      : DataFrame, monthly (month-start) index levels, columns = keys
    meta     : DataFrame indexed by key with at least 'name'
    weights  : DataFrame same shape as idx; share (fraction) of the headline used to
               weight the m/m change in month t (i.e. based on t-1 expenditure/RI)
    specs    : {"Headline"|"Core": {"Major"|"Detailed": [ {label, terms:[(key, sign)]} ]}}
    views    : release-table views: {view name: [(key, indent level), ...]}
    """
    name: str
    idx: pd.DataFrame
    meta: pd.DataFrame
    weights: pd.DataFrame
    headline: str
    core: str
    specs: dict
    views: dict
    aggregates: list
    diffusion_keys: list
    heat_center: float = 0.165
    heat_scale: float = 0.5
    notes: list = field(default_factory=list)
    extras: dict = field(default_factory=dict)

    def label(self, key):
        try:
            return str(self.meta.loc[key, "name"])
        except KeyError:
            return str(key)

    def has(self, key):
        return key in self.idx.columns and self.idx[key].notna().any()


# ------------------------------------------------------------------ basic rates
def mom(idx):
    return idx.pct_change(fill_method=None) * 100


def yoy(idx):
    return idx.pct_change(12, fill_method=None) * 100


def annualized(idx, n):
    """n-month change, compounded to an annual rate (n=12 -> y/y)."""
    return ((idx / idx.shift(n)) ** (12.0 / n) - 1) * 100


def rates_table(idx: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({
        "1m ann.": annualized(idx, 1),
        "3m ann.": annualized(idx, 3),
        "6m ann.": annualized(idx, 6),
        "12m": annualized(idx, 12),
    })


# ------------------------------------------------------------------ weights
def ri_weights(idx: pd.DataFrame, ri: pd.Series, headline: str) -> pd.DataFrame:
    """BLS-style relative-importance weights updated for relative price change.

    w_i(t) = RI_i/100 * [I_i(t-1)/I_i(Dec)] / [I_all(t-1)/I_all(Dec)]
    where Dec is the December preceding month t's year. The same RI vintage is
    applied to every year (an approximation for older years)."""
    ri = ri.reindex(idx.columns)
    prev = idx.shift(1)
    dec = idx[idx.index.month == 12]
    dec.index = dec.index.year
    base = dec.reindex(idx.index.year - 1)
    base.index = idx.index
    rel = prev / base
    w = rel.div(rel[headline], axis=0) * (ri / 100.0)
    return w


def nominal_weights(nominal: pd.DataFrame, headline: str) -> pd.DataFrame:
    """Expenditure shares of the previous month (PCE)."""
    sh = nominal.div(nominal[headline], axis=0)
    return sh.shift(1)


# ------------------------------------------------------------------ contributions
def contribution(ds: Dataset, terms, m: pd.DataFrame | None = None) -> pd.Series:
    """Contribution (pp of headline) of a linear combination of series."""
    m = mom(ds.idx) if m is None else m
    out = None
    for key, sign in terms:
        if key not in m.columns or key not in ds.weights.columns:
            return pd.Series(np.nan, index=ds.idx.index)
        c = sign * ds.weights[key] * m[key]
        out = c if out is None else out + c
    return out


def target_key(ds: Dataset, target: str):
    """Series key for a contribution target ('Headline', 'Core', or extras['targets'])."""
    if target == "Headline":
        return ds.headline
    if target == "Core":
        return ds.core
    return ds.extras.get("targets", {})[target]


def contributions(ds: Dataset, target: str, level: str, horizon: str = "m/m"):
    """Returns (contrib DataFrame, actual target series, residual series).
    target: 'Headline' or 'Core'. Contributions to core are scaled by core's weight.
    horizon 'm/m': weight(t-1) x item m/m.
    horizon '12m': weight a year earlier x item y/y (computed from levels, so a
    missing month such as Oct 2025 doesn't blank the following 11 months)."""
    specs = ds.specs[target][level]
    tkey = target_key(ds, target)
    if horizon == "12m":
        chg, w = yoy(ds.idx), ds.weights.shift(11)
        actual = yoy(ds.idx[tkey])
    else:
        chg, w = mom(ds.idx), ds.weights
        actual = chg[tkey]
    cols = {}
    for s in specs:
        acc = None
        for key, sign in s["terms"]:
            if key not in chg.columns or key not in w.columns:
                acc = pd.Series(np.nan, index=ds.idx.index)
                break
            c = sign * w[key] * chg[key]
            acc = c if acc is None else acc + c
        cols[s["label"]] = acc
    df = pd.DataFrame(cols)
    if target != "Headline":
        df = df.div(w[tkey], axis=0)
    resid = actual - df.sum(axis=1, min_count=1)
    return df, actual, resid


def chain_from_mom(m: pd.Series, base=100.0) -> pd.Series:
    """Build an index from m/m % changes (gaps stay gaps; chain restarts at 100)."""
    lvl = (1 + m / 100).cumprod() * base
    return lvl


def derived_index(ds: Dataset, terms, label: str) -> pd.Series:
    """Index for a combination such as core services ex shelter:
    change = sum(sign*w*change_i) / sum(sign*w), chained between months where all
    components are published. Across a missing month (e.g. Oct 2025) the change is
    taken over the whole gap, so the level after the gap stays correct."""
    keys = [k for k, _ in terms]
    if any(k not in ds.idx.columns for k in keys):
        return pd.Series(np.nan, index=ds.idx.index, name=label)
    lv = ds.idx[keys]
    w_next = ds.weights[keys].shift(-1)  # weight row based on this month's levels
    valid = lv.notna().all(axis=1)
    dates = list(lv.index[valid])
    out = pd.Series(np.nan, index=ds.idx.index, name=label)
    prev, level = None, 100.0
    sign = np.array([s for _, s in terms], dtype=float)
    for d in dates:
        if prev is not None:
            w = w_next.loc[prev].to_numpy(dtype=float)
            chg = (lv.loc[d] / lv.loc[prev] - 1).to_numpy(dtype=float)
            den = (sign * w).sum()
            if np.isnan(den) or den == 0:
                prev = None
                continue
            level *= 1 + (sign * w * chg).sum() / den
        out.loc[d] = level
        prev = d
    return out


# ------------------------------------------------------------------ diffusion
def diffusion(idx: pd.DataFrame, keys, threshold=3.0, weights: pd.DataFrame | None = None):
    """Share (%) of items whose 3m/6m annualised and 12m change exceed threshold."""
    keys = [k for k in keys if k in idx.columns]
    sub = idx[keys]
    out = {}
    for n, lab in [(3, "3m annualized"), (6, "6m annualized"), (12, "12m")]:
        r = annualized(sub, n)
        valid = r.notna()
        above = (r > threshold) & valid
        if weights is None:
            share = above.sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
        else:
            w = weights.reindex(columns=keys).ffill()
            share = (w * above).sum(axis=1) / (w * valid).sum(axis=1).replace(0, np.nan)
        out[lab] = share * 100
    out["items"] = sub.notna().sum(axis=1)
    return pd.DataFrame(out)


# ------------------------------------------------------------------ release table
def release_table(ds: Dataset, view: str, n_months=13) -> pd.DataFrame:
    rows = ds.views[view]
    keys = [k for k, _ in rows if k in ds.idx.columns]
    lvl = dict(rows)
    m = mom(ds.idx[keys])
    m = m.dropna(how="all")
    m = m.iloc[-n_months:]
    out = m.T.copy()
    out.columns = [d.strftime("%b %y") for d in m.index]
    a3 = annualized(ds.idx[keys], 3).reindex(m.index).iloc[-1]
    a6 = annualized(ds.idx[keys], 6).reindex(m.index).iloc[-1]
    y = yoy(ds.idx[keys]).reindex(m.index).iloc[-1]
    w = ds.weights.reindex(columns=keys).reindex(m.index).iloc[-1] * 100
    out.insert(0, "Weight", w)
    out["3m ann."] = a3
    out["6m ann."] = a6
    out["YoY"] = y
    names = [(" " * lvl[k]) + ds.label(k) for k in out.index]
    out.insert(0, "Item", names)
    out.insert(0, "Code", list(out.index))
    return out.reset_index(drop=True)


def heat_color(v, center, scale):
    """Diverging blue (below) / red (above) background for a value."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    t = max(-1.0, min(1.0, (v - center) / scale))
    if t >= 0:
        r, g, b = 255, int(255 - 150 * t), int(255 - 160 * t)
    else:
        t = -t
        r, g, b = int(255 - 160 * t), int(255 - 110 * t), 255
    return f"background-color: rgb({r},{g},{b}); color: #111"


# ------------------------------------------------------------------ movers
def top_movers(ds: Dataset, keys, n=8):
    """Largest contributions to the latest m/m change versus their own trailing
    12-month average contribution (what moved this month)."""
    m = mom(ds.idx)
    rows = []
    for k in keys:
        if k not in m.columns or k not in ds.weights.columns:
            continue
        c = ds.weights[k] * m[k] * 100  # basis points
        c = c.dropna()
        if len(c) < 13:
            continue
        rows.append({"key": k, "Item": ds.label(k), "Latest (bp)": c.iloc[-1],
                     "12m avg (bp)": c.iloc[-13:-1].mean(),
                     "Surprise vs avg (bp)": c.iloc[-1] - c.iloc[-13:-1].mean(),
                     "m/m %": m[k].dropna().iloc[-1]})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.reindex(df["Surprise vs avg (bp)"].abs().sort_values(ascending=False).index).head(n)
    return df.drop(columns="key")


# ------------------------------------------------------------------ BEA hierarchy
def bea_tree(names: list[str], values: list[float], tol=0.002):
    """Reconstruct the indentation of a BEA table from nominal values.

    A line is an aggregate if a run of the following sub-trees sums to it
    (lines starting 'Less:' are subtracted). Returns (levels, parents, is_leaf)
    for the lines before 'Addenda'. Lines after it get level 0, parent None."""
    import sys
    sys.setrecursionlimit(max(5000, sys.getrecursionlimit()))
    n_all = len(names)
    n = next((i for i, s in enumerate(names) if s.lower().startswith("addenda")), n_all)
    vals = [float(v) if v is not None and not np.isnan(v) else np.nan for v in values]
    sign = [-1 if names[i].lower().startswith("less") else 1 for i in range(n_all)]
    memo = {}

    def sub(i):
        if i in memo:
            return memo[i]
        v = vals[i]
        memo[i] = (i + 1, [])  # provisional (guards cycles)
        if np.isnan(v) or v == 0 or i + 1 >= n:
            return memo[i]
        j, s, ch = i + 1, 0.0, []
        while j < n and len(ch) < 200:
            if np.isnan(vals[j]):
                break
            s += sign[j] * vals[j]
            ch.append(j)
            end_j, _ = sub(j)
            j = end_j
            if abs(s - v) <= tol * abs(v) + 1.0:
                memo[i] = (j, ch)
                return memo[i]
            if abs(s) > abs(v) * 1.5 + 10 and not (j < n and sign[j] < 0):
                break
        memo[i] = (i + 1, [])
        return memo[i]

    levels = [0] * n_all
    parents = [None] * n_all
    leaf = [True] * n_all

    def assign(i, lvl):
        levels[i] = lvl
        _, ch = sub(i)
        leaf[i] = len(ch) == 0
        for c in ch:
            parents[c] = i
            assign(c, lvl + 1)

    root_end, root_children = sub(0)
    if root_children:
        # Only lines inside the first line's (total PCE's) breakdown are real detail.
        # Everything after it is addenda/special aggregates, with or without an
        # "Addenda:" header (e.g. "PCE excluding energy", "Control group").
        assign(0, 0)
        for k in range(root_end, n_all):
            leaf[k] = False
            levels[k] = 0
    else:  # total didn't reconcile: fall back to top-level runs before 'Addenda'
        i = 0
        while i < n:
            assign(i, 0)
            i = sub(i)[0]
        for k in range(n, n_all):
            leaf[k] = False
    return levels, parents, leaf
