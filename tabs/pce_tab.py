import pandas as pd
import streamlit as st

from config import pce as PCE
from core import analytics as A
from core.builders import find_line
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
    render_ai(ds, 6)
    st.divider()
    render_goods_services(ds, 7)
    st.divider()
    U.render_distribution(ds, 8, keys=keys)
    st.divider()
    if fred_loader:
        U.render_fred(FRED_ALT, fred_key, 9, "Dallas Fed trimmed-mean PCE", fred_loader)


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


def render_ai(ds: A.Dataset, num):
    """The CPI tab's AI-exposed categories, rebuilt with PCE lines and PCE weights."""
    U.section(num, "AI-exposed categories — PCs & peripherals, software, smartphones, TVs",
              "Contribution to headline PCE = previous month's share of total PCE spending × m/m change "
              "(BEA Table 2.4.4U prices, 2.4.5U spending). BEA has no separate smartphone line; "
              "'Telephone and related communication equipment' is mostly smartphones. Lines are set in config/pce.py.")
    found = [(find_line(ds.meta, name, "U:"), label) for name, label in PCE.AI_ITEMS]
    found = [(k, lab) for k, lab in found if k and k in ds.idx.columns and k in ds.weights.columns]
    if not found:
        st.info("AI category lines not available (the PCE underlying-detail table didn't load).")
        return
    codes = [k for k, _ in found]
    names = dict(found)
    m = A.mom(ds.idx[codes])
    contrib_bp = (ds.weights[codes] * m * 100).rename(columns=names)
    total = contrib_bp.sum(axis=1, min_count=1)
    c1, c2 = st.columns(2)
    with c1:
        span = contrib_bp.dropna(how="all").iloc[-36:]
        U.show(C.stacked_contrib(span, total.reindex(span.index), "Contribution to headline PCE, m/m",
                                 "basis points", total_name="AI basket total"))
    with c2:
        # y/y change x spending share a year earlier, from index levels (as in the CPI tab)
        roll = (ds.weights[codes].shift(11) * A.yoy(ds.idx[codes]) * 100).rename(columns=names)
        rt = roll.sum(axis=1, min_count=len(codes))
        roll = U.win(roll).dropna(how="all")
        U.show(C.stacked_contrib(roll, U.win(rt).reindex(roll.index),
                                 "Contribution to headline PCE, y/y", "basis points",
                                 total_name="AI basket total"))
    c3, c4 = st.columns(2)
    with c3:
        U.show(C.lines(U.win(A.yoy(ds.idx[codes])).rename(columns=names), "Price change y/y", "% y/y"))
    with c4:
        base = U.win(ds.idx[codes]).dropna(how="all")
        reb = base / base.bfill().iloc[0] * 100
        U.show(C.lines(reb.rename(columns=names), "Price level (rebased = 100)", "index"))
    w = ds.weights[codes].dropna(how="all")
    if len(w):
        st.caption("Current share of total PCE spending: " + ", ".join(
            f"{names[c]} {w[c].iloc[-1] * 100:.2f}%" for c in codes) +
            f" — basket total {w.iloc[-1].sum() * 100:.2f}%")
