"""Impact tab — FWCI, citations, h-index distributions + top performers.

All charts, KPI tiles and the top-10 table are callback-driven so they
react to the global filter bar.
"""
from __future__ import annotations

import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html
from dash_iconify import DashIconify

from .. import data, theme

PAGE_TITLE = "Research Impact"
PAGE_HREF  = "/impact"


def build_h_index_hist(df: pd.DataFrame) -> go.Figure:
    if df.empty or "h_index" not in df.columns:
        return go.Figure()
    x = df["h_index"].dropna()
    if x.empty:
        return go.Figure()
    fig = go.Figure(go.Histogram(
        x=x, nbinsx=30,
        marker_color=theme.PRIMARY, opacity=0.88,
        hovertemplate="h-index %{x}<br>%{y} members<extra></extra>",
    ))
    median = float(x.median())
    fig.add_vline(x=median, line_width=2, line_dash="dash",
                  line_color=theme.ACCENT,
                  annotation_text=f"median {median:.0f}",
                  annotation_position="top")
    fig.update_layout(title="h-index distribution",
                      xaxis_title="h-index", yaxis_title="Members",
                      height=320, bargap=0.05)
    return fig


def build_fwci_boxplot(df: pd.DataFrame) -> go.Figure:
    if df.empty or "fwci_mean" not in df.columns:
        return go.Figure()
    vals = df["fwci_mean"].dropna()
    if vals.empty:
        return go.Figure()
    fig = go.Figure()
    fig.add_trace(go.Box(
        x=vals, name="FWCI mean", marker_color=theme.VIOLET, boxmean="sd",
    ))
    fig.update_layout(
        title="Field-weighted citation impact (FWCI)",
        xaxis_title="FWCI mean", yaxis=dict(visible=False),
        height=200, showlegend=False,
    )
    return fig


