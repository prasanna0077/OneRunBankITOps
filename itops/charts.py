"""Plotly figures for the OneRun Bank IT Operations app. No Streamlit calls."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

ACCENT = "#1D4ED8"
GREY = "#94A3B8"
INK = "#0F172A"
MUTED = "#475569"
GRID = "#E2E8F0"
ORANGE = "#C2410C"
SEV_COLOUR = {"P1": "#9F1239", "P2": "#C2410C", "P3": "#64748B", "P4": "#CBD5E1"}
TYPE_COLOUR = {"Incidents": ACCENT, "Service requests": "#64748B", "Changes": "#0F766E", "New vulns": "#C2410C"}


def _layout(fig: go.Figure, height: int = 360, title: str | None = None, **kw) -> go.Figure:
    if title:
        fig.update_layout(title=dict(text=title, x=0, xanchor="left", font=dict(size=15, color=INK)))
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=56 if title else 16, b=8),
        font=dict(family="IBM Plex Sans, Segoe UI, Helvetica, Arial, sans-serif", size=13, color=INK),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hoverlabel=dict(font_size=12),
        **kw,
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    return fig


def hbar(s: pd.Series, title: str | None = None, highlight: int = 1, height: int | None = None,
         suffix: str = "", extra: pd.Series | None = None, extra_label: str = "") -> go.Figure:
    """Horizontal bars, largest on top; the first `highlight` bars in the accent colour."""
    s = s.sort_values(ascending=True)
    n = len(s)
    colours = [ACCENT if k >= n - highlight else GREY for k in range(n)]
    text = [f"{v:,.0f}{suffix}" for v in s.values]
    if extra is not None:
        text = [f"{t} ({int(extra.get(idx, 0))} {extra_label})" for t, idx in zip(text, s.index)]
    fig = go.Figure(go.Bar(x=s.values, y=[str(x) for x in s.index], orientation="h", marker_color=colours,
                           text=text, textposition="outside", cliponaxis=False,
                           hovertemplate="%{y}: %{x:,}" + suffix + "<extra></extra>"))
    fig.update_xaxes(showticklabels=False, showgrid=False, range=[0, (s.max() if n else 1) * 1.28])
    fig.update_yaxes(showgrid=False)
    fig.update_layout(showlegend=False, bargap=0.3)
    return _layout(fig, height or max(220, 30 * n + 70), title)


def monthly_trend(inc: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, title: str | None = None) -> go.Figure:
    m = inc.assign(M=inc["Date"].dt.to_period("M"))
    tot = m.groupby("M").size()
    p1 = m[m["Severity"] == "P1"].groupby("M").size().reindex(tot.index, fill_value=0)
    labels = [p.strftime("%b %y") for p in tot.index]
    sel = [(p.end_time >= start) and (p.start_time <= end) for p in tot.index]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=tot.values, name="All incidents",
                         marker_color=[ACCENT if s else GREY for s in sel], opacity=0.85,
                         hovertemplate="%{x}: %{y:,} incidents<extra></extra>"))
    fig.add_trace(go.Scatter(x=labels, y=p1.values, name="P1 incidents", yaxis="y2", mode="lines+markers+text",
                             text=[str(v) for v in p1.values], textposition="top center",
                             line=dict(color="#9F1239", width=2.5), marker=dict(size=7),
                             hovertemplate="%{x}: %{y} P1<extra></extra>"))
    fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, rangemode="tozero",
                                  title=dict(text="P1"), range=[0, max(1, p1.max()) * 1.35]))
    fig.update_yaxes(title_text="Incidents", rangemode="tozero")
    return _layout(fig, 340, title)


def heatmap(df: pd.DataFrame, title: str | None = None, fmt: str = "d", colorscale: str = "Blues",
            zmin=None, zmax=None, height: int | None = None, x_title: str = "", y_title: str = "") -> go.Figure:
    z = df.values.astype(float)
    text = [[(f"{v:.2f}" if fmt == ".2f" else f"{v:,.0f}") for v in row] for row in z]
    fig = go.Figure(go.Heatmap(z=z, x=[str(c) for c in df.columns], y=[str(i) for i in df.index],
                               colorscale=colorscale, zmin=zmin, zmax=zmax, text=text, texttemplate="%{text}",
                               textfont=dict(size=13), showscale=False, xgap=3, ygap=3,
                               hovertemplate="%{y} × %{x}: %{text}<extra></extra>"))
    fig.update_yaxes(autorange="reversed", showgrid=False, title_text=y_title)
    fig.update_xaxes(showgrid=False, side="top", title_text=x_title)
    return _layout(fig, height or 70 + 44 * len(df.index), title)


def stacked_lob(matrix: pd.DataFrame, cols: list[str], title: str | None = None) -> go.Figure:
    m = matrix.sort_values(cols[0], ascending=True)
    fig = go.Figure()
    for c in cols:
        fig.add_trace(go.Bar(y=list(m.index), x=m[c].values, name=c, orientation="h",
                             marker_color=TYPE_COLOUR.get(c, GREY),
                             hovertemplate="%{y} · " + c + ": %{x:,}<extra></extra>"))
    fig.update_layout(barmode="stack", bargap=0.25)
    fig.update_xaxes(title_text="Tickets")
    return _layout(fig, 90 + 26 * len(m), title)


def severity_bars(i: pd.DataFrame, by: str, top: int = 12, title: str | None = None) -> go.Figure:
    ct = pd.crosstab(i[by], i["Severity"]).reindex(columns=["P1", "P2", "P3", "P4"], fill_value=0)
    ct = ct.loc[ct.sum(axis=1).sort_values(ascending=False).index[:top]].iloc[::-1]
    fig = go.Figure()
    for sev in ["P1", "P2", "P3", "P4"]:
        fig.add_trace(go.Bar(y=list(ct.index), x=ct[sev].values, name=sev, orientation="h",
                             marker_color=SEV_COLOUR[sev], hovertemplate="%{y} · " + sev + ": %{x}<extra></extra>"))
    fig.update_layout(barmode="stack", bargap=0.25)
    return _layout(fig, 90 + 28 * len(ct), title)


def layer_bars(ls: pd.DataFrame, title: str | None = None) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=list(ls.index), y=ls["Incidents"].values, name="Incidents", marker_color=GREY,
                         text=[f"{v:,.0f}" for v in ls["Incidents"]], textposition="outside", cliponaxis=False,
                         hovertemplate="%{x}: %{y:,} incidents<extra></extra>"))
    fig.add_trace(go.Scatter(x=list(ls.index), y=ls["In shared events %"].values, name="% in multi-app events",
                             yaxis="y2", mode="markers+text", marker=dict(size=14, color=ACCENT, symbol="diamond"),
                             text=[f"{v:.0f}%" for v in ls["In shared events %"]], textposition="middle right",
                             hovertemplate="%{x}: %{y:.1f}% arrived in multi-app events<extra></extra>"))
    fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, range=[0, 100], ticksuffix="%",
                                  title=dict(text="In multi-app events")))
    fig.update_yaxes(title_text="Incidents", range=[0, ls["Incidents"].max() * 1.2 if len(ls) else 1])
    return _layout(fig, 360, title)


def kpi_trend(months: list[str], values: list[float], target: float | None, unit: str, title: str | None = None):
    fig = go.Figure(go.Scatter(x=months, y=values, mode="lines+markers", line=dict(color=ACCENT, width=2.5),
                               marker=dict(size=7), hovertemplate="%{x}: %{y:.2f}" + (unit if unit == "%" else "") +
                               "<extra></extra>"))
    if target is not None and not pd.isna(target):
        fig.add_hline(y=target, line_dash="dash", line_color=ORANGE, annotation_text=f"target {target:g}",
                      annotation_position="top left")
    fig.update_yaxes(ticksuffix="%" if unit == "%" else "")
    return _layout(fig, 300, title)


def rec_mix(s: pd.Series, title: str | None = None) -> go.Figure:
    return hbar(s, title=title, highlight=1)


def score_hist(scores: pd.Series, title: str | None = None) -> go.Figure:
    fig = go.Figure(go.Histogram(x=scores, xbins=dict(start=0, end=101, size=5), marker_color=GREY,
                                 hovertemplate="score %{x}: %{y} apps<extra></extra>"))
    fig.add_vline(x=80, line_dash="dash", line_color=ACCENT, annotation_text="act this week (80+)",
                  annotation_position="top left")
    fig.add_vline(x=50, line_dash="dot", line_color=MUTED, annotation_text="this month (50+)",
                  annotation_position="top left")
    fig.update_xaxes(title_text="Risk score", range=[0, 101])
    fig.update_yaxes(title_text="Applications")
    fig.update_layout(showlegend=False, bargap=0.05)
    return _layout(fig, 280, title)
