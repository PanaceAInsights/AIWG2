"""ACD Dashboard — Overview page."""
from __future__ import annotations

from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from dashboard.theme import (
    COPPER, MAUVE_PURPLE, LIGHT_COPPER, BLUE_VIOLET, BURNT_COPPER,
    BG_CARD, BORDER_COLOR, TEXT_MUTED, WHITE, WARM_CREAM, CHART_PALETTE,
    apply_plotly_theme, CARD_STYLE, TIER_HIGH, TIER_REVIEW,
)
from dashboard.data import get_summary_kpis, load_authors, load_publications, load_clinical_trials

PAGE_TITLE = "Overview"
PAGE_HREF  = "/"


def _kpi_card(value, label, color=COPPER, icon="bi bi-graph-up"):
    return html.Div([
        html.I(className=icon, style={"fontSize": "20px", "color": color, "marginBottom": "8px"}),
        html.Div(str(value), style={"fontSize": "28px", "fontWeight": "700", "color": color}),
        html.Div(label, style={"fontSize": "11px", "color": TEXT_MUTED, "marginTop": "4px",
                               "textTransform": "uppercase", "letterSpacing": "0.8px"}),
    ], style={**CARD_STYLE, "textAlign": "center", "minHeight": "110px",
              "display": "flex", "flexDirection": "column", "justifyContent": "center"})


def layout():
    return html.Div([
        # KPI row
        html.Div(id="overview-kpis"),
        # Charts row 1
        dbc.Row([
            dbc.Col(html.Div([
                html.Div("Dermatologists by State", className="acd-card-title"),
                dcc.Graph(id="overview-state-bar", config={"displayModeBar": False}),
            ], className="acd-card"), md=6),
            dbc.Col(html.Div([
                html.Div("Resolution Confidence Distribution", className="acd-card-title"),
                dcc.Graph(id="overview-confidence-pie", config={"displayModeBar": False}),
            ], className="acd-card"), md=6),
        ]),
        # Charts row 2
        dbc.Row([
            dbc.Col(html.Div([
                html.Div("Publications per Year", className="acd-card-title"),
                dcc.Graph(id="overview-pubs-trend", config={"displayModeBar": False}),
            ], className="acd-card"), md=8),
            dbc.Col(html.Div([
                html.Div("Top Research Topics", className="acd-card-title"),
                dcc.Graph(id="overview-topics-bar", config={"displayModeBar": False}),
            ], className="acd-card"), md=4),
        ]),
        # Interval for live KPI refresh
        dcc.Interval(id="overview-interval", interval=60_000, n_intervals=0),
    ])


@callback(Output("overview-kpis", "children"), Input("overview-interval", "n_intervals"))
def update_kpis(_):
    kpis = get_summary_kpis()
    cards = [
        _kpi_card(kpis.get("n_total", 0),         "Total Dermatologists",   COPPER,       "bi bi-people-fill"),
        _kpi_card(kpis.get("n_resolved", 0),       "Resolved to OpenAlex",  TIER_HIGH,    "bi bi-check-circle-fill"),
        _kpi_card(kpis.get("n_review", 0),         "Flagged for Review",    TIER_REVIEW,  "bi bi-exclamation-triangle-fill"),
        _kpi_card(f"{kpis.get('n_pubs', 0):,}",    "Total Publications",    MAUVE_PURPLE, "bi bi-journal-text"),
        _kpi_card(f"{kpis.get('total_citations', 0):,}", "Total Citations",  LIGHT_COPPER, "bi bi-quote"),
        _kpi_card(kpis.get("n_trials", 0),         "Clinical Trials",       BLUE_VIOLET,  "bi bi-clipboard2-pulse-fill"),
    ]
    return dbc.Row([dbc.Col(c, md=2) for c in cards])


@callback(Output("overview-state-bar", "figure"), Input("overview-interval", "n_intervals"))
def update_state_bar(_):
    df = load_authors()
    if df.empty or "state" not in df.columns:
        return go.Figure()
    counts = df["state"].value_counts().reset_index()
    counts.columns = ["State", "Count"]
    fig = px.bar(counts, x="State", y="Count", color_discrete_sequence=[COPPER])
    apply_plotly_theme(fig)
    fig.update_traces(marker_line_width=0)
    return fig


@callback(Output("overview-confidence-pie", "figure"), Input("overview-interval", "n_intervals"))
def update_confidence_pie(_):
    df = load_authors()
    if df.empty or "confidence" not in df.columns:
        return go.Figure()
    counts = df["confidence"].value_counts().reset_index()
    counts.columns = ["Confidence", "Count"]
    colour_map = {"HIGH": TIER_HIGH, "REVIEW": "#FF9800", "LOW": "#F44336", "NOT_FOUND": "#9E9E9E"}
    fig = px.pie(counts, names="Confidence", values="Count",
                 color="Confidence", color_discrete_map=colour_map,
                 hole=0.45)
    apply_plotly_theme(fig)
    fig.update_traces(textfont_color=WHITE)
    return fig


@callback(Output("overview-pubs-trend", "figure"), Input("overview-interval", "n_intervals"))
def update_pubs_trend(_):
    pubs = load_publications()
    if pubs.empty or "Year" not in pubs.columns:
        return go.Figure()
    yearly = pubs.groupby("Year").size().reset_index(name="Publications")
    yearly = yearly[yearly["Year"].between(2000, 2026)]
    fig = px.area(yearly, x="Year", y="Publications", color_discrete_sequence=[COPPER])
    apply_plotly_theme(fig)
    fig.update_traces(line_color=COPPER, fillcolor=f"rgba(194,125,78,0.2)")
    return fig


@callback(Output("overview-topics-bar", "figure"), Input("overview-interval", "n_intervals"))
def update_topics_bar(_):
    pubs = load_publications()
    if pubs.empty or "SubTopic" not in pubs.columns:
        return go.Figure()
    top = pubs["SubTopic"].dropna().value_counts().head(10).reset_index()
    top.columns = ["Topic", "Count"]
    fig = px.bar(top, x="Count", y="Topic", orientation="h",
                 color_discrete_sequence=[MAUVE_PURPLE])
    apply_plotly_theme(fig)
    fig.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=10, r=10, t=10, b=10))
    fig.update_traces(marker_line_width=0)
    return fig
