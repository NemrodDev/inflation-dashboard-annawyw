import pandas as pd
import streamlit as st

from config import ppi as PPI
from core import analytics as A
from core import charts as C
from tabs import common as U


def render(ds: A.Dataset):
    st.header("Producer Price Index — Final Demand")
    U.render_snapshot(ds, {"Core ex trade": PPI.CORE_CORE, "Services": "FD42"})
    st.divider()
    U.render_release_table(ds, 1)
    st.divider()
    U.render_aggregates(ds, 2)
    st.divider()
    U.render_contributions(ds, 3)
    st.divider()
    U.render_diffusion(ds, 4)
    st.divider()
    U.render_annualized(ds, 5, extra_keys=["FD412", "FD411", "FD422", "FD43"])
    st.divider()
    render_pce_inputs(ds, 6)
    st.divider()
    U.render_distribution(ds, 7, mover_keys=[c for c, _, lvl, _ in PPI.RELEASE_TABLE if lvl >= 2])


def render_pce_inputs(ds: A.Dataset, num):
    U.section(num, "PPI components that feed PCE (health care, airfares, portfolio management)",
              "These industry PPIs (not seasonally adjusted) replace CPI prices in the PCE index; "
              "they are the main reason core PCE and core CPI diverge month to month.")
    keys = [k for k in ds.extras.get("pce_inputs", []) if k in ds.idx.columns]
    if not keys:
        st.info("PCE-input PPI series not available.")
        return
    sel = st.multiselect("Series", keys, default=keys[:3], format_func=ds.label, key="ppi_pce_sel")
    if sel:
        c1, c2 = st.columns(2)
        with c1:
            U.show(C.lines(U.win(A.yoy(ds.idx[sel])).rename(columns=ds.label), "y/y %", "% y/y"))
        with c2:
            m = A.mom(ds.idx[sel]).dropna(how="all").iloc[-24:].rename(columns=ds.label)
            U.show(C.bars(m, "m/m % (NSA)", "% m/m"))
    rows = []
    m, y, a3 = A.mom(ds.idx[keys]), A.yoy(ds.idx[keys]), A.annualized(ds.idx[keys], 3)
    for k in keys:
        mm = m[k].dropna()
        if mm.empty:
            continue
        rows.append({"Series": ds.label(k), "Id": k, "Latest": f"{mm.index[-1]:%b %Y}",
                     "m/m %": mm.iloc[-1], "3m ann. %": a3[k].dropna().iloc[-1],
                     "y/y %": y[k].dropna().iloc[-1]})
    if rows:
        t = pd.DataFrame(rows)
        U.show_df(t.style.format({"m/m %": "{:.2f}", "3m ann. %": "{:.2f}", "y/y %": "{:.2f}"}), hide_index=True)
