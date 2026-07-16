"""ACD Dashboard — Compare & Rank page.

Users enter their own metrics (h-index, citations, publications, FWCI)
and see where they would rank among all ACD dermatologists, with
distribution charts and percentile indicators.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, callback, Input, Output, State, no_update
import dash_mantine_components as dmc
from dash_iconify import DashIconify

from ..data import load_stats

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
METRICS = [
    ("h_index", "h-index", "Your h-index", "tabler:chart-bar"),
    ("pub_count", "Publications", "Total publications", "tabler:books"),
    ("citation_count", "Citations", "Total citations", "tabler:quote"),
    ("fwci_mean", "FWCI", "Field-Weighted Citation Impact", "tabler:trending-up"),
]

COPPER = "#B87333"
DARK_BG = "#1a1a2e"
CARD_BG = "#16213e"
ACCENT = "#e94560"
GOLD = "#f5a623"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _percentile_rank(value: float, series: pd.Series) -> float:
    """Return the percentile rank (0-100) of value within series."""
    if pd.isna(value) or len(series) == 0:
        return 0.0
    return float((series < value).sum() / len(series) * 100)


def _rank_position(value: float, series: pd.Series) -> int:
    """Return rank position (1 = highest) of value within series."""
    if pd.isna(value):
        return len(series) + 1
    return int((series > value).sum() + 1)


def _build_distribution_chart(series: pd.Series, user_value: float,
                              metric_label: str, color: str = COPPER) -> go.Figure:
    """Build a histogram with the user's position marked."""
    fig = go.Figure()

    # Histogram of all members
    fig.add_trace(go.Histogram(
        x=series.dropna(),
        nbinsx=30,
        marker_color=color,
        opacity=0.7,
        name="ACD Members",
        hovertemplate="%{x:.1f}<br>Count: %{y}<extra></extra>",
    ))

    # User's position as a vertical line
    if not pd.isna(user_value):
        fig.add_vline(
            x=user_value,
            line_width=3,
            line_dash="dash",
            line_color=ACCENT,
            annotation_text=f"You: {user_value:.1f}",
            annotation_position="top",
            annotation_font_color=ACCENT,
            annotation_font_size=13,
        )

    fig.update_layout(
        title=dict(text=f"{metric_label} Distribution", font=dict(size=14, color="#eee")),
        xaxis_title=metric_label,
        yaxis_title="Number of Members",
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=20, t=50, b=40),
        height=280,
        showlegend=False,
        font=dict(color="#ccc"),
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.1)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.1)")

    return fig


def _build_radar_chart(user_percentiles: dict) -> go.Figure:
    """Build a radar/spider chart showing the user's percentile across all metrics."""
    categories = list(user_percentiles.keys())
    values = list(user_percentiles.values())
    # Close the polygon
    categories.append(categories[0])
    values.append(values[0])

    fig = go.Figure()

    fig.add_trace(go.Scatterpolar(
        r=values,
        theta=categories,
        fill="toself",
        fillcolor=f"rgba(184, 115, 51, 0.3)",
        line_color=COPPER,
        marker=dict(size=8, color=ACCENT),
        name="Your Percentile",
    ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                tickfont=dict(size=10, color="#aaa"),
                gridcolor="rgba(255,255,255,0.15)",
            ),
            angularaxis=dict(
                tickfont=dict(size=12, color="#ddd"),
                gridcolor="rgba(255,255,255,0.15)",
            ),
            bgcolor="rgba(0,0,0,0)",
        ),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=60, r=60, t=30, b=30),
        height=350,
        showlegend=False,
        font=dict(color="#ccc"),
    )
    return fig