def build_scatter(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()
    needed = {"pub_count", "citation_count", "h_index", "acd_name"}
    if not needed.issubset(df.columns):
        return go.Figure()
    d = df.dropna(subset=["pub_count", "citation_count"])
    if d.empty:
        return go.Figure()
    fig = go.Figure(go.Scatter(
        x=d["pub_count"],
        y=d["citation_count"],
        mode="markers",
        marker=dict(
            color=d["h_index"] if "h_index" in d.columns else theme.PRIMARY,
            colorscale=[[0, theme.VIOLET], [1, theme.PRIMARY]],
            size=8, opacity=0.75,
            colorbar=dict(title="h-index", ticks="outside"),
            showscale=True,
        ),
        text=d["acd_name"],
        hovertemplate=(
            "<b>%{text}</b><br>"
            "Publications: %{x}<br>"
            "Citations: %{y:,}<extra></extra>"
        ),
    ))
    fig.update_layout(
        title="Productivity vs citation impact",
        xaxis_title="Publications",
        yaxis_title="Citations (log)",
        yaxis_type="log",
        height=520,
        coloraxis_colorbar=dict(title="h-index", ticks="outside"),
    )
    return fig


def build_top_performers(df: pd.DataFrame) -> html.Div:
    if df.empty or "h_index" not in df.columns:
        return html.Div()
    name_col = next((c for c in ("acd_name", "rams_name") if c in df.columns), None)
    if name_col is None:
        return html.Div()
    top = df.dropna(subset=["h_index"]).sort_values("h_index", ascending=False).head(10)
    if top.empty:
        return html.Div()
    rows = []
    for rank, (_, row) in enumerate(top.iterrows(), 1):
        rows.append(html.Tr([
            html.Td(str(rank), style={"color": theme.GRAY_500}),
            html.Td(row[name_col], style={"fontWeight": 600}),
            html.Td(f"{int(row['h_index'])}", style={"textAlign": "right"}),
            html.Td(
                f"{int(row['citation_count']):,}" if pd.notna(row.get("citation_count")) else "-",
                style={"textAlign": "right"},
            ),
            html.Td(
                f"{row['fwci_mean']:.2f}" if pd.notna(row.get("fwci_mean")) else "-",
                style={"textAlign": "right"},
            ),
        ]))
    return html.Table([
        html.Thead(html.Tr([
            html.Th("#"), html.Th("Member"),
            html.Th("h", style={"textAlign": "right"}),
            html.Th("Citations", style={"textAlign": "right"}),
            html.Th("FWCI", style={"textAlign": "right"}),
        ])),
        html.Tbody(rows),
    ], style={"width": "100%", "borderCollapse": "collapse", "fontSize": "0.85rem"})


def build_impact_kpi(df: pd.DataFrame) -> dmc.SimpleGrid:
    total_members = len(df) if not df.empty else 0
    median_h  = float(df["h_index"].median()) if "h_index" in df.columns and total_members else 0
    mean_fwci = float(df["fwci_mean"].mean()) if "fwci_mean" in df.columns and total_members else 0
    total_cit = int(df["citation_count"].sum()) if "citation_count" in df.columns and total_members else 0
    return dmc.SimpleGrid(
        cols={"base": 2, "sm": 4},
        spacing="sm", mb="md",
        children=[
            dmc.Card([dmc.Text("Members with data", size="xs", c="dimmed", tt="uppercase"),
                      dmc.Text(f"{total_members:,}", size="xl", fw=700)]),
            dmc.Card([dmc.Text("Median h-index", size="xs", c="dimmed", tt="uppercase"),
                      dmc.Text(f"{median_h:.0f}", size="xl", fw=700)]),
            dmc.Card([dmc.Text("Mean FWCI", size="xs", c="dimmed", tt="uppercase"),
                      dmc.Text(f"{mean_fwci:.2f}", size="xl", fw=700)]),
            dmc.Card([dmc.Text("Total citations", size="xs", c="dimmed", tt="uppercase"),
                      dmc.Text(f"{total_cit:,}", size="xl", fw=700)]),
        ],
    )


def render() -> html.Div:
    header = dmc.Group([
        dmc.Stack([
            dmc.Text("Research impact", fw=700, size="xl"),
            dmc.Text(
                "Citation weight, productivity distribution, and the most-cited "
                "researchers across the ACD member cohort.",
                size="sm", c="dimmed",
            ),
            dmc.Group([
                dmc.Tooltip(
                    dmc.Badge("H-index", variant="light", size="sm"),
                    label="The h-index measures both productivity and citation impact. "
                          "An h-index of N means the researcher has N publications each "
                          "cited at least N times.",
                    multiline=True, w=280, withArrow=True,
                ),
                dmc.Tooltip(
                    dmc.Badge("FWCI", variant="light", size="sm"),
                    label="Field-Weighted Citation Impact normalises citations by "
                          "subject area, publication type and year. A value above 1.0 "
                          "means above world average.",
                    multiline=True, w=280, withArrow=True,
                ),
            ], gap="xs", mt="xs"),
        ], gap=2),
        dmc.Button(
            "Export impact data",
            id="impact-export-btn",
            leftSection=DashIconify(icon="tabler:download", width=16),
            variant="light",
            color="acd-copper",
            size="xs",
        ),
    ], justify="space-between", align="flex-start")

    kpi_row = html.Div(id="impact-kpi-row")

    row1 = dmc.Grid([
        dmc.GridCol(
            html.Div([
                html.Div("h-index distribution", className="section-title"),
                dcc.Graph(id="impact-h-hist",
                          config={"displayModeBar": False},
                          style={"height": "320px"}),
            ], className="section-card", style={"minHeight": "370px"}),
            span={"base": 12, "md": 7},
        ),
        dmc.GridCol(
            html.Div([
                html.Div("FWCI distribution", className="section-title"),
                dcc.Graph(id="impact-fwci-box",
                          config={"displayModeBar": False},
                          style={"height": "200px"}),
            ], className="section-card", style={"minHeight": "250px"}),
            span={"base": 12, "md": 5},
        ),
    ], gutter="lg", mt="md")

    row2 = dmc.Grid([
        dmc.GridCol(
            html.Div([
                html.Div("Productivity vs impact", className="section-title"),
                dcc.Graph(id="impact-scatter",
                          config={"displayModeBar": False, "responsive": True},
                          style={"height": "520px"}),
            ], className="section-card", style={"minHeight": "570px"}),
            span={"base": 12, "md": 8},
        ),
        dmc.GridCol(
            html.Div([
                html.Div("Top 10 by h-index", className="section-title"),
                html.Div(id="impact-top10"),
            ], className="section-card"),
            span={"base": 12, "md": 4},
        ),
    ], gutter="lg", mt="lg")

    return html.Div([header, kpi_row, row1, row2, dcc.Download(id="impact-download")])


layout = render
