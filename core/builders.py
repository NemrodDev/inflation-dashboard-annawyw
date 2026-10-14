"""Assemble Dataset objects for CPI, PPI and PCE from live sources."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from config import cpi as CPI, ppi as PPI, pce as PCE
from core import sources as src
from core.analytics import Dataset, ri_weights, nominal_weights, derived_index, bea_tree

CFG_DIR = Path(__file__).resolve().parent.parent / "config"


def _ri_override(path: Path, base: dict) -> dict:
    """Optional CSV override: columns code,relative_importance."""
    if path.exists():
        df = pd.read_csv(path, dtype={0: str})
        code_col, val_col = df.columns[0], df.columns[1]
        base = dict(base)
        base.update({str(c).strip(): float(v) for c, v in zip(df[code_col], df[val_col])})
    return base


# =========================================================================== CPI
def build_cpi(idx: pd.DataFrame, names: dict, notes: list, full_view: list | None,
              diffusion_keys: list) -> Dataset:
    rows = CPI.RELEASE_TABLE + CPI.EXTRA_SERIES
    ri = {c: w for c, _, _, w in rows}
    ri.update({c: w for c, _, w in CPI.AI_ITEMS})
    ri = _ri_override(CFG_DIR / "cpi_relative_importance.csv", ri)
    meta = pd.DataFrame({"name": pd.Series(names)})
    for c, n, _, _ in rows:
        meta.loc[c, "name"] = n
    for c, n, _ in CPI.AI_ITEMS:
        meta.loc[c, "name"] = n
    w = ri_weights(idx, pd.Series(ri), CPI.HEADLINE)

    ds = Dataset(
        name="CPI", idx=idx, meta=meta, weights=w,
        headline=CPI.HEADLINE, core=CPI.CORE, specs=CPI.CONTRIB_SPECS,
        views={"Release summary (Table A style)": [(c, l) for c, _, l, _ in CPI.RELEASE_TABLE]},
        aggregates=CPI.AGGREGATES, diffusion_keys=diffusion_keys,
        heat_center=CPI.HEAT_CENTER, heat_scale=CPI.HEAT_SCALE, notes=notes,
    )
    if full_view:
        ds.views["Full detail (all SA items)"] = full_view
    # derived: supercore = core services less shelter
    sc = derived_index(ds, [(CPI.CORE_SERVICES, 1), (CPI.SHELTER, -1)], "SUPERCORE")
    ds.idx["SUPERCORE"] = sc
    ds.meta.loc["SUPERCORE", "name"] = "Core services ex shelter (supercore)"
    ds.weights["SUPERCORE"] = ds.weights[CPI.CORE_SERVICES] - ds.weights[CPI.SHELTER]
    ds.extras["targets"] = {"Supercore": "SUPERCORE"}
    return ds


def load_cpi_live(start_year: int, end_year: int, bls_key: str | None, email: str | None,
                  full_catalog: bool = True) -> Dataset:
    notes = []
    codes = [c for c, *_ in CPI.RELEASE_TABLE + CPI.EXTRA_SERIES]
    names, full_view, diff_keys = {}, None, list(CPI.DIFFUSION_FALLBACK)
    ai_codes = [c for c, *_ in CPI.AI_ITEMS]
    if full_catalog:
        try:
            cat = src.cpi_catalog(email)
            sa_items = cat[cat.has_sa]
            names = dict(zip(cat.item_code, cat.item_name))
            # extra AI-related items discovered by name (e.g. smartphones)
            phones = cat[cat.item_name.str.contains("martphone", na=False)].item_code.tolist()
            ai_codes += [p for p in phones if p not in ai_codes]
            hier = sa_items[~sa_items.item_code.str.startswith("SA0")
                            | (sa_items.item_code == "SA0")]
            full_view = list(zip(hier.item_code, hier.display_level))
            leaves = sa_items[sa_items.is_leaf & (sa_items.display_level >= 2)
                              & ~sa_items.item_code.str.startswith("SA0")]
            diff_keys = leaves.item_code.tolist()
            codes = list(dict.fromkeys(codes + sa_items.item_code.tolist()))
        except Exception as e:  # noqa: BLE001
            notes.append(f"Full CPI item catalog unavailable ({e}); using the curated item list.")

    sa_ids = [CPI.SA_PREFIX + c for c in codes + ai_codes]
    nsa_ids = [CPI.NSA_PREFIX + c for c in ai_codes]
    raw, missing = src.bls_fetch(sa_ids + nsa_ids, start_year, end_year, bls_key)
    idx = pd.DataFrame(index=raw.index)
    for c in codes:
        sid = CPI.SA_PREFIX + c
        if sid in raw.columns:
            idx[c] = raw[sid]
    for c in ai_codes:  # SA if published, else NSA
        if CPI.SA_PREFIX + c in raw.columns and raw[CPI.SA_PREFIX + c].notna().sum() > 24:
            idx[c] = raw[CPI.SA_PREFIX + c]
        elif CPI.NSA_PREFIX + c in raw.columns:
            idx[c] = raw[CPI.NSA_PREFIX + c]
            notes.append(f"{c}: no SA series published; using NSA.")
    miss_core = [s for s in missing if s.startswith(CPI.SA_PREFIX) and s[len(CPI.SA_PREFIX):] in
                 [r[0] for r in CPI.RELEASE_TABLE]]
    if miss_core:
        notes.append("Not returned by BLS: " + ", ".join(miss_core))
    ds = build_cpi(idx.copy(), names, notes, full_view, diff_keys)
    ds.extras["ai_codes"] = [c for c in ai_codes if c in idx.columns]
    return ds


# =========================================================================== PPI
def _ppi_name(code):
    for c, n, *_ in PPI.RELEASE_TABLE:
        if c == code:
            return n
    return PPI.PCE_INPUTS.get(code, code)


def build_ppi(idx: pd.DataFrame, names: dict, notes: list, diffusion_keys: list) -> Dataset:
    ri = _ri_override(CFG_DIR / "ppi_relative_importance.csv",
                      {c: w for c, _, _, w in PPI.RELEASE_TABLE})
    meta = pd.DataFrame({"name": pd.Series(names, dtype=object)})
    for c in list(idx.columns):
        if c not in meta.index or pd.isna(meta.loc[c, "name"]):
            meta.loc[c, "name"] = _ppi_name(c)
    w = ri_weights(idx, pd.Series(ri), PPI.HEADLINE)
    return Dataset(
        name="PPI", idx=idx, meta=meta, weights=w, headline=PPI.HEADLINE, core=PPI.CORE,
        specs=PPI.CONTRIB_SPECS,
        views={"Final demand (Table A style)": [(c, l) for c, _, l, _ in PPI.RELEASE_TABLE]},
        aggregates=PPI.AGGREGATES, diffusion_keys=diffusion_keys,
        heat_center=PPI.HEAT_CENTER, heat_scale=PPI.HEAT_SCALE, notes=notes,
        extras={"pce_inputs": list(PPI.PCE_INPUTS)},
    )


def load_ppi_live(start_year, end_year, bls_key, email, full_catalog=True) -> Dataset:
    notes = []
    fd = [c for c, *_ in PPI.RELEASE_TABLE]
    names = {}
    diff = []
    if full_catalog:
        try:
            cat = src.ppi_catalog(email)
            com = cat[~cat.group_code.str.startswith(("FD", "ID"))]
            codes = set(com.code)
            # leaves: no other SA code extends this one
            leaves = [c for c in com.code if not any(o != c and o.startswith(c) for o in codes)]
            leaves = leaves[: PPI.DIFFUSION_MAX_SERIES]
            diff = leaves
            names = dict(zip(com.code, com.series_title.str.replace(r"^PPI Commodity data for ", "", regex=True)))
        except Exception as e:  # noqa: BLE001
            notes.append(f"PPI commodity catalog unavailable ({e}); diffusion uses FD-ID components.")
    if not diff:
        diff = [c for c, _, lvl, _ in PPI.RELEASE_TABLE if lvl >= 2]
    ids = [PPI.SA_PREFIX + c for c in fd + diff] + list(PPI.PCE_INPUTS)
    raw, missing = src.bls_fetch(ids, start_year, end_year, bls_key)
    idx = pd.DataFrame(index=raw.index)
    for c in dict.fromkeys(fd + diff):
        if PPI.SA_PREFIX + c in raw.columns:
            idx[c] = raw[PPI.SA_PREFIX + c]
    for c in PPI.PCE_INPUTS:
        if c in raw.columns:
            idx[c] = raw[c]
    miss = [m for m in missing if m[len(PPI.SA_PREFIX):] in fd or m in PPI.PCE_INPUTS]
    if miss:
        notes.append("Not returned by BLS: " + ", ".join(miss))
    return build_ppi(idx, names, notes, [d for d in diff if d in idx.columns])


# =========================================================================== PCE
def find_line(meta: pd.DataFrame, name: str, prefix: str):
    """Locate a BEA line key (within keys starting with prefix) by description."""
    sub = meta[meta.index.str.startswith(prefix)]
    low = sub["name"].str.lower().str.strip()
    t = name.lower().strip()
    for mask in (low == t, low.str.startswith(t), low.str.contains(t, regex=False)):
        hit = sub.index[mask]
        if len(hit):
            return hit[0]
    return None


def build_pce(maj_p, maj_n, maj_meta, det_p, det_n, det_meta, notes) -> Dataset:
    """maj_* = T20804/T20805, det_* = U20404/U20405 (wide frames keyed L###)."""
    pref = lambda df, p: df.add_prefix(p)  # noqa: E731
    idx = pd.concat([pref(maj_p, "T:"), pref(det_p, "U:")], axis=1)
    nom = pd.concat([pref(maj_n, "T:"), pref(det_n, "U:")], axis=1).reindex(idx.index)
    meta = pd.concat([maj_meta.rename(index=lambda k: "T:" + k),
                      det_meta.rename(index=lambda k: "U:" + k)])
    head = find_line(meta, PCE.HEADLINE, "T:")
    core = find_line(meta, PCE.CORE, "T:")
    if head is None or core is None:
        raise src.SourceError("Could not find PCE / core PCE lines in T20804.")
    nom_head = nom[head]
    w = nom.div(nom_head, axis=0).shift(1)

    # map spec names -> keys
    def resolve(specs):
        out = {}
        for tgt, levels in specs.items():
            out[tgt] = {}
            for lvl, items in levels.items():
                res = []
                for s in items:
                    terms = []
                    for nm, sg in s["terms"]:
                        k = find_line(meta, nm, "T:")
                        if k is None:
                            notes.append(f"PCE line not found: '{nm}'")
                            terms = []
                            break
                        terms.append((k, sg))
                    if terms:
                        res.append({"label": s["label"], "terms": terms})
                out[tgt][lvl] = res
        return out

    specs = resolve(PCE.CONTRIB_SPECS)

    # hierarchy for both tables (latest complete nominal row)
    views, det_leaves = {}, []
    meta["level"] = pd.Series(0, index=meta.index, dtype=object)
    meta["is_leaf"] = pd.Series(False, index=meta.index, dtype=object)
    meta["fe"] = pd.Series("", index=meta.index, dtype=object)
    meta["sign"] = pd.Series(1, index=meta.index, dtype=object)
    meta["parent"] = pd.Series(None, index=meta.index, dtype=object)
    for pfx, m_, n_, title in [("T:", maj_meta, maj_n, "Major types (Table 2.8.4)"),
                               ("U:", det_meta, det_n, "Underlying detail (Table 2.4.4U)")]:
        if n_.empty:
            continue
        last = n_.dropna(how="all").iloc[-1]
        names = m_["name"].tolist()
        lv, par, leaf = bea_tree(names, [last.get(k, np.nan) for k in m_.index])
        keys = [pfx + k for k in m_.index]
        views[title] = list(zip(keys, lv))
        meta.loc[keys, "level"] = lv
        meta.loc[keys, "is_leaf"] = leaf
        if pfx == "U:":
            # food/energy flags via ancestors
            anc_names = [n.lower() for n in names]
            fe, sgn = [], []
            for i in range(len(keys)):
                p, flag, sg = i, "", 1
                while p is not None:
                    a = anc_names[p]
                    if a.startswith("less"):
                        sg = -sg
                    if any(a == x.lower() for x in PCE.FOOD_ANCESTORS):
                        flag = "food"
                    if any(a == x.lower() for x in PCE.ENERGY_ANCESTORS):
                        flag = "energy"
                    p = par[p]
                fe.append(flag)
                sgn.append(sg)
            meta.loc[keys, "fe"] = fe
            meta.loc[keys, "sign"] = sgn
            meta.loc[keys, "parent"] = [keys[q] if q is not None else None for q in par]
            det_leaves = [k for k, lf, nm in zip(keys, leaf, names) if lf
                          and not nm.lower().startswith("less")
                          and "nonprofit" not in nm.lower()]

    aggs = [find_line(meta, n, "T:") for n in PCE.AGGREGATE_NAMES]
    aggs = [a for a in aggs if a is not None]
    ds = Dataset(name="PCE", idx=idx, meta=meta, weights=w, headline=head, core=core,
                 specs=specs, views=views, aggregates=aggs,
                 diffusion_keys=det_leaves or [k for k in idx.columns if k.startswith("U:")],
                 heat_center=PCE.HEAT_CENTER, heat_scale=PCE.HEAT_SCALE, notes=notes)
    ds.extras["supercore"] = find_line(meta, PCE.SUPERCORE, "T:")
    ds.extras["goods"] = find_line(meta, "Goods", "T:")
    ds.extras["services"] = find_line(meta, "Services", "T:")
    ds.extras["housing"] = find_line(meta, "Housing", "T:")
    ds.extras["food"] = find_line(meta, "Food", "T:")
    ds.extras["energy"] = find_line(meta, "Energy goods and services", "T:")
    ds.extras["nominal"] = nom
    return ds


def load_pce_live(start_year, end_year, bea_key) -> Dataset:
    if not bea_key:
        raise src.SourceError("BEA_API_KEY is not set.")
    years = list(range(start_year, end_year + 1))
    notes = []
    maj_p, maj_meta = src.bea_table(*PCE.MAJOR_PRICE, years, bea_key)
    maj_n, _ = src.bea_table(*PCE.MAJOR_NOMINAL, years, bea_key)
    try:
        det_p, det_meta = src.bea_table(*PCE.DETAIL_PRICE, years, bea_key)
        det_n, _ = src.bea_table(*PCE.DETAIL_NOMINAL, years, bea_key)
    except Exception as e:  # noqa: BLE001
        notes.append(f"Underlying detail unavailable ({e}); diffusion uses major types.")
        det_p = det_n = pd.DataFrame(index=maj_p.index)
        det_meta = pd.DataFrame(columns=["name"])
    return build_pce(maj_p, maj_n, maj_meta, det_p, det_n, det_meta, notes)


# =========================================================================== nowcast inputs
def load_nowcast_series_live(ids, start_year, end_year, bls_key):
    raw, missing = src.bls_fetch(list(ids), start_year, end_year, bls_key)
    return raw, missing


def demo_nowcast_series(ids, end):
    rng = np.random.default_rng(5)
    idx = pd.date_range("2014-01-01", end, freq="MS")
    data = {}
    for i, sid in enumerate(ids):
        drift = rng.uniform(-0.1, 0.4)
        vol = 1.5 if sid.startswith("PCU523") else rng.uniform(0.1, 0.8)
        m = drift + rng.normal(0, vol, len(idx))
        data[sid] = 100 * np.cumprod(1 + m / 100)
    return pd.DataFrame(data, index=idx), []
