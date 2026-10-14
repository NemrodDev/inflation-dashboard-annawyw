"""Helpers shared by the nowcast tab."""
from __future__ import annotations

import numpy as np
import pandas as pd


def backtest_stats(nc: pd.Series, actual: pd.Series, months=36):
    df = pd.concat([nc.rename("nc"), actual.rename("act")], axis=1).dropna().iloc[-months:]
    if df.empty:
        return {}
    err = df.nc - df.act
    return {"months": len(df), "MAE (pp)": err.abs().mean(), "Bias (pp)": err.mean(),
            "RMSE (pp)": float(np.sqrt((err ** 2).mean())),
            "Hit rate ±0.05pp (%)": float((err.abs() <= 0.05).mean() * 100),
            "Corr": df.nc.corr(df.act)}


def implied_yoy(actual_index: pd.Series, nowcast_m: pd.Series) -> pd.Series:
    """Extend the published index with nowcast months beyond its last observation."""
    lvl = actual_index.dropna().copy()
    last = lvl.index.max()
    for d, v in nowcast_m.loc[nowcast_m.index > last].dropna().items():
        lvl.loc[d] = lvl.iloc[-1] * (1 + v / 100)
    return lvl.sort_index()
