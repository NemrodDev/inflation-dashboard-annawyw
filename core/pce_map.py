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
    rules = {_norm(k): v for k, v in getattr(SS, "NOWCAST_RULES", {}).items()}
    for r in mapping.itertuples():
        terms = SS.SOURCE_SERIES.get(r.source)
        kind = "trend"
        if terms:
            kinds = {t[0].split("_")[0] for t in terms}
            kind = kinds.pop() if len(kinds) == 1 else "mixed"
        out = {"line": r.line, "kind": kind, "method": "BEA workbook",
               "terms": [(_ids(k, c, r.seasonal), w) for k, c, w in (terms or [])],
               "new_terms": None, "start": None, "note": "", "constant": 0.0,
               "lag_w": float(rules.get(_norm(r.component), {}).get("pce_lag_weight", 0.0)),
               "bea_sa": "by bea" in r.seasonal.lower()}
        if not terms and r.source:
            out["note"] = "BEA uses non-CPI/PPI data; line trend used"
        ch = changes.get(_norm(r.component))
        if apply_2026 and ch:
            new = [(_ids(k, c, r.seasonal), w) for k, c, w in ch["series"]]
            out.update(method="BEA 2026 update", note=ch["note"], constant=float(ch.get("constant", 0.0)))
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
def _mnemonic_wb(code: str) -> str:
    """Workbook series code 'E1NDC1' -> 'NDC'."""
    c = str(code).strip().upper()
    return c[2:-1] if len(c) >= 5 and c.startswith("E1") else ""


def _mnemonic_api(code: str) -> str:
    """BEA API series code 'DNDCRG' / 'DNDCRC' / 'DNDCRG3' -> 'NDC'."""
    c = str(code).strip().upper()
    m = re.match(r"^D([A-Z0-9]{3,4}?)R[GCX]\d*$", c)
    return m.group(1) if m else ""


def _clean_name(s) -> str:
    s = re.sub(r"\\\d+\\|\(\d+\)", "", str(s))  # footnote marks like \1\ or (1)
    return _norm(s)


def align(mapping: pd.DataFrame, pce_meta: pd.DataFrame, prefix="U:", report=False):
    """workbook line -> dataset key. BEA renumbers lines and rewords names, so match
    (1) on the series mnemonic shared by both codes (E1MOT1 <-> DMOTRG), then
    (2) on cleaned names in table order, then (3) on close names (difflib >= 0.88)."""
    import difflib
    sub = pce_meta[pce_meta.index.str.startswith(prefix)]
    keys = list(sub.index)
    names = [_clean_name(n) for n in sub["name"]]
    codes = sub["bea_code"] if "bea_code" in sub.columns else pd.Series("", index=sub.index)
    by_mn = {}
    for k, c in codes.items():
        mn = _mnemonic_api(c)
        if mn and mn not in by_mn:
            by_mn[mn] = k
    out, how, taken = {}, {}, set()
    for r in mapping.itertuples():  # (1) mnemonic
        k = by_mn.get(_mnemonic_wb(r.bea_code))
        if k and k not in taken:
            out[r.line], how[r.line] = k, "code"
            taken.add(k)
    pos = {k: i for i, k in enumerate(keys)}
    j = 0
    for r in mapping.itertuples():  # (2) exact cleaned name, in order
        if r.line in out:
            j = pos[out[r.line]] + 1
            continue
        t = _clean_name(r.component)
        for i in range(j, min(j + 40, len(keys))):
            if keys[i] not in taken and names[i] == t:
                out[r.line], how[r.line] = keys[i], "name"
                taken.add(keys[i])
                j = i + 1
                break
    free = [i for i, k in enumerate(keys) if k not in taken]
    for r in mapping.itertuples():  # (3) close name
        if r.line in out or not free:
            continue
        t = _clean_name(r.component)
        best, score = None, 0.0
        for i in free:
            sc = difflib.SequenceMatcher(None, t, names[i]).ratio()
            if sc > score:
                best, score = i, sc
        if best is not None and score >= 0.88:
            out[r.line], how[r.line] = keys[best], f"similar name ({score:.2f})"
            taken.add(keys[best])
            free.remove(best)
    return (out, how) if report else out


# ------------------------------------------------------------------ 4. inputs
def seasonal_adjust(m: pd.Series, years=5) -> pd.Series:
    """Remove the average same-calendar-month excess over the prior `years` years
    (a simple stand-in for BEA's own seasonal adjustment of NSA PPIs)."""
    same = pd.concat([m.shift(12 * k) for k in range(1, years + 1)], axis=1).mean(axis=1)
    base = m.shift(1).rolling(12 * years, min_periods=24).mean()
    return m - (same - base).fillna(0)


