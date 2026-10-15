"""CPI/PPI -> PCE nowcast, line by line, on BEA's source-data table (Table 2.4.4U-D)."""
import numpy as np
import pandas as pd
import streamlit as st

from config import pce as PCE_CFG
from config import pce_source_series as SS
from core import analytics as A
from core import charts as C
from core import pce_map as PM
from core import pm_model as PMM
from core import npish_model as NPM
from core import nowcast as N
from tabs import common as U

PROXIES = {"Line's own 3m average (published PCE)": "trend3",
           "Line's last published m/m": "last",
           "Line's own 12m average": "trend12",
           "Core CPI m/m": "corecpi"}


def _yoy_estimate(index: pd.Series, nc: pd.Series, target) -> tuple[float, float]:
    """Nowcast y/y for `target`: the published index up to the month before, chained forward with the
    nowcast m/m through `target`, over the published level 12 months earlier. Also returns the
    previous month's y/y (published where available) for the change."""
    act = index.dropna()
    lvl = act[act.index < target].copy()
    if lvl.empty:
        return np.nan, np.nan
    for d in nc.index[(nc.index > lvl.index.max()) & (nc.index <= target)]:
        if pd.notna(nc[d]):
            lvl.loc[d] = lvl.iloc[-1] * (1 + nc[d] / 100)
    yy = lambda d: (lvl.get(d, np.nan) / act.get(d - pd.DateOffset(months=12), np.nan) - 1) * 100  # noqa: E731
    return yy(target), yy(target - pd.DateOffset(months=1))


PROXY_TEXT = {"trend3": "3mma of the line's published PCE m/m",
              "last": "line's last published PCE m/m (no 3mma)",
              "trend12": "12-month average of the line's published PCE m/m (no 3mma)",
              "corecpi": "core CPI m/m (no 3mma)"}


def _effective_ids(resolved, used, target) -> dict:
    """Series that actually feed `target`, per series id -> PCE lines. Drops the pre-switch series of
    lines whose source changes at a date (e.g. legal services: CPI before 2024, PPIs after)."""
    rs = resolved.set_index("line")
    out = {}
    for ln, ids in used.items():
        r = rs.loc[ln] if ln in rs.index else None
        if r is not None and isinstance(r["new_terms"], list) and pd.notna(r["start"]):
            new_ids = {c for cands, _ in r["new_terms"] for c in cands}
            ids = [i for i in ids if (i in new_ids) == (target >= r["start"])]
        for sid in ids:
            out.setdefault(sid, []).append(ln)
    return out


