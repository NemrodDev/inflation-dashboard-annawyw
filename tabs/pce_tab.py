import pandas as pd
import streamlit as st

from core import analytics as A
from core import charts as C
from tabs import common as U

FRED_ALT = ["PCETRIM1M158SFRBDAL", "PCETRIM12M159SFRBDAL"]


def render(ds: A.Dataset, fred_key=None, fred_loader=None):
    st.header("PCE Price Index")
    ex = ds.extras
    U.render_snapshot(ds, {k: v for k, v in {"Supercore": ex.get("supercore"),
                                              "Services": ex.get("services")}.items() if v})
    st.divider()
    U.render_release_table(ds, 1)
    st.divider()
    U.render_aggregates(ds, 2)
    st.divider()
    U.render_contributions(ds, 3)
    st.divider()
    core_only = st.toggle("Diffusion: core items only (exclude food & energy)", True, key="pce_core_only")
    keys = [k for k in ds.diffusion_keys
            if not (core_only and ds.meta.get("fe") is not None and ds.meta.loc[k, "fe"] in ("food", "energy"))]
    U.render_diffusion(ds, 4, keys=keys,
                       caption=f"Universe: {len(keys)} most-detailed lines of BEA Table 2.4.4U "
                               f"(hierarchy reconstructed from nominal spending).")
    st.divider()
    U.render_annualized(ds, 5)
    st.divider()
    render_goods_services(ds, 6)
    st.divider()
    U.render_distribution(ds, 7, keys=keys)
    st.divider()
    if fred_loader:
        U.render_fred(FRED_ALT, fred_key, 8, "Dallas Fed trimmed-mean PCE", fred_loader)


def render_goods_services(ds: A.Dataset, num):
    U.section(num, "Supercore and goods vs services")
    ex = ds.extras
    keys = [k for k in [ex.get("goods"), ex.get("services"), ex.get("housing"), ex.get("supercore"), ds.core]
            if k and ds.has(k)]
    c1, c2 = st.columns(2)
    with c1:
        U.show(C.lines(U.win(A.yoy(ds.idx[keys])).rename(columns=ds.label), "y/y %", "% y/y", hline=2.0))
    with c2:
        sc = ex.get("supercore")
        if sc and ds.has(sc):
            U.show(C.lines(U.win(A.rates_table(ds.idx[sc])), f"{ds.label(sc)} — annualised rates",
                           "% ann.", hline=2.0, dash_cols=("1m ann.",)))
