import pandas as pd
import streamlit as st

from config import cpi as CPI
from core import analytics as A
from core import charts as C
from tabs import common as U

FRED_ALT = ["MEDCPIM158SFRBCLE", "TRMMEANCPIM158SFRBCLE", "CORESTICKM159SFRBATL"]


def render(ds: A.Dataset, fred_key=None, fred_loader=None):
    st.header("Consumer Price Index (CPI-U)")
    U.render_snapshot(ds, {"Supercore": "SUPERCORE", "Shelter": CPI.SHELTER})
    st.divider()
    U.render_release_table(ds, 1)
    st.divider()
    U.render_aggregates(ds, 2)
    st.divider()
    U.render_contributions(ds, 3)
    st.divider()
    U.render_diffusion(ds, 4)
    st.divider()
    U.render_annualized(ds, 5, extra_keys=["SAC", "SAS", "SASL2RS"])
    st.divider()
    render_ai(ds, 6)
    st.divider()
    render_supercore(ds, 7)
    st.divider()
    U.render_distribution(ds, 8, mover_keys=_detail_keys(ds))
    st.divider()
    if fred_loader:
        U.render_fred(FRED_ALT, fred_key, 9, "Alternative core measures (Cleveland Fed median & trimmed mean, Atlanta Fed sticky)",
                      fred_loader)


def _detail_keys(ds):
    keys = []
    for s in ds.specs["Core"]["Detailed"] + ds.specs["Headline"]["Detailed"][:4]:
        keys += [k for k, sg in s["terms"] if sg > 0]
    return list(dict.fromkeys(keys))


def render_ai(ds: A.Dataset, num):
    U.section(num, "AI-exposed categories — software, computers & peripherals, TVs, phones",
              "Contribution to headline CPI = price-updated relative importance × m/m change. "
              "Relative importances are approximate; update them in config/cpi.py.")
    codes = [c for c in ds.extras.get("ai_codes", []) if c in ds.idx.columns]
    if not codes:
        st.info("AI category series not available.")
        return
    m = A.mom(ds.idx[codes])
    contrib_bp = (ds.weights[codes] * m * 100).rename(columns=ds.label)
    total = contrib_bp.sum(axis=1, min_count=1)
    c1, c2 = st.columns(2)
    with c1:
        span = contrib_bp.dropna(how="all").iloc[-36:]
        show_total = total.reindex(span.index)
        U.show(C.stacked_contrib(span, show_total, "Contribution to headline CPI, m/m",
                                 "basis points", total_name="AI basket total"))
    with c2:
        roll = contrib_bp.rolling(12, min_periods=12).sum()
        rt = roll.sum(axis=1, min_count=1)
        U.show(C.stacked_contrib(U.win(roll).dropna(how="all"), U.win(rt).dropna(),
                                 "Contribution to headline CPI, trailing 12m", "basis points",
                                 total_name="AI basket total"))
    c3, c4 = st.columns(2)
    with c3:
        U.show(C.lines(U.win(A.yoy(ds.idx[codes])).rename(columns=ds.label), "Price change y/y", "% y/y"))
    with c4:
        base = U.win(ds.idx[codes]).dropna(how="all")
        reb = base / base.bfill().iloc[0] * 100
        U.show(C.lines(reb.rename(columns=ds.label), "Price level (rebased = 100)", "index"))
    w = ds.weights[codes].dropna(how="all")
    if len(w):
        st.caption("Current weight in headline CPI: " + ", ".join(
            f"{ds.label(c)} {w[c].iloc[-1] * 100:.2f}%" for c in codes) +
            f" — basket total {w.iloc[-1].sum() * 100:.2f}%")


def render_supercore(ds: A.Dataset, num):
    U.section(num, "Supercore and goods vs services",
              "Supercore = core services excluding shelter, built from weighted m/m changes of "
              "services less energy services and shelter.")
    keys = [k for k in ["SACL1E", "SASLE", "SAH1", "SUPERCORE"] if ds.has(k)]
    c1, c2 = st.columns(2)
    with c1:
        U.show(C.lines(U.win(A.yoy(ds.idx[keys])).rename(columns=ds.label), "Core goods vs services, y/y",
                       "% y/y", hline=2.0))
    with c2:
        r = U.win(A.rates_table(ds.idx["SUPERCORE"])) if ds.has("SUPERCORE") else pd.DataFrame()
        if not r.empty:
            U.show(C.lines(r, "Supercore — annualised rates", "% ann.", hline=2.0, dash_cols=("1m ann.",)))
    c3, c4 = st.columns(2)
    with c3:
        gs = [k for k in ["SACL1E", "SASLE"] if ds.has(k)]
        mm = A.mom(ds.idx[gs]).dropna(how="all").iloc[-36:].rename(columns=ds.label)
        U.show(C.bars(mm, "Core goods vs core services, m/m", "% m/m"))
    with c4:
        if ds.has("SUPERCORE"):
            m = A.mom(ds.idx)
            wsc = ds.weights["SUPERCORE"]
            parts = {s["label"]: A.contribution(ds, s["terms"], m) / wsc for s in CPI.SUPERCORE_SPECS}
            df = pd.DataFrame(parts).dropna(how="all").iloc[-36:]
            act = m["SUPERCORE"].reindex(df.index)
            resid = act - df.sum(axis=1)
            U.show(C.stacked_contrib(df, act, "Contributions to supercore, m/m", "pp of supercore", resid,
                                     total_name="Supercore"))
    gs2 = [k for k in ["SAC", "SAS"] if ds.has(k)]
    if gs2:
        U.show(C.lines(U.win(A.yoy(ds.idx[gs2])).rename(columns=ds.label),
                       "All commodities vs all services (incl. food & energy), y/y", "% y/y", height=360))