def _inputs_table(res, leaves, resolved, used, info, sid_rows, src_text, overrides, target, mm_col, proxy,
                  missing, show_overrides=True):
    """Every input to the target month: each CPI/PPI series, and each PCE line priced by a stand-in."""
    comp = leaves.set_index("line")["component"]
    terms = resolved.set_index("line")
    sid_rows = _effective_ids(resolved, used, target)
    src_text = src_text.copy()
    for ln, r in terms.iterrows():           # 2026 method lines: describe the source actually used
        if r["method"] == "BEA 2026 update" and (pd.isna(r["start"]) or target >= r["start"]):
            src_text[ln] = r["note"]
    st_t = res["status"].loc[target] if target in res["status"].index else pd.Series(dtype=str)
    vals = res["values"].loc[target] if target in res["values"].index else pd.Series(dtype=float)

    # Contributions: line share of last month's nominal PCE (BEA 2.4.5U, as used by the nowcast) x m/m.
    W_t = res["weights"].loc[target] if target in res["weights"].index else pd.Series(dtype=float)
    ok = vals.reindex(W_t.index).notna() & W_t.notna()
    is_core = pd.Series(~leaves["fe"].isin(["food", "energy"]).values, index=leaves["line"]).reindex(W_t.index,
                                                                                                    fill_value=False)
    tot_h, tot_c = W_t[ok].sum(), W_t[ok & is_core].sum()

    def shares(ln):
        if ln not in W_t.index or not ok.get(ln, False) or not tot_h:
            return 0.0, 0.0
        return (W_t[ln] / tot_c if is_core.get(ln, False) and tot_c else 0.0), W_t[ln] / tot_h

    def term_w(ln, sid):
        """Weight of sid in line ln's composite, among the series actually used for the target month."""
        r = terms.loc[ln]
        tl = []
        for col in ("new_terms", "terms"):
            cand = r[col] if isinstance(r[col], list) else []
            if any(sid in c for c, _ in cand):
                tl = cand
                break
        present = {i for i, ls in sid_rows.items() if ln in ls}
        tw = {i: wt for c, wt in tl for i in c if i in present}
        return tw.get(sid, 0.0) / sum(tw.values()) if tw else 1.0

    const_pp = {ln: float(r.get("constant", 0) or 0) * 100 for ln, r in terms.iterrows()
                if pd.isna(r["start"]) or target >= r["start"]}
    # nowcast rules: share w of a line taken from its own previous-month published PCE m/m
    lag = {}
    for ln, (w, prev) in (res.get("lag_prev") or {}).items():
        if st_t.get(ln) in ("data", "carried"):
            lag[ln] = (w, prev.get(target, np.nan))

    def src_part(ln):
        """Weight of the CPI/PPI source in the line (1 unless a nowcast rule blends in last month's PCE)."""
        return 1 - lag[ln][0] if ln in lag else 1.0
    rows = []
    for sid, lns in sid_rows.items():
        lns_in = [ln for ln in lns if ln in comp.index]
        # share of this series in the line's composite (re-scaled if a component series is missing)
        w = term_w(lns_in[0], sid) * src_part(lns_in[0]) * 100 if len(lns_in) == 1 else np.nan
        mm = info.get(sid, {}).get("mm", np.nan)
        adj = info.get(sid, {}).get("adj", "")
        carried = pd.isna(mm) and any(st_t.get(ln) == "carried" for ln in lns_in)
        eff = overrides.get(sid, np.nan)
        eff = mm if pd.isna(eff) else eff
        cc = ch = 0.0
        for ln in lns_in:
            sc, sh = shares(ln)
            if pd.notna(eff):
                x = eff
            else:                                   # carried: back out the source value from the line value
                v = vals.get(ln, np.nan)
                if ln in lag:
                    v = (v - lag[ln][0] * lag[ln][1]) / (1 - lag[ln][0])
                x = v - const_pp.get(ln, 0.0)
            if pd.notna(x):
                f = term_w(ln, sid) * src_part(ln)
                cc, ch = cc + sc * f * x * 100, ch + sh * f * x * 100
        rows.append({
            "Input": sid, "Type": "PPI" if sid.startswith(("PCU", "WP")) else "CPI",
            "PCE line(s)": "; ".join(comp.get(ln, f"line {ln}") for ln in (lns_in or lns)),
            "BEA source": src_text.get((lns_in or lns)[0], ""),
            "Weight in line %": w, mm_col: mm,
            "Contrib. core (bp)": cc if lns_in else np.nan, "Contrib. headline (bp)": ch if lns_in else np.nan,
            "Adjustment": (adj or "–") + " · monthly, no 3mma"
                          + (" · not out yet: last month carried" if carried else ""),
            "Override m/m": overrides.get(sid, np.nan)})
    for ln, r in terms.iterrows():           # constants added to a line's monthly change (BEA 2026 software)
        c = float(r.get("constant", 0) or 0)
        if c and ln in comp.index and (pd.isna(r["start"]) or target >= r["start"]):
            rows.append({"Input": "Constant", "Type": "Adj.", "PCE line(s)": comp[ln], "BEA source": r["note"],
                         "Weight in line %": np.nan, mm_col: c * 100,
                         "Contrib. core (bp)": shares(ln)[0] * c * 1e4 * src_part(ln),
                         "Contrib. headline (bp)": shares(ln)[1] * c * 1e4 * src_part(ln),
                         "Adjustment": f"{c:+.6f} (fraction) added to the composite's m/m every month",
                         "Override m/m": np.nan})
    for ln, (w, pv) in lag.items():          # the previous-month PCE part of blended lines
        if ln not in comp.index:
            continue
        sc, sh = shares(ln)
        rows.append({"Input": "PCE prior month", "Type": "PCE", "PCE line(s)": comp[ln],
                     "BEA source": f"Nowcast rule: {w:.0%} the line's own published PCE m/m for "
                                   f"{target - pd.DateOffset(months=1):%b %Y} + {1 - w:.0%} its CPI/PPI source",
                     "Weight in line %": w * 100, mm_col: pv,
                     "Contrib. core (bp)": sc * w * pv * 100, "Contrib. headline (bp)": sh * w * pv * 100,
                     "Adjustment": "SA (BEA) · previous month's published PCE m/m (no 3mma)",
                     "Override m/m": np.nan})
    for sid in missing:
        rows.append({"Input": sid, "Type": "PPI" if sid.startswith(("PCU", "WP")) else "CPI",
                     "PCE line(s)": "", "BEA source": "", "Weight in line %": np.nan, mm_col: np.nan,
                     "Contrib. core (bp)": np.nan, "Contrib. headline (bp)": np.nan,
                     "Adjustment": "not returned by BLS: line uses its stand-in below",
                     "Override m/m": np.nan})
    stand_in = {"trend": "no CPI/PPI source", "series missing": "series not returned",
                "fallback": "series not out yet"}
    model_text = res.get("model_text") or {}
    for ln in leaves["line"]:
        stt = st_t.get(ln)
        if stt == "model":
            lab, txt = model_text.get(ln, ("Model", "model estimate"))
            rows.append({"Input": lab, "Type": "Model", "PCE line(s)": comp.get(ln, f"line {ln}"),
                         "BEA source": src_text.get(ln, ""), "Weight in line %": 100.0,
                         mm_col: vals.get(ln, np.nan),
                         "Contrib. core (bp)": shares(ln)[0] * vals.get(ln, np.nan) * 100,
                         "Contrib. headline (bp)": shares(ln)[1] * vals.get(ln, np.nan) * 100,
                         "Adjustment": f"SA · monthly, no 3mma · {txt}", "Override m/m": np.nan})
            continue
        if stt not in stand_in:
            continue
        kind = terms["kind"].get(ln, "trend") if ln in terms.index else "trend"
        why = "BEA 2026: implicit price" if kind == "implicit" else stand_in[stt]
        rows.append({"Input": "PCE line stand-in", "Type": "PCE",
                     "PCE line(s)": comp.get(ln, f"line {ln}"), "BEA source": src_text.get(ln, ""),
                     "Weight in line %": 100.0, mm_col: vals.get(ln, np.nan),
                     "Contrib. core (bp)": shares(ln)[0] * vals.get(ln, np.nan) * 100,
                     "Contrib. headline (bp)": shares(ln)[1] * vals.get(ln, np.nan) * 100,
                     "Adjustment": f"SA (BEA) · {PROXY_TEXT.get(proxy, proxy)} ({why})",
                     "Override m/m": np.nan})
    t = pd.DataFrame(rows)
    if t.empty:
        st.info("No inputs.")
        return
    view = st.radio("Rows", ["By input", "By PCE line"], index=1, horizontal=True, key="nc_rows_view",
                    help="By PCE line: every input feeding a line (its series, any constant, or its stand-in) "
                         "is combined into one row per unique PCE line item.")
    if view == "By PCE line":
        lrows = []
        for ln in leaves["line"]:
            ids = [sid for sid, lns in sid_rows.items() if ln in lns]
            stt, v = st_t.get(ln), vals.get(ln, np.nan)
            if not ids and stt not in stand_in and pd.isna(v):
                continue
            sc, sh = shares(ln)
            if stt == "model":
                mt = model_text.get(ln, ("Model", "model estimate"))
                inputs, types = mt[0], "Model"
                adj = f"SA · monthly, no 3mma · {mt[1]}"
            elif stt in stand_in or not ids:
                kind = terms["kind"].get(ln, "trend") if ln in terms.index else "trend"
                why = "BEA 2026: implicit price" if kind == "implicit" else stand_in.get(stt, "no CPI/PPI source")
                inputs, types = "PCE line stand-in", "PCE"
                adj = f"SA (BEA) · {PROXY_TEXT.get(proxy, proxy)} ({why})"
            else:
                inputs = ", ".join(ids) + (" + constant" if const_pp.get(ln) else "") + \
                    (f" + prior-month PCE ({lag[ln][0]:.0%})" if ln in lag else "")
                types = "/".join(dict.fromkeys(["PPI" if i.startswith(("PCU", "WP")) else "CPI" for i in ids]
                                               + (["PCE"] if ln in lag else [])))
                labs = list(dict.fromkeys(info.get(i, {}).get("adj", "–") for i in ids))
                adj = "; ".join(labs) + " · monthly, no 3mma" + \
                      (" · not out yet: last month carried" if stt == "carried" else "") + \
                      (f"; {lag[ln][0]:.0%} previous month's published PCE m/m" if ln in lag else "")
            ovs = [f"{i} {overrides[i]:.3f}" for i in ids if pd.notna(overrides.get(i, np.nan))]
            lrows.append({"PCE line": comp.get(ln, f"line {ln}"), "BEA source": src_text.get(ln, ""),
                          "Inputs": inputs, "Type": types, "Share of PCE %": sh * 100, mm_col: v,
                          "Contrib. core (bp)": sc * v * 100 if pd.notna(v) else np.nan,
                          "Contrib. headline (bp)": sh * v * 100 if pd.notna(v) else np.nan,
                          "Adjustment": adj, "Overrides": ", ".join(ovs)})
        t = pd.DataFrame(lrows)
    t.insert(0, "Line", range(1, len(t) + 1))   # row number; stays with its row when sorting
    def cscale(c):
        """Colour scale for a contribution column: full colour at the 90th percentile of |bp|."""
        a = t[c].abs().dropna()
        return max(float(a.quantile(0.9)) if len(a) else 0.0, 0.05)
    st.caption(f"Heat maps — {mm_col}: centred on {PCE_CFG.HEAT_CENTER:.3f}% m/m (≈2% annualised); "
               "contributions: centred on 0 bp, full colour at the 90th percentile of their size. "
               "Red = adds to inflation / hotter, blue = subtracts / cooler.")
    if view == "By PCE line":
        head = (f"{len(t)} PCE line items for {target:%B %Y}. {mm_col} is the line's nowcast change (its "
                "inputs combined with their weights, plus any constant). Share of PCE % = the line's share of "
                "last month's nominal PCE. Contributions (bp) = share (of core or of total) × m/m;")
    else:
        n_ser, n_pce = int(t["Type"].isin(["CPI", "PPI"]).sum()), int((t["Type"] == "PCE").sum())
        n_adj, n_mod = int((t["Type"] == "Adj.").sum()), int((t["Type"] == "Model").sum())
        head = (f"All {len(t)} inputs for {target:%B %Y}: {n_ser} CPI/PPI series, "
                f"{n_pce} PCE-based inputs (stand-ins and prior-month PCE)" +
                (f", {n_mod} model" if n_mod else "") + (f", {n_adj} constant" if n_adj else "") +
                f". {mm_col} is the change that enters the nowcast. Contributions (bp) = the line's share of "
                "last month's nominal PCE (of core or of total) × the input's weight in the line × its m/m;")
    st.caption(head + f" they add up to {t['Contrib. core (bp)'].sum():.1f} bp core and "
               f"{t['Contrib. headline (bp)'].sum():.1f} bp headline (before any bias correction). "
               "Adjustment: SA = seasonally adjusted by BLS (or BEA for PCE lines); NSA = not seasonally "
               "adjusted, used as published; NSA → SA here = not adjusted by BLS, seasonally adjusted in this "
               "app because BEA marks the line 'SA by BEA'. 3mma = 3-month moving average.")
    if not show_overrides:
        t = t.drop(columns=[c for c in ("Override m/m", "Overrides") if c in t.columns])
    U.sortable_table(t, fmt={"Weight in line %": "{:.1f}", "Share of PCE %": "{:.3f}", mm_col: "{:.3f}",
                             "Override m/m": "{:.3f}", "Contrib. core (bp)": "{:.2f}",
                             "Contrib. headline (bp)": "{:.2f}"},
                     wrap_cols=("PCE line(s)", "PCE line", "BEA source", "Inputs", "Adjustment", "Overrides"),
                     wrap_width=300, max_height=640,
                     heat={mm_col: (PCE_CFG.HEAT_CENTER, PCE_CFG.HEAT_SCALE),
                           "Contrib. core (bp)": (0.0, cscale("Contrib. core (bp)")),
                           "Contrib. headline (bp)": (0.0, cscale("Contrib. headline (bp)"))})


