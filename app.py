"""Inflation dashboard: CPI, PPI, PCE and a CPI/PPI -> PCE nowcast.

Run:  streamlit run app.py
Keys: .streamlit/secrets.toml (see secrets.toml.example) or environment variables.
"""
from __future__ import annotations

import os
from datetime import date

import pandas as pd
import streamlit as st

from core import sources as src
from core import builders as B
from tabs import cpi_tab, ppi_tab, pce_tab, nowcast_tab

st.set_page_config(page_title="Inflation Dashboard", page_icon="📈", layout="wide")


def secret(name):
    try:
        v = st.secrets.get(name)
        if v:
            return str(v)
    except Exception:  # noqa: BLE001  (no secrets file)
        pass
    return os.environ.get(name) or None


BLS_KEY, BEA_KEY, FRED_KEY = secret("BLS_API_KEY"), secret("BEA_API_KEY"), secret("FRED_API_KEY")
EMAIL = secret("BLS_CONTACT_EMAIL")
TTL = 6 * 3600


# ------------------------------------------------------------------ cached loaders
@st.cache_data(ttl=TTL, show_spinner="Loading CPI from BLS…")
def get_cpi(start_year, end_year, full):
    return B.load_cpi_live(start_year, end_year, BLS_KEY, EMAIL, full)


@st.cache_data(ttl=TTL, show_spinner="Loading PPI from BLS…")
def get_ppi(start_year, end_year, full):
    return B.load_ppi_live(start_year, end_year, BLS_KEY, EMAIL, full)


@st.cache_data(ttl=TTL, show_spinner="Loading PCE from BEA…")
def get_pce(start_year, end_year):
    return B.load_pce_live(start_year, end_year, BEA_KEY)


@st.cache_data(ttl=TTL, show_spinner="Loading CPI/PPI inputs for the PCE nowcast…")
def get_nowcast_series(start_year, end_year):
    from core import pce_map as PM
    ids = PM.series_needed(PM.resolve(PM.load_mapping(), True)) + \
        PM.series_needed(PM.resolve(PM.load_mapping(), False))
    ids = list(dict.fromkeys(ids))
    return B.load_nowcast_series_live(ids, start_year, end_year, BLS_KEY)


@st.cache_data(ttl=TTL)
def get_fred(series_id, key):
    return src.fred_series(series_id, key)


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("📈 Inflation")
    this_year = date.today().year
    start_year = st.number_input("Load data from", 2000, this_year - 2, this_year - 11, step=1)
    full = st.toggle("Full item catalogs (diffusion, full release table)", True,
                     help="Pulls every SA CPI item and PPI commodity index.")
    win_years = st.slider("Chart window (years)", 2, 12, 5)
    st.session_state["win_start"] = pd.Timestamp(this_year - win_years, date.today().month, 1)
    if st.button("Refresh data"):
        st.cache_data.clear()
        src.clear_cache()
        st.rerun()
    st.divider()
    st.caption("API keys: " + " · ".join(f"{n} {'✅' if k else '❌'}" for n, k in
                                         [("BLS", BLS_KEY), ("BEA", BEA_KEY), ("FRED", FRED_KEY)]))
    if not EMAIL and full:
        st.caption("Set BLS_CONTACT_EMAIL so BLS allows the item-catalog download.")

missing_keys = [n for n, k in [("BLS_API_KEY", BLS_KEY), ("BEA_API_KEY", BEA_KEY)] if not k]
if missing_keys:
    st.error("Live data needs API keys: " + ", ".join(missing_keys) + " not set. Add them to "
             ".streamlit/secrets.toml (local) or the app's Settings → Secrets (Streamlit Cloud), "
             "then reload.")
    st.code('BLS_API_KEY = "..."\nBEA_API_KEY = "..."\nBLS_CONTACT_EMAIL = "you@example.com"', language="toml")
    st.stop()


def load(fn, *args):
    try:
        return fn(*args), None
    except Exception as e:  # noqa: BLE001
        return None, e


cpi, cpi_err = load(get_cpi, int(start_year), this_year, full)
ppi, ppi_err = load(get_ppi, int(start_year), this_year, full)
pce, pce_err = load(get_pce, int(start_year), this_year)

tabs = st.tabs(["CPI", "PPI", "PCE", "CPI/PPI → PCE nowcast"])
with tabs[0]:
    if cpi is not None:
        cpi_tab.render(cpi, FRED_KEY, get_fred)
    else:
        st.error(f"CPI load failed: {cpi_err}")
with tabs[1]:
    if ppi is not None:
        ppi_tab.render(ppi)
    else:
        st.error(f"PPI load failed: {ppi_err}")
with tabs[2]:
    if pce is not None:
        pce_tab.render(pce, FRED_KEY, get_fred)
    else:
        st.error(f"PCE load failed: {pce_err}")
with tabs[3]:
    nc_in, nc_err = load(get_nowcast_series, int(start_year), this_year)
    if nc_err:
        st.error(f"Nowcast inputs failed to load: {nc_err}")
    else:
        nowcast_tab.render(cpi, pce, nc_in[0], nc_in[1])
