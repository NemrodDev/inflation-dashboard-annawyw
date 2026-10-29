"""Section renderers shared by the CPI, PPI and PCE tabs."""
from __future__ import annotations

import itertools
import re
import warnings
from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

from core import analytics as A
from core import charts as C


# ------------------------------------------------------------------ helpers
_DOWNLOADS = itertools.count()


def fig_frame(fig) -> pd.DataFrame:
    """The data a Plotly chart plots: one column per line/bar series, keyed by the x value (date or
    category). Horizontal bars are keyed by their category; a histogram lists the values it plots."""
    cols, hist, horizontal = [], [], False
    for i, tr in enumerate(getattr(fig, "data", []) or []):
        name = (getattr(tr, "name", None) or f"series {i + 1}").strip()
        x, y = getattr(tr, "x", None), getattr(tr, "y", None)
        if getattr(tr, "type", "") == "histogram":
            v = x if x is not None else y
            if v is not None:
                hist.append(pd.Series(list(v), name=name))
            continue
        if x is None or y is None:
            continue
        if getattr(tr, "orientation", None) == "h":
            x, y, horizontal = y, x, True
        sr = pd.Series(list(y), index=list(x), name=name)
        cols.append(sr[~sr.index.duplicated(keep="last")])
    if not cols:
        return pd.concat(hist, axis=1) if hist else pd.DataFrame()
    out = pd.concat(cols, axis=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        idx = pd.to_datetime(pd.Series(out.index), errors="coerce")
    if not horizontal and idx.notna().all():
        out.index = pd.DatetimeIndex(idx)
        out = out.sort_index()
    xt = None if horizontal else getattr(getattr(getattr(fig.layout, "xaxis", None), "title", None), "text", None)
    out.index.name = xt or ("Date" if isinstance(out.index, pd.DatetimeIndex) else "Category")
    return out.reset_index()


def _fig_name(fig) -> str:
    t = getattr(getattr(fig.layout, "title", None), "text", None) or "chart"
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")[:60] or "chart"


def show(fig, name: str | None = None):
    """Draw a Plotly chart with a Download CSV button for its data underneath."""
    try:
        st.plotly_chart(fig, width="stretch")
    except TypeError:
        st.plotly_chart(fig, use_container_width=True)
    try:
        data = fig_frame(fig)
    except Exception:  # noqa: BLE001
        data = pd.DataFrame()
    if not data.empty:
        name = name or _fig_name(fig)
        st.download_button("⬇ Download CSV", data.to_csv(index=False).encode(),
                           file_name=f"{name}_{date.today():%Y-%m-%d}.csv", mime="text/csv",
                           key=f"dl_{name}_{next(_DOWNLOADS)}")


def numeric_columns(data: pd.DataFrame) -> list:
    """Columns holding numbers (bools excluded; object columns of numbers included)."""
    out = []
    for c in data.columns:
        s = data[c]
        if pd.api.types.is_bool_dtype(s):
            continue
        if pd.api.types.is_numeric_dtype(s):
            out.append(c)
        elif s.dtype == object:
            v = s.dropna()
            if len(v) and all(isinstance(x, (int, float, np.number)) and not isinstance(x, bool) for x in v):
                out.append(c)
    return out


def right_align_config(df, extra=None):
    """column_config right-aligning numeric cells in editable tables (st.data_editor).
    Streamlit's grid draws headers itself, so header alignment can't be set there."""
    data = getattr(df, "data", df)
    cfg = {}
    try:
        for c in numeric_columns(data):
            cfg[str(c)] = st.column_config.Column(alignment="right")
    except TypeError:  # older Streamlit without 'alignment'
        cfg = {}
    cfg.update(extra or {})
    return cfg


_TABLE_CSS = """
<style>
.infl-tbl {overflow:auto; border:1px solid #e3e6ea; border-radius:6px; margin-bottom:0.6rem;}
.infl-tbl table {border-collapse:collapse; width:100%; font-size:13px;
  font-variant-numeric: tabular-nums;}
.infl-tbl th, .infl-tbl td {padding:4px 10px; border-bottom:1px solid #eef0f3;
  white-space:nowrap; text-align:left;}
.infl-tbl thead th {position:sticky; top:0; z-index:1; background:#f6f7f9; font-weight:600;
  border-bottom:1px solid #d9dde3;}
.infl-tbl tbody tr:hover td {filter:brightness(0.97);}
</style>
"""


def show_df(df, hide_index=False, height=None, **_ignored):
    """Render a read-only table as HTML so numeric columns have right-aligned
    headers and cells. Accepts a DataFrame or a pandas Styler (keeps its colours)."""
    sty = df if hasattr(df, "to_html") and hasattr(df, "data") else None
    data = sty.data if sty is not None else df
    if sty is None:
        num = numeric_columns(data)
        fmt = {c: ("{:,.0f}" if pd.api.types.is_integer_dtype(data[c]) else "{:.2f}") for c in num}
        sty = data.style.format(fmt, na_rep="–")
    num = numeric_columns(data)
    pos = {c: i for i, c in enumerate(data.columns)}
    styles = []
    for c in num:
        j = pos[c]
        styles += [{"selector": f"th.col_heading.col{j}", "props": "text-align: right;"},
                   {"selector": f"td.col{j}", "props": "text-align: right;"}]
    sty = sty.set_table_styles(styles, overwrite=False)
    if hide_index:
        sty = sty.hide(axis="index")
    max_h = f"max-height:{int(height)}px;" if height else "max-height:640px;"
    html = f'{_TABLE_CSS}<div class="infl-tbl" style="{max_h}">{sty.to_html()}</div>'
    if hasattr(st, "html"):
        st.html(html)
    else:
        st.markdown(html, unsafe_allow_html=True)


def win(obj):
    """Clip a time-indexed object to the sidebar chart window."""
    start = st.session_state.get("win_start")
    if start is None:
        return obj
    return obj.loc[obj.index >= pd.Timestamp(start)]


def _style_map(styler, fn, subset):
    return styler.map(fn, subset=subset) if hasattr(styler, "map") else styler.applymap(fn, subset=subset)


def section(num, title, help_text=None):
    st.markdown(f"### {num}. {title}")
    if help_text:
        st.caption(help_text)


def latest_valid(s: pd.Series):
    s = s.dropna()
    return (s.index[-1], s.iloc[-1]) if len(s) else (None, np.nan)


# ------------------------------------------------------------------ snapshot
def render_snapshot(ds: A.Dataset, extra: dict | None = None):
    """KPI strip for the latest month: m/m, y/y, 3m ann. for headline, core (+extras)."""
    keys = {"Headline": ds.headline, "Core": ds.core}
    keys.update(extra or {})
    m, y, a3 = A.mom(ds.idx), A.yoy(ds.idx), A.annualized(ds.idx, 3)
    d, _ = latest_valid(m[ds.headline])
    if d is None:
        st.warning("No data.")
        return
    st.markdown(f"**Latest month: {d:%B %Y}**")
    cols = st.columns(len(keys))
    for col, (lab, k) in zip(cols, keys.items()):
        if k not in m.columns:
            continue
        for lab2, ser in (("y/y", y[k].dropna()), ("m/m", m[k].dropna())):
            cur = ser.iloc[-1] if len(ser) else np.nan
            prev = ser.iloc[-2] if len(ser) > 1 else np.nan
            col.metric(f"{lab} {lab2}", f"{cur:.2f}%", f"{cur - prev:+.2f} pp vs prior",
                       delta_color="inverse")
        aa = a3[k].dropna()
        col.caption(f"3m annualised {aa.iloc[-1]:.2f}%" if len(aa) else "")
    for n in ds.notes:
        st.caption(f"ℹ️ {n}")


# ------------------------------------------------------------------ 1. release table
def render_release_table(ds: A.Dataset, num=1):
    section(num, "Release table — m/m % change, seasonally adjusted",
            f"Heat map centred on {ds.heat_center:.3f}% m/m (≈2% annualised): red = hotter, blue = cooler. "
            "Weight = share of headline (%), price-updated from the last relative-importance vintage.")
    c1, c2 = st.columns([3, 1])
    view = c1.selectbox("Table", list(ds.views), key=f"{ds.name}_view")
    n = c2.slider("Months", 6, 24, 13, key=f"{ds.name}_tbl_n")
    t = A.release_table(ds, view, n)
    mcols = [c for c in t.columns if c not in ("Code", "Item", "Weight", "3m ann.", "6m ann.", "YoY")]
    acols = ["3m ann.", "6m ann.", "YoY"]
    sty = t.style.format({c: "{:.2f}" for c in mcols + acols + ["Weight"]}, na_rep="–")
    sty = _style_map(sty, lambda v: A.heat_color(v, ds.heat_center, ds.heat_scale), mcols)
    sty = _style_map(sty, lambda v: A.heat_color(v, 2.0, 3.0), acols)
    sty = sty.set_properties(subset=["Item"], **{"text-align": "left", "white-space": "pre"})
    show_df(sty, hide_index=True, height=min(38 * (len(t) + 1), 900))
    st.download_button("Download table (CSV)", t.to_csv(index=False).encode(),
                       f"{ds.name.lower()}_release_table.csv", "text/csv", key=f"{ds.name}_dl")


# ------------------------------------------------------------------ 2. aggregates
def render_aggregates(ds: A.Dataset, num=2):
    section(num, "Key aggregates — y/y and m/m (SA)")
    opts = [k for k in ds.aggregates if ds.has(k)]
    default = opts[:2]
    sel = st.multiselect("Series", opts, default=default, format_func=ds.label, key=f"{ds.name}_agg")
    if not sel:
        return
    y = win(A.yoy(ds.idx[sel])).rename(columns=ds.label)
    m = win(A.mom(ds.idx[sel])).rename(columns=ds.label)
    c1, c2 = st.columns(2)
    with c1:
        show(C.lines(y, "Year-over-year %", "% y/y", hline=2.0))
    with c2:
        if len(sel) <= 2:
            show(C.bars(m, "Month-over-month % (SA)", "% m/m"))
        else:
            show(C.lines(m, "Month-over-month % (SA)", "% m/m"))


# ------------------------------------------------------------------ 3. contributions
def render_contributions(ds: A.Dataset, num=3):
    section(num, "Contributions — line items adding up to core and to headline",
            "Contribution = previous-month weight × item m/m. Grey bar = gap between the published "
            "aggregate and the sum of contributions (rounding, weight approximation, chain effects).")
    c1, c2, c3 = st.columns(3)
    targets = ["Core", "Headline"] + [t for t in ds.specs if t not in ("Core", "Headline")]
    target = c1.radio("Target", targets, horizontal=True, key=f"{ds.name}_ct_t")
    levels = list(ds.specs[target])
    level = c2.radio("Granularity", levels, horizontal=True, key=f"{ds.name}_ct_l")
    horizon = c3.radio("Horizon", ["m/m", "12m"], horizontal=True, key=f"{ds.name}_ct_h",
                       help="12m = sum of the last 12 monthly contributions (≈ y/y contribution)")
    df, actual, resid = A.contributions(ds, target, level, horizon)
    if df.dropna(how="all").empty:
        st.info("Not enough data for contributions.")
        return
    tgt_name = ds.label(A.target_key(ds, target))
    span = st.slider("Months shown", 12, 120, 36 if horizon == "m/m" else 60, key=f"{ds.name}_ct_n")
    dfw, aw, rw = (x.dropna(how="all").iloc[-span:] if isinstance(x, pd.DataFrame)
                   else x.dropna().iloc[-span:] for x in (df, actual, resid))
    unit = "pp of " + target.lower()
    show(C.stacked_contrib(dfw, aw.reindex(dfw.index), f"Contributions to {tgt_name} ({horizon})",
                           unit, rw.reindex(dfw.index)))
    last = df.dropna(how="all").iloc[-3:].T * 100
    last.columns = [f"{d:%b %y} (bp)" for d in last.columns]
    last = last.sort_values(last.columns[-1], ascending=False)
    with st.expander("Latest contributions (basis points)"):
        show_df(last.style.format("{:.1f}"))


# ------------------------------------------------------------------ 4. diffusion
def render_diffusion(ds: A.Dataset, num=4, keys=None, caption=None):
    section(num, "Diffusion — share of line items with inflation above a threshold",
            caption or f"Universe: {len(keys or ds.diffusion_keys)} item-level series.")
    c1, c2, c3 = st.columns(3)
    thr = c1.slider("Threshold (% annualised)", 0.0, 6.0, 3.0, 0.5, key=f"{ds.name}_df_thr")
    weighted = c2.toggle("Expenditure-weighted", False, key=f"{ds.name}_df_w",
                         help="Weights items by their share of the headline (where available)")
    show3 = c3.toggle("Show 3m annualised", False, key=f"{ds.name}_df_3")
    k = keys or ds.diffusion_keys
    d = A.diffusion(ds.idx, k, thr, ds.weights if weighted else None)
    cols = ["6m annualized", "12m"] + (["3m annualized"] if show3 else [])
    plot = win(d[cols]).rename(columns=lambda c: f"Share with {c} > {thr:g}%")
    show(C.lines(plot, f"Diffusion: share of items above {thr:g}%", "% of items", hline=50))


# ------------------------------------------------------------------ 5. annualized rates
def render_annualized(ds: A.Dataset, num=5, extra_keys=()):
    section(num, "Momentum — 1m, 3m, 6m annualised and 12m change")
    opts = [k for k in list(ds.aggregates) + list(extra_keys) if ds.has(k)]
    opts = list(dict.fromkeys(opts))
    k = st.selectbox("Series", opts, index=min(1, len(opts) - 1), format_func=ds.label,
                     key=f"{ds.name}_ann")
    r = win(A.rates_table(ds.idx[k]))
    show(C.lines(r, f"{ds.label(k)} — annualised rates", "% ann.", hline=2.0, dash_cols=("1m ann.",)))
    rows = []
    for key in opts:
        rt = A.rates_table(ds.idx[key]).dropna(how="all")
        if len(rt):
            rows.append(pd.Series(rt.iloc[-1], name=ds.label(key)))
    if rows:
        tbl = pd.DataFrame(rows)
        sty = _style_map(tbl.style.format("{:.2f}"), lambda v: A.heat_color(v, 2.0, 3.0), list(tbl.columns))
        st.caption("Latest annualised rates across aggregates")
        show_df(sty)


# ------------------------------------------------------------------ extras
def render_distribution(ds: A.Dataset, num, keys=None, mover_keys=None):
    section(num, "Breadth of this month's print",
            "Distribution of item-level m/m changes (annualised) and the items whose contribution "
            "differs most from their own 12-month average.")
    k = [x for x in (keys or ds.diffusion_keys) if x in ds.idx.columns]
    m = A.annualized(ds.idx[k], 1)
    d, _ = latest_valid(m.median(axis=1))
    c1, c2 = st.columns([1, 1])
    with c1:
        if d is not None:
            v = m.loc[d]
            wt = ds.weights.reindex(columns=k).loc[d] if st.toggle(
                "Weight by importance", False, key=f"{ds.name}_hist_w") else None
            show(C.histogram(v, f"Item m/m annualised, {d:%b %Y}", "% ann.", center=2.0, weights=wt))
            st.caption(f"Median {v.median():.1f}% · share above 2%: {(v > 2).mean() * 100:.0f}% "
                       f"· share negative: {(v < 0).mean() * 100:.0f}%")
    with c2:
        mv = A.top_movers(ds, mover_keys or k, n=10)
        if not mv.empty:
            show_df(mv.style.format({c: "{:.1f}" for c in mv.columns if "bp" in c} | {"m/m %": "{:.2f}"}),
                    hide_index=True)


def render_fred(series: list, fred_key: str | None, num, title, loader):
    section(num, title)
    if not fred_key:
        st.info("Add FRED_API_KEY to secrets to show alternative underlying-inflation measures.")
        return
    frames, errs = {}, []
    for sid in series:
        try:
            s, meta = loader(sid, fred_key)
            frames[f"{meta['title']} [{meta['units']}]"] = s
        except Exception as e:  # noqa: BLE001
            errs.append(f"{sid}: {e}")
    if frames:
        df = win(pd.DataFrame(frames))
        show(C.lines(df, title, "%", hline=2.0, height=460))
    for e in errs:
        st.caption(f"⚠️ {e}")


# ------------------------------------------------------------------ sortable compact table
_SORT_HTML = """<!doctype html><html><head><meta charset="utf-8">
<style>
body {margin:0; font-family:'Source Sans Pro','Source Sans 3',sans-serif; color:#1f2328; background:#fff;}
.wrap {overflow:auto; max-height:__H__px; border:1px solid #e3e6ea; border-radius:6px; display:inline-block;
  max-width:100%;}
table {border-collapse:collapse; width:auto; font-size:13px; font-variant-numeric:tabular-nums;}
th, td {padding:3px 8px; border-bottom:1px solid #eef0f3; text-align:left; vertical-align:top;
  white-space:nowrap;}
td.wrap-col {white-space:normal; min-width:120px; max-width:__W__px;}
th {position:sticky; top:0; z-index:1; background:#f6f7f9; font-weight:600; border-bottom:1px solid #d9dde3;
  cursor:pointer; user-select:none;}
th:hover {background:#eceff3;}
th .arr {color:#8a9099; font-size:10px; margin-left:3px;}
.num {text-align:right;}
tbody tr:hover td {background:#f7f8fa;}
</style></head><body><div class="wrap"><table id="t"><thead><tr>__HEAD__</tr></thead>
<tbody>__BODY__</tbody></table></div>
<script>
const t=document.getElementById('t'), ths=t.tHead.rows[0].cells; let col=-1, asc=true;
for (let i=0;i<ths.length;i++) ths[i].addEventListener('click',()=>{
  asc = (col===i) ? !asc : true; col=i;
  const num = ths[i].dataset.num==='1', rows=[...t.tBodies[0].rows];
  const key = r => {const v=r.cells[i].dataset.v; return num ? (v===''? null : parseFloat(v)) : v.toLowerCase();};
  rows.sort((a,b)=>{const x=key(a), y=key(b);
    if (x===null||x==='') return 1; if (y===null||y==='') return -1;   // blanks always last
    return (x<y?-1:x>y?1:0)*(asc?1:-1);});
  rows.forEach(r=>t.tBodies[0].appendChild(r));
  for (const h of ths) h.querySelector('.arr').textContent='↕';
  ths[i].querySelector('.arr').textContent = asc ? '▲' : '▼';
});
</script></body></html>"""


def sortable_table(df: pd.DataFrame, fmt: dict | None = None, wrap_cols=(), wrap_width=300,
                   max_height=640, heat: dict | None = None):
    """Compact HTML table: click a heading to sort (again to reverse); columns as narrow as their
    content; numeric columns and headings right-aligned; long text columns wrap at wrap_width px."""
    import streamlit.components.v1 as components
    doc, h = sortable_doc(df, fmt, wrap_cols, wrap_width, max_height, heat)
    components.html(doc, height=h + 6, scrolling=False)


def sortable_doc(df, fmt=None, wrap_cols=(), wrap_width=300, max_height=640, heat=None):
    """heat: {column: (center, scale)} -> diverging red (above center) / blue (below) cell colours."""
    import html as _h
    fmt, heat = fmt or {}, heat or {}
    est = 30   # header; rows: one line (21px) plus extra lines where wrapped text overflows
    for _, r in df.iterrows():
        lines = max([1] + [-(-len(str(r[c])) * 6.3 // max(wrap_width - 16, 50)) for c in wrap_cols if c in df])
        est += 22 + 16 * (int(lines) - 1)
    height = int(min(max_height, est + 12))
    num = set(numeric_columns(df))
    head = "".join(f'<th class="{"num" if c in num else ""}" data-num="{int(c in num)}">{_h.escape(str(c))}'
                   f'<span class="arr">↕</span></th>' for c in df.columns)
    body = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            blank = v is None or (not isinstance(v, str) and pd.isna(v))
            shown = "–" if blank else (fmt[c].format(v) if c in fmt else str(v))
            key = "" if blank else (repr(float(v)) if c in num else str(v))
            cls = "num" if c in num else ("wrap-col" if c in wrap_cols else "")
            sty = A.heat_color(float(v), *heat[c]) if c in heat and not blank else ""
            cells.append(f'<td class="{cls}" style="{sty}" data-v="{_h.escape(key, quote=True)}">'
                         f'{_h.escape(shown)}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    doc = (_SORT_HTML.replace("__HEAD__", head).replace("__BODY__", "".join(body))
           .replace("__H__", str(height)).replace("__W__", str(wrap_width)))
    return doc, height
