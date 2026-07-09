"""Clinical Trials page — trial activity for ACD members.
Charts, KPIs and grid are callback-driven so they react to global filters.
"""
from __future__ import annotations

import dash_ag_grid as dag
import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html
from dash_iconify import DashIconify

from .. import data, theme

PAGE_TITLE = "Clinical Trials"
PAGE_HREF  = "/trials"


def _detect_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def build_trials_kpi(df: pd.DataFrame) -> dmc.SimpleGrid:
    total = len(df)
    name_col = _detect_col(df, ["acd_name", "rams_name"])
    members = df[name_col].nunique() if name_col and not df.empty else 0
    return dmc.SimpleGrid(
        cols={"base": 1, "sm": 3}, spacing="lg", mb="lg",
        children=[
            dmc.Card([dmc.Text("Total trials", size="xs", c="dimmed", tt="uppercase"),
                      dmc.Text(f"{total:,}", size="xl", fw=700)]),
            dmc.Card([dmc.Text("Members involved", size="xs", c="dimmed", tt="uppercase"),
                      dmc.Text(f"{members}", size="xl", fw=700)]),
            dmc.Card([dmc.Text("Registry sources", size="xs", c="dimmed", tt="uppercase"),
                      dmc.Text("ANZCTR + CT.gov", size="xl", fw=700)]),
        ],
    )


def build_status_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    col = _detect_col(df, ["status", "overall_status", "trial_status", "Status"])
    if col and not df.empty:
        counts = df[col].fillna("Unknown").value_counts()
        fig.add_trace(go.Bar(
            x=counts.values, y=counts.index,
            orientation="h", marker_color=theme.PRIMARY,
        ))
        fig.update_layout(title="Trials by Status", height=300,
                          margin=dict(l=180, r=20, t=50, b=30),
                          xaxis_title="Number of trials")
    return fig


def build_year_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    col = _detect_col(df, ["start_date", "start_year", "year"])
    if col and not df.empty:
        years = pd.to_numeric(
            df[col].astype(str).str[:4], errors="coerce"
        ).dropna().astype(int)
        counts = years.value_counts().sort_index()
        fig.add_trace(go.Bar(x=counts.index, y=counts.values,
                             marker_color=theme.PRIMARY_LIGHT))
        fig.update_layout(title="Trials by Start Year", height=300,
                          margin=dict(l=50, r=20, t=50, b=30),
                          xaxis_title="Year", yaxis_title="Trials")
    return fig


def build_investigator_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    name_col = _detect_col(df, ["acd_name", "rams_name"])
    if name_col and not df.empty:
        counts = df[name_col].value_counts().head(15)
        if not counts.empty:
            fig.add_trace(go.Bar(x=counts.values, y=counts.index,
                                 orientation="h", marker_color=theme.ACCENT))
            fig.update_layout(title="Most Active Trial Investigators",
                              height=400, margin=dict(l=200, r=20, t=50, b=30),
                              xaxis_title="Number of trials")
    return fig


def render() -> html.Div:
    trials = data.load_clinical_trials()

    if trials.empty:
        return html.Div([
            dmc.Title("Clinical Trials", order=2, mb="md"),
            dmc.Alert(
                "Clinical trial data is being compiled. This view will be "
                "populated once trial registry matching is complete.",
                title="Coming soon", color="acd-copper", variant="light",
            ),
            dcc.Download(id="trials-download"),
        ])

    name_col = _detect_col(trials, ["acd_name", "rams_name"]) or "acd_name"
    grid_cols = [c for c in (name_col, "title", "trial_id", "registry",
                              "status", "phase", "start_date",
                              "condition", "intervention", "url")
                 if c in trials.columns]

    col_defs = []
    for c in grid_cols:
        header = c.replace("_", " ").title()
        if c == name_col:
            header = "Member"
        d = {
            "field": c, "headerName": header, "minWidth": 160,
            "filter": "agTextColumnFilter",
            "wrapText": c in ("title", "condition"),
            "autoHeight": c in ("title", "condition"),
        }
        if c == "trial_id":
            d["cellRenderer"] = "markdown"
            d["valueFormatter"] = {
                "function": (
                    "params.value ? '[' + params.value + ']"
                    "(https://clinicaltrials.gov/study/' + params.value + ')' : ''"
                )
            }
            d["minWidth"] = 180
        if c == "url":
            d["cellRenderer"] = "markdown"
            d["valueFormatter"] = {
                "function": "params.value ? '[Link](' + params.value + ')' : ''"
            }
            d["maxWidth"] = 100
        col_defs.append(d)

    grid_data = trials[grid_cols].fillna("").to_dict("records")

    return html.Div([
        dmc.Group([
            dmc.Stack([
                dmc.Title("Clinical Trials", order=2),
                dmc.Text(
                    "Trial registry activity for ACD members (ANZCTR + ClinicalTrials.gov)",
                    size="sm", c="dimmed",
                ),
            ], gap=2),
            dmc.Button(
                "Export trials", id="trials-export-btn",
                leftSection=DashIconify(icon="tabler:download", width=16),
                variant="light", color="acd-copper", size="xs",
            ),
        ], justify="space-between", mb="md"),
        html.Div(id="trials-kpi-row"),
        dmc.Grid([
            dmc.GridCol(
                html.Div(
                    dcc.Graph(id="trials-status-chart",
                              config={"displayModeBar": False},
                              style={"height": "300px"}),
                    className="section-card", style={"minHeight": "350px"},
                ),
                span={"base": 12, "md": 6},
            ),
            dmc.GridCol(
                html.Div(
                    dcc.Graph(id="trials-year-chart",
                              config={"displayModeBar": False},
                              style={"height": "300px"}),
                    className="section-card", style={"minHeight": "350px"},
                ),
                span={"base": 12, "md": 6},
            ),
        ], gutter="lg", mb="lg"),
        html.Div(id="trials-investigator-wrap"),
        html.Div([
            html.Div("All trials (searchable)", className="section-title"),
            dag.AgGrid(
                id="trials-grid",
                rowData=grid_data,
                columnDefs=col_defs,
                defaultColDef={"sortable": True, "filter": True, "resizable": True,
                               "floatingFilter": True},
                dashGridOptions={"pagination": True, "paginationPageSize": 25,
                                 "animateRows": True, "rowHeight": 42},
                className="ag-theme-alpine",
                style={"height": "480px", "width": "100%"},
                dangerously_allow_code=True,
            ),
        ], className="section-card", style={"padding": "0.5rem"}),
        dcc.Download(id="trials-download"),
    ])


layout = render