def _pm_panel(pm_lab, preds, bt, err, real, bond_lv, bond_src, spx_me, y, target, emp_id, allow_edit=True):
    """Portfolio management: this month's real / price / nominal, the LUATTRUU entry table, the backtest."""
    t2, t3 = target - pd.DateOffset(months=2), target - pd.DateOffset(months=3)
    if err or preds is None:
        st.warning(f"Model inputs unavailable ({err or 'no data'}); the line uses its 3-month average.")
    else:
        price = preds["handoff"].get(target, np.nan)
        r = real["real"].get(target, np.nan) if real is not None and len(real) else np.nan
        k = st.columns(3)
        k[0].metric(f"Price m/m, {target:%b %Y} (handoff)", f"{price:.3f}%")
        k[1].metric("Real m/m (CES hours EMA)", f"{r:.3f}%" if pd.notna(r) else "–",
                    help="H = CES employment × average weekly hours, NAICS 52394; E = 12-month EMA of H on "
                         "levels (2/13 weight); real = 100 × ln(E_t / E_t-1).")
        k[2].metric("Nominal m/m = real + price", f"{r + price:.3f}%" if pd.notna(r) and pd.notna(price) else "–")
        if real is not None and len(real) and bool(real["H_held"].get(target, False)):
            st.caption(f"CES NAICS 52394 detail for {target:%b %Y} isn't out yet, so hours H are held flat at the "
                       "last published month (handoff rule).")
        src2 = bond_src.get(t2, "missing") if bond_src is not None else "missing"
        spx_ok = spx_me is not None and target in spx_me.index
        st.caption(f"Inputs for {target:%b %Y}: last month's BEA price m/m {y.get(target - pd.DateOffset(months=1), np.nan):.3f} pp; "
                   f"S&P 500 month-end {target:%b} {'%.2f' % spx_me[target] if spx_ok else '(not available)'}; "
                   f"Treasury TR return for {t2:%b %Y} from **{src2}**"
                   + ("" if src2 == "LUATTRUU" else
                      f" (GOVT ETF stands in for LUATTRUU; enter LUATTRUU month-ends for {t3:%b} and {t2:%b} "
                      "below to use the exact index)" if allow_edit else " (standing in for LUATTRUU)") + ".")
    if not allow_edit:
        st.caption("Treasury total return: GOVT (iShares U.S. Treasury Bond ETF, tracks the Bloomberg US Treasury "
                   "Index) month-end adjusted close from Alpha Vantage, standing in for LUATTRUU; a 5-year-yield "
                   "proxy only if GOVT is unavailable.")
    else:
        st.markdown("**Treasury total return.** Order of use: LUATTRUU month-end levels you enter here → GOVT "
                    "(iShares U.S. Treasury Bond ETF, tracks the Bloomberg US Treasury Index) month-end adjusted "
                    "close from Alpha Vantage → a 5-year-yield proxy only if GOVT is unavailable. Optional: add "
                    "LUATTRUU month-ends below (or paste a column from Bloomberg).")
        with st.form("nc_luattruu_form", border=False):
            ed = st.data_editor(bond_lv.assign(month=bond_lv["month"].dt.date), key="nc_luattruu",
                                num_rows="dynamic", hide_index=True, column_config={
                                    "month": st.column_config.DateColumn("Month (any day in the month)",
                                                                         format="MMM YYYY"),
                                    "level": st.column_config.NumberColumn("LUATTRUU month-end", format="%.2f")})
            if st.form_submit_button("Save Treasury levels"):
                PMM.save_bond_levels(ed.dropna())
                st.session_state.pop("nc_luattruu", None)
                st.rerun()
    if bt is not None and len(bt):
        best = bt.sort_values("RMSE (pp)").iloc[0]
        st.caption(f"Backtest vs BEA's published line, last 36 months (one month ahead, using the BEA price "
                   f"for the month before). Lowest error: **{best['Model']}** (RMSE {best['RMSE (pp)']:.2f} pp). "
                   f"In use: **{pm_lab}**. Treasury returns come from GOVT where you haven't entered LUATTRUU, "
                   f"so the handoff backtest is close to, not exactly, the recipe's own inputs. Employment for the simple rules: CES {emp_id}.")
        U.show_df(bt.style.format({"MAE (pp)": "{:.3f}", "RMSE (pp)": "{:.3f}", "Bias (pp)": "{:+.3f}",
                                   "Correlation": "{:.2f}", "Months": "{:.0f}"}), hide_index=True)
        show = pd.DataFrame({lab: preds[c] for lab, c in PMM.MODELS.items() if c in preds})
        show["BEA published"] = y
        show = show.loc[show.index <= target].iloc[-37:]
        U.show(C.lines(show, "Portfolio management & investment advice: price m/m %, models vs BEA", "% m/m",
                       hline=0, dash_cols=[c for c in show.columns if c != "BEA published"]))


