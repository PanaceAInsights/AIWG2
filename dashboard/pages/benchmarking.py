"""ACD Dashboard — Benchmarking page."""
from __future__ import annotations

from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from dashboard.theme import (
    COPPER, MAUVE_PURPLE, LIGHT_COPPER, BG_CARD, TEXT_MUTED,
    WHITE, WARM_CREAM, CHART_PALETTE, apply_plotly_theme,
)
from dashboard.data import load_stats, get_all_states

PAGE_TITLE = "Benchmarking"
PAGE_HREF  = "/benchmarking"


def layout():
    states = ["All"] + get_all_states()
    return html.Div([
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Label("Compare States", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Dropdown(
                        id="bench-states",
                        options=[{"label": s, "value": s} for s in states[1:]],
                        value=states[1:4] if len(states) > 3 else states[1:],
                        multi=True,
                        style={"backgroundColor": BG_CARD},
                    ),
                ], md=6),
                dbc.Col([
                    html.Label("Metric", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Dropdown(
                        id="bench-metric",
                        options=[
                            {"label": "Avg. Publications per Researcher", "value": "avg_works"},
                            {"label": "Avg. Citations per Researcher", "value": "avg_citations"},
                            {"label": "Total Publications", "value": "total_works"},
                            {"label": "Total Citations", "value": "total_citations"},
                        ],
                        value="avg_works", clearable=False,
                        style={"backgroundColor": BG_CARD},
                    ),
                ], md=4),
            ]),
        ], className="acd-card"),

        dbc.Row([
            dbc.Col(html.Div([
                html.Div("State Comparison", className="acd-card-title"),
                dcc.Graph(id="bench-state-bar", config={"displayModeBar": False}),
            ], className="acd-card"), md=6),
            dbc.Col(html.Div([
                html.Div("Productivity Distribution (Publications per Researcher)", className="acd-card-title"),
                dcc.Graph(id="bench-box", config={"displayModeBar": False}),
            ], className="acd-card"), md=6),
        ]),

        html.Div([
            html.Div("Researcher Scatter: Publications vs Citations", className="acd-card-title"),
            dcc.Graph(id="bench-scatter", config={"displayModeBar": True},
                      style={"height": "450px"}),
        ], className="acd-card"),
    ])


@callback(
    Output("bench-state-bar", "figure"),
    Input("bench-states", "value"),
    Input("bench-metric", "value"),
)
def update_state_bar(states, metric):
    stats = load_stats()
    if stats.empty or "state" not in stats.columns:
        return go.Figure()
    df = stats[stats["state"].isin(states)] if states else stats
    works_col = "total_works" if "total_works" in df.columns else "works_count"
    cite_col = "total_citations" if "total_citations" in df.columns else None

    if metric == "avg_works" and works_col in df.columns:
        agg = df.groupby("state")[works_col].mean().reset_index()
        agg.columns = ["State", "Value"]
    elif metric == "avg_citations" and cite_col and cite_col in df.columns:
        agg = df.groupby("state")[cite_col].mean().reset_index()
        agg.columns = ["State", "Value"]
    elif metric == "total_works" and works_col in df.columns:
        agg = df.groupby("state")[works_col].sum().reset_index()
        agg.columns = ["State", "Value"]
    elif metric == "total_citations" and cite_col and cite_col in df.columns:
        agg = df.groupby("state")[cite_col].sum().reset_index()
        agg.columns = ["State", "Value"]
    else:
        return go.Figure()

    fig = px.bar(agg, x="State", y="Value", color="State",
                 color_discrete_sequence=CHART_PALETTE)
    apply_plotly_theme(fig)
    fig.update_traces(marker_line_width=0)
    return fig


@callback(
    Output("bench-box", "figure"),
    Input("bench-states", "value"),
)
def update_box(states):
    stats = load_stats()
    if stats.empty or "state" not in stats.columns:
        return go.Figure()
    df = stats[stats["state"].isin(states)] if states else stats
    works_col = "total_works" if "total_works" in df.columns else "works_count"
    if works_col not in df.columns:
        return go.Figure()
    fig = px.box(df, x="state", y=works_col, color="state",
                 color_discrete_sequence=CHART_PALETTE)
    apply_plotly_theme(fig)
    return fig


@callback(
    Output("bench-scatter", "figure"),
    Input("bench-states", "value"),
)
def update_scatter(states):
    stats = load_stats()
    if stats.empty:
        return go.Figure()
    df = stats[stats["state"].isin(states)] if states else stats
    works_col = "total_works" if "total_works" in df.columns else "works_count"
    cite_col = "total_citations" if "total_citations" in df.columns else None
    if works_col not in df.columns or not cite_col or cite_col not in df.columns:
        return go.Figure()
    fig = px.scatter(
        df, x=works_col, y=cite_col,
        color="state" if "state" in df.columns else None,
        hover_name="acd_name" if "acd_name" in df.columns else None,
        color_discrete_sequence=CHART_PALETTE,
        size=works_col,
        size_max=20,
    )
    apply_plotly_theme(fig)
    fig.update_layout(xaxis_title="Publications", yaxis_title="Citations")
    return fig
