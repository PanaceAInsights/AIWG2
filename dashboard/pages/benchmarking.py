"""Benchmarking tab — percentile distributions + member quantile lookup."""
from __future__ import annotations

import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html
from dash_iconify import DashIconify

from .. import data, theme

PAGE_TITLE = "Benchmarking"
PAGE_HREF  = "/benchmarking"

METRIC_MAP = {
    "pub_count_pctile":        ("Publications",         theme.PRIMARY),
    "citation_count_pctile":   ("Citations",            theme.CYAN),
    "h_index_pctile":          ("h-index",              theme.VIOLET),
    "oa_rate_pctile":          ("Open access rate",     theme.SUCCESS),
    "intl_collab_rate_pctile": ("International collab", theme.PINK),
    "grants_count_pctile":     ("Grants",               theme.ACCENT),
}


def build_ridge_chart(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()
    fig = go.Figure()
    for col, (label, color) in METRIC_MAP.items():
        if col not in df.columns:
            continue
        vals = df[col].dropna().values
        if len(vals) < 5:
            continue
        fig.add_trace(go.Violin(
            x=vals, name=label,
            orientation="h",
            side="positive", width=2.2,
            meanline_visible=True,
            line_color=color, fillcolor=color, opacity=0.4,
            points=False, box_visible=False,
            hovertemplate=f"{label}<br>%{{x:.0f}}th<extra></extra>",
        ))
    fig.update_layout(
        title="Percentile distributions across the ACD member cohort",
        xaxis_title="Percentile", yaxis_title="",
        height=480,
        violingap=0, violinmode="overlay",
        showlegend=False,
        margin=dict(l=140),
    )
    return fig


def build_quantile_bars(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()
    rows = []
    for col, (label, color) in METRIC_MAP.items():
        if col not in df.columns:
            continue
        s = df[col].dropna()
        if s.empty:
            continue
        rows.append({
            "metric": label,
            "p25": float(s.quantile(0.25)),
            "p50": float(s.quantile(0.50)),
            "p75": float(s.quantile(0.75)),
            "p95": float(s.quantile(0.95)),
            "color": color,
        })
    if not rows:
        return go.Figure()
    rdf = pd.DataFrame(rows)
    fig = go.Figure()
    for _, r in rdf.iterrows():
        fig.add_trace(go.Bar(
            x=[r["p95"] - r["p25"]], y=[r["metric"]], base=r["p25"],
            orientation="h", marker_color=r["color"],
            name=r["metric"], showlegend=False,
            hovertemplate=(
                f"{r['metric']}<br>"
                f"P25 {r['p25']:.0f} \u2022 P50 {r['p50']:.0f} \u2022 "
                f"P75 {r['p75']:.0f} \u2022 P95 {r['p95']:.0f}<extra></extra>"
            ),
        ))
        fig.add_trace(go.Scatter(
            x=[r["p50"]], y=[r["metric"]],
            mode="markers",
            marker=dict(symbol="diamond", size=14, color="#ffffff",
                        line=dict(color=r["color"], width=2)),
            showlegend=False, hoverinfo="skip",
        ))
    fig.update_layout(
        title="P25 \u2192 P95 band with median",
        xaxis_title="Percentile", yaxis_title="",
        xaxis=dict(range=[0, 100]),
        height=340, margin=dict(l=160),
    )
    return fig


def _member_options() -> list[dict]:
    summary = data.load_summary()
    if summary.empty:
        return []
    name_col = next((c for c in ("acd_name", "rams_name") if c in summary.columns), None)
    if name_col is None:
        return []
    return [{"label": n, "value": n}
            for n in sorted(summary[name_col].dropna().unique())]


def render() -> html.Div:
    header = dmc.Group([
        dmc.Stack([
            dmc.Text("Benchmarking", fw=700, size="xl"),
            dmc.Text(
                "This view shows the distribution of research activity across "
                "the ACD member cohort. Percentile ranks are computed within "
                "the confirmed member group.",
                size="sm", c="dimmed",
            ),
            dmc.Text(
                "Percentile ranks show where each member sits relative to their "
                "ACD peers. A value of 75 means this member's metric exceeds "
                "75% of the cohort.",
                size="xs", c="dimmed", fs="italic",
            ),
        ], gap=2),
        dmc.Button(
            "Export benchmarking",
            id="bench-export-btn",
            leftSection=DashIconify(icon="tabler:download", width=16),
            variant="light",
            color="acd-copper",
            size="xs",
        ),
    ], justify="space-between", align="flex-start", mb="md")

    row1 = dmc.Grid([
        dmc.GridCol(
            html.Div([
                html.Div("Distribution ridges", className="section-title"),
                dcc.Graph(id="bench-ridge-chart",
                          config={"displayModeBar": False},
                          style={"height": "480px"}),
            ], className="section-card", style={"minHeight": "530px"}),
            span={"base": 12, "md": 7},
        ),
        dmc.GridCol(
            html.Div([
                html.Div("Quantile bands", className="section-title"),
                dcc.Graph(id="bench-quantile-chart",
                          config={"displayModeBar": False},
                          style={"height": "340px"}),
            ], className="section-card", style={"minHeight": "390px"}),
            span={"base": 12, "md": 5},
        ),
    ], gutter="lg")

    comparison = html.Div([
        html.Div("Member comparison", className="section-title"),
        dmc.Text("Select two members to compare their percentile standings.",
                 size="xs", c="dimmed", mb="sm"),
        dmc.Group([
            dmc.Select(
                id="bench-member-a",
                label="Member A",
                data=_member_options(),
                searchable=True,
                placeholder="Select member...",
                size="xs",
                style={"flex": 1},
            ),
            dmc.Select(
                id="bench-member-b",
                label="Member B",
                data=_member_options(),
                searchable=True,
                placeholder="Select member...",
                size="xs",
                style={"flex": 1},
            ),
            dmc.Button(
                "Compare",
                id="bench-compare-btn",
                variant="filled",
                color="acd-copper",
                size="xs",
                mt="xl",
            ),
        ], grow=True, gap="md"),
        html.Div(id="bench-comparison-result", style={"marginTop": "1rem"}),
    ], className="section-card", style={"marginTop": "1.5rem"})

    return html.Div([header, row1, comparison, dcc.Download(id="bench-download")])


layout = render
