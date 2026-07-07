"""ACD Dashboard — Clinical Trials page."""
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
from dashboard.data import load_clinical_trials

PAGE_TITLE = "Clinical Trials"
PAGE_HREF  = "/trials"


def layout():
    return html.Div([
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Label("Status", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Dropdown(
                        id="trials-status-filter",
                        options=[{"label": "All", "value": "All"}],
                        value="All", clearable=False,
                        style={"backgroundColor": BG_CARD},
                    ),
                ], md=3),
                dbc.Col([
                    html.Label("Search", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Input(
                        id="trials-search", type="text",
                        placeholder="Search by title, condition...",
                        debounce=True,
                        style={"width": "100%", "backgroundColor": BG_CARD,
                               "border": f"1px solid {BORDER_COLOR}", "borderRadius": "6px",
                               "color": WARM_CREAM, "padding": "8px 12px"},
                    ),
                ], md=5),
                dbc.Col([
                    html.Div(style={"height": "20px"}),
                    html.Button("Export CSV", id="trials-export-btn",
                                className="btn-outline-copper",
                                style={"padding": "8px 16px"}),
                    dcc.Download(id="trials-download"),
                ], md=2),
            ]),
        ], className="acd-card"),

        dbc.Row([
            dbc.Col(html.Div([
                html.Div("Trials by Status", className="acd-card-title"),
                dcc.Graph(id="trials-status-pie", config={"displayModeBar": False}),
            ], className="acd-card"), md=4),
            dbc.Col(html.Div([
                html.Div("Trials Started per Year", className="acd-card-title"),
                dcc.Graph(id="trials-year-bar", config={"displayModeBar": False}),
            ], className="acd-card"), md=8),
        ]),

        html.Div([
            html.Div("Clinical Trials Registry", className="acd-section-header"),
            html.Div(id="trials-table-container"),
        ], className="acd-card"),
    ])


@callback(
    Output("trials-status-filter", "options"),
    Input("trials-status-filter", "id"),
)
def populate_status_options(_):
    trials = load_clinical_trials()
    if trials.empty or "status" not in trials.columns:
        return [{"label": "All", "value": "All"}]
    statuses = trials["status"].dropna().unique().tolist()
    return [{"label": "All", "value": "All"}] + [{"label": s, "value": s} for s in sorted(statuses)]


@callback(
    Output("trials-status-pie", "figure"),
    Input("trials-status-filter", "value"),
)
def update_status_pie(_):
    trials = load_clinical_trials()
    if trials.empty or "status" not in trials.columns:
        return go.Figure()
    counts = trials["status"].fillna("Unknown").value_counts().reset_index()
    counts.columns = ["Status", "Count"]
    fig = px.pie(counts, names="Status", values="Count",
                 color_discrete_sequence=CHART_PALETTE, hole=0.4)
    apply_plotly_theme(fig)
    fig.update_traces(textfont_color=WHITE)
    return fig


@callback(
    Output("trials-year-bar", "figure"),
    Input("trials-status-filter", "value"),
)
def update_year_bar(_):
    trials = load_clinical_trials()
    if trials.empty or "start_date" not in trials.columns:
        return go.Figure()
    trials = trials.copy()
    trials["start_year"] = pd.to_datetime(trials["start_date"], errors="coerce").dt.year
    yearly = trials.dropna(subset=["start_year"]).groupby("start_year").size().reset_index(name="Trials")
    yearly = yearly[yearly["start_year"].between(2000, 2026)]
    fig = px.bar(yearly, x="start_year", y="Trials", color_discrete_sequence=[MAUVE_PURPLE])
    apply_plotly_theme(fig)
    fig.update_traces(marker_line_width=0)
    return fig


@callback(
    Output("trials-table-container", "children"),
    Input("trials-status-filter", "value"),
    Input("trials-search", "value"),
)
def update_table(status, search):
    trials = load_clinical_trials()
    if trials.empty:
        return html.Div("No clinical trials data loaded.", style={"color": TEXT_MUTED, "padding": "20px"})
    if status and status != "All" and "status" in trials.columns:
        trials = trials[trials["status"] == status]
    if search:
        mask = (
            trials.get("title", pd.Series(dtype=str)).str.contains(search, case=False, na=False)
            | trials.get("condition", pd.Series(dtype=str)).str.contains(search, case=False, na=False)
            | trials.get("acd_name", pd.Series(dtype=str)).str.contains(search, case=False, na=False)
        )
        trials = trials[mask]

    display_cols = [c for c in ["acd_name", "trial_id", "title", "status", "condition",
                                 "phase", "start_date", "sponsor", "url"] if c in trials.columns]
    return dash_table.DataTable(
        data=trials[display_cols].head(500).to_dict("records"),
        columns=[{"name": c.replace("_", " ").title(), "id": c,
                  "presentation": "markdown" if c == "url" else "input"}
                 for c in display_cols],
        page_size=20,
        sort_action="native",
        filter_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG_CARD, "color": WARM_CREAM,
                    "border": f"1px solid {BORDER_COLOR}", "fontSize": "13px",
                    "padding": "8px 12px", "maxWidth": "300px",
                    "overflow": "hidden", "textOverflow": "ellipsis"},
        style_header={"backgroundColor": DARK_PLUM, "color": COPPER,
                      "fontWeight": "600", "fontSize": "12px",
                      "textTransform": "uppercase"},
    )


@callback(
    Output("trials-download", "data"),
    Input("trials-export-btn", "n_clicks"),
    prevent_initial_call=True,
)
def export_trials(_):
    trials = load_clinical_trials()
    if trials.empty:
        return dcc.no_update
    return dcc.send_data_frame(trials.to_csv, "acd_clinical_trials.csv", index=False)
