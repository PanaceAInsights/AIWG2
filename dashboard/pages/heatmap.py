"""ACD Dashboard — Heatmap page (topic × state research activity)."""
from __future__ import annotations

from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from dashboard.theme import (
    COPPER, MAUVE_PURPLE, BG_CARD, TEXT_MUTED, WHITE, WARM_CREAM,
    apply_plotly_theme,
)
from dashboard.data import load_publications, get_all_states

PAGE_TITLE = "Heatmap"
PAGE_HREF  = "/heatmap"


def layout():
    return html.Div([
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Label("Metric", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Dropdown(
                        id="heatmap-metric",
                        options=[
                            {"label": "Publication Count", "value": "count"},
                            {"label": "Total Citations", "value": "citations"},
                        ],
                        value="count", clearable=False,
                        style={"backgroundColor": BG_CARD},
                    ),
                ], md=3),
                dbc.Col([
                    html.Label("Top N Topics", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Slider(id="heatmap-top-n", min=5, max=30, step=5, value=15,
                               marks={5: "5", 10: "10", 15: "15", 20: "20", 30: "30"},
                               tooltip={"placement": "bottom"}),
                ], md=5),
            ]),
        ], className="acd-card"),

        html.Div([
            html.Div("Research Activity Heatmap — Topic × State", className="acd-section-header"),
            dcc.Graph(id="heatmap-chart", config={"displayModeBar": True},
                      style={"height": "600px"}),
        ], className="acd-card"),
    ])


@callback(
    Output("heatmap-chart", "figure"),
    Input("heatmap-metric", "value"),
    Input("heatmap-top-n", "value"),
)
def update_heatmap(metric, top_n):
    pubs = load_publications()
    if pubs.empty or "SubTopic" not in pubs.columns or "state" not in pubs.columns:
        return go.Figure()

    cite_col = next((c for c in ["CitedByCount", "cited_by_count"] if c in pubs.columns), None)

    if metric == "citations" and cite_col:
        pivot = pubs.groupby(["SubTopic", "state"])[cite_col].sum().reset_index()
        pivot.columns = ["SubTopic", "state", "value"]
    else:
        pivot = pubs.groupby(["SubTopic", "state"]).size().reset_index(name="value")

    top_topics = pivot.groupby("SubTopic")["value"].sum().nlargest(top_n).index
    pivot = pivot[pivot["SubTopic"].isin(top_topics)]

    matrix = pivot.pivot(index="SubTopic", columns="state", values="value").fillna(0)

    fig = go.Figure(data=go.Heatmap(
        z=matrix.values,
        x=matrix.columns.tolist(),
        y=matrix.index.tolist(),
        colorscale=[[0, "#2A1F33"], [0.5, MAUVE_PURPLE], [1, COPPER]],
        hoverongaps=False,
        hovertemplate="<b>%{y}</b><br>State: %{x}<br>Value: %{z}<extra></extra>",
    ))
    apply_plotly_theme(fig)
    fig.update_layout(
        xaxis_title="State",
        yaxis_title="Research Topic",
        height=600,
        margin=dict(l=200, r=20, t=40, b=60),
    )
    return fig