def _build_rank_card(metric_label: str, value: float, rank: int,
                     total: int, percentile: float, icon: str) -> html.Div:
    """Build a single metric rank card."""
    pctile_color = GOLD if percentile >= 75 else (COPPER if percentile >= 50 else "#888")
    return html.Div([
        html.Div([
            DashIconify(icon=icon, width=24, color=pctile_color),
            html.Span(metric_label, style={"fontWeight": "600", "fontSize": "0.95rem"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "0.5rem", "marginBottom": "0.5rem"}),
        html.Div([
            html.Span(f"{value:.1f}" if isinstance(value, float) and value != int(value) else str(int(value)),
                      style={"fontSize": "1.8rem", "fontWeight": "700", "color": pctile_color}),
        ]),
        html.Div([
            html.Span(f"Rank: ", style={"color": "#aaa"}),
            html.Span(f"#{rank}", style={"fontWeight": "700", "color": "#eee"}),
            html.Span(f" of {total}", style={"color": "#aaa"}),
        ], style={"fontSize": "0.85rem", "marginTop": "0.3rem"}),
        html.Div([
            html.Span(f"Percentile: ", style={"color": "#aaa"}),
            html.Span(f"{percentile:.0f}th", style={"fontWeight": "700", "color": pctile_color}),
        ], style={"fontSize": "0.85rem", "marginTop": "0.2rem"}),
    ], style={
        "background": CARD_BG,
        "borderRadius": "10px",
        "padding": "1.2rem",
        "border": f"1px solid rgba(184,115,51,0.3)",
    })


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

def render() -> html.Div:
    """Return the Compare & Rank page layout."""
    return html.Div([
        html.H2("Compare & Rank", style={"color": "#eee", "marginBottom": "0.3rem"}),
        html.P(
            "Enter your research metrics below to see where you would rank "
            "among all Australasian College of Dermatologists members.",
            style={"color": "#aaa", "marginBottom": "1.5rem", "maxWidth": "700px"},
        ),

        # Input form
        html.Div([
            html.Div([
                html.Label("Your Name (optional)", style={"color": "#ccc", "fontSize": "0.85rem"}),
                dcc.Input(
                    id="compare-name",
                    type="text",
                    placeholder="e.g., Dr Jane Smith",
                    style={
                        "width": "100%", "padding": "0.6rem", "borderRadius": "6px",
                        "border": "1px solid #444", "background": "#1e1e3a",
                        "color": "#eee", "fontSize": "0.95rem",
                    },
                ),
            ], style={"gridColumn": "span 2"}),

            html.Div([
                html.Label("h-index", style={"color": "#ccc", "fontSize": "0.85rem"}),
                dcc.Input(
                    id="compare-h-index",
                    type="number",
                    placeholder="e.g., 15",
                    min=0, max=200,
                    style={
                        "width": "100%", "padding": "0.6rem", "borderRadius": "6px",
                        "border": "1px solid #444", "background": "#1e1e3a",
                        "color": "#eee", "fontSize": "0.95rem",
                    },
                ),
            ]),

            html.Div([
                html.Label("Total Publications", style={"color": "#ccc", "fontSize": "0.85rem"}),
                dcc.Input(
                    id="compare-publications",
                    type="number",
                    placeholder="e.g., 50",
                    min=0, max=5000,
                    style={
                        "width": "100%", "padding": "0.6rem", "borderRadius": "6px",
                        "border": "1px solid #444", "background": "#1e1e3a",
                        "color": "#eee", "fontSize": "0.95rem",
                    },
                ),
            ]),

            html.Div([
                html.Label("Total Citations", style={"color": "#ccc", "fontSize": "0.85rem"}),
                dcc.Input(
                    id="compare-citations",
                    type="number",
                    placeholder="e.g., 500",
                    min=0, max=100000,
                    style={
                        "width": "100%", "padding": "0.6rem", "borderRadius": "6px",
                        "border": "1px solid #444", "background": "#1e1e3a",
                        "color": "#eee", "fontSize": "0.95rem",
                    },
                ),
            ]),

            html.Div([
                html.Label("FWCI (Field-Weighted Citation Impact)", style={"color": "#ccc", "fontSize": "0.85rem"}),
                dcc.Input(
                    id="compare-fwci",
                    type="number",
                    placeholder="e.g., 1.5",
                    min=0, max=50, step=0.01,
                    style={
                        "width": "100%", "padding": "0.6rem", "borderRadius": "6px",
                        "border": "1px solid #444", "background": "#1e1e3a",
                        "color": "#eee", "fontSize": "0.95rem",
                    },
                ),
            ]),
        ], style={
            "display": "grid",
            "gridTemplateColumns": "1fr 1fr",
            "gap": "1rem",
            "maxWidth": "700px",
            "marginBottom": "1.5rem",
        }),

        # Compare button
        html.Button(
            [DashIconify(icon="tabler:chart-arrows", width=18), " Compare My Metrics"],
            id="compare-submit-btn",
            style={
                "background": COPPER,
                "color": "#fff",
                "border": "none",
                "padding": "0.7rem 1.5rem",
                "borderRadius": "8px",
                "fontSize": "1rem",
                "fontWeight": "600",
                "cursor": "pointer",
                "display": "flex",
                "alignItems": "center",
                "gap": "0.5rem",
                "marginBottom": "2rem",
            },
        ),

        # Results area
        html.Div(id="compare-results", children=[
            html.Div(
                "Enter your metrics above and click 'Compare My Metrics' to see your ranking.",
                style={"color": "#888", "fontStyle": "italic", "padding": "2rem 0"},
            ),
        ]),
    ], style={"padding": "1.5rem 2rem"})


# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------

@callback(
    Output("compare-results", "children"),
    Input("compare-submit-btn", "n_clicks"),
    State("compare-name", "value"),
    State("compare-h-index", "value"),
    State("compare-publications", "value"),
    State("compare-citations", "value"),
    State("compare-fwci", "value"),
    prevent_initial_call=True,
)
def update_comparison(n_clicks, name, h_index, publications, citations, fwci):
    """Process the comparison and return ranking results."""
    if not n_clicks:
        return no_update

    # Validate - at least one metric must be provided
    if all(v is None for v in [h_index, publications, citations, fwci]):
        return html.Div(
            "Please enter at least one metric to compare.",
            style={"color": ACCENT, "padding": "1rem 0"},
        )

    # Load the stats data
    df = load_stats()
    # Filter to only members with publications (accepted profiles)
    df = df[df["h_index"] > 0].copy()
    total = len(df)

    user_name = name or "You"

    # Calculate ranks and percentiles for each metric
    results = []
    user_percentiles = {}

    metric_inputs = {
        "h_index": h_index,
        "pub_count": publications,
        "citation_count": citations,
        "fwci_mean": fwci,
    }

    for col, label, desc, icon in METRICS:
        value = metric_inputs.get(col)
        if value is not None:
            value = float(value)
            series = df[col].dropna()
            percentile = _percentile_rank(value, series)
            rank = _rank_position(value, series)
            user_percentiles[label] = percentile
            results.append((col, label, value, rank, len(series), percentile, icon))

    if not results:
        return html.Div(
            "Please enter at least one metric to compare.",
            style={"color": ACCENT, "padding": "1rem 0"},
        )

    # Build the results layout
    children = []

    # Summary header
    if h_index is not None:
        h_rank = _rank_position(float(h_index), df["h_index"].dropna())
        h_pctile = _percentile_rank(float(h_index), df["h_index"].dropna())
        summary_text = (
            f"With an h-index of {int(h_index)}, {user_name} would rank "
            f"#{h_rank} out of {total} ACD dermatologists "
            f"(top {100 - h_pctile:.0f}%)."
        )
    else:
        first = results[0]
        summary_text = (
            f"{user_name} would rank #{first[3]} out of {first[4]} "
            f"ACD dermatologists in {first[1]} (top {100 - first[5]:.0f}%)."
        )

    children.append(html.Div([
        html.H3(f"Results for {user_name}", style={"color": "#eee", "marginBottom": "0.5rem"}),
        html.P(summary_text, style={"color": "#ccc", "fontSize": "1.05rem", "marginBottom": "1.5rem"}),
    ]))

    # Rank cards grid
    rank_cards = []
    for col, label, value, rank, count, percentile, icon in results:
        rank_cards.append(_build_rank_card(label, value, rank, count, percentile, icon))

    children.append(html.Div(
        rank_cards,
        style={
            "display": "grid",
            "gridTemplateColumns": "repeat(auto-fit, minmax(200px, 1fr))",
            "gap": "1rem",
            "marginBottom": "2rem",
        },
    ))

    # Radar chart (if 2+ metrics)
    if len(user_percentiles) >= 2:
        children.append(html.Div([
            html.H4("Percentile Profile", style={"color": "#eee", "marginBottom": "0.5rem"}),
            dcc.Graph(
                figure=_build_radar_chart(user_percentiles),
                config={"displayModeBar": False},
                style={"maxWidth": "500px"},
            ),
        ], style={"marginBottom": "2rem"}))

    # Distribution charts
    children.append(html.H4("Where You Stand", style={"color": "#eee", "marginBottom": "0.5rem"}))
    chart_grid = []
    for col, label, value, rank, count, percentile, icon in results:
        series = df[col].dropna()
        fig = _build_distribution_chart(series, value, label)
        chart_grid.append(html.Div([
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
        ]))

    children.append(html.Div(
        chart_grid,
        style={
            "display": "grid",
            "gridTemplateColumns": "1fr 1fr",
            "gap": "1rem",
            "marginBottom": "2rem",
        },
    ))

    # Nearby members table
    if h_index is not None:
        h_val = float(h_index)
        nearby = df.iloc[(df["h_index"] - h_val).abs().argsort()[:10]].copy()
        nearby = nearby.sort_values("h_index", ascending=False)

        table_rows = []
        for _, row in nearby.iterrows():
            table_rows.append(html.Tr([
                html.Td(row["acd_name"], style={"padding": "0.5rem", "color": "#ddd"}),
                html.Td(str(int(row["h_index"])), style={"padding": "0.5rem", "color": "#eee", "fontWeight": "600"}),
                html.Td(str(int(row.get("pub_count", 0))), style={"padding": "0.5rem", "color": "#ccc"}),
                html.Td(f"{int(row.get('citation_count', 0)):,}", style={"padding": "0.5rem", "color": "#ccc"}),
            ]))

        # Insert user row in the right position
        user_row = html.Tr([
            html.Td(f"→ {user_name}", style={"padding": "0.5rem", "color": ACCENT, "fontWeight": "700"}),
            html.Td(str(int(h_index)), style={"padding": "0.5rem", "color": ACCENT, "fontWeight": "700"}),
            html.Td(str(int(publications)) if publications else "—", style={"padding": "0.5rem", "color": ACCENT}),
            html.Td(f"{int(citations):,}" if citations else "—", style={"padding": "0.5rem", "color": ACCENT}),
        ], style={"background": "rgba(233, 69, 96, 0.15)"})

        # Find insertion point
        insert_idx = 0
        for i, (_, row) in enumerate(nearby.iterrows()):
            if row["h_index"] >= h_val:
                insert_idx = i + 1
            else:
                break
        table_rows.insert(insert_idx, user_row)

        children.append(html.Div([
            html.H4("Your Nearest Peers (by h-index)", style={"color": "#eee", "marginBottom": "0.5rem"}),
            html.Table([
                html.Thead(html.Tr([
                    html.Th("Name", style={"padding": "0.5rem", "color": "#aaa", "textAlign": "left"}),
                    html.Th("h-index", style={"padding": "0.5rem", "color": "#aaa", "textAlign": "left"}),
                    html.Th("Pubs", style={"padding": "0.5rem", "color": "#aaa", "textAlign": "left"}),
                    html.Th("Citations", style={"padding": "0.5rem", "color": "#aaa", "textAlign": "left"}),
                ]), style={"borderBottom": "1px solid #444"}),
                html.Tbody(table_rows),
            ], style={
                "width": "100%",
                "borderCollapse": "collapse",
                "background": CARD_BG,
                "borderRadius": "8px",
                "overflow": "hidden",
            }),
        ], style={"marginBottom": "2rem", "maxWidth": "800px"}))

    return html.Div(children)
