"""Line-level CPI/PPI -> PCE nowcast built on BEA's source-data table
(Table 2.4.4U-D, supplied as config/Detail_CPI_PCE_mapping.xlsx).

Steps
 1. read the workbook (line, PCE component, BEA series code, price source, seasonal status)
 2. translate each price source into BLS series ids (config/pce_source_series.py),
    optionally applying BEA's 2026 annual-update method changes
 3. align workbook lines with BEA API lines of Tables 2.4.4U/2.4.5U (by name, in order)
 4. for every most-detailed line: m/m from its CPI/PPI source(s); lines BEA prices
    from other data use the line's own recent trend
 5. aggregate with last month's nominal spending (signed for 'Less:' lines);
    core = all lines outside food & energy
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from config import pce_source_series as SS

WORKBOOK = Path(__file__).resolve().parent.parent / "config" / "Detail_CPI_PCE_mapping.xlsx"


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


# ------------------------------------------------------------------ 1. workbook
def load_mapping(path=WORKBOOK) -> pd.DataFrame:
    raw = pd.read_excel(path, header=None)
    hdr = raw.index[raw.iloc[:, 0].astype(str).str.strip().str.lower() == "item"][0]
    d = raw.iloc[hdr + 1:, :5].copy()
    d.columns = ["line", "component", "bea_code", "source", "seasonal"]
    d = d[pd.to_numeric(d["line"], errors="coerce").notna()].copy()
    d["line"] = d["line"].astype(int)
    for c in ["component", "bea_code", "source", "seasonal"]:
        d[c] = d[c].fillna("").astype(str).str.strip()
    return d.reset_index(drop=True)


# ------------------------------------------------------------------ 2. translation
def _ids(kind, code, seasonal):
    """Candidate series ids (first that BLS returns wins)."""
    if kind == "ppi":
        return code.split("|")
    sa_first = kind == "cpi_sa" or (kind == "cpi" and seasonal.upper() == "SA")
    sa, nsa = "CUSR0000" + code, "CUUR0000" + code
    return [sa, nsa] if sa_first else [nsa, sa]


def resolve(mapping: pd.DataFrame, apply_2026=True) -> pd.DataFrame:
    rows = []
    changes = {_norm(k): v for k, v in SS.BEA_2026_CHANGES.items()}
    for r in mapping.itertuples():
        terms = SS.SOURCE_SERIES.get(r.source)
        kind = "trend"
        if terms:
            kinds = {t[0].split("_")[0] for t in terms}
            kind = kinds.pop() if len(kinds) == 1 else "mixed"
        out = {"line": r.line, "kind": kind, "method": "BEA workbook",
               "terms": [(_ids(k, c, r.seasonal), w) for k, c, w in (terms or [])],
               "new_terms": None, "start": None, "note": "",
               "bea_sa": "by bea" in r.seasonal.lower()}
        if not terms and r.source:
            out["note"] = "BEA uses non-CPI/PPI data; line trend used"
        ch = changes.get(_norm(r.component))
        if apply_2026 and ch:
            new = [(_ids(k, c, r.seasonal), w) for k, c, w in ch["series"]]
            out.update(method="BEA 2026 update", note=ch["note"])
            if ch.get("start"):
                out.update(new_terms=new, start=pd.Timestamp(ch["start"]), kind=ch["kind"])
            else:
                out.update(terms=new, kind=ch["kind"])
        rows.append(out)
    return mapping.merge(pd.DataFrame(rows), on="line")


def series_needed(resolved: pd.DataFrame) -> list[str]:
    ids = []
    for col in ("terms", "new_terms"):
        for terms in resolved[col].dropna():
            for cands, _ in terms:
                ids += cands
    return list(dict.fromkeys(ids))


# ------------------------------------------------------------------ 3. align with BEA lines
def align(mapping: pd.DataFrame, pce_meta: pd.DataFrame, prefix="U:") -> dict:
    """workbook line -> dataset key, matching names in order (BEA renumbers lines)."""
    sub = pce_meta[pce_meta.index.str.startswith(prefix)]
    keys, names = list(sub.index), [_norm(n) for n in sub["name"]]
    out, j = {}, 0
    for r in mapping.itertuples():
        t = _norm(r.component)
        for k in range(j, min(j + 25, len(keys))):
            if names[k] == t:
                out[r.line] = keys[k]
                j = k + 1
                break
    return out


# ------------------------------------------------------------------ 4. inputs
def seasonal_adjust(m: pd.Series, years=5) -> pd.Series:
    """Remove the average same-calendar-month excess over the prior `years` years
    (a simple stand-in for BEA's own seasonal adjustment of NSA PPIs)."""
    same = pd.concat([m.shift(12 * k) for k in range(1, years + 1)], axis=1).mean(axis=1)
    base = m.shift(1).rolling(12 * years, min_periods=24).mean()
    return m - (same - base).fillna(0)


def build_inputs(resolved, levels: pd.DataFrame, sa_adjust=True, overrides=None, target=None):
    """Returns (M: month x line m/m from sources, used: line -> ids used, missing ids)."""
    mom = levels.pct_change(fill_method=None) * 100
    overrides = overrides or {}
    used, missing, cols = {}, set(), {}

    def comb(terms, bea_sa):
        acc, wsum, ids = None, None, []
        for cands, w in terms:
            sid = next((c for c in cands if c in mom.columns and mom[c].notna().sum() > 12), None)
            if sid is None:
                missing.update(cands[:1])
                continue
            m = mom[sid].copy()
            if sa_adjust and bea_sa and not sid.startswith("CUSR"):
                m = seasonal_adjust(m)
            if target is not None and sid in overrides and pd.notna(overrides[sid]):
                m.loc[target] = float(overrides[sid])
            ids.append(sid)
            valid = m.notna().astype(float) * w
            acc = m.fillna(0) * w if acc is None else acc + m.fillna(0) * w
            wsum = valid if wsum is None else wsum + valid
        if acc is None:
            return None, ids
        return acc / wsum.replace(0, np.nan), ids

    for r in resolved.itertuples():
        if r.kind == "trend" or not r.terms and not r.new_terms:
            continue
        s, ids = comb(r.terms, r.bea_sa) if r.terms else (None, [])
        if r.new_terms:
            s2, ids2 = comb(r.new_terms, r.bea_sa)
            if s2 is not None:
                s = s2 if s is None else s.where(s.index < r.start, s2)
                ids = ids + ids2
        if s is not None:
            cols[r.line] = s
            used[r.line] = ids
    M = pd.DataFrame(cols)
    return M, used, sorted(missing)


# ------------------------------------------------------------------ 5. aggregate
def leaf_table(resolved, pce_meta, keymap):
    """Most-detailed lines with their dataset key, sign and food/energy flag."""
    rows = []
    for r in resolved.itertuples():
        k = keymap.get(r.line)
        if k is None or not bool(pce_meta.loc[k].get("is_leaf", False)):
            continue
        rows.append({"line": r.line, "key": k, "component": r.component,
                     "sign": int(pce_meta.loc[k].get("sign", 1) or 1),
                     "fe": pce_meta.loc[k].get("fe", "") or "",
                     "group": _group(k, pce_meta)})
    return pd.DataFrame(rows)


def _group(key, meta, depth=3):
    """Ancestor at a readable depth (e.g. 'Motor vehicles and parts', 'Health care')."""
    chain = [key]
    while True:
        p = meta.loc[chain[-1]].get("parent")
        if p is None or (isinstance(p, float) and np.isnan(p)):
            break
        chain.append(p)
    chain = chain[::-1]  # root ... key
    k = chain[min(depth, len(chain) - 1)]
    return str(meta.loc[k, "name"])


def run(leaves: pd.DataFrame, resolved, M, actual_line: pd.DataFrame, nominal: pd.DataFrame,
        proxy="trend3", core_cpi: pd.Series | None = None, carry=True):
    """Nowcast every month in M's index. Returns dict of results."""
    idx = M.index.union(actual_line.index)
    lines = leaves["line"].tolist()
    keys = dict(zip(leaves.line, leaves.key))
    kind = resolved.set_index("line")["kind"]
    A = pd.DataFrame({ln: actual_line[keys[ln]] for ln in lines}).reindex(idx)
    if proxy == "last":
        P = A.shift(1).ffill()
    elif proxy == "trend12":
        P = A.rolling(12, min_periods=3).mean().shift(1).ffill()
    elif proxy == "corecpi" and core_cpi is not None:
        P = pd.DataFrame({ln: core_cpi.reindex(idx) for ln in lines})
    else:  # trend3
        P = A.rolling(3, min_periods=1).mean().shift(1).ffill()
    S = M.reindex(index=idx, columns=lines)
    status = pd.DataFrame("data", index=idx, columns=lines)
    for ln in lines:
        if kind.get(ln, "trend") in ("trend", "implicit"):
            S[ln] = np.nan
            status[ln] = "trend"
        elif ln not in M.columns:
            S[ln] = np.nan
            status[ln] = "series missing"
    if carry:
        prev = S.shift(1)
        carried = S.isna() & prev.notna() & (status == "data")
        S = S.where(~carried, prev)
        status = status.mask(carried, "carried")
    fb = S.isna() & (status == "data")
    status = status.mask(fb, "fallback")
    F = S.where(S.notna(), P)

    sign = pd.Series(dict(zip(leaves.line, leaves.sign)))
    W = pd.DataFrame({ln: nominal[keys[ln]] for ln in lines}).reindex(idx).shift(1).ffill() * sign
    is_core = pd.Series(dict(zip(leaves.line, ~leaves.fe.isin(["food", "energy"]))))

    def agg(X, mask):
        w = W.loc[:, mask[mask].index]
        x = X.loc[:, w.columns]
        ok = x.notna() & w.notna()
        return (w * x).where(ok).sum(axis=1) / w.where(ok).sum(axis=1).replace(0, np.nan)

    allm = pd.Series(True, index=is_core.index)
    out = {
        "core": agg(F, is_core), "headline": agg(F, allm),
        "core_replicated": agg(A, is_core), "headline_replicated": agg(A, allm),
        "values": F, "status": status, "weights": W,
        "contrib_core": W.loc[:, is_core[is_core].index].mul(F.loc[:, is_core[is_core].index])
            .div(W.loc[:, is_core[is_core].index].sum(axis=1), axis=0),
    }
    return out


# ------------------------------------------------------------------ demo support
def synthetic(mapping, resolved, levels, seed=4):
    """Demo-only PCE detail consistent with the workbook: leaves = priced lines."""
    rng = np.random.default_rng(seed)
    M, _, _ = build_inputs(resolved, levels, sa_adjust=False)
    lines = mapping[(mapping.source != "") & ~mapping.component.str.lower().str.startswith("less")].line.tolist()
    idx = levels.index
    act, nom = {}, {}
    for ln in lines:
        base = M[ln] if ln in M.columns else pd.Series(rng.normal(0.25, 0.3, len(idx)), index=idx)
        a = base.fillna(0.2) + rng.normal(0, 0.05, len(idx))
        act[ln] = a
        nom[ln] = pd.Series(rng.lognormal(0, 1) * np.cumprod(1 + a / 100 + 0.002), index=idx)
    keys = {ln: f"U:L{ln:03d}" for ln in lines}
    actual_line = pd.DataFrame({keys[l]: act[l] for l in lines}).iloc[:-1]  # PCE one month behind
    nominal = pd.DataFrame({keys[l]: nom[l] for l in lines})
    fe = {ln: ("food" if 71 <= ln <= 101 else "energy" if ln in range(111, 118) or ln in range(167, 170) else "")
          for ln in lines}
    leaves = pd.DataFrame({"line": lines, "key": [keys[l] for l in lines],
                           "component": mapping.set_index("line").loc[lines, "component"].values,
                           "sign": 1, "fe": [fe[l] for l in lines], "group": "Demo"})
    return leaves, actual_line, nominal
