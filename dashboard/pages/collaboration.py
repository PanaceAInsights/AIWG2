"""ACD Dashboard — Collaboration network page."""
from __future__ import annotations

from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import numpy as np

from dashboard.theme import (
    COPPER, MAUVE_PURPLE, LIGHT_COPPER, BLUE_VIOLET, BG_CARD,
    TEXT_MUTED, WHITE, WARM_CREAM, apply_plotly_theme,
)
from dashboard.data import load_publications, get_all_states

PAGE_TITLE = "Collaboration"
PAGE_HREF  = "/collaboration"


def layout():
    states = ["All"] + get_all_states()
    return html.Div([
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Label("State", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Dropdown(
                        id="collab-state-filter",
                        options=[{"label": s, "value": s} for s in states],
                        value="All", clearable=False,
                        style={"backgroundColor": BG_CARD},
                    ),
                ], md=3),
                dbc.Col([
                    html.Label("Min. Shared Publications", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Slider(id="collab-min-shared", min=1, max=10, step=1, value=2,
                               marks={i: str(i) for i in range(1, 11)},
                               tooltip={"placement": "bottom"}),
                ], md=5),
            ]),
        ], className="acd-card"),

        html.Div([
            html.Div("Co-authorship Network", className="acd-section-header"),
            html.P(
                "Nodes represent dermatologists; edges indicate co-authorship. "
                "Node size reflects publication count. Increase the minimum shared publications "
                "threshold to reduce clutter.",
                style={"fontSize": "12px", "color": TEXT_MUTED, "marginBottom": "12px"},
            ),
            dcc.Graph(id="collab-network", config={"displayModeBar": True},
                      style={"height": "600px"}),
        ], className="acd-card"),

        html.Div([
            html.Div("Top Collaboration Pairs", className="acd-card-title"),
            html.Div(id="collab-top-pairs"),
        ], className="acd-card"),
    ])


def _build_network(pubs: pd.DataFrame, min_shared: int) -> tuple[list, list, list, list]:
    """Return (node_x, node_y, node_text, edge_traces) for a co-authorship network."""
    if pubs.empty or "acd_name" not in pubs.columns:
        return [], [], [], []

    # Build co-authorship from shared DOI/work_id
    id_col = next((c for c in ["DOI", "work_id", "WorkID"] if c in pubs.columns), None)
    if not id_col:
        return [], [], [], []

    # Group by work → list of authors
    work_authors = pubs.groupby(id_col)["acd_name"].apply(list)
    pairs: dict[tuple, int] = {}
    for authors in work_authors:
        authors = [a for a in authors if pd.notna(a)]
        for i in range(len(authors)):
            for j in range(i + 1, len(authors)):
                pair = tuple(sorted([authors[i], authors[j]]))
                pairs[pair] = pairs.get(pair, 0) + 1

    if not pairs:
        return [], [], [], []

    # Filter by min_shared
    pairs = {k: v for k, v in pairs.items() if v >= min_shared}
    if not pairs:
        return [], [], [], []

    # Build node positions (circular layout)
    nodes = list({n for pair in pairs for n in pair})
    n = len(nodes)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    pos = {node: (np.cos(a), np.sin(a)) for node, a in zip(nodes, angles)}

    node_counts = pubs["acd_name"].value_counts().to_dict()

    node_x = [pos[n][0] for n in nodes]
    node_y = [pos[n][1] for n in nodes]
    node_text = [f"{n} ({node_counts.get(n, 0)} pubs)" for n in nodes]
    node_sizes = [max(8, min(30, node_counts.get(n, 1) * 0.5)) for n in nodes]

    edge_traces = []
    for (a, b), weight in list(pairs.items())[:500]:  # cap for performance
        x0, y0 = pos[a]
        x1, y1 = pos[b]
        edge_traces.append(go.Scatter(
            x=[x0, x1, None], y=[y0, y1, None],
            mode="lines",
            line=dict(width=min(weight * 0.5, 3), color=MAUVE_PURPLE),
            hoverinfo="none",
            showlegend=False,
        ))

    return node_x, node_y, node_text, node_sizes, edge_traces, pairs


@callback(
    Output("collab-network", "figure"),
    Output("collab-top-pairs", "children"),
    Input("collab-state-filter", "value"),
    Input("collab-min-shared", "value"),
)
def update_network(state, min_shared):
    pubs = load_publications()
    if pubs.empty:
        return go.Figure(), html.Div("No data.", style={"color": TEXT_MUTED})

    result = _build_network(pubs, min_shared)
    if len(result) == 0 or not result[0]:
        return go.Figure(), html.Div("No co-authorship pairs found with this threshold.",
                                     style={"color": TEXT_MUTED})

    node_x, node_y, node_text, node_sizes, edge_traces, pairs = result

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        text=[t.split(" (")[0] for t in node_text],
        textposition="top center",
        textfont=dict(size=9, color=WARM_CREAM),
        hovertext=node_text,
        hoverinfo="text",
        marker=dict(
            size=node_sizes,
            color=COPPER,
            line=dict(width=1, color=LIGHT_COPPER),
        ),
    )

    fig = go.Figure(data=edge_traces + [node_trace])
    apply_plotly_theme(fig)
    fig.update_layout(
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=600,
    )

    # Top pairs table
    top_pairs = sorted(pairs.items(), key=lambda x: -x[1])[:20]
    items = [
        html.Div(f"{a} ↔ {b} — {count} shared publications",
                 style={"fontSize": "12px", "color": WARM_CREAM, "marginBottom": "4px"})
        for (a, b), count in top_pairs
    ]

    return fig, html.Div(items)
