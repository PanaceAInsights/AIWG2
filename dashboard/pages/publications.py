"""ACD Dashboard — Publications page."""
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
    apply_plotly_theme, CARD_STYLE,
)
from dashboard.data import load_publications, get_all_subtopics

PAGE_TITLE = "Publications"
PAGE_HREF  = "/publications"


def layout():
    subtopics = ["All"] + get_all_subtopics()
    return html.Div([
        # Filters
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Label("Topic", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Dropdown(
                        id="pubs-topic-filter",
                        options=[{"label": s, "value": s} for s in subtopics],
                        value="All", clearable=False,
                        style={"backgroundColor": BG_CARD, "color": WARM_CREAM},
                    ),
                ], md=3),
                dbc.Col([
                    html.Label("Year Range", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.RangeSlider(
                        id="pubs-year-slider",
                        min=2000, max=2026, step=1,
                        marks={y: str(y) for y in range(2000, 2027, 5)},
                        value=[2000, 2026],
                        tooltip={"placement": "bottom", "always_visible": False},
                    ),
                ], md=5),
                dbc.Col([
                    html.Label("Derm-Relevant Only", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Checklist(
                        id="pubs-derm-only",
                        options=[{"label": " Dermatology-relevant only", "value": "derm"}],
                        value=[],
                        style={"color": WARM_CREAM, "fontSize": "13px", "marginTop": "8px"},
                    ),
                ], md=2),
                dbc.Col([
                    html.Div(style={"height": "20px"}),
                    html.Button("Export CSV", id="pubs-export-btn",
                                className="btn-outline-copper",
                                style={"width": "100%", "padding": "8px"}),
                    dcc.Download(id="pubs-download"),
                ], md=2),
            ]),
        ], className="acd-card"),

        # Charts
        dbc.Row([
            dbc.Col(html.Div([
                html.Div("Publications by Year", className="acd-card-title"),
                dcc.Graph(id="pubs-year-chart", config={"displayModeBar": False}),
            ], className="acd-card"), md=8),
            dbc.Col(html.Div([
                html.Div("Open Access Status", className="acd-card-title"),
                dcc.Graph(id="pubs-oa-pie", config={"displayModeBar": False}),
            ], className="acd-card"), md=4),
        ]),

        # Table
        html.Div([
            html.Div("Publication List", className="acd-section-header"),
            html.Div(id="pubs-table-container"),
        ], className="acd-card"),
    ])


def _filter_pubs(topic, year_range, derm_only):
    pubs = load_publications()
    if pubs.empty:
        return pubs
    if topic and topic != "All" and "SubTopic" in pubs.columns:
        pubs = pubs[pubs["SubTopic"] == topic]
    if year_range and "Year" in pubs.columns:
        pubs = pubs[pubs["Year"].between(year_range[0], year_range[1])]
    if derm_only and "derm" in derm_only and "is_derm_relevant" in pubs.columns:
        pubs = pubs[pubs["is_derm_relevant"] == True]
    return pubs


@callback(
    Output("pubs-year-chart", "figure"),
    Input("pubs-topic-filter", "value"),
    Input("pubs-year-slider", "value"),
    Input("pubs-derm-only", "value"),
)
def update_year_chart(topic, year_range, derm_only):
    pubs = _filter_pubs(topic, year_range, derm_only)
    if pubs.empty or "Year" not in pubs.columns:
        return go.Figure()
    yearly = pubs.groupby("Year").size().reset_index(name="Publications")
    fig = px.bar(yearly, x="Year", y="Publications", color_discrete_sequence=[COPPER])
    apply_plotly_theme(fig)
    fig.update_traces(marker_line_width=0)
    return fig


@callback(
    Output("pubs-oa-pie", "figure"),
    Input("pubs-topic-filter", "value"),
    Input("pubs-year-slider", "value"),
    Input("pubs-derm-only", "value"),
)
def update_oa_pie(topic, year_range, derm_only):
    pubs = _filter_pubs(topic, year_range, derm_only)
    oa_col = next((c for c in ["OA_Type", "Open_Access", "OA_Status", "open_access_status", "is_oa"] if c in pubs.columns), None)
    if pubs.empty or not oa_col:
        return go.Figure()
    counts = pubs[oa_col].fillna("Unknown").value_counts().reset_index()
    counts.columns = ["Status", "Count"]
    fig = px.pie(counts, names="Status", values="Count",
                 color_discrete_sequence=CHART_PALETTE, hole=0.4)
    apply_plotly_theme(fig)
    fig.update_traces(textfont_color=WHITE)
    return fig


@callback(
    Output("pubs-table-container", "children"),
    Input("pubs-topic-filter", "value"),
    Input("pubs-year-slider", "value"),
    Input("pubs-derm-only", "value"),
)
def update_table(topic, year_range, derm_only):
    pubs = _filter_pubs(topic, year_range, derm_only)
    if pubs.empty:
        return html.Div("No publications found.", style={"color": TEXT_MUTED, "padding": "20px"})

    display_cols = ["acd_name", "Title", "Year", "Journal", "CitedByCount", "SubTopic", "DOI"]
    display_cols = [c for c in display_cols if c in pubs.columns]

    return dash_table.DataTable(
        data=pubs[display_cols].head(500).to_dict("records"),
        columns=[{"name": c.replace("_", " ").title(), "id": c} for c in display_cols],
        page_size=20,
        sort_action="native",
        filter_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG_CARD, "color": WARM_CREAM,
                    "border": f"1px solid {BORDER_COLOR}", "fontSize": "13px",
                    "padding": "8px 12px", "textAlign": "left",
                    "maxWidth": "300px", "overflow": "hidden", "textOverflow": "ellipsis"},
        style_header={"backgroundColor": DARK_PLUM, "color": COPPER,
                      "fontWeight": "600", "fontSize": "12px",
                      "textTransform": "uppercase", "letterSpacing": "0.5px"},
    )


@callback(
    Output("pubs-download", "data"),
    Input("pubs-export-btn", "n_clicks"),
    Input("pubs-topic-filter", "value"),
    Input("pubs-year-slider", "value"),
    Input("pubs-derm-only", "value"),
    prevent_initial_call=True,
)
def export_pubs(_, topic, year_range, derm_only):
    pubs = _filter_pubs(topic, year_range, derm_only)
    if pubs.empty:
        return dcc.no_update
    return dcc.send_data_frame(pubs.to_csv, "acd_publications.csv", index=False)
