"""ACD Dashboard — Funding page."""
from __future__ import annotations

from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
from dash import dash_table
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from dashboard.theme import (
    COPPER, MAUVE_PURPLE, LIGHT_COPPER, BG_CARD, BORDER_COLOR,
    TEXT_MUTED, WHITE, WARM_CREAM, CHART_PALETTE, DARK_PLUM,
    apply_plotly_theme,
)
from dashboard.data import load_funding, get_all_states

PAGE_TITLE = "Funding"
PAGE_HREF  = "/funding"


def layout():
    states = ["All"] + get_all_states()
    return html.Div([
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Label("State", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Dropdown(
                        id="funding-state-filter",
                        options=[{"label": s, "value": s} for s in states],
                        value="All", clearable=False,
                        style={"backgroundColor": BG_CARD},
                    ),
                ], md=3),
                dbc.Col([
                    html.Div(style={"height": "20px"}),
                    html.Button("Export CSV", id="funding-export-btn",
                                className="btn-outline-copper",
                                style={"padding": "8px 16px"}),
                    dcc.Download(id="funding-download"),
                ], md=2),
            ]),
        ], className="acd-card"),

        dbc.Row([
            dbc.Col(html.Div([
                html.Div("Top Funded Researchers", className="acd-card-title"),
                dcc.Graph(id="funding-top-bar", config={"displayModeBar": False}),
            ], className="acd-card"), md=7),
            dbc.Col(html.Div([
                html.Div("Funding by Source", className="acd-card-title"),
                dcc.Graph(id="funding-source-pie", config={"displayModeBar": False}),
            ], className="acd-card"), md=5),
        ]),

        html.Div([
            html.Div("Funding Grants", className="acd-section-header"),
            html.Div(id="funding-table-container"),
        ], className="acd-card"),
    ])


@callback(
    Output("funding-top-bar", "figure"),
    Input("funding-state-filter", "value"),
)
def update_top_bar(state):
    df = load_funding()
    if df.empty:
        return go.Figure()
    amount_col = next((c for c in ["amount", "Amount", "award_amount"] if c in df.columns), None)
    if not amount_col:
        # Count grants
        top = df.groupby("acd_name").size().reset_index(name="grants").nlargest(20, "grants")
        fig = px.bar(top, x="grants", y="acd_name", orientation="h",
                     color_discrete_sequence=[COPPER])
    else:
        top = df.groupby("acd_name")[amount_col].sum().reset_index().nlargest(20, amount_col)
        fig = px.bar(top, x=amount_col, y="acd_name", orientation="h",
                     color_discrete_sequence=[COPPER])
    apply_plotly_theme(fig)
    fig.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=10, r=10, t=10, b=10))
    fig.update_traces(marker_line_width=0)
    return fig


@callback(
    Output("funding-source-pie", "figure"),
    Input("funding-state-filter", "value"),
)
def update_source_pie(_):
    df = load_funding()
    funder_col = next((c for c in ["funder_name", "funder", "Funder", "source", "agency"] if c in df.columns), None)
    if df.empty or not funder_col:
        return go.Figure()
    counts = df[funder_col].fillna("Unknown").value_counts().head(10).reset_index()
    counts.columns = ["Funder", "Count"]
    fig = px.pie(counts, names="Funder", values="Count",
                 color_discrete_sequence=CHART_PALETTE, hole=0.4)
    apply_plotly_theme(fig)
    fig.update_traces(textfont_color=WHITE)
    return fig


@callback(
    Output("funding-table-container", "children"),
    Input("funding-state-filter", "value"),
)
def update_table(state):
    df = load_funding()
    if df.empty:
        return html.Div("No funding data loaded.", style={"color": TEXT_MUTED, "padding": "20px"})
    display_cols = [c for c in ["acd_name", "funder_name", "award_id", "award_name", "title", "funder", "amount", "year", "grant_id"] if c in df.columns]
    return dash_table.DataTable(
        data=df[display_cols].head(500).to_dict("records"),
        columns=[{"name": c.replace("_", " ").title(), "id": c} for c in display_cols],
        page_size=20,
        sort_action="native",
        filter_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG_CARD, "color": WARM_CREAM,
                    "border": f"1px solid {BORDER_COLOR}", "fontSize": "13px",
                    "padding": "8px 12px"},
        style_header={"backgroundColor": DARK_PLUM, "color": COPPER,
                      "fontWeight": "600", "fontSize": "12px",
                      "textTransform": "uppercase"},
    )


@callback(
    Output("funding-download", "data"),
    Input("funding-export-btn", "n_clicks"),
    prevent_initial_call=True,
)
def export_funding(_):
    df = load_funding()
    if df.empty:
        return dcc.no_update
    return dcc.send_data_frame(df.to_csv, "acd_funding.csv", index=False)
