"""NPISH (nonprofit institutions serving households): gross output and "Less: receipts" legs.

Method (npish_gross_output_receipts_methodology.md): forecast each leg separately, then let the
identity net them (the receipts line carries a negative weight in PCE):

    gross_t    = a + b x TM6(gross)_t    + c x AHE_mm_t       AHE: CES6500000003 (Education & health)
    receipts_t = a + b x TM6(receipts)_t + c x PPI_mm_t       PPI: PCU622---622--- (Hospitals), SA here

TM6 = mean of the leg's own BEA m/m over the previous 6 months (at least 3 of 6 required).
OLS refit every month on months strictly before it (expanding window, >= 36 months), so every
historical prediction is out of sample. If the regressor isn't out for that month the equation
drops it (a + b x TM6); with < 36 months of history the prediction is TM6 itself.

The gross prediction is applied to all 11 "..., gross output" lines (BEA line 341's children) and the
receipts prediction to the receipts line, so the category aggregates land exactly on the equations;
net NPISH = (Wgo x gross - Wrc x receipts) / (Wgo - Wrc) falls out of the normal PCE aggregation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WAGE_ID = "CES6500000003"        # avg hourly earnings, education & health services (SA)
PPI_ID = "PCU622---622---"       # PPI hospitals (NSA -> seasonally adjusted in the app)
IDS = [WAGE_ID, PPI_ID]
TM_WINDOW, TM_MIN, MIN_TRAIN = 6, 3, 36


def gross_lines(leaves: pd.DataFrame) -> list:
    comp = leaves["component"].str.lower()
    return leaves.loc[comp.str.endswith("gross output") & (leaves["sign"] > 0), "line"].tolist()


def receipts_line(leaves: pd.DataFrame):
    comp = leaves["component"].str.lower()
    hit = leaves.loc[comp.str.startswith("less: receipts from sales"), "line"]
    return hit.iloc[0] if len(hit) else None


def leg_actual(actual_line: pd.DataFrame, nominal: pd.DataFrame, keys: list) -> pd.Series:
    """BEA m/m of a leg: nominal-weighted (previous month) average of its lines' published m/m."""
    a = actual_line[keys]
    w = nominal[keys].shift(1).reindex(a.index)
    ok = a.notna() & w.notna()
    return (a * w).where(ok).sum(axis=1) / w.where(ok).sum(axis=1).replace(0, np.nan)


def trailing_mean(y: pd.Series, idx) -> pd.Series:
    y = y.reindex(idx)
    return y.shift(1).rolling(TM_WINDOW, min_periods=TM_MIN).mean()


def leg_forecast(y: pd.Series, x: pd.Series, idx) -> pd.DataFrame:
    """Out-of-sample prediction for every month in idx. Columns: pred, tm6, x, a, b, c, mode."""
    y, x = y.reindex(idx), x.reindex(idx)
    tm = trailing_mean(y, idx)
    rows = []
    for i, d in enumerate(idx):
        r = {"pred": np.nan, "tm6": tm.iloc[i], "x": x.iloc[i], "a": np.nan, "b": np.nan, "c": np.nan,
             "mode": ""}
        if pd.isna(tm.iloc[i]):
            rows.append(r)
            continue
        use_x = pd.notna(x.iloc[i])
        cols = ["tm", "x"] if use_x else ["tm"]
        train = pd.DataFrame({"y": y.iloc[:i], "tm": tm.iloc[:i], "x": x.iloc[:i]}).dropna(subset=["y"] + cols)
        if len(train) < MIN_TRAIN:
            r.update(pred=tm.iloc[i], mode="6m trailing mean (short history)")
        else:
            X = np.column_stack([np.ones(len(train))] + [train[c].values for c in cols])
            beta, *_ = np.linalg.lstsq(X, train["y"].values, rcond=None)
            xi = np.array([1.0, tm.iloc[i]] + ([x.iloc[i]] if use_x else []))
            r.update(pred=float(xi @ beta), a=beta[0], b=beta[1], c=beta[2] if use_x else np.nan,
                     mode="trailing mean + regressor" if use_x else "trailing mean only (regressor not out)")
        rows.append(r)
    return pd.DataFrame(rows, index=idx)


def build(leaves, actual_line, nominal, levels, seasonal_adjust, through) -> dict | None:
    """Everything the nowcast needs: per-line model inputs, both legs' detail and the actual legs."""
    g_lines, r_line = gross_lines(leaves), receipts_line(leaves)
    if not g_lines or r_line is None:
        return None
    key = leaves.set_index("line")["key"]
    g_keys = [key[ln] for ln in g_lines if key[ln] in actual_line]
    r_key = key[r_line]
    if not g_keys or r_key not in actual_line:
        return None
    idx = pd.date_range(actual_line.index.min(), max(pd.Timestamp(through), actual_line.index.max()), freq="MS")
    y_g = leg_actual(actual_line, nominal, g_keys).reindex(idx)
    y_r = actual_line[r_key].reindex(idx)
    wage = (levels[WAGE_ID].pct_change(fill_method=None) * 100) if WAGE_ID in levels else pd.Series(dtype=float)
    ppi = levels[PPI_ID].pct_change(fill_method=None) * 100 if PPI_ID in levels else pd.Series(dtype=float)
    if len(ppi.dropna()) > 36:
        ppi = seasonal_adjust(ppi)
    g = leg_forecast(y_g, wage, idx)
    r = leg_forecast(y_r, ppi, idx)
    inputs = {ln: g["pred"] for ln in g_lines}
    inputs[r_line] = r["pred"]
    w_g = nominal[g_keys].shift(1).reindex(idx).sum(axis=1)
    w_r = nominal[r_key].shift(1).reindex(idx)
    return {"inputs": inputs, "gross": g, "receipts": r, "y_gross": y_g, "y_receipts": y_r,
            "w_gross": w_g, "w_receipts": w_r, "gross_lines": g_lines, "receipts_line": r_line}


def net(g, r, wg, wr):
    return (wg * g - wr * r) / (wg - wr)
