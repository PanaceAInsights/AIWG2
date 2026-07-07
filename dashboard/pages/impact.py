"""ACD Dashboard — Impact page (citations, h-index, top cited works)."""
from __future__ import annotations

from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from dashboard.theme import (
    COPPER, MAUVE_PURPLE, LIGHT_COPPER, BG_CARD, BORDER_COLOR,
    TEXT_MUTED, WHITE, WARM_CREAM, CHART_PALETTE, DARK_PLUM,
    apply_plotly_theme,
)
from dashboard.data import load_publications, load_stats, get_all_states

PAGE_TITLE = "Impact"
PAGE_HREF  = "/impact"


def layout():
    states = ["All"] + get_all_states()
    return html.Div([
        # Filters
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Label("State", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Dropdown(
                        id="impact-state-filter",
                        options=[{"label": s, "value": s} for s in states],
                        value="All", clearable=False,
                        style={"backgroundColor": BG_CARD},
                    ),
                ], md=3),
                dbc.Col([
                    html.Label("Metric", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Dropdown(
                        id="impact-metric",
                        options=[
                            {"label": "Total Citations", "value": "total_citations"},
                            {"label": "H-Index", "value": "h_index"},
                            {"label": "Publications Count", "value": "total_works"},
                        ],
                        value="total_citations", clearable=False,
                        style={"backgroundColor": BG_CARD},
                    ),
                ], md=3),
            ]),
        ], className="acd-card"),

        # Charts
        dbc.Row([
            dbc.Col(html.Div([
                html.Div("Top 20 Researchers by Impact", className="acd-card-title"),
                dcc.Graph(id="impact-top-bar", config={"displayModeBar": False}),
            ], className="acd-card"), md=8),
            dbc.Col(html.Div([
                html.Div("Citations by State", className="acd-card-title"),
                dcc.Graph(id="impact-state-pie", config={"displayModeBar": False}),
            ], className="acd-card"), md=4),
        ]),

        dbc.Row([
            dbc.Col(html.Div([
                html.Div("Citation Distribution", className="acd-card-title"),
                dcc.Graph(id="impact-citation-hist", config={"displayModeBar": False}),
            ], className="acd-card"), md=6),
            dbc.Col(html.Div([
                html.Div("Top Cited Publications", className="acd-card-title"),
                html.Div(id="impact-top-pubs"),
            ], className="acd-card"), md=6),
        ]),
    ])


@callback(
    Output("impact-top-bar", "figure"),
    Input("impact-state-filter", "value"),
    Input("impact-metric", "value"),
)
def update_top_bar(state, metric):
    stats = load_stats()
    if stats.empty or metric not in stats.columns:
        return go.Figure()
    df = stats.copy()
    if state != "All" and "state" in df.columns:
        df = df[df["state"] == state]
    top = df.nlargest(20, metric)[["acd_name", metric, "state"]].fillna("")
    fig = px.bar(top, x=metric, y="acd_name", orientation="h",
                 color=metric, color_continuous_scale=[[0, MAUVE_PURPLE], [1, COPPER]],
                 hover_data=["state"])
    apply_plotly_theme(fig)
    fig.update_layout(yaxis=dict(autorange="reversed"), coloraxis_showscale=False,
                      margin=dict(l=10, r=10, t=10, b=10))
    fig.update_traces(marker_line_width=0)
    return fig


@callback(
    Output("impact-state-pie", "figure"),
    Input("impact-metric", "value"),
)
def update_state_pie(metric):
    stats = load_stats()
    if stats.empty or metric not in stats.columns or "state" not in stats.columns:
        return go.Figure()
    by_state = stats.groupby("state")[metric].sum().reset_index()
    fig = px.pie(by_state, names="state", values=metric,
                 color_discrete_sequence=CHART_PALETTE, hole=0.4)
    apply_plotly_theme(fig)
    fig.update_traces(textfont_color=WHITE)
    return fig


@callback(
    Output("impact-citation-hist", "figure"),
    Input("impact-state-filter", "value"),
)
def update_hist(state):
    stats = load_stats()
    if stats.empty or "total_citations" not in stats.columns:
        return go.Figure()
    df = stats.copy()
    if state != "All" and "state" in df.columns:
        df = df[df["state"] == state]
    fig = px.histogram(df, x="total_citations", nbins=40,
                       color_discrete_sequence=[COPPER])
    apply_plotly_theme(fig)
    fig.update_traces(marker_line_width=0)
    return fig


@callback(
    Output("impact-top-pubs", "children"),
    Input("impact-state-filter", "value"),
)
def update_top_pubs(state):
    pubs = load_publications()
    if pubs.empty:
        return html.Div("No publications loaded.", style={"color": TEXT_MUTED})
    cite_col = next((c for c in ["CitedByCount", "cited_by_count"] if c in pubs.columns), None)
    if not cite_col:
        return html.Div("Citation data not available.", style={"color": TEXT_MUTED})
    top = pubs.nlargest(10, cite_col)[["Title", cite_col, "Year", "acd_name"]].fillna("")
    items = []
    for _, row in top.iterrows():
        items.append(html.Div([
            html.Div(str(row.get("Title", ""))[:80] + "...",
                     style={"fontSize": "12px", "color": WARM_CREAM}),
            html.Div(f"{row.get('acd_name', '')} · {int(row.get(cite_col, 0))} citations · {int(row.get('Year', 0)) if row.get('Year') else ''}",
                     style={"fontSize": "11px", "color": TEXT_MUTED, "marginBottom": "8px"}),
        ]))
    return html.Div(items, style={"maxHeight": "300px", "overflowY": "auto"})
