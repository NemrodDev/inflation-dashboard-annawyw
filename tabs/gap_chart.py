"""Horizontal bars: PCE minus CPI contributions to core inflation, by category.

Monthly (m/m) gaps for the months selected are stacked in each category's bar; the 12-month (y/y) gap
can be shown alongside as a diamond marker (it is on a different basis, so it is never added to the
monthly bars). Only totals are labelled."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from core import charts as C

# latest first: the newest month is always blue, the one before amber, then muted tones
MONTH_COLORS = ["#2E8BEA", "#F3A712", "#9AA5B1", "#C9B79C", "#B5838D", "#6D597A",
                "#66A182", "#E4572E", "#8E5CC2", "#5C677D", "#D1B3C4", "#17A398"]
YY_COLOR = "#111111"


def figure(gap: pd.DataFrame | None, labels: list[str], title: str, height=None,
           yy: pd.Series | None = None, yy_label: str = "12-month (y/y) gap"):
    """gap: rows = categories (+ 'Total'), columns = months oldest first, values pp (m/m); may be empty.
    yy: optional 12-month gap by category (+ 'Residual', 'Total'), pp. With no months it is drawn as bars."""
    gap = gap if gap is not None else pd.DataFrame()
    rows = list(dict.fromkeys(list(gap.index) + (list(yy.index) if yy is not None else [])))
    fixed = [r for r in ("Residual", "Total") if r in rows]            # kept at the top, in this order
    m = gap.reindex(rows).fillna(0.0) if len(gap.columns) else pd.DataFrame(index=rows)
    y = yy.reindex(rows) if yy is not None else None
    key = (y.fillna(0) if y is not None else m.sum(axis=1)).drop(fixed)
    order = list(key.sort_values().index) + fixed                       # largest positive at the top
    m, y = m.loc[order], (y.loc[order] if y is not None else None)
    ylab = ["Total (core PCE − core CPI)" if r == "Total" else r for r in order]

    fig = go.Figure()
    n = len(m.columns)
    if n == 0 and y is not None:                                        # y/y only: bars
        fig.add_trace(go.Bar(y=ylab, x=y, orientation="h", name=yy_label, marker_color=MONTH_COLORS[0],
                             text=[f"{v:+.2f}" for v in y.fillna(0)], textposition="outside", cliponaxis=False,
                             textfont=dict(size=11),
                             hovertemplate="%{y}: %{x:+.3f} pp<extra>" + yy_label + "</extra>"))
    for i, col in enumerate(m.columns):
        fig.add_trace(go.Bar(
            y=ylab, x=m[col], orientation="h", name=f"{labels[i]} (m/m)",
            marker_color=MONTH_COLORS[(n - 1 - i) % len(MONTH_COLORS)],
            text=[f"{v:+.2f}" for v in m[col]] if (n == 1 and y is None) else None,
            textposition="outside", cliponaxis=False, textfont=dict(size=11),
            hovertemplate="%{y}: %{x:+.3f} pp<extra>" + labels[i] + " (m/m)</extra>"))
    if n > 1 or (n >= 1 and y is not None):                             # total of the months selected
        tot = m.sum(axis=1)
        fig.add_trace(go.Scatter(y=ylab, x=tot, mode="markers+text",
                                 name="Sum of the months selected (m/m)" if n > 1 else f"{labels[0]} total (m/m)",
                                 marker=dict(symbol="line-ns-open", size=14, color="#555", line=dict(width=2)),
                                 text=[f"{v:+.2f}" for v in tot], textposition="middle left",
                                 textfont=dict(size=11, color="#555"),
                                 hovertemplate="%{y}: %{x:+.3f} pp (months selected, m/m)<extra></extra>"))
    if n >= 1 and y is not None:                                        # y/y alongside: diamonds
        fig.add_trace(go.Scatter(y=ylab, x=y, mode="markers+text", name=yy_label,
                                 marker=dict(symbol="diamond", size=11, color=YY_COLOR),
                                 text=[f"{v:+.2f}" if pd.notna(v) else "" for v in y], textposition="middle right",
                                 textfont=dict(size=11, color=YY_COLOR),
                                 hovertemplate="%{y}: %{x:+.3f} pp (y/y)<extra></extra>"))
    fig = C._layout(fig, title, "", height or max(420, 26 * len(order) + 120))
    if n:
        xt = "PCE − CPI contributions to core inflation (pp): bars = m/m for the months selected" + \
            ("; diamonds = 12-month (y/y) gap" if y is not None else "")
    else:
        xt = "PCE y/y contributions − CPI y/y contributions (pp)"
    fig.update_layout(barmode="relative", hovermode="closest",
                      xaxis=dict(title=xt, zeroline=True, zerolinecolor="#555", showgrid=True),
                      yaxis=dict(title=None, automargin=True, tickfont=dict(size=12)))
    return fig


def month_buttons(container, months: list, label_of, key: str, yy_option: str):
    """Toggle buttons for each month (latest first) plus the y/y gap. Returns (months picked oldest first,
    y/y picked?)."""
    opts = [label_of(d) for d in reversed(months)] + [yy_option]
    default = [label_of(months[-1])]
    try:
        picked = container.pills("Show on the chart (click to add or remove)", opts, selection_mode="multi",
                                 default=default, key=key)
    except (AttributeError, TypeError):                                 # older Streamlit without st.pills
        picked = container.multiselect("Show on the chart", opts, default=default, key=key)
    picked = picked or []
    chosen = [d for d in months if label_of(d) in picked]
    return chosen, yy_option in picked