def _npish_panel(nb, err, res, leaves, target, _has_core):
    """The two leg equations for the target month, the implied net, and a backtest of the net."""
    if err or not nb:
        st.warning(f"NPISH equations unavailable ({err or 'no data'}); the lines use their stand-ins.")
        return
    g, r = nb["gross"].loc[target], nb["receipts"].loc[target]
    wg, wr = nb["w_gross"].get(target, np.nan), nb["w_receipts"].get(target, np.nan)
    netv = NPM.net(g["pred"], r["pred"], wg, wr)
    lines = nb["gross_lines"] + [nb["receipts_line"]]
    W_t = res["weights"].loc[target] if target in res["weights"].index else pd.Series(dtype=float)
    vals = res["values"].loc[target] if target in res["values"].index else pd.Series(dtype=float)
    is_core = pd.Series(~leaves["fe"].isin(["food", "energy"]).values, index=leaves["line"])
    ok = vals.reindex(W_t.index).notna() & W_t.notna()
    tot_c, tot_h = W_t[ok & is_core.reindex(W_t.index, fill_value=False)].sum(), W_t[ok].sum()
    contrib = (W_t.reindex(lines) * vals.reindex(lines)).sum()
    k = st.columns(4)
    k[0].metric(f"Gross output m/m, {target:%b %Y}", f"{g['pred']:.3f}%")
    k[1].metric("Receipts m/m", f"{r['pred']:.3f}%")
    k[2].metric("Net NPISH m/m", f"{netv:.3f}%", help="(Wgo·gross − Wrc·receipts) / (Wgo − Wrc)")
    k[3].metric("Contribution to core / headline", f"{contrib / tot_c * 100:+.2f} / {contrib / tot_h * 100:+.2f} bp"
                if tot_c and tot_h else "–")

    def leg_line(name, row, regressor):
        if pd.isna(row["a"]):
            return f"**{name}**: {row['mode'] or 'no estimate'}; 6m trailing mean {row['tm6']:.3f}"
        term = lambda c, v: f"{'−' if c < 0 else '+'} {abs(c):.3f} × {v:.3f}"  # noqa: E731
        xs = f" {term(row['c'], row['x'])} ({regressor} m/m)" if pd.notna(row["c"]) else ""
        return (f"**{name}** = {row['a']:.3f} {term(row['b'], row['tm6'])} (6m trailing mean){xs} "
                f"= **{row['pred']:.3f}%** — {row['mode']}")
    st.markdown(leg_line("Gross output", g, f"AHE educ. & health, {NPM.WAGE_ID}") + "  \n" +
                leg_line("Receipts", r, f"hospital PPI SA, {NPM.PPI_ID}") + "  \n" +
                f"**Net** = ({wg:,.0f} × {g['pred']:.3f} − {wr:,.0f} × {r['pred']:.3f}) / ({wg:,.0f} − {wr:,.0f}) "
                f"= **{netv:.3f}%** (weights: last month's nominal spending, $bn annual rate)")
    # backtest of the net, last 36 months, vs each line's 3-month-average stand-in
    idx = nb["gross"].index
    wg_s, wr_s = nb["w_gross"], nb["w_receipts"]
    act = NPM.net(nb["y_gross"], nb["y_receipts"], wg_s, wr_s)
    eq = NPM.net(nb["gross"]["pred"], nb["receipts"]["pred"], wg_s, wr_s)
    base = NPM.net(nb["y_gross"].shift(1).rolling(3, min_periods=1).mean(),
                   nb["y_receipts"].shift(1).rolling(3, min_periods=1).mean(), wg_s, wr_s)
    rows = []
    for lab, p in (("Gross & receipts equations", eq), ("Line stand-ins (3m average)", base)):
        d = pd.DataFrame({"p": p, "y": act}).dropna()
        d = d[d.index < target].iloc[-36:]
        if len(d) >= 6:
            e = d["p"] - d["y"]
            rows.append({"Method": lab, "Months": len(d), "MAE (pp)": e.abs().mean(),
                         "RMSE (pp)": float(np.sqrt((e ** 2).mean())), "Correlation": d["p"].corr(d["y"])})
    if rows:
        st.caption("Backtest of net NPISH m/m against BEA, last 36 months (equations refit each month on earlier "
                   "data only).")
        U.show_df(pd.DataFrame(rows).style.format({"MAE (pp)": "{:.3f}", "RMSE (pp)": "{:.3f}",
                                                   "Correlation": "{:.2f}", "Months": "{:.0f}"}), hide_index=True)
        show = pd.DataFrame({"Equations": eq, "Stand-ins (3m avg)": base, "BEA net NPISH": act})
        show = show.loc[show.index <= target].dropna(subset=["Equations"]).iloc[-37:]
        U.show(C.lines(show, "Net NPISH final consumption: m/m %, nowcast vs BEA", "% m/m", hline=0,
                       dash_cols=["Equations", "Stand-ins (3m avg)"]))


