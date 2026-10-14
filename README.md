# Inflation dashboard (CPI · PPI · PCE · nowcast)

Streamlit app with one tab per measure and a CPI/PPI → PCE nowcast tab.

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # add your keys
streamlit run app.py
```

Without keys the app opens in **Demo mode** (synthetic data with the real structure),
so you can check the layout before wiring up APIs. Free keys: BLS (registration
needed for 50 series/query and 20 years), BEA (required for PCE), FRED (optional,
for the Cleveland/Atlanta/Dallas Fed alternative measures).

## What each tab shows

| # | CPI | PPI (final demand) | PCE |
|---|-----|-----|-----|
| 1 | Release table, m/m SA with heat map (Table A view + full SA item hierarchy) | FD-ID table | Table 2.8.4 + full underlying detail (2.4.4U) |
| 2 | y/y and m/m of key aggregates | same | same |
| 3 | Contributions to core and headline (major / detailed; m/m or 12m) | same | same |
| 4 | Diffusion: share of items with 6m ann. / 12m > threshold (default 3%) | same, SA commodity indexes | same, most-detailed BEA lines (core-only toggle) |
| 5 | 1m / 3m / 6m annualised and 12m | same | same |
| 6 | AI categories: software, computers & peripherals, TVs, phones — contribution to CPI | PPIs that feed PCE (physicians, hospitals, airfares, portfolio mgmt) | Supercore, goods vs services |
| 7 | Supercore and goods vs services, contributions to supercore | Breadth of the print | Breadth of the print |
| 8 | Breadth of the print (item distribution + top movers vs 12m average) | | Dallas Fed trimmed mean (FRED) |
| 9 | Cleveland Fed median / trimmed mean, Atlanta Fed sticky core (FRED) | | |

Every tab opens with a KPI strip (latest m/m, y/y, 3m annualised for headline, core and
supercore).

**Nowcast tab** (line by line, on BEA's own source table):
- `config/Detail_CPI_PCE_mapping.xlsx` (BEA Table 2.4.4U-D) decides which price feeds each of
  the 354 PCE lines. `config/pce_source_series.py` only translates BEA's source names into
  BLS series IDs (CPI codes from the BLS item list; PPI ids marked VERIFY are best matches).
- BEA's 2026 annual-update changes are applied on top (toggle): portfolio management →
  implicit price (CES quantity extrapolator, so it uses the line's trend); legal services →
  PPIs from 2024 (PPI offices of lawyers as stand-in, BEA doesn't name its PPIs); computer
  software → CPI software + PPI game software publishing + PPI hosting/ASP (equal weights).
- Weights = last month's nominal spending by line (Table 2.4.5U), signed for "Less:" lines;
  core excludes the food and energy subtrees.
- Lines BEA prices from non-CPI/PPI data use the line's own recent trend (choice of method).
- Inputs BEA seasonally adjusts itself ("SA by BEA") get a simple 5-year seasonal correction.
- Override any input series for the target month; backtest vs published PCE plus a
  "replication" check that aggregates BEA's own line prices to validate the structure.

## Things to maintain

- **Weights.** CPI and PPI relative importances in `config/cpi.py` and `config/ppi.py`
  are approximate. Update them each year (CPI in January, PPI in February), or drop
  `config/cpi_relative_importance.csv` / `config/ppi_relative_importance.csv` with
  columns `code,relative_importance` to override. PCE weights come from BEA nominal
  spending, so they are exact.
- **Nowcast mapping.** Replace `config/Detail_CPI_PCE_mapping.xlsx` when BEA updates Table
  2.4.4U-D; add any new source names to `config/pce_source_series.py` (the Diagnostics
  expander lists series BLS doesn't return).
- **Series IDs.** Any series BLS doesn't return is listed under the KPI strip; the
  rest of the tab still works.

## How the numbers are built

- Contributions = previous-month weight × item m/m. CPI/PPI weights are relative
  importances updated for relative price change since December (the BLS method);
  PCE uses last month's nominal shares. The grey bar is the unallocated gap.
- "12m" contributions sum the last 12 monthly contributions (≈ y/y contribution).
- CPI supercore = services less energy services minus shelter, rebuilt from weighted m/m.
- PCE hierarchy (for indentation and diffusion leaves) is reconstructed from nominal
  spending because the BEA API doesn't report indentation.
- Months BLS didn't publish (e.g. October 2025) show as gaps; the following month's
  m/m is also blank because there is no prior level to compare with.
- Raw API responses are cached on disk in `.cache/` for 6 hours ("Refresh data" clears it).

## Layout

```
app.py                 sidebar, data loading, tabs
config/                series lists, weights, contribution specs, nowcast mapping
core/sources.py        BLS / BEA / FRED clients + disk cache (no streamlit)
core/builders.py       turns raw data into Dataset objects
core/analytics.py      rates, weights, contributions, diffusion, release table
core/pce_map.py        line-level nowcast engine (BEA workbook)
core/demo.py           synthetic data
core/charts.py         plotly figures
tabs/                  one module per tab
tests/smoke_test.py    analytics on demo data
```
