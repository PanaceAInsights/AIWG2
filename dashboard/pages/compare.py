"""ACD Dashboard — Compare & Rank page (v2 — Modern Visual Design).

Users enter their own metrics (h-index, citations, publications, FWCI)
and see where they would rank among all ACD dermatologists, with
animated gauge charts, gradient area distributions, glassmorphism cards,
and a polished radar chart.
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

# Modern color palette
COPPER = "#B87333"
DARK_BG = "#0f0f23"
CARD_BG = "rgba(22, 33, 62, 0.6)"
GLASS_BG = "rgba(255, 255, 255, 0.03)"
GLASS_BORDER = "rgba(255, 255, 255, 0.08)"
ACCENT = "#e94560"
GOLD = "#FFD700"
TEAL = "#00d4aa"
PURPLE = "#a855f7"
BLUE = "#3b82f6"

METRIC_COLORS = {
    "h-index": "#FFD700",
    "Publications": "#00d4aa",
    "Citations": "#3b82f6",
    "FWCI": "#a855f7",
}

METRIC_GRADIENTS = {
    "h-index": ["#FFD700", "#FF8C00"],
    "Publications": ["#00d4aa", "#00b4d8"],
    "Citations": ["#3b82f6", "#8b5cf6"],
    "FWCI": ["#a855f7", "#ec4899"],
}


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


def _build_gauge_chart(value: float, percentile: float, label: str,
                       color: str, gradient: list) -> go.Figure:
    """Build an animated semicircular gauge chart."""
    fig = go.Figure()

    # Background arc
    fig.add_trace(go.Pie(
        values=[1],
        hole=0.75,
        marker=dict(colors=["rgba(255,255,255,0.05)"]),
        textinfo="none",
        hoverinfo="none",
        showlegend=False,
    ))

    # Use indicator gauge for the main display
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=percentile,
        number=dict(
            suffix="th",
            font=dict(size=28, color=color, family="Inter, sans-serif"),
        ),
        gauge=dict(
            axis=dict(
                range=[0, 100],
                tickwidth=0,
                tickcolor="rgba(0,0,0,0)",
                dtick=25,
                tickfont=dict(size=9, color="#666"),
            ),
            bar=dict(color=color, thickness=0.85),
            bgcolor="rgba(255,255,255,0.04)",
            borderwidth=0,
            steps=[
                dict(range=[0, 25], color="rgba(255,255,255,0.02)"),
                dict(range=[25, 50], color="rgba(255,255,255,0.03)"),
                dict(range=[50, 75], color="rgba(255,255,255,0.04)"),
                dict(range=[75, 100], color="rgba(255,255,255,0.06)"),
            ],
            threshold=dict(
                line=dict(color=ACCENT, width=3),
                thickness=0.9,
                value=percentile,
            ),
        ),
    ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=30, b=10),
        height=160,
        font=dict(color="#ccc", family="Inter, sans-serif"),
    )
    return fig


def _build_distribution_chart(series: pd.Series, user_value: float,
                              metric_label: str, color: str,
                              gradient: list) -> go.Figure:
    """Build a gradient-filled area chart showing distribution with user position."""
    fig = go.Figure()

    # Calculate KDE-like smooth distribution
    s = series.dropna().values
    if len(s) < 5:
        return go.Figure()

    # Create histogram data for smooth area
    counts, bin_edges = np.histogram(s, bins=40)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

    # Smooth the counts slightly
    from scipy.ndimage import gaussian_filter1d
    smooth_counts = gaussian_filter1d(counts.astype(float), sigma=1.2)

    # Gradient area fill
    fig.add_trace(go.Scatter(
        x=bin_centers,
        y=smooth_counts,
        mode="lines",
        fill="tozeroy",
        line=dict(color=color, width=2.5, shape="spline"),
        fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.15)",
        fillgradient=dict(
            type="vertical",
            colorscale=[[0, f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.01)"],
                        [1, f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.3)"]],
        ) if hasattr(go.Scatter, 'fillgradient') else None,
        hovertemplate=f"{metric_label}: %{{x:.1f}}<br>Members: %{{y:.0f}}<extra></extra>",
        name="",
    ))

    # User position - glowing vertical line
    if not pd.isna(user_value):
        # Add a subtle glow effect with multiple lines
        for width, opacity in [(8, 0.1), (4, 0.3), (2, 0.8)]:
            fig.add_vline(
                x=user_value,
                line_width=width,
                line_color=f"rgba(233, 69, 96, {opacity})",
            )
        # Annotation with modern styling
        fig.add_annotation(
            x=user_value,
            y=max(smooth_counts) * 0.95,
            text=f"<b>YOU</b><br>{user_value:.1f}",
            showarrow=True,
            arrowhead=0,
            arrowwidth=1.5,
            arrowcolor=ACCENT,
            ax=30,
            ay=-30,
            font=dict(size=11, color=ACCENT, family="Inter, sans-serif"),
            bordercolor=ACCENT,
            borderwidth=1,
            borderpad=4,
            bgcolor="rgba(233, 69, 96, 0.1)",
        )

    fig.update_layout(
        xaxis=dict(
            title=dict(text=metric_label, font=dict(size=11, color="#888")),
            gridcolor="rgba(255,255,255,0.04)",
            zeroline=False,
            tickfont=dict(size=10, color="#666"),
        ),
        yaxis=dict(
            title=dict(text="Members", font=dict(size=11, color="#888")),
            gridcolor="rgba(255,255,255,0.04)",
            zeroline=False,
            tickfont=dict(size=10, color="#666"),
        ),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=45, r=15, t=15, b=45),
        height=220,
        showlegend=False,
        font=dict(color="#ccc", family="Inter, sans-serif"),
    )

    return fig


def _build_radar_chart(user_percentiles: dict) -> go.Figure:
    """Build a polished radar/spider chart with gradient fill and glow."""
    categories = list(user_percentiles.keys())
    values = list(user_percentiles.values())
    # Close the polygon
    categories.append(categories[0])
    values.append(values[0])

    fig = go.Figure()

    # Background rings for reference
    for ring_val in [25, 50, 75]:
        fig.add_trace(go.Scatterpolar(
            r=[ring_val] * len(categories),
            theta=categories,
            mode="lines",
            line=dict(color="rgba(255,255,255,0.06)", width=1, dash="dot"),
            showlegend=False,
            hoverinfo="none",
        ))

    # Main user polygon with glow effect
    # Outer glow
    fig.add_trace(go.Scatterpolar(
        r=values,
        theta=categories,
        fill="toself",
        fillcolor="rgba(255, 215, 0, 0.05)",
        line=dict(color="rgba(255, 215, 0, 0.3)", width=6),
        showlegend=False,
        hoverinfo="none",
    ))

    # Main polygon
    fig.add_trace(go.Scatterpolar(
        r=values,
        theta=categories,
        fill="toself",
        fillcolor="rgba(255, 215, 0, 0.12)",
        line=dict(color=GOLD, width=2.5),
        marker=dict(
            size=10,
            color=GOLD,
            line=dict(color="#fff", width=2),
            symbol="circle",
        ),
        name="Your Percentile",
        hovertemplate="%{theta}: %{r:.0f}th percentile<extra></extra>",
    ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                tickvals=[25, 50, 75, 100],
                ticktext=["25th", "50th", "75th", "100th"],
                tickfont=dict(size=9, color="#555"),
                gridcolor="rgba(255,255,255,0.04)",
                linecolor="rgba(255,255,255,0.05)",
            ),
            angularaxis=dict(
                tickfont=dict(size=13, color="#ddd", family="Inter, sans-serif"),
                gridcolor="rgba(255,255,255,0.06)",
                linecolor="rgba(255,255,255,0.06)",
            ),
            bgcolor="rgba(0,0,0,0)",
        ),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=80, r=80, t=40, b=40),
        height=380,
        showlegend=False,
        font=dict(color="#ccc", family="Inter, sans-serif"),
    )
    return fig


def _build_rank_card(metric_label: str, value: float, rank: int,
                     total: int, percentile: float, icon: str) -> html.Div:
    """Build a modern glassmorphism metric rank card with gauge."""
    color = METRIC_COLORS.get(metric_label, COPPER)
    gradient = METRIC_GRADIENTS.get(metric_label, [COPPER, GOLD])

    gauge_fig = _build_gauge_chart(value, percentile, metric_label, color, gradient)

    # Determine tier label
    if percentile >= 90:
        tier = "Elite"
        tier_color = GOLD
    elif percentile >= 75:
        tier = "Excellent"
        tier_color = TEAL
    elif percentile >= 50:
        tier = "Above Average"
        tier_color = BLUE
    elif percentile >= 25:
        tier = "Developing"
        tier_color = "#888"
    else:
        tier = "Emerging"
        tier_color = "#666"

    return html.Div([
        # Header with icon and label
        html.Div([
            html.Div([
                DashIconify(icon=icon, width=22, color=color),
            ], style={
                "width": "36px", "height": "36px", "borderRadius": "8px",
                "display": "flex", "alignItems": "center", "justifyContent": "center",
                "background": f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.12)",
            }),
            html.Span(metric_label, style={
                "fontWeight": "600", "fontSize": "0.9rem", "color": "#ddd",
                "fontFamily": "Inter, sans-serif",
            }),
        ], style={"display": "flex", "alignItems": "center", "gap": "0.6rem", "marginBottom": "0.3rem"}),

        # Gauge chart
        dcc.Graph(
            figure=gauge_fig,
            config={"displayModeBar": False},
            style={"marginTop": "-10px", "marginBottom": "-15px"},
        ),

        # Value display
        html.Div([
            html.Span(
                f"{value:.1f}" if isinstance(value, float) and value != int(value) else str(int(value)),
                style={"fontSize": "1.6rem", "fontWeight": "700", "color": color,
                       "fontFamily": "Inter, sans-serif"},
            ),
        ], style={"textAlign": "center"}),

        # Rank info
        html.Div([
            html.Div([
                html.Span("Rank ", style={"color": "#777", "fontSize": "0.8rem"}),
                html.Span(f"#{rank}", style={"fontWeight": "700", "color": "#eee", "fontSize": "0.9rem"}),
                html.Span(f" / {total}", style={"color": "#666", "fontSize": "0.8rem"}),
            ], style={"textAlign": "center"}),
            html.Div([
                html.Span(tier, style={
                    "fontSize": "0.7rem", "fontWeight": "600", "color": tier_color,
                    "textTransform": "uppercase", "letterSpacing": "0.5px",
                    "padding": "2px 8px", "borderRadius": "4px",
                    "background": f"rgba({int(tier_color[1:3],16)},{int(tier_color[3:5],16)},{int(tier_color[5:7],16)},0.12)",
                }),
            ], style={"textAlign": "center", "marginTop": "0.4rem"}),
        ], style={"marginTop": "0.3rem"}),
    ], className="compare-glass-card")


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

def render() -> html.Div:
    """Return the Compare & Rank page layout."""
    return html.Div([
        # Hero section
        html.Div([
            html.Div([
                DashIconify(icon="tabler:chart-arrows-vertical", width=32, color=GOLD),
            ], style={
                "width": "56px", "height": "56px", "borderRadius": "14px",
                "display": "flex", "alignItems": "center", "justifyContent": "center",
                "background": "rgba(255, 215, 0, 0.08)",
                "border": "1px solid rgba(255, 215, 0, 0.15)",
                "marginBottom": "1rem",
            }),
            html.H2("Compare & Rank", style={
                "color": "#fff", "marginBottom": "0.4rem", "fontSize": "1.8rem",
                "fontWeight": "700", "fontFamily": "Inter, sans-serif",
            }),
            html.P(
                "Enter your research metrics to discover where you stand among "
                "all Australasian College of Dermatologists members.",
                style={"color": "#999", "marginBottom": "0", "maxWidth": "600px",
                       "lineHeight": "1.6", "fontSize": "0.95rem"},
            ),
        ], style={"marginBottom": "2rem"}),

        # Input form with glassmorphism
        html.Div([
            html.Div([
                html.Label("Your Name", style={
                    "color": "#aaa", "fontSize": "0.8rem", "fontWeight": "500",
                    "textTransform": "uppercase", "letterSpacing": "0.5px",
                    "marginBottom": "0.4rem", "display": "block",
                }),
                dcc.Input(
                    id="compare-name",
                    type="text",
                    placeholder="e.g., Dr Jane Smith",
                    className="compare-input",
                ),
            ], style={"gridColumn": "span 2"}),

            html.Div([
                html.Label("h-index", style={
                    "color": "#aaa", "fontSize": "0.8rem", "fontWeight": "500",
                    "textTransform": "uppercase", "letterSpacing": "0.5px",
                    "marginBottom": "0.4rem", "display": "block",
                }),
                dcc.Input(
                    id="compare-h-index",
                    type="number",
                    placeholder="e.g., 15",
                    min=0, max=200,
                    className="compare-input",
                ),
            ]),

            html.Div([
                html.Label("Total Publications", style={
                    "color": "#aaa", "fontSize": "0.8rem", "fontWeight": "500",
                    "textTransform": "uppercase", "letterSpacing": "0.5px",
                    "marginBottom": "0.4rem", "display": "block",
                }),
                dcc.Input(
                    id="compare-publications",
                    type="number",
                    placeholder="e.g., 50",
                    min=0, max=5000,
                    className="compare-input",
                ),
            ]),

            html.Div([
                html.Label("Total Citations", style={
                    "color": "#aaa", "fontSize": "0.8rem", "fontWeight": "500",
                    "textTransform": "uppercase", "letterSpacing": "0.5px",
                    "marginBottom": "0.4rem", "display": "block",
                }),
                dcc.Input(
                    id="compare-citations",
                    type="number",
                    placeholder="e.g., 500",
                    min=0, max=100000,
                    className="compare-input",
                ),
            ]),

            html.Div([
                html.Label("FWCI", style={
                    "color": "#aaa", "fontSize": "0.8rem", "fontWeight": "500",
                    "textTransform": "uppercase", "letterSpacing": "0.5px",
                    "marginBottom": "0.4rem", "display": "block",
                }),
                dcc.Input(
                    id="compare-fwci",
                    type="number",
                    placeholder="e.g., 1.5",
                    min=0, max=50, step=0.01,
                    className="compare-input",
                ),
            ]),
        ], className="compare-form-grid"),

        # Compare button
        dmc.Button(
            "Analyze My Position",
            id="compare-submit-btn",
            leftSection=DashIconify(icon="tabler:sparkles", width=20),
            size="lg",
            variant="gradient",
            gradient={"from": "#e94560", "to": "#FF6B6B", "deg": 135},
            n_clicks=0,
            style={
                "marginTop": "1.5rem",
                "padding": "0.8rem 2.5rem",
                "fontSize": "1.05rem",
                "fontWeight": "600",
                "borderRadius": "12px",
                "boxShadow": "0 4px 20px rgba(233, 69, 96, 0.3)",
                "cursor": "pointer",
            },
        ),

        # Results area
        html.Div(id="compare-results", children=[
            html.Div([
                DashIconify(icon="tabler:chart-dots-3", width=48, color="#444"),
                html.P(
                    "Enter your metrics above and click 'Analyze My Position' to see your ranking.",
                    style={"color": "#666", "marginTop": "1rem", "fontSize": "0.95rem"},
                ),
            ], style={"textAlign": "center", "padding": "4rem 0"}),
        ]),
    ], style={"padding": "1.5rem 2rem", "maxWidth": "1200px"})


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
            [DashIconify(icon="tabler:alert-circle", width=20, color=ACCENT),
             html.Span(" Please enter at least one metric to compare.", style={"color": ACCENT})],
            style={"display": "flex", "alignItems": "center", "gap": "0.5rem", "padding": "1rem 0"},
        )

    # Load the stats data
    df = load_stats()
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
        return no_update

    # Build the results layout
    children = []

    # Summary banner with gradient
    if h_index is not None:
        h_rank = _rank_position(float(h_index), df["h_index"].dropna())
        h_pctile = _percentile_rank(float(h_index), df["h_index"].dropna())
        top_pct = 100 - h_pctile
        summary_rank = f"#{h_rank}"
        summary_detail = f"out of {total} ACD dermatologists"
    else:
        first = results[0]
        top_pct = 100 - first[5]
        summary_rank = f"#{first[3]}"
        summary_detail = f"out of {first[4]} in {first[1]}"

    children.append(html.Div([
        html.Div([
            html.Div([
                html.Span(summary_rank, style={
                    "fontSize": "3rem", "fontWeight": "800", "color": "#fff",
                    "lineHeight": "1", "fontFamily": "Inter, sans-serif",
                }),
                html.Div([
                    html.Span(summary_detail, style={"color": "rgba(255,255,255,0.7)", "fontSize": "0.9rem"}),
                    html.Br(),
                    html.Span(f"Top {top_pct:.0f}%", style={
                        "color": GOLD, "fontSize": "1.1rem", "fontWeight": "700",
                    }),
                ], style={"marginLeft": "1rem"}),
            ], style={"display": "flex", "alignItems": "center"}),
            html.P(f"Based on the metrics provided for {user_name}", style={
                "color": "rgba(255,255,255,0.5)", "fontSize": "0.85rem", "marginTop": "0.5rem",
            }),
        ], style={"flex": "1"}),
        html.Div([
            DashIconify(icon="tabler:trophy", width=64, color="rgba(255,215,0,0.3)"),
        ]),
    ], className="compare-summary-banner"))

    # Gauge cards grid
    rank_cards = []
    for col, label, value, rank, count, percentile, icon in results:
        rank_cards.append(_build_rank_card(label, value, rank, count, percentile, icon))

    children.append(html.Div([
        html.H4("Metric Breakdown", style={
            "color": "#eee", "marginBottom": "1rem", "fontSize": "1.1rem",
            "fontWeight": "600", "fontFamily": "Inter, sans-serif",
        }),
        html.Div(rank_cards, className="compare-cards-grid"),
    ], style={"marginBottom": "2.5rem"}))

    # Radar chart (if 2+ metrics)
    if len(user_percentiles) >= 2:
        children.append(html.Div([
            html.H4("Percentile Profile", style={
                "color": "#eee", "marginBottom": "0.5rem", "fontSize": "1.1rem",
                "fontWeight": "600", "fontFamily": "Inter, sans-serif",
            }),
            html.P("Your position relative to all ACD members across each metric",
                   style={"color": "#777", "fontSize": "0.85rem", "marginBottom": "0.5rem"}),
            html.Div([
                dcc.Graph(
                    figure=_build_radar_chart(user_percentiles),
                    config={"displayModeBar": False},
                ),
            ], className="compare-glass-panel"),
        ], style={"marginBottom": "2.5rem"}))

    # Distribution charts
    children.append(html.Div([
        html.H4("Distribution Analysis", style={
            "color": "#eee", "marginBottom": "0.5rem", "fontSize": "1.1rem",
            "fontWeight": "600", "fontFamily": "Inter, sans-serif",
        }),
        html.P("See where your metrics fall within the full ACD membership distribution",
               style={"color": "#777", "fontSize": "0.85rem", "marginBottom": "1rem"}),
    ]))

    chart_grid = []
    for col, label, value, rank, count, percentile, icon in results:
        series = df[col].dropna()
        color = METRIC_COLORS.get(label, COPPER)
        gradient = METRIC_GRADIENTS.get(label, [COPPER, GOLD])
        fig = _build_distribution_chart(series, value, label, color, gradient)
        chart_grid.append(html.Div([
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
        ], className="compare-glass-panel"))

    children.append(html.Div(
        chart_grid,
        style={
            "display": "grid",
            "gridTemplateColumns": "1fr 1fr",
            "gap": "1rem",
            "marginBottom": "2.5rem",
        },
    ))

    # Nearby members table with modern styling
    if h_index is not None:
        h_val = float(h_index)
        nearby = df.iloc[(df["h_index"] - h_val).abs().argsort()[:10]].copy()
        nearby = nearby.sort_values("h_index", ascending=False)

        table_rows = []
        for _, row in nearby.iterrows():
            table_rows.append(html.Tr([
                html.Td(row["acd_name"], style={"padding": "0.7rem 1rem", "color": "#ccc", "fontSize": "0.9rem"}),
                html.Td(str(int(row["h_index"])), style={
                    "padding": "0.7rem", "color": GOLD, "fontWeight": "600", "textAlign": "center",
                }),
                html.Td(str(int(row.get("pub_count", 0))), style={
                    "padding": "0.7rem", "color": TEAL, "textAlign": "center",
                }),
                html.Td(f"{int(row.get('citation_count', 0)):,}", style={
                    "padding": "0.7rem", "color": BLUE, "textAlign": "center",
                }),
            ], style={"borderBottom": "1px solid rgba(255,255,255,0.04)"}))

        # Insert user row in the right position
        user_row = html.Tr([
            html.Td([
                DashIconify(icon="tabler:arrow-right", width=14, color=ACCENT),
                html.Span(f" {user_name}", style={"fontWeight": "700"}),
            ], style={"padding": "0.7rem 1rem", "color": ACCENT, "fontSize": "0.9rem"}),
            html.Td(str(int(h_index)), style={
                "padding": "0.7rem", "color": ACCENT, "fontWeight": "700", "textAlign": "center",
            }),
            html.Td(str(int(publications)) if publications else "—", style={
                "padding": "0.7rem", "color": ACCENT, "textAlign": "center",
            }),
            html.Td(f"{int(citations):,}" if citations else "—", style={
                "padding": "0.7rem", "color": ACCENT, "textAlign": "center",
            }),
        ], style={
            "background": "rgba(233, 69, 96, 0.08)",
            "borderBottom": "1px solid rgba(233, 69, 96, 0.2)",
            "borderTop": "1px solid rgba(233, 69, 96, 0.2)",
        })

        # Find insertion point
        insert_idx = 0
        for i, (_, row) in enumerate(nearby.iterrows()):
            if row["h_index"] >= h_val:
                insert_idx = i + 1
            else:
                break
        table_rows.insert(insert_idx, user_row)

        children.append(html.Div([
            html.H4("Your Nearest Peers", style={
                "color": "#eee", "marginBottom": "0.5rem", "fontSize": "1.1rem",
                "fontWeight": "600", "fontFamily": "Inter, sans-serif",
            }),
            html.P("Members with similar h-index values",
                   style={"color": "#777", "fontSize": "0.85rem", "marginBottom": "1rem"}),
            html.Div([
                html.Table([
                    html.Thead(html.Tr([
                        html.Th("Name", style={
                            "padding": "0.7rem 1rem", "color": "#666", "textAlign": "left",
                            "fontSize": "0.75rem", "textTransform": "uppercase", "letterSpacing": "0.5px",
                            "fontWeight": "600",
                        }),
                        html.Th("h-index", style={
                            "padding": "0.7rem", "color": "#666", "textAlign": "center",
                            "fontSize": "0.75rem", "textTransform": "uppercase", "letterSpacing": "0.5px",
                            "fontWeight": "600",
                        }),
                        html.Th("Pubs", style={
                            "padding": "0.7rem", "color": "#666", "textAlign": "center",
                            "fontSize": "0.75rem", "textTransform": "uppercase", "letterSpacing": "0.5px",
                            "fontWeight": "600",
                        }),
                        html.Th("Citations", style={
                            "padding": "0.7rem", "color": "#666", "textAlign": "center",
                            "fontSize": "0.75rem", "textTransform": "uppercase", "letterSpacing": "0.5px",
                            "fontWeight": "600",
                        }),
                    ]), style={"borderBottom": "1px solid rgba(255,255,255,0.08)"}),
                    html.Tbody(table_rows),
                ], style={"width": "100%", "borderCollapse": "collapse"}),
            ], className="compare-glass-panel", style={"padding": "0", "overflow": "hidden"}),
        ], style={"marginBottom": "2rem"}))

    return html.Div(children)