def is_sa_id(sid: str) -> bool:
    """BLS ids that are already seasonally adjusted: CPI CUSR/CUSS..., PPI WPS... (PCU/WPU are NSA)."""
    return sid.startswith(("CUSR", "CUSS", "WPS"))


ADJ_LABEL = {"sa": "SA", "nsa": "NSA", "nsa_sa": "NSA → SA here"}


def build_inputs(resolved, levels: pd.DataFrame, sa_adjust=True, overrides=None, target=None):
    """Returns (M: month x line m/m from sources, used: line -> ids used, missing ids).
    build_inputs.info afterwards maps each id used -> {"adj": "SA" | "NSA" | "NSA → SA here",
    "mm": the m/m that went into the nowcast for `target` (after any seasonal adjustment)}."""
    mom = levels.pct_change(fill_method=None) * 100
    overrides = overrides or {}
    used, missing, cols = {}, set(), {}
    info = {}

    def comb(terms, bea_sa):
        acc, wsum, ids = None, None, []
        for cands, w in terms:
            sid = next((c for c in cands if c in mom.columns and mom[c].notna().sum() > 12), None)
            if sid is None:
                missing.update(cands[:1])
                continue
            m = mom[sid].copy()
            adj = "sa" if is_sa_id(sid) else "nsa"
            if sa_adjust and bea_sa and not is_sa_id(sid):
                m = seasonal_adjust(m)
                adj = "nsa_sa"
            prev = info.get(sid)
            info[sid] = {"adj": ADJ_LABEL[adj] if not prev or prev["adj"] == ADJ_LABEL[adj] else "mixed",
                         "mm": m.get(target, np.nan) if target is not None else np.nan}
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
            const = float(getattr(r, "constant", 0.0) or 0.0) * 100   # fraction -> percentage points
            if const:
                s = s + const if r.start is None or pd.isna(r.start) else s.where(s.index < r.start, s + const)
            cols[r.line] = s
            used[r.line] = ids
    M = pd.DataFrame(cols)
    build_inputs.info = info
    return M, used, sorted(missing)


# ------------------------------------------------------------------ 5. aggregate
def leaf_table(resolved, pce_meta, keymap, prefix="U:"):
    """Every most-detailed line of BEA's API table (so weights always cover all of PCE).
    Lines matched to the workbook carry its line number and price source; API lines with
    no workbook match get id 1000 + their API line number and use their own trend."""
    rev = {k: ln for ln, k in keymap.items()}
    comp = resolved.set_index("line")["component"]
    sub = pce_meta[pce_meta.index.str.startswith(prefix)]
    rows = []
    for k, r in sub.iterrows():
        if not bool(r.get("is_leaf", False)):
            continue
        ln = rev.get(k)
        in_wb = ln is not None
        if not in_wb:
            ln = 1000 + int(r.get("line", 0) or 0)
        rows.append({"line": ln, "key": k,
                     "component": comp.get(ln, r["name"]) if in_wb else str(r["name"]),
                     "in_workbook": in_wb,
                     "sign": int(r.get("sign", 1) or 1),
                     "fe": r.get("fe", "") or "",
                     "group": _group(k, pce_meta)})
    return pd.DataFrame(rows)


# Major PCE categories (Table 2.8.4 level) used to label workbook lines
MAJOR_GROUPS = [
    "Motor vehicles and parts", "Furnishings and durable household equipment",
    "Recreational goods and vehicles", "Other durable goods",
    "Food and beverages purchased for off-premises consumption", "Clothing and footwear",
    "Gasoline and other energy goods", "Other nondurable goods", "Housing and utilities",
    "Health care", "Transportation services", "Recreation services",
    "Food services and accommodations", "Financial services and insurance", "Other services",
    "Net foreign travel", "Final consumption expenditures of nonprofit institutions serving households",
]


