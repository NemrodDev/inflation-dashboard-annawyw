"""Plotly figure builders with one consistent look."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

PALETTE = ["#2E5BBA", "#E4572E", "#17A398", "#F3A712", "#8E5CC2", "#5C677D",
           "#D1495B", "#66A182", "#00798C", "#EDAE49", "#9C6644", "#3D5A80",
           "#B5838D", "#6D597A", "#43AA8B", "#F28482", "#577590", "#90BE6D",
           "#F9844A", "#4D908E", "#277DA1", "#F94144"]
TOTAL_COLOR = "#111111"


def _layout(fig, title, ytitle, height=420, legend_bottom=True):
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", font=dict(size=16)),
        height=height, margin=dict(l=10, r=10, t=50, b=10),
        hovermode="x unified", template="plotly_white",
        yaxis=dict(title=ytitle, zeroline=True, zerolinecolor="#999", ticksuffix=""),
        xaxis=dict(showgrid=False),
        legend=dict(orientation="h", yanchor="top", y=-0.12, x=0) if legend_bottom else None,
    )
    return fig


def _label_last(fig, items, fmt="{:.2f}"):
    """Write the value of each line's last data point just right of it.
    items: [(series, color)]. Labels that would overlap are nudged apart."""
    pts = []
    for s, color in items:
        s = pd.Series(s).dropna()
        if len(s):
            pts.append([s.index[-1], float(s.iloc[-1]), color])
    if not pts:
        return fig
    ys = [p[1] for p in pts]
    allv = np.concatenate([pd.Series(s).dropna().to_numpy(dtype=float) for s, _ in items
                           if pd.Series(s).notna().any()])
    gap = 0.06 * (np.nanmax(allv) - np.nanmin(allv) or 1.0)
    order = np.argsort(ys)
    placed = []
    for i in order:  # push each label up until it clears the one below
        y = pts[i][1]
        if placed and y < placed[-1] + gap:
            y = placed[-1] + gap
        placed.append(y)
        pts[i].append(y)
    for x, v, color, y in pts:
        fig.add_annotation(x=x, y=y, text=f"<b>{fmt.format(v)}</b>", showarrow=False,
                           xanchor="left", xshift=6, font=dict(color=color, size=12))
    fig.update_layout(margin=dict(r=60))
    return fig


def lines(df: pd.DataFrame, title: str, ytitle="%", hline=None, height=420, dash_cols=()):
    fig = go.Figure()
    for i, c in enumerate(df.columns):
        fig.add_trace(go.Scatter(
            x=df.index, y=df[c], name=str(c), mode="lines",
            line=dict(color=PALETTE[i % len(PALETTE)], width=2.2,
                      dash="dot" if c in dash_cols else "solid"),
            hovertemplate="%{y:.2f}"))
    if hline is not None:
        fig.add_hline(y=hline, line=dict(color="#888", dash="dash", width=1),
                      annotation_text=f"{hline:g}", annotation_position="left")
    fig = _layout(fig, title, ytitle, height)
    return _label_last(fig, [(df[c], PALETTE[i % len(PALETTE)]) for i, c in enumerate(df.columns)])


def bars(df: pd.DataFrame, title: str, ytitle="%", height=420, barmode="group"):
    fig = go.Figure()
    for i, c in enumerate(df.columns):
        fig.add_trace(go.Bar(x=df.index, y=df[c], name=str(c),
                             marker_color=PALETTE[i % len(PALETTE)], hovertemplate="%{y:.2f}"))
    fig.update_layout(barmode=barmode, bargap=0.15)
    return _layout(fig, title, ytitle, height)


def stacked_contrib(contrib: pd.DataFrame, total: pd.Series, title: str, ytitle="pp",
                    resid: pd.Series | None = None, total_name="Actual", height=480):
    fig = go.Figure()
    for i, c in enumerate(contrib.columns):
        fig.add_trace(go.Bar(x=contrib.index, y=contrib[c], name=str(c),
                             marker_color=PALETTE[i % len(PALETTE)], hovertemplate="%{y:.3f}"))
    if resid is not None and resid.notna().any():
        fig.add_trace(go.Bar(x=resid.index, y=resid, name="Residual / unallocated",
                             marker_color="#CCCCCC", hovertemplate="%{y:.3f}"))
    fig.add_trace(go.Scatter(x=total.index, y=total, name=total_name, mode="lines+markers",
                             line=dict(color=TOTAL_COLOR, width=2), marker=dict(size=5),
                             hovertemplate="%{y:.3f}"))
    fig.update_layout(barmode="relative", bargap=0.1)
    fig = _layout(fig, title, ytitle, height)
    return _label_last(fig, [(total, TOTAL_COLOR)])


def histogram(values: pd.Series, title: str, xtitle="%", center=None, weights=None, height=360):
    v = values.dropna()
    fig = go.Figure()
    if weights is not None:
        w = weights.reindex(v.index).fillna(0)
        bins = np.linspace(v.quantile(0.02), v.quantile(0.98), 31)
        h, e = np.histogram(v.clip(bins[0], bins[-1]), bins=bins, weights=w)
        fig.add_trace(go.Bar(x=(e[:-1] + e[1:]) / 2, y=h / max(h.sum(), 1e-9) * 100,
                             marker_color=PALETTE[0], name="weighted share"))
        ytitle = "% of weight"
    else:
        fig.add_trace(go.Histogram(x=v, nbinsx=40, marker_color=PALETTE[0], name="items"))
        ytitle = "# items"
    if center is not None:
        fig.add_vline(x=center, line=dict(color="#E4572E", dash="dash"))
    fig = _layout(fig, title, ytitle, height)
    fig.update_xaxes(title=xtitle)
    fig.update_layout(hovermode="closest", showlegend=False)
    return fig


def nowcast_backtest(nowcast: pd.Series, actual: pd.Series, title: str, height=420):
    fig = go.Figure()
    fig.add_trace(go.Bar(x=actual.index, y=actual, name="Actual (BEA)", marker_color="#B8C4D9"))
    fig.add_trace(go.Scatter(x=nowcast.index, y=nowcast, name="Nowcast (CPI/PPI mapping)",
                             mode="lines+markers", line=dict(color=PALETTE[1], width=2)))
    fig = _layout(fig, title, "% m/m", height)
    return _label_last(fig, [(nowcast, PALETTE[1])], "{:.3f}")
