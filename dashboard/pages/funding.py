"""Funding tab — funder breakdown + grant concentration + awards grid.

All charts, KPIs and the awards grid are callback-driven so they react
to the global filter bar.
"""
from __future__ import annotations

import dash_ag_grid as dag
import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html
from dash_iconify import DashIconify

from .. import data, theme

PAGE_TITLE = "Funding"
PAGE_HREF  = "/funding"


def build_funders_bar(df: pd.DataFrame, n: int = 15) -> go.Figure:
    if df.empty or "funder_name" not in df.columns:
        return go.Figure()
    top = (
        df["funder_name"].fillna("").replace("", "(unknown)")
        .value_counts().head(n).iloc[::-1]
    )
    fig = go.Figure(go.Bar(
        y=top.index, x=top.values,
        orientation="h", marker_color=theme.PINK,
        hovertemplate="%{y}<br>%{x} awards<extra></extra>",
    ))
    fig.update_layout(
        title=f"Top {n} funders by award count",
        xaxis_title="Awards", yaxis_title="",
        height=460, margin=dict(l=260),
    )
    return fig


def build_grants_treemap(summary: pd.DataFrame) -> go.Figure:
    if summary.empty or "grants_count" not in summary.columns:
        return go.Figure()
    df = summary.dropna(subset=["grants_count"]).copy()
    df = df[df["grants_count"] > 0].sort_values("grants_count", ascending=False).head(60)
    if df.empty:
        return go.Figure()
    name_col = next((c for c in ("acd_name", "rams_name") if c in df.columns), None)
    if name_col is None:
        return go.Figure()
    fig = go.Figure(go.Treemap(
        labels=df[name_col],
        parents=[""] * len(df),
        values=df["grants_count"].astype(int),
        hovertemplate="%{label}<br>%{value} grants<extra></extra>",
        marker=dict(
            colors=df["grants_count"].astype(int),
            colorscale=[[0, theme.PRIMARY_SOFT], [1, theme.PRIMARY]],
            showscale=False,
        ),
        tiling=dict(packing="squarify"),
    ))
    fig.update_layout(
        title="Grant concentration across the top 60 members",
        height=480, margin=dict(l=8, r=8, t=48, b=8),
    )
    return fig


def build_funding_kpi(df: pd.DataFrame) -> dmc.SimpleGrid:
    total_awards   = len(df)
    unique_funders = df["funder_name"].nunique() if "funder_name" in df.columns else 0
    name_col = next((c for c in ("acd_name", "rams_name") if c in df.columns), None)
    unique_members = df[name_col].nunique() if name_col else 0
    return dmc.SimpleGrid(
        cols={"base": 2, "sm": 3},
        spacing="sm", mb="md",
        children=[
            dmc.Card([dmc.Text("Total awards", size="xs", c="dimmed", tt="uppercase"),
                      dmc.Text(f"{total_awards:,}", size="xl", fw=700)]),
            dmc.Card([dmc.Text("Unique funders", size="xs", c="dimmed", tt="uppercase"),
                      dmc.Text(f"{unique_funders:,}", size="xl", fw=700)]),
            dmc.Card([dmc.Text("Members funded", size="xs", c="dimmed", tt="uppercase"),
                      dmc.Text(f"{unique_members:,}", size="xl", fw=700)]),
        ],
    )


def render() -> html.Div:
    funding  = data.load_funding()
    name_col = next((c for c in ("acd_name", "rams_name") if c in funding.columns), "acd_name")
    cols = [c for c in (name_col, "funder_name", "award_id", "award_name", "funder_ror")
            if c in funding.columns]
    grid_data = funding[cols].fillna("").to_dict("records") if not funding.empty else []

    grid_col_defs = [
        {"field": name_col, "headerName": "Member", "minWidth": 180,
         "filter": "agTextColumnFilter", "pinned": "left"},
        {"field": "funder_name", "headerName": "Funder", "minWidth": 260,
         "filter": "agTextColumnFilter"},
        {"field": "award_id", "headerName": "Award ID", "minWidth": 140},
        {"field": "award_name", "headerName": "Award name", "minWidth": 360,
         "wrapText": True, "autoHeight": True},
    ]

    header = dmc.Group([
        dmc.Stack([
            dmc.Text("Funding", fw=700, size="xl"),
            dmc.Text(
                "Who is funding ACD-aligned research? Funders, award "
                "counts, and per-member concentration.",
                size="sm", c="dimmed",
            ),
            dmc.Text(
                "The term 'funding' covers grants, fellowships and "
                "other funding records identified through OpenAlex.",
                size="xs", c="dimmed", fs="italic",
            ),
        ], gap=2),
        dmc.Button(
            "Export funding",
            id="funding-export-btn",
            leftSection=DashIconify(icon="tabler:download", width=16),
            variant="light",
            color="acd-copper",
            size="xs",
        ),
    ], justify="space-between", mb="md")

    kpi_row = html.Div(id="funding-kpi-row")

    row1 = dmc.Grid([
        dmc.GridCol(
            html.Div([
                html.Div("Funders", className="section-title"),
                dcc.Graph(id="funding-funders-bar",
                          config={"displayModeBar": False},
                          style={"height": "460px"}),
            ], className="section-card", style={"minHeight": "510px"}),
            span={"base": 12, "md": 6},
        ),
        dmc.GridCol(
            html.Div([
                html.Div("Grant concentration", className="section-title"),
                dcc.Graph(id="funding-treemap",
                          config={"displayModeBar": False},
                          style={"height": "480px"}),
            ], className="section-card", style={"minHeight": "530px"}),
            span={"base": 12, "md": 6},
        ),
    ], gutter="lg")

    row2 = dmc.Grid([
        dmc.GridCol(
            html.Div([
                html.Div("All awards", className="section-title"),
                dag.AgGrid(
                    id="funding-grid",
                    rowData=grid_data,
                    columnDefs=grid_col_defs,
                    defaultColDef={"sortable": True, "filter": True,
                                   "resizable": True, "floatingFilter": True},
                    dashGridOptions={"pagination": True, "paginationPageSize": 25,
                                     "animateRows": True, "rowHeight": 40},
                    className="ag-theme-alpine",
                    style={"height": "520px", "width": "100%"},
                ),
            ], className="section-card", style={"padding": "0.5rem"}),
            span=12,
        ),
    ], mt="lg")

    return html.Div([header, kpi_row, row1, row2, dcc.Download(id="funding-download")])


layout = render