def _num_col():
    try:
        return st.column_config.NumberColumn(format="%.3f", alignment="right")
    except TypeError:  # older Streamlit without 'alignment'
        return st.column_config.NumberColumn(format="%.3f")


@st.cache_data
def _mapping():
    return PM.load_mapping()


@st.cache_data(ttl=6 * 3600, show_spinner="Loading market data from FRED…")
def _fred_daily(series_id, fred_key, _loader):
    return PMM.fred_daily(series_id, _loader, fred_key)


@st.cache_data(ttl=12 * 3600, show_spinner="Loading GOVT (Treasury ETF) from Alpha Vantage…")
def _govt(av_key):
    return PMM.govt_month_end(av_key)


def render(cpi, pce, levels: pd.DataFrame | None, fetch_missing, fred_key=None, fred_loader=None, av_key=None,
           allow_bond_edit=True, allow_overrides=True):
    """Public site switches:
    allow_bond_edit=False: the LUATTRUU levels table is hidden, so visitors can't change the saved Treasury
      levels; GOVT (Alpha Vantage) supplies the Treasury return instead.
    allow_overrides=False: no "Override m/m" box and no override columns in the inputs table."""
    st.header("CPI/PPI → PCE nowcast")
    mapping = _mapping()
    n_priced = (mapping.source != "").sum()
    st.caption(f"Mapping: BEA Table 2.4.4U-D source data (your workbook) — {len(mapping)} PCE lines, "
               f"{n_priced} with a stated price source — plus BEA's 2026 annual-update changes. "
               "Weights are last month's nominal spending by line (BEA Table 2.4.5U).")
    if cpi is None or levels is None or levels.empty:
        st.error("CPI/PPI input series are not loaded.")
        return

    # ---------------------------------------------------------- settings
    c = st.columns(5)
    meth = c[0].selectbox(
        "Methodology", ["BEA 2026 (current)", "Pre-2026 (workbook as published)"], index=0, key="nc_method",
        help="BEA 2026: portfolio mgmt → implicit price (CES quantity); legal services → composite of 5 "
             "PPIs from 2024 (civil negligence 36.8%, legal services 35.0%, wills/estate/probate 17.2%, "
             "real estate 8.6%, labor & employment 2.4%); software → 0.6 CPI software + 0.2 PPI game "
             "software + 0.2 PPI hosting/ASP/IT infrastructure − 0.1087 pp")
    apply26 = meth.startswith("BEA 2026")
    proxy_lab = c[1].selectbox("Lines without CPI/PPI source", list(PROXIES), key="nc_proxy")
    sa_adj = c[2].toggle("Seasonally adjust 'SA by BEA' inputs", True, key="nc_sa",
                         help="BEA seasonally adjusts these NSA PPIs itself; this removes the average "
                              "same-month excess over the past 5 years")
    carry = c[3].toggle("Carry forward missing PPI", True, key="nc_carry")
    bias = c[4].toggle("Bias-correct (12m)", False, key="nc_bias")
    c2 = st.columns(5)
    pm_lab = c2[0].selectbox("Portfolio management (BEA 2026)", list(PMM.MODELS), index=0, key="nc_pm2",
                             disabled=not apply26,
                             help="Handoff price model (default): 0.017752 + 0.785998 × last month's price m/m "
                                  "+ 6.154821 × S&P 500 month-end log return + 5.740161 × Treasury total-return "
                                  "(LUATTRUU) log return two months earlier. Alternatives: the line's 3m average, "
                                  "or S&P 500 − CES employment. Backtest below the inputs table.")
    npish_lab = c2[1].selectbox("NPISH (nonprofits)", ["Gross output & receipts equations", "Line stand-ins"],
                                index=0, key="nc_npish",
                                help="Equations (default): gross output = OLS on its 6-month trailing mean + AHE "
                                     "education & health (CES6500000003); receipts = OLS on its 6-month trailing "
                                     "mean + hospital PPI (PCU622---622---, seasonally adjusted), both refit every "
                                     "month; net = (Wgo·gross − Wrc·receipts)/(Wgo − Wrc). Stand-ins: each line's "
                                     "own setting under 'Lines without CPI/PPI source'.")

    resolved = PM.resolve(mapping, apply26)
    target = A.mom(cpi.idx[cpi.core]).dropna().index.max()

    # ---------------------------------------------------------- PCE detail from BEA
    if pce is None or not any(k.startswith("U:") for k in pce.idx.columns):
        st.error("BEA underlying-detail PCE data (Tables 2.4.4U/2.4.5U) is required for the nowcast.")
        return
    keymap, match_how = PM.align(mapping, pce.meta, report=True)
    leaves, wb_unmatched = PM.leaves_from_workbook(resolved, pce.meta, keymap)
    ukeys = [k for k in pce.idx.columns if k.startswith("U:")]
    actual_line = A.mom(pce.idx[ukeys])
    nominal = pce.extras["nominal"].reindex(columns=ukeys)
    no_data = leaves[~leaves.key.isin([k for k in ukeys if nominal[k].notna().any()])]
    if len(no_data):
        wb_unmatched = list(wb_unmatched) + no_data.line.tolist()
        leaves = leaves[~leaves.line.isin(no_data.line)]
    actual_core, actual_head = A.mom(pce.idx[pce.core]), A.mom(pce.idx[pce.headline])
    unaligned = mapping[~mapping.line.isin(keymap)]
    unpriced = unaligned[unaligned.source != ""]
    st.caption(f"Building blocks: the {len(leaves)} workbook lines with a price source in column D "
               f"(BEA's deflation level); BEA's API supplies their spending weights and published prices.")
    if len(unpriced):
        st.caption(f"⚠️ {len(unpriced)} priced workbook lines not found in BEA's API table and left out "
                   f"(see Diagnostics).")
    if leaves.empty:
        st.error("Could not match the workbook to BEA's detail lines.")
        return

    # ---------------------------------------------------------- overrides
    M0, used, missing = PM.build_inputs(resolved, levels, sa_adj, target=target)
    info = getattr(PM.build_inputs, "info", {})
    sid_rows = {}
    for ln, ids in used.items():
        for sid in ids:
            sid_rows.setdefault(sid, []).append(ln)
    src_text = mapping.set_index("line")["source"]
    mm_col = f"m/m {target:%b %y}"
    overrides = {}
    with st.expander("Inputs to the nowcast, with overrides for the target month "
                     "(e.g. PPI consensus before the PPI release)" if allow_overrides else
                     "Inputs to the nowcast", expanded=False):
        table_slot = st.container()
        if allow_overrides:
            st.markdown("**Override m/m** — type a value next to a CPI/PPI series to replace its "
                        f"{target:%b %Y} change")
            ov_in = pd.DataFrame({"Series": list(_effective_ids(resolved, used, target)), "Override m/m": np.nan})
            ov = st.data_editor(ov_in, key="nc_ov", hide_index=True, disabled=["Series"],
                                column_config={"Override m/m": _num_col()})
            overrides = dict(zip(ov["Series"], ov["Override m/m"])) if len(ov) else {}
    M, used, missing = PM.build_inputs(resolved, levels, sa_adj, overrides, target)
    info = getattr(PM.build_inputs, "info", info)

    core_cpi = A.mom(cpi.idx[cpi.core])
    # ---------------------------------------------------------- portfolio management model (BEA 2026)
    pm_rows = resolved[resolved.component.str.strip().str.lower()
                       == "portfolio management and investment advice services"]
    pm_ln = pm_rows.line.iloc[0] if len(pm_rows) else None
    pm_key = leaves.set_index("line")["key"].get(pm_ln) if pm_ln is not None else None
    pm_preds, pm_bt, pm_err, model_inputs, emp_id = None, None, "", {}, None
    bond_lv, bond_src, spx_me, pm_real, govt_err = PMM.load_bond_levels(), None, None, None, ""
    code = PMM.MODELS[pm_lab]
    if apply26 and pm_key is not None:
        try:
            spx_me = PMM.month_end(_fred_daily(PMM.EQUITY_FRED, fred_key, fred_loader))
            try:
                yld = _fred_daily(PMM.YIELD_FRED, fred_key, fred_loader)
            except Exception:  # noqa: BLE001
                yld = None
            govt, govt_err = None, ""
            if av_key:
                try:
                    govt = _govt(av_key)
                except Exception as e:  # noqa: BLE001
                    govt_err = str(e)
            else:
                govt_err = "no ALPHAVANTAGE_API_KEY"
            bond_r, bond_src = PMM.bond_returns(bond_lv, yld, govt)
            emp_lvl, emp_id = PMM.employment(levels)
            pm_preds = PMM.candidates(actual_line[pm_key].dropna(), spx_me, emp_lvl, bond_r, target)
            pm_bt = PMM.backtest(actual_line[pm_key], pm_preds, 36)
            if PMM.EMP_ID in levels and PMM.HOURS_ID in levels:
                pm_real = PMM.real_growth(levels[PMM.EMP_ID], levels[PMM.HOURS_ID], target)
        except Exception as e:  # noqa: BLE001
            pm_err = str(e)
        if pm_preds is not None and code != "trend3":
            model_inputs = {pm_ln: pm_preds[code]}
    # ---------------------------------------------------------- NPISH gross output & receipts equations
    npish, npish_err = None, ""
    if npish_lab.startswith("Gross"):
        try:
            npish = NPM.build(leaves, actual_line, nominal, levels, PM.seasonal_adjust, target)
            if npish is None:
                npish_err = "NPISH lines not found in BEA's table"
        except Exception as e:  # noqa: BLE001
            npish_err = str(e)
    if npish:
        model_inputs.update(npish["inputs"])
    res = PM.run(leaves, resolved, M, actual_line, nominal, PROXIES[proxy_lab], core_cpi, carry,
                 model_inputs=model_inputs)
    model_text = {}
    if npish:
        gm, rm = npish["gross"].loc[target, "mode"], npish["receipts"].loc[target, "mode"]
        for ln in npish["gross_lines"]:
            model_text[ln] = ("Model: NPISH gross-output equation",
                              f"a + b × 6m trailing mean of BEA gross output + c × AHE education & health "
                              f"m/m ({NPM.WAGE_ID}); {gm}; same value for all 11 gross-output lines")
        model_text[npish["receipts_line"]] = ("Model: NPISH receipts equation",
                                              f"a + b × 6m trailing mean of BEA receipts + c × hospital PPI m/m "
                                              f"({NPM.PPI_ID}, SA here); {rm}")
    res["model_text"] = model_text
    if pm_ln in model_inputs:
        b_t2 = target - pd.DateOffset(months=2)
        res["model_text"][pm_ln] = (
            f"Model: {pm_lab}",
            "0.017752 + 0.785998 × last month's published price m/m + 6.154821 × ln(SPX month-end ratio) "
            f"+ 5.740161 × Treasury TR log return for {b_t2:%b %Y} "
            f"({bond_src.get(b_t2, 'missing') if bond_src is not None else 'missing'})"
            if code == "handoff" else
            f"S&P 500 month-end % change{' (lagged 1m)' if code == 'eq1' else ''} − CES employment "
            f"% change ({emp_id})")
    core_nc, head_nc = res["core"], res["headline"]
    with table_slot:
        _inputs_table(res, leaves, resolved, used, info, sid_rows, src_text, overrides, target, mm_col,
                      PROXIES[proxy_lab], missing, show_overrides=allow_overrides)
    if apply26 and pm_key is not None:
        with st.expander("Portfolio management: handoff model, Treasury index levels and backtest"):
            if govt_err:
                st.caption(f"⚠️ GOVT ETF not loaded ({govt_err}); the yield proxy fills months without "
                           "LUATTRUU entries.")
            _pm_panel(pm_lab, pm_preds, pm_bt, pm_err, pm_real, bond_lv, bond_src, spx_me,
                      actual_line[pm_key], target, emp_id, allow_bond_edit)
    if npish_lab.startswith("Gross"):
        with st.expander("NPISH: gross output & receipts equations"):
            _npish_panel(npish, npish_err, res, leaves, target, actual_core is not None)
    if bias and actual_core is not None:
        for nm, act in (("core", actual_core), ("headline", actual_head)):
            e = (res[nm] - act).dropna().iloc[-12:].mean()
            res[nm] = res[nm] - (e if pd.notna(e) else 0)
        core_nc, head_nc = res["core"], res["headline"]

    # structure check: BEA's own line prices through this tab's weights must reproduce core PCE
    rep = N.backtest_stats(res["core_replicated"], actual_core, 24)
    if rep and rep["MAE (pp)"] * 100 > 2.0:
        st.warning(f"Structure check failed: aggregating BEA's own line prices with these weights "
                   f"misses published core PCE by {rep['MAE (pp)'] * 100:.1f} bp a month on average "
                   f"(should be under ~1 bp). The line hierarchy or food/energy split read from BEA's "
                   f"table is off, so treat the nowcast with caution and send me the Diagnostics.")
    elif rep:
        st.caption(f"✅ Structure check: BEA's line prices aggregate to published core PCE within "
                   f"{rep['MAE (pp)'] * 100:.2f} bp/month (24m average).")

    # ---------------------------------------------------------- headline numbers
    st.subheader(f"Nowcast for {target:%B %Y}")
    st_t = res["status"].loc[target] if target in res["status"].index else pd.Series(dtype=str)
    w_t = res["weights"].loc[target] if target in res["weights"].index else pd.Series(dtype=float)
    core_lines = leaves.loc[~leaves.fe.isin(["food", "energy"]), "line"]
    wc = w_t.reindex(core_lines).abs()
    share = (wc.groupby(st_t.reindex(core_lines)).sum() / wc.sum() * 100) if wc.sum() else pd.Series(dtype=float)
    core_yy, _ = _yoy_estimate(pce.idx[pce.core], core_nc, target)
    head_yy, _ = _yoy_estimate(pce.idx[pce.headline], head_nc, target)
    prev = target - pd.DateOffset(months=1)
    prev_lab = f"{prev:%b %Y}"

    def pub_yy(index):
        i = index.dropna()
        return (i.get(prev, np.nan) / i.get(prev - pd.DateOffset(months=12), np.nan) - 1) * 100

    def under(col, prev_val, cur_val, dp, unit="%", label="published"):
        """Line under a big number: previous month's value, and in brackets this month's change from it."""
        if pd.isna(prev_val):
            col.caption(f"{prev_lab}: not yet {label}")
        else:
            d = f" (Δ {cur_val - prev_val:+.{dp}f})" if pd.notna(cur_val) else ""
            col.caption(f"{prev_lab} {label}: {prev_val:.{dp}f}{unit}{d}")

    cm, hm = core_nc.get(target, np.nan), head_nc.get(target, np.nan)
    k = st.columns(4)
    k[0].metric("Core PCE m/m", f"{cm:.3f}%")
    under(k[0], actual_core.get(prev, np.nan) if actual_core is not None else np.nan, cm, 3)
    k[1].metric("Core PCE y/y", f"{core_yy:.2f}%")
    under(k[1], pub_yy(pce.idx[pce.core]), core_yy, 2)
    k[2].metric("Headline PCE m/m", f"{hm:.3f}%")
    under(k[2], actual_head.get(prev, np.nan) if actual_head is not None else np.nan, hm, 3)
    k[3].metric("Headline PCE y/y", f"{head_yy:.2f}%")
    under(k[3], pub_yy(pce.idx[pce.headline]), head_yy, 2)
    k = st.columns(4)
    cc = core_cpi.get(target, np.nan)
    k[0].metric("Core CPI m/m (ref.)", f"{cc:.3f}%", f"{cm - cc:+.3f} PCE–CPI", delta_color="off")
    under(k[0], core_cpi.get(prev, np.nan), cc, 3)
    priced = share.get("data", 0) + share.get("carried", 0)
    k[1].metric("Core weight priced by CPI/PPI", f"{priced:.0f}%")
    st_p = res["status"].loc[prev] if prev in res["status"].index else pd.Series(dtype=str)
    w_p = res["weights"].loc[prev] if prev in res["weights"].index else pd.Series(dtype=float)
    wcp = w_p.reindex(core_lines).abs()
    priced_p = (wcp[st_p.reindex(core_lines).isin(["data", "carried"])].sum() / wcp.sum() * 100) \
        if wcp.sum() else np.nan
    under(k[1], priced_p, priced, 0, label="nowcast")
    st.caption("Core weight by input status: " + " · ".join(f"{i} {v:.1f}%" for i, v in share.items()))

    last_act = pce.idx[pce.core].dropna().index.max()
    rows = []
    for lab, base, nc in (("Core PCE", pce.idx[pce.core], core_nc), ("Headline PCE", pce.idx[pce.headline], head_nc)):
        lvl = N.implied_yoy(base, nc)
        r = A.rates_table(lvl)
        for d in r.index[r.index > last_act]:
            rows.append({"Measure": lab, "Month": f"{d:%b %Y}", "m/m %": nc.get(d, np.nan),
                         **r.loc[d].to_dict()})
    if rows:
        t = pd.DataFrame(rows)
        st.caption(f"Implied rates (nowcast chained onto BEA data through {last_act:%b %Y})")
        U.show_df(t.style.format({c: "{:.2f}" for c in t.columns if c not in ("Measure", "Month")}
                                 | {"m/m %": "{:.3f}"}), hide_index=True)

    # ---------------------------------------------------------- build-up
    st.subheader("Build-up by PCE category")
    contrib = res["contrib_core"]
    if target in contrib.index:
        ct = contrib.loc[target].dropna() * 100  # bp
        g = leaves.set_index("line").reindex(ct.index)["group"]
        by = ct.groupby(g).sum().sort_values()
        fig = C.bars(pd.DataFrame({"bp": by}), f"Contributions to core PCE, {target:%b %Y} (bp)", "bp",
                     labels="{:.1f}")
        U.show(fig)
    tbl = leaves.set_index("line")[["component", "group", "fe"]].copy()
    tbl["BEA source"] = src_text.reindex(tbl.index)
    tbl["Method"] = resolved.set_index("line")["method"].reindex(tbl.index)
    tbl["Series used"] = [", ".join(used.get(l, [])) for l in tbl.index]
    tbl["Status"] = st_t.reindex(tbl.index)
    tot = w_t.reindex(tbl.index).sum()
    tbl["Weight %"] = w_t.reindex(tbl.index) / tot * 100 if tot else np.nan
    tbl["m/m %"] = res["values"].loc[target].reindex(tbl.index) if target in res["values"].index else np.nan
    tbl["Contrib. headline (bp)"] = tbl["Weight %"] * tbl["m/m %"]
    tbl = tbl.reset_index().rename(columns={"line": "Line", "component": "PCE component",
                                            "group": "Category", "fe": "Food/energy"})
    with st.expander(f"All {len(tbl)} most-detailed PCE lines"):
        flt = st.multiselect("Status", sorted(tbl["Status"].dropna().unique()), key="nc_flt")
        view = tbl[tbl["Status"].isin(flt)] if flt else tbl
        U.show_df(view.style.format({"Weight %": "{:.3f}", "m/m %": "{:.3f}",
                                     "Contrib. headline (bp)": "{:.2f}"}, na_rep="–"),
                  hide_index=True, height=500)
        st.download_button("Download (CSV)", tbl.to_csv(index=False).encode(), "pce_nowcast_lines.csv",
                           "text/csv", key="nc_dl")

    # ---------------------------------------------------------- backtest
    st.subheader("Backtest vs published PCE")
    n = st.slider("Window (months)", 12, 96, 36, key="nc_bt_n")
    c1, c2 = st.columns(2)
    for col, lab, nc, act in ((c1, "Core", core_nc, actual_core), (c2, "Headline", head_nc, actual_head)):
        df = pd.concat([nc.rename("nc"), act.rename("act")], axis=1).dropna(how="all").iloc[-n:]
        with col:
            U.show(C.nowcast_backtest(df["nc"], df["act"], f"{lab} PCE m/m: nowcast vs actual"))
    stats = pd.DataFrame({
        "Core nowcast": N.backtest_stats(core_nc, actual_core, n),
        "Headline nowcast": N.backtest_stats(head_nc, actual_head, n),
        "Core replication": N.backtest_stats(res["core_replicated"], actual_core, n),
    })
    U.show_df(stats.T.style.format("{:.3f}"))
    st.caption("Replication = BEA's own line prices aggregated with this tab's weights and "
               "food/energy split; it should be near zero error and checks the structure. "
               "Nowcast errors are on revised data, so real-time errors are larger.")

    # ---------------------------------------------------------- error attribution
    _error_attribution(res, leaves, resolved, used, core_nc, actual_core, n)

    # ---------------------------------------------------------- diagnostics
    with st.expander("Diagnostics"):
        st.markdown("**BEA 2026 annual-update changes applied**" if apply26 else "**BEA 2026 changes off**")
        if apply26:
            for comp, ch in SS.BEA_2026_CHANGES.items():
                st.caption(f"• {comp}: {ch['note']}")
        miss = sorted(set(missing) | set(fetch_missing or []))
        if miss:
            st.caption("Series not returned by BLS (lines fall back to their trend): " + ", ".join(miss))
        # why lines fall back to their own trend, by core weight
        kind = resolved.set_index("line")["kind"]
        srcs = resolved.set_index("line")["source"]
        def reason(ln, status, in_wb):
            if status in ("data", "carried"):
                return None
            if not in_wb:
                return "BEA line not in workbook"
            if status == "series missing":
                return "BLS series not returned"
            if kind.get(ln) == "implicit":
                return "BEA 2026: implicit price (portfolio mgmt)"
            if srcs.get(ln, "") == "":
                return "No price source in workbook"
            return "BEA uses non-CPI/PPI data (input costs, implicit, USDA, foreign CPIs)"
        rs = pd.DataFrame({"line": leaves.line, "in_wb": leaves.in_workbook,
                           "core": ~leaves.fe.isin(["food", "energy"]),
                           "status": st_t.reindex(leaves.line).values})
        rs["reason"] = [reason(l, s_, w) for l, s_, w in zip(rs.line, rs.status, rs.in_wb)]
        rs["w"] = w_t.reindex(rs.line).abs().values
        cw = rs.loc[rs.core, "w"].sum()
        why = (rs[rs.core & rs.reason.notna()].groupby("reason")
               .agg(Lines=("line", "size"), w=("w", "sum")))
        if len(why):
            why["Core weight %"] = why.pop("w") / cw * 100
            st.markdown("**Why core lines use their own trend**")
            U.show_df(why.sort_values("Core weight %", ascending=False).reset_index()
                      .rename(columns={"reason": "Reason"}), hide_index=True)
        mh = pd.Series(match_how).str.split(" ").str[0].value_counts()
        st.caption("Workbook ↔ BEA API matching: " + ", ".join(f"{v} by {k}" for k, v in mh.items())
                   + f"; {len(unaligned)} workbook lines unmatched ({len(unpriced)} of them priced).")
        if len(unaligned):
            U.show_df(unaligned[["line", "component", "bea_code", "source"]], hide_index=True, height=300)
        api = pce.meta[pce.meta.index.str.startswith("U:")][["name"] + [c for c in ("bea_code", "is_leaf")
                                                                        if c in pce.meta.columns]]
        st.download_button("Download BEA API line list (CSV)", api.to_csv().encode(),
                           "bea_api_lines.csv", "text/csv", key="nc_api_dl")


