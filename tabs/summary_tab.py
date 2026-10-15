"""Summary measures: core PCE, core CPI, trimmed means, median, market-based and services measures (y/y)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import charts as C
from core import pm_model as PMM
from core import pce_cpi_gap as GAP
from core import summary_measures as SM
from tabs import common as U
from tabs import gap_chart as GC


@st.cache_data(ttl=6 * 3600, show_spinner="Loading the Dallas Fed trimmed mean from FRED…")
def _dallas(fred_key, _loader):
    return PMM.fred_daily(SM.DALLAS_TM, _loader, fred_key)


@st.cache_data(ttl=6 * 3600, show_spinner="Computing trimmed-mean and median PCE…")
def _measures(_pce, _cpi, dallas, stamp):
    return SM.compute(_pce, _cpi, dallas)


def render(pce, cpi, fred_key=None, fred_loader=None, nowcast: dict | None = None):
    st.header("Summary measures of core inflation")
    if pce is None:
        st.error("PCE data from BEA is required for this tab.")
        return
    try:
        dallas = _dallas(fred_key, fred_loader)
    except Exception:  # noqa: BLE001
        dallas = None
    stamp = (str(pce.idx.index.max()), str(cpi.idx.index.max()) if cpi is not None else "")
    df, notes = _measures(pce, cpi, dallas, stamp)

    this_year = pd.Timestamp.today().year
    c = st.columns([2, 3])
    start = c[0].slider("Start year", 2000, this_year - 2, 2017, key="sm_start")
    picked = c[1].multiselect("Measures", list(df.columns), default=list(df.columns), key="sm_pick")
    view = df.loc[df.index >= pd.Timestamp(start, 1, 1), picked].dropna(how="all")
    if view.empty:
        st.info("No data for this selection.")
        return

    fig = C.lines(view, "Alternative core inflation measures, year-over-year % change", "% y/y",
                  height=520, dash_cols=[c for c in view.columns if c.startswith("Bias-Adjusted")])
    if nowcast and pd.notna(nowcast.get("core_yy")):
        t = pd.Timestamp(nowcast["target"])
        fig.add_vrect(x0=t - pd.Timedelta(days=15), x1=t + pd.Timedelta(days=15), fillcolor="#888",
                      opacity=0.25, line_width=0, layer="below")
        last = df["Core PCE"].dropna()
        xs, ys = ([last.index[-1], t], [last.iloc[-1], nowcast["core_yy"]]) if len(last) else ([t], [nowcast["core_yy"]])
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=f"Core PCE nowcast, {t:%b %Y}",
                                 line=dict(color="#111", dash="dot", width=2),
                                 marker=dict(size=[0, 10] if len(xs) == 2 else [10], color="#111")))
        fig.add_annotation(x=t, y=nowcast["core_yy"], text=f"<b>{nowcast['core_yy']:.2f}</b>", showarrow=False,
                           xanchor="left", xshift=8, yshift=10, font=dict(color="#111", size=12))
    U.show(fig)

    # latest readings
    rows = []
    for m in df.columns:
        s = df[m].dropna()
        if s.empty:
            continue
        last_d = s.index[-1]
        get = lambda k: s.get(last_d - pd.DateOffset(months=k), np.nan)  # noqa: E731
        rows.append({"Measure": m, "Latest month": f"{last_d:%b %Y}", "y/y %": s.iloc[-1],
                     "1 month earlier": get(1), "3 months earlier": get(3), "12 months earlier": get(12),
                     "Change vs 3m (pp)": s.iloc[-1] - get(3)})
    if nowcast and pd.notna(nowcast.get("core_yy")):
        t = pd.Timestamp(nowcast["target"])
        cp = df["Core PCE"]
        rows.append({"Measure": "Core PCE — nowcast", "Latest month": f"{t:%b %Y}", "y/y %": nowcast["core_yy"],
                     "1 month earlier": cp.get(t - pd.DateOffset(months=1), np.nan),
                     "3 months earlier": cp.get(t - pd.DateOffset(months=3), np.nan),
                     "12 months earlier": cp.get(t - pd.DateOffset(months=12), np.nan),
                     "Change vs 3m (pp)": nowcast["core_yy"] - cp.get(t - pd.DateOffset(months=3), np.nan)})
    t = pd.DataFrame(rows)
    U.show_df(t.style.format({c: "{:.2f}" for c in t.columns if c not in ("Measure", "Latest month")}
                             | {"Change vs 3m (pp)": "{:+.2f}"}, na_rep="–"), hide_index=True)

    chk = notes.get("tm_check")
    st.caption(
        "Sources: BEA (core PCE; market-based core PCE, Table 2.4.4U line 402), BLS (core CPI), "
        f"Dallas Fed via FRED (trimmed mean 24/31{'' if notes.get('tm_source', '').startswith('Dallas') else ' — FRED unavailable, computed here instead'}). "
        "Computed here from BEA's detailed PCE lines "
        f"({notes.get('n_components', 0)} components, weighted by last month's spending): the 19/20 trimmed "
        "mean and median PCE (monthly trimmed/median changes chained into an index), market-based core "
        "excluding housing (line 402 less market-based housing, line 385) and core services excluding housing "
        "(services ex energy less housing). Bias-adjusted trimmed mean = the 24/31 trimmed mean minus its "
        "average gap to headline PCE over the prior 10 years."
        + (f" Check: our own 24/31 calculation differs from the Dallas Fed's by {chk[0]:.2f} pp on average "
           f"({chk[1]} months)." if chk else "")
        + (f" Shaded month: this dashboard's core PCE nowcast for {pd.Timestamp(nowcast['target']):%B %Y}."
           if nowcast and pd.notna(nowcast.get('core_yy')) else ""))

    # ------------------------------------------------------------- PCE vs CPI by category
    st.subheader("Where core PCE differs from core CPI")
    if cpi is None:
        st.info("CPI data is needed for this chart.")
        return
    pc, cc = GAP.pce_contrib(pce), GAP.cpi_contrib(cpi)
    tot_p = pce.idx[pce.core].pct_change(fill_method=None) * 100
    tot_c = cpi.idx[cpi.core].pct_change(fill_method=None) * 100
    both = sorted(pc.dropna(how="all").index.intersection(tot_c.dropna().index))
    if not both:
        st.info("No month with both PCE and CPI published.")
        return
    latest = both[-1]

    # published core PCE and core CPI y/y for the latest month both are out, and the gap
    pce_yy, cpi_yy = SM.yoy(pce.idx[pce.core]), SM.yoy(cpi.idx[cpi.core])
    prev = latest - pd.DateOffset(months=1)
    gap_now = pce_yy.get(latest, np.nan) - cpi_yy.get(latest, np.nan)
    gap_prev = pce_yy.get(prev, np.nan) - cpi_yy.get(prev, np.nan)

    def under(col, pv, cv, unit="%"):
        if pd.notna(pv):
            col.caption(f"{prev:%b %Y}: {pv:.2f}{unit}" + (f" (Δ {cv - pv:+.2f})" if pd.notna(cv) else ""))

    k = st.columns(3)
    k[0].metric(f"Core PCE y/y, {latest:%b %Y} (published)", f"{pce_yy.get(latest, np.nan):.2f}%")
    under(k[0], pce_yy.get(prev, np.nan), pce_yy.get(latest, np.nan))
    k[1].metric(f"Core CPI y/y, {latest:%b %Y} (published)", f"{cpi_yy.get(latest, np.nan):.2f}%")
    under(k[1], cpi_yy.get(prev, np.nan), cpi_yy.get(latest, np.nan))
    k[2].metric("Gap: core PCE − core CPI", f"{gap_now:+.2f} pp")
    under(k[2], gap_prev, gap_now, " pp")

    yy_opt = f"12-month (y/y) gap, {latest:%b %Y}"
    chosen, show_yy = GC.month_buttons(st, list(both[-12:]), lambda d: f"{d:%b %Y}", "sm_gap_pick", yy_opt)
    g = None
    if chosen:
        g = GAP.gap(pc.loc[chosen], cc.loc[chosen]).T
        g.loc["Total"] = [tot_p[m] - tot_c[m] for m in chosen]
    yy = GAP.yy_gap(pce, cpi, latest, pce_yy.get(latest, np.nan), cpi_yy.get(latest, np.nan)) if show_yy else None
    if g is None and yy is None:
        st.info("Pick at least one month or the 12-month gap above.")
    else:
        span = (f"{chosen[0]:%b} – {chosen[-1]:%b %Y}" if len(chosen) > 1 else f"{chosen[0]:%B %Y}") if chosen else ""
        title = "Core PCE minus core CPI, by category: " + " · ".join(
            x for x in ((f"m/m {span}" if chosen else ""), (f"y/y {latest:%b %Y}" if show_yy else "")) if x) \
            + " (published)"
        U.show(GC.figure(g, [f"{m:%b %Y}" for m in chosen], title, yy=yy, yy_label=yy_opt))
    st.caption("Bars: each category's contribution to core PCE m/m minus its contribution to core CPI m/m "
               "(pp) for each month selected, stacked; the latest published month is shown by default. Diamonds "
               "(or bars, if picked alone): the 12-month gap — each category's 12-month change × its weight 12 "
               "months earlier, PCE minus CPI; its Total equals the y/y gap above and 'Residual' is what the "
               "category split doesn't capture. PCE "
               "weights: previous month's share of core PCE spending; CPI weights: relative importance within "
               "core CPI. Food services, financial services, nonprofits and other durables have no core-CPI "
               "counterpart (food away from home is outside core CPI). For the monthly bars, Total = core PCE m/m − "
               "core CPI m/m; the small difference from the sum of categories reflects chaining and CPI items not "
               "mapped.")
