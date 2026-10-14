"""Raw data clients for BLS, BEA and FRED with a small on-disk cache.

Nothing here imports streamlit, so the module can be used from scripts/notebooks.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

CACHE_DIR = Path(os.environ.get("INFL_CACHE_DIR", Path(__file__).resolve().parent.parent / ".cache"))
TIMEOUT = 60


class SourceError(RuntimeError):
    pass


# --------------------------------------------------------------------------- cache
def disk_cache(key: str, ttl_hours: float, fn):
    """Return fn() cached on disk under `key` for ttl_hours (0 disables)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / (hashlib.md5(key.encode()).hexdigest() + ".pkl")
    if ttl_hours > 0 and path.exists() and (time.time() - path.stat().st_mtime) < ttl_hours * 3600:
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    out = fn()
    try:
        with open(path, "wb") as f:
            pickle.dump(out, f)
    except Exception:
        pass
    return out


def clear_cache():
    if CACHE_DIR.exists():
        for p in CACHE_DIR.glob("*.pkl"):
            p.unlink()


# --------------------------------------------------------------------------- BLS
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


def bls_fetch(series_ids: list[str], start_year: int, end_year: int, api_key: str | None,
              ttl_hours: float = 6) -> tuple[pd.DataFrame, list[str]]:
    """Fetch monthly BLS series. Returns (wide DataFrame indexed by month start, missing ids)."""
    series_ids = list(dict.fromkeys(series_ids))
    chunk = 50 if api_key else 25
    span = 20 if api_key else 10
    frames, missing = [], []

    def _one(ids, y0, y1):
        payload = {"seriesid": ids, "startyear": str(y0), "endyear": str(y1)}
        if api_key:
            payload["registrationkey"] = api_key
        r = requests.post(BLS_URL, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        js = r.json()
        if js.get("status") != "REQUEST_SUCCEEDED":
            msg = "; ".join(js.get("message", [])) or js.get("status")
            # partial successes still carry data; only hard failures raise
            if not js.get("Results"):
                raise SourceError(f"BLS API: {msg}")
        return js

    windows = []
    y = start_year
    while y <= end_year:
        windows.append((y, min(y + span - 1, end_year)))
        y += span

    for i in range(0, len(series_ids), chunk):
        ids = series_ids[i:i + chunk]
        for (y0, y1) in windows:
            key = f"bls|{','.join(ids)}|{y0}|{y1}|{bool(api_key)}"
            js = disk_cache(key, ttl_hours, lambda: _one(ids, y0, y1))
            for s in js.get("Results", {}).get("series", []):
                rows = []
                for d in s.get("data", []):
                    p = d.get("period", "")
                    if not p.startswith("M") or p == "M13":
                        continue
                    try:
                        v = float(str(d.get("value", "")).replace(",", ""))
                    except ValueError:
                        v = np.nan
                    rows.append((pd.Timestamp(int(d["year"]), int(p[1:]), 1), v))
                if rows:
                    frames.append(pd.Series(dict(rows), name=s["seriesID"]))
    if not frames:
        return pd.DataFrame(), series_ids
    wide = pd.concat(frames, axis=1)
    wide = wide.T.groupby(level=0).first().T.sort_index()  # merge year windows
    wide = wide.reindex(pd.date_range(wide.index.min(), wide.index.max(), freq="MS"))
    missing = [s for s in series_ids if s not in wide.columns or wide[s].notna().sum() == 0]
    return wide, missing


def bls_flatfile(survey: str, name: str, contact_email: str | None, ttl_hours: float = 24 * 7) -> pd.DataFrame:
    """Download a BLS LABSTAT flat file (e.g. cu.series, cu.item). BLS requires a
    User-Agent that identifies the requester with a contact email."""
    url = f"https://download.bls.gov/pub/time.series/{survey}/{name}"
    ua = f"inflation-dashboard/1.0 ({contact_email})" if contact_email else "inflation-dashboard/1.0"

    def _get():
        r = requests.get(url, headers={"User-Agent": ua}, timeout=TIMEOUT)
        if r.status_code == 403:
            raise SourceError("BLS download server refused the request (403). Set BLS_CONTACT_EMAIL.")
        r.raise_for_status()
        return r.text

    text = disk_cache(f"flat|{survey}|{name}", ttl_hours, _get)
    df = pd.read_csv(io.StringIO(text), sep="\t", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].str.strip()
    return df


def cpi_catalog(contact_email: str | None) -> pd.DataFrame:
    """All U.S. city average, monthly, SA CPI-U series with item names and hierarchy."""
    series = bls_flatfile("cu", "cu.series", contact_email)
    items = bls_flatfile("cu", "cu.item", contact_email)
    s = series[(series.area_code == "0000") & (series.periodicity_code == "R")
               & (series.base_code == "S")]
    sa = set(s[s.seasonal == "S"].item_code)
    nsa = set(s[s.seasonal == "U"].item_code)
    items = items.copy()
    items["display_level"] = pd.to_numeric(items["display_level"], errors="coerce").fillna(0).astype(int)
    items["sort_sequence"] = pd.to_numeric(items["sort_sequence"], errors="coerce")
    items = items.sort_values("sort_sequence").reset_index(drop=True)
    items["has_sa"] = items.item_code.isin(sa)
    items["has_nsa"] = items.item_code.isin(nsa)
    # leaf = next item in sort order is not deeper
    nxt = items["display_level"].shift(-1).fillna(-1)
    items["is_leaf"] = nxt <= items["display_level"]
    return items


def ppi_catalog(contact_email: str | None) -> pd.DataFrame:
    """Active seasonally adjusted PPI commodity series (wp.series)."""
    s = bls_flatfile("wp", "wp.series", contact_email)
    s = s[(s.seasonal == "S")].copy()
    s["end_year"] = pd.to_numeric(s["end_year"], errors="coerce")
    s = s[s.end_year >= pd.Timestamp.today().year - 1]
    s["code"] = s["group_code"] + s["item_code"]
    return s


# --------------------------------------------------------------------------- BEA
BEA_URL = "https://apps.bea.gov/api/data"


def bea_table(dataset: str, table: str, years: list[int], api_key: str,
              ttl_hours: float = 6) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch a monthly BEA table. Returns (wide values by line key, line meta).
    Line keys are 'L001', 'L002', ... in table order."""
    params = {
        "UserID": api_key, "method": "GetData", "DataSetName": dataset,
        "TableName": table, "Frequency": "M", "Year": ",".join(str(y) for y in years),
        "ResultFormat": "JSON",
    }

    def _get():
        r = requests.get(BEA_URL, params=params, timeout=TIMEOUT * 2)
        r.raise_for_status()
        return r.json()

    js = disk_cache(f"bea|{dataset}|{table}|{params['Year']}", ttl_hours, _get)
    res = js.get("BEAAPI", {}).get("Results", {})
    if isinstance(res, list):
        res = res[0]
    if "Error" in res or "Data" not in res:
        err = res.get("Error", js.get("BEAAPI", {}).get("Error", "unknown error"))
        raise SourceError(f"BEA API ({table}): {json.dumps(err)[:300]}")
    d = pd.DataFrame(res["Data"])
    d["line"] = pd.to_numeric(d["LineNumber"], errors="coerce").astype(int)
    d["date"] = pd.to_datetime(d["TimePeriod"].str.replace("M", "-") + "-01", format="%Y-%m-%d")
    d["value"] = pd.to_numeric(d["DataValue"].astype(str).str.replace(",", ""), errors="coerce")
    d["key"] = d["line"].map(lambda x: f"L{x:03d}")
    meta = (d.drop_duplicates("key").sort_values("line")
            .set_index("key")[["line", "LineDescription", "SeriesCode"]]
            .rename(columns={"LineDescription": "name", "SeriesCode": "bea_code"}))
    meta["name"] = meta["name"].str.strip()
    wide = d.pivot_table(index="date", columns="key", values="value", aggfunc="first").sort_index()
    wide = wide[meta.index]
    return wide, meta


# --------------------------------------------------------------------------- FRED
FRED_URL = "https://api.stlouisfed.org/fred"


def fred_series(series_id: str, api_key: str, start: str = "2010-01-01",
                ttl_hours: float = 6) -> tuple[pd.Series, dict]:
    def _get():
        obs = requests.get(f"{FRED_URL}/series/observations", params={
            "series_id": series_id, "api_key": api_key, "file_type": "json",
            "observation_start": start}, timeout=TIMEOUT).json()
        info = requests.get(f"{FRED_URL}/series", params={
            "series_id": series_id, "api_key": api_key, "file_type": "json"}, timeout=TIMEOUT).json()
        return obs, info

    obs, info = disk_cache(f"fred|{series_id}|{start}", ttl_hours, _get)
    if "observations" not in obs:
        raise SourceError(f"FRED {series_id}: {obs.get('error_message', 'error')}")
    s = pd.Series({pd.Timestamp(o["date"]): pd.to_numeric(o["value"], errors="coerce")
                   for o in obs["observations"]}, name=series_id)
    meta = (info.get("seriess") or [{}])[0]
    return s, {"title": meta.get("title", series_id), "units": meta.get("units", "")}