def _error_attribution(res, leaves, resolved, used, core_nc, actual_core, n):
    st.markdown("**Line items driving the core PCE nowcast error**")
    both = pd.concat([core_nc.rename("nc"), actual_core.rename("act")], axis=1).dropna()
    if both.empty:
        st.info("No months with both a nowcast and published core PCE yet.")
        return
    months = list(both.index[-n:])[::-1]
    a1, a2 = st.columns([2, 1])
    m_sel = a1.selectbox("Month to explain", months, format_func=lambda d: f"{d:%b %Y}", key="nc_err_m")
    top = a2.selectbox("Rows", [10, 15, 25, 50], index=1, key="nc_err_n")
    et = PM.error_table(res, leaves, resolved, used, m_sel, n, top)
    tot_err = (both.loc[m_sel, "nc"] - both.loc[m_sel, "act"]) * 100
    lines_err = res["error_core"].loc[m_sel].sum() * 100
    struct = (res["core_replicated"].get(m_sel, np.nan) - actual_core.get(m_sel, np.nan)) * 100
    k = st.columns(3)
    k[0].metric(f"Core nowcast error, {m_sel:%b %Y}", f"{tot_err:+.1f} bp",
                help="Nowcast minus published core PCE m/m, in basis points")
    k[1].metric("From line-item inputs", f"{lines_err:+.1f} bp",
                help="Sum over core lines of weight share × (nowcast input − BEA's actual line m/m)")
    k[2].metric("From structure / chaining", f"{struct:+.1f} bp",
                help="Replicated core (BEA line prices, this tab's weights) minus published core")
    if not et.empty:
        fmt = {c: "{:.2f}" for c in et.columns if et[c].dtype.kind == "f"}
        fmt.update({"Core weight %": "{:.3f}", "Nowcast m/m %": "{:.3f}", "Actual m/m %": "{:.3f}",
                    "Gap (pp)": "{:+.3f}", "Error (bp of core)": "{:+.2f}"})
        sty = et.style.format(fmt, na_rep="–")
        sty = U._style_map(sty, lambda v: A.heat_color(v, 0.0, 2.0) if isinstance(v, (int, float)) else "",
                           ["Error (bp of core)"])
        U.show_df(sty, hide_index=True)
        st.caption(f"Ranked by the size of each line's contribution to the {m_sel:%b %Y} error. "
                   f"Error = line's share of core weight × (nowcast input − BEA's published line m/m); "
                   f"positive = the nowcast was too high. The last two columns average each line's "
                   f"error over the {n}-month backtest window.")
