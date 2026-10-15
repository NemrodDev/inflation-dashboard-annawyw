"""Portfolio management & investment advice (PCE) under BEA's 2026 method.

Primary method ("handoff" recipe, PORTFOLIO_MGMT_HANDOFF.md):
  * Price (implicit deflator DPMIRG) m/m, in pp — fixed Huber-robust coefficients, not re-estimated:
        price_t = 0.017752 + 0.785998 x price_(t-1) + 6.154821 x ln(SPX_t/SPX_(t-1))
                  + 5.740161 x ln(TSY_(t-2)/TSY_(t-3))
    SPX = S&P 500 month-end close; TSY = Bloomberg US Treasury Total Return index (LUATTRUU) month-end.
    The return terms are raw log fractions (not x100); price_(t-1) is BEA's published line m/m in pp.
  * Real (DPMIRX) m/m: H = CES employment x average weekly hours (NAICS 52394, CES5552394001/2),
        E_t = (2/13) H_t + (11/13) E_(t-1)  (12-month EMA on levels),  real_t = 100 ln(E_t/E_(t-1)),
    holding H flat at its last value when the month isn't published yet.
  * Nominal = real + price.

Alternatives kept for comparison: the line's 3m average and simple equities − employment rules.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import requests

EMP_ID, HOURS_ID = "CES5552394001", "CES5552394002"          # NAICS 52394: employment, avg weekly hours
CES_IDS = [EMP_ID, HOURS_ID, "CES5552390001", "CES5552300001"]
EQUITY_FRED = "SP500"            # S&P 500 daily close (FRED keeps ~10 years)
YIELD_FRED = "DGS5"              # 5-year Treasury yield, last-resort bond-return proxy
GOVT_SYMBOL = "GOVT"             # iShares U.S. Treasury Bond ETF (tracks the Bloomberg US Treasury Index)
AV_URL = "https://www.alphavantage.co/query"
PROXY_DURATION = 5.9             # approx. modified duration of the US Treasury index (years)

COEF = {"const": 0.017752, "price_lag": 0.785998, "spx": 6.154821, "bond_lag2": 5.740161}

BOND_FILE = Path(__file__).resolve().parents[1] / "data" / "luattruu.csv"
BOND_SEED = {"2026-06-01": 2441.65, "2026-07-01": 2414.46}    # month-end levels from the handoff

MODELS = {
    "Handoff: price model (SPX + Treasury TR)": "handoff",
    "3m average (stand-in)": "trend3",
    "Equities − employment": "eq0",
    "Equities (1m lag) − employment": "eq1",
}


# ------------------------------------------------------------------ data
def fred_daily(series_id: str, fred_loader=None, fred_key=None) -> pd.Series:
    """Daily FRED series (API with key, else FRED's public CSV)."""
    s = None
    if fred_loader and fred_key:
        try:
            s, _ = fred_loader(series_id, fred_key)
        except Exception:  # noqa: BLE001
            s = None
    if s is None or s.dropna().empty:
        r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series_id},
                         timeout=(10, 60), headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ["date", "v"]
        s = pd.Series(pd.to_numeric(df["v"], errors="coerce").values, index=pd.to_datetime(df["date"]))
    return s.dropna().sort_index()


def month_end(daily: pd.Series) -> pd.Series:
    """Last observation of each month, indexed by month start."""
    m = daily.resample("MS").last()
    return m.dropna()


def govt_month_end(av_key: str) -> pd.Series:
    """GOVT month-end adjusted close (dividends reinvested) from Alpha Vantage, indexed by month start.
    The current, unfinished month is dropped."""
    r = requests.get(AV_URL, params={"function": "TIME_SERIES_MONTHLY_ADJUSTED", "symbol": GOVT_SYMBOL,
                                     "apikey": av_key}, timeout=(10, 60))
    r.raise_for_status()
    js = r.json()
    ts = js.get("Monthly Adjusted Time Series")
    if not ts:
        msg = js.get("Information") or js.get("Note") or js.get("Error Message") or "no data"
        raise RuntimeError(f"Alpha Vantage GOVT: {str(msg).replace(av_key, '•••')[:200]}")
    s = pd.Series({pd.Timestamp(d): float(v.get("5. adjusted close", np.nan)) for d, v in ts.items()}).sort_index()
    s.index = s.index.to_period("M").to_timestamp()
    s = s[s.index < pd.Timestamp.today().to_period("M").to_timestamp()]   # drop the month-to-date entry
    return s.dropna()


def load_bond_levels() -> pd.DataFrame:
    """User-entered LUATTRUU month-end levels (data/luattruu.csv), seeded from the handoff."""
    try:
        df = pd.read_csv(BOND_FILE, parse_dates=["month"])
    except Exception:  # noqa: BLE001
        df = pd.DataFrame({"month": pd.to_datetime(list(BOND_SEED)), "level": list(BOND_SEED.values())})
    df["level"] = pd.to_numeric(df["level"], errors="coerce")
    return df.dropna().sort_values("month").reset_index(drop=True)


