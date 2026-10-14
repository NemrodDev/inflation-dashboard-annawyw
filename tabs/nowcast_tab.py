"""CPI/PPI -> PCE nowcast, line by line, on BEA's source-data table (Table 2.4.4U-D)."""
import numpy as np
import pandas as pd
import streamlit as st

from config import pce_source_series as SS
from core import analytics as A
from core import charts as C
from core import pce_map as PM
from core import nowcast as N
from tabs import common as U

PROXIES = {"Line's own 3m average (published PCE)": "trend3",
           "Line's last published m/m": "last",
           "Line's own 12m average": "trend12",
           "Core CPI m/m": "corecpi"}


@st.cache_data
def _mapping():
    return PM.load_mapping()


def render(cpi, pce, levels: pd.DataFrame | None, fetch_missing):
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
    apply26 = c[0].toggle("BEA 2026 method changes", True, key="nc26",
                          help="Portfolio mgmt → implicit (CES quantity); legal services → PPIs from 2024; "
                               "software → CPI + 2 PPIs")
    proxy_lab = c[1].selectbox("Lines without CPI/PPI source", list(PROXIES), key="nc_proxy")
    sa_adj = c[2].toggle("Seasonally adjust 'SA by BEA' inputs", True, key="nc_sa",
                         help="BEA seasonally adjusts these NSA PPIs itself; this removes the average "
                              "same-month excess over the past 5 years")
    carry = c[3].toggle("Carry forward missing PPI", True, key="nc_carry")
    bias = c[4].toggle("Bias-correct (12m)", False, key="nc_bias")

    resolved = PM.resolve(mapping, apply26)
    target = A.mom(cpi.idx[cpi.core]).dropna().index.max()

    # ---------------------------------------------------------- PCE detail from BEA
    if pce is None or not any(k.startswith("U:") for k in pce.idx.columns):
        st.error("BEA underlying-detail PCE data (Tables 2.4.4U/2.4.5U) is required for the nowcast.")
        return
    keymap, match_how = PM.align(mapping, pce.meta, report=True)
    leaves = PM.leaf_table(resolved, pce.meta, keymap)
    ukeys = [k for k in pce.idx.columns if k.startswith("U:")]
    actual_line = A.mom(pce.idx[ukeys])
    nominal = pce.extras["nominal"][ukeys]
    actual_core, actual_head = A.mom(pce.idx[pce.core]), A.mom(pce.idx[pce.headline])
    unaligned = mapping[~mapping.line.isin(keymap)]
    unpriced = unaligned[unaligned.source != ""]
    api_only = int((~leaves.in_workbook).sum()) if "in_workbook" in leaves else 0
    if len(unpriced) or api_only:
        st.caption(f"⚠️ {len(unpriced)} priced workbook lines not matched to BEA's API table; "
                   f"{api_only} BEA detail lines have no workbook match (see Diagnostics).")
    if leaves.empty:
        st.error("Could not match the workbook to BEA's detail lines.")
        return

    # ---------------------------------------------------------- overrides
    M0, used, missing = PM.build_inputs(resolved, levels, sa_adj)
    sid_rows = {}
    for ln, ids in used.items():
        for sid in ids:
            sid_rows.setdefault(sid, []).append(ln)
    src_text = mapping.set_index("line")["source"]
    mom_lv = levels.pct_change(fill_method=None) * 100
    ov_df = pd.DataFrame([{
        "Series": sid, "BEA source": src_text.get(lns[0], ""), "PCE lines": len(lns),
        f"m/m {target:%b %y}": mom_lv[sid].get(target, np.nan),
        "Override m/m": np.nan} for sid, lns in sid_rows.items()])
    with st.expander("Override inputs for the target month (e.g. PPI consensus before the PPI release)"):
        cfg = {"Override m/m": st.column_config.NumberColumn(format="%.3f")}
        ov = st.data_editor(ov_df, key="nc_ov", hide_index=True, disabled=[c for c in ov_df.columns
                                                                           if c != "Override m/m"],
                            column_config=U.right_align_config(ov_df, cfg))
    overrides = dict(zip(ov["Series"], ov["Override m/m"])) if len(ov) else {}
    M, used, missing = PM.build_inputs(resolved, levels, sa_adj, overrides, target)

    core_cpi = A.mom(cpi.idx[cpi.core])
    res = PM.run(leaves, resolved, M, actual_line, nominal, PROXIES[proxy_lab], core_cpi, carry)
    core_nc, head_nc = res["core"], res["headline"]
    if bias and actual_core is not None:
        for nm, act in (("core", actual_core), ("headline", actual_head)):
            e = (res[nm] - act).dropna().iloc[-12:].mean()
            res[nm] = res[nm] - (e if pd.notna(e) else 0)
        core_nc, head_nc = res["core"], res["headline"]

    # ---------------------------------------------------------- headline numbers
    st.subheader(f"Nowcast for {target:%B %Y}")
    st_t = res["status"].loc[target] if target in res["status"].index else pd.Series(dtype=str)
    w_t = res["weights"].loc[target] if target in res["weights"].index else pd.Series(dtype=float)
    core_lines = leaves.loc[~leaves.fe.isin(["food", "energy"]), "line"]
    wc = w_t.reindex(core_lines).abs()
    share = (wc.groupby(st_t.reindex(core_lines)).sum() / wc.sum() * 100) if wc.sum() else pd.Series(dtype=float)
    k = st.columns(4)
    k[0].metric("Core PCE m/m", f"{core_nc.get(target, np.nan):.3f}%")
    k[1].metric("Headline PCE m/m", f"{head_nc.get(target, np.nan):.3f}%")
    cc = core_cpi.get(target, np.nan)
    k[2].metric("Core CPI m/m (ref.)", f"{cc:.3f}%", f"{core_nc.get(target, np.nan) - cc:+.3f} PCE–CPI",
                delta_color="off")
    k[3].metric("Core weight priced by CPI/PPI", f"{share.get('data', 0) + share.get('carried', 0):.0f}%")
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