def leaves_from_workbook(resolved, pce_meta, keymap):
    """Building blocks = the workbook lines that have a price source in column D
    (BEA's own deflation level). BEA's API supplies only each line's spending weight
    and published price. Returns (leaves, unmatched priced lines)."""
    mp = resolved.sort_values("line").reset_index(drop=True)
    names = mp["component"].str.strip()
    low = names.str.lower()

    def span(start, end):
        a = mp.index[names == start]
        b = mp.index[names == end]
        if not len(a) or not len(b):
            return set()
        return set(mp.loc[a[0]:b[0] - 1, "line"])

    food = span("Food and beverages purchased for off-premises consumption", "Clothing and footwear")
    energy = (span("Gasoline and other energy goods", "Other nondurable goods")
              | span("Electricity and gas", "Health care"))
    majors = [g.lower() for g in MAJOR_GROUPS]
    rows, unmatched = [], []
    group, neg_block = "", False
    for i, r in mp.iterrows():
        nm, lw = names[i], low[i]
        # exact names only: "Clothing and footwear services" or "Recreation services, gross
        # output" must not start a new category (NPISH carries a suffix, so prefix-match it)
        hit = next((MAJOR_GROUPS[j] for j, g in enumerate(majors)
                    if lw == g or (g.startswith("final consumption") and lw.startswith(g))), None)
        if hit:
            group = hit
        priced = r["source"] != ""
        if not priced:
            # a 'Less:' header with no source makes the priced lines under it negative
            neg_block = lw.startswith("less")
            continue
        sign = -1 if (lw.startswith("less") or neg_block) else 1
        k = keymap.get(r["line"])
        if k is None:
            unmatched.append(r["line"])
            continue
        rows.append({"line": r["line"], "key": k, "component": nm, "in_workbook": True,
                     "sign": sign,
                     "fe": "food" if r["line"] in food else "energy" if r["line"] in energy else "",
                     "group": group or "Other"})
    return pd.DataFrame(rows), unmatched


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
        proxy="trend3", core_cpi: pd.Series | None = None, carry=True, model_inputs: dict | None = None):
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
        if model_inputs and ln in model_inputs:          # e.g. portfolio mgmt: equities − employment
            S[ln] = model_inputs[ln].reindex(idx)
            status[ln] = "model"
            continue
        if kind.get(ln, "trend") in ("trend", "implicit"):
            S[ln] = np.nan
            status[ln] = "trend"
        elif ln not in M.columns:
            S[ln] = np.nan
            status[ln] = "series missing"
    status = status.mask((status == "model") & S.isna(), "trend")   # model has no value -> stand-in
    if carry:
        prev = S.shift(1)
        carried = S.isna() & prev.notna() & (status == "data")
        S = S.where(~carried, prev)
        status = status.mask(carried, "carried")
    fb = S.isna() & (status == "data")
    status = status.mask(fb, "fallback")
    F = S.where(S.notna(), P)
    # nowcast rules: blend the source with the line's own published PCE m/m for the previous month
    lag_w = resolved.set_index("line")["lag_w"] if "lag_w" in resolved else pd.Series(dtype=float)
    lag_prev = {}
    for ln in lines:
        w = float(lag_w.get(ln, 0) or 0)
        if w and kind.get(ln, "trend") not in ("trend", "implicit"):
            prev = A[ln].shift(1).fillna(P[ln])
            ok = status[ln].isin(["data", "carried"])
            F[ln] = F[ln].where(~ok, w * prev + (1 - w) * F[ln])
            lag_prev[ln] = (w, prev)

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
        "values": F, "status": status, "weights": W, "lag_prev": lag_prev,
        "contrib_core": W.loc[:, is_core[is_core].index].mul(F.loc[:, is_core[is_core].index])
            .div(W.loc[:, is_core[is_core].index].sum(axis=1), axis=0),
        "actual": A, "is_core": is_core,
    }
    cl = is_core[is_core].index
    wc = W.loc[:, cl]
    # each core line's share of the nowcast error: weight share x (nowcast input - BEA's actual)
    out["error_core"] = wc.mul(F.loc[:, cl] - A.loc[:, cl]).div(wc.sum(axis=1), axis=0)
    return out


def error_table(res, leaves, resolved, used, month, window_months=None, n=15):
    """Core lines ranked by how much of the nowcast's core error they explain.
    month: the month to explain; window_months: also average over this many months."""
    E = res["error_core"]
    if month not in E.index:
        return pd.DataFrame()
    e = E.loc[month].dropna()
    info = leaves.set_index("line")
    st_ = res["status"].loc[month]
    w = res["weights"].loc[month, e.index]
    df = pd.DataFrame({
        "PCE component": info.loc[e.index, "component"],
        "Category": info.loc[e.index, "group"],
        "Input": st_.reindex(e.index),
        "Series used": [", ".join(used.get(l, [])) or "line trend" for l in e.index],
        "Core weight %": w / w.sum() * 100,
        "Nowcast m/m %": res["values"].loc[month, e.index],
        "Actual m/m %": res["actual"].loc[month, e.index],
        "Error (bp of core)": e * 100,
    })
    df["Gap (pp)"] = df["Nowcast m/m %"] - df["Actual m/m %"]
    if window_months:
        win = E.dropna(how="all").loc[:month].iloc[-window_months:]
        df[f"Avg error {window_months}m (bp)"] = win.mean().reindex(e.index) * 100
        df[f"Avg |error| {window_months}m (bp)"] = win.abs().mean().reindex(e.index) * 100
    df = df.reindex(df["Error (bp of core)"].abs().sort_values(ascending=False).index)
    df.index.name = "Line"
    return df.head(n).reset_index()


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