def save_bond_levels(df: pd.DataFrame) -> None:
    d = df.copy()
    d["month"] = pd.to_datetime(d["month"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    d["level"] = pd.to_numeric(d["level"], errors="coerce")
    d = d.dropna().drop_duplicates("month", keep="last").sort_values("month")
    BOND_FILE.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(BOND_FILE, index=False, date_format="%Y-%m-%d")


def bond_returns(entered: pd.DataFrame, yields_daily: pd.Series | None, govt: pd.Series | None = None
                 ) -> tuple[pd.Series, pd.Series]:
    """Monthly log total return of the Treasury index, by priority:
      1. LUATTRUU month-end levels you entered (both month-ends needed),
      2. GOVT ETF month-end adjusted close (Alpha Vantage) — tracks the Bloomberg US Treasury Index,
      3. a proxy from the 5-year yield: r_t ~ y_(t-1)/12 - D x (y_t - y_(t-1)), D ~ 5.9.
    Returns (returns, source label per month)."""
    lv = pd.Series(pd.to_numeric(entered["level"], errors="coerce").values,
                   index=pd.DatetimeIndex(pd.to_datetime(entered["month"]))).dropna().sort_index()
    lv = lv[~lv.index.duplicated(keep="last")].asfreq("MS")      # gaps -> NaN, so no return across a gap
    r_user = np.log(lv / lv.shift(1)).dropna()
    r_proxy = pd.Series(dtype=float)
    if yields_daily is not None and len(yields_daily):
        y = month_end(yields_daily) / 100
        r_proxy = np.log(1 + y.shift(1) / 12 - PROXY_DURATION * (y - y.shift(1))).dropna()
    r_govt = pd.Series(dtype=float)
    if govt is not None and len(govt):
        g = govt.asfreq("MS")
        r_govt = np.log(g / g.shift(1)).dropna()
    idx = r_proxy.index.union(r_govt.index).union(r_user.index)
    r = r_proxy.reindex(idx)
    src = pd.Series("yield proxy", index=idx).where(r.notna())
    r.loc[r_govt.index] = r_govt
    src.loc[r_govt.index] = "GOVT ETF"
    r.loc[r_user.index] = r_user
    src.loc[r_user.index] = "LUATTRUU"
    return r, src


# ------------------------------------------------------------------ models
def handoff_price(y: pd.Series, spx_me: pd.Series, bond_r: pd.Series, through) -> pd.Series:
    """price_t for every month with inputs. price_(t-1) is BEA's published line m/m when available,
    otherwise this model's own previous prediction (for months beyond the last BEA release)."""
    spx_me = spx_me.asfreq("MS")
    spx_r = np.log(spx_me / spx_me.shift(1))
    b2 = bond_r.shift(2, freq="MS")           # bond return two calendar months before the target month
    idx = pd.date_range(min(y.dropna().index.min(), spx_r.dropna().index.min()), through, freq="MS")
    y, spx_r, b2 = y.reindex(idx), spx_r.reindex(idx), b2.reindex(idx)
    out = pd.Series(np.nan, index=idx)
    for i in range(1, len(idx)):
        p_prev = y.iloc[i - 1] if pd.notna(y.iloc[i - 1]) else out.iloc[i - 1]
        if pd.isna(p_prev) or pd.isna(spx_r.iloc[i]) or pd.isna(b2.iloc[i]):
            continue
        out.iloc[i] = (COEF["const"] + COEF["price_lag"] * p_prev + COEF["spx"] * spx_r.iloc[i]
                       + COEF["bond_lag2"] * b2.iloc[i])
    return out


def real_growth(emp: pd.Series, hours: pd.Series, through) -> pd.DataFrame:
    """Real m/m (%) from the CES employment-hours EMA; H held flat beyond its last published month."""
    H = (emp * hours).dropna()
    if H.empty:
        return pd.DataFrame(columns=["H", "E", "real", "H_held"])
    idx = pd.date_range(H.index.min(), max(pd.Timestamp(through), H.index.max()), freq="MS")
    held = ~idx.isin(H.index)
    H = H.reindex(idx).ffill()
    E = H.ewm(alpha=2 / 13, adjust=False).mean()           # E_t = 2/13 H_t + 11/13 E_(t-1)
    return pd.DataFrame({"H": H, "E": E, "real": 100 * np.log(E / E.shift(1)), "H_held": held}, index=idx)


def employment(levels: pd.DataFrame) -> tuple[pd.Series | None, str | None]:
    for sid in (EMP_ID, "CES5552390001", "CES5552300001"):
        if sid in levels.columns and levels[sid].notna().sum() > 24:
            return levels[sid].dropna(), sid
    return None, None


def candidates(y: pd.Series, spx_me: pd.Series, emp_lvl: pd.Series | None, bond_r: pd.Series, through
               ) -> pd.DataFrame:
    """Monthly m/m % predictions for the line, each using only information available at the time."""
    out = pd.DataFrame({"handoff": handoff_price(y, spx_me, bond_r, through)})
    idx = out.index
    yy = y.reindex(idx)
    out["trend3"] = yy.rolling(3, min_periods=1).mean().shift(1)
    eq = (spx_me.pct_change(fill_method=None) * 100).reindex(idx)
    if emp_lvl is not None:
        emp = (emp_lvl.pct_change(fill_method=None) * 100).reindex(idx).fillna(0)
        out["eq0"] = eq - emp
        out["eq1"] = eq.shift(1) - emp
    else:
        out["eq0"], out["eq1"] = eq, eq.shift(1)
    return out


def backtest(y: pd.Series, preds: pd.DataFrame, months: int = 36) -> pd.DataFrame:
    rows = []
    for lab, code in MODELS.items():
        if code not in preds:
            continue
        df = pd.DataFrame({"p": preds[code], "y": y}).dropna().iloc[-months:]
        if len(df) < 6:
            continue
        e = df["p"] - df["y"]
        rows.append({"Model": lab, "Months": len(df), "MAE (pp)": e.abs().mean(),
                     "RMSE (pp)": float(np.sqrt((e ** 2).mean())), "Bias (pp)": e.mean(),
                     "Correlation": df["p"].corr(df["y"])})
    return pd.DataFrame(rows)
