"""ACD Dashboard — Expert Finder page."""
from __future__ import annotations

from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import pandas as pd

from dashboard.theme import (
    COPPER, MAUVE_PURPLE, LIGHT_COPPER, BG_CARD, BORDER_COLOR,
    TEXT_MUTED, WHITE, WARM_CREAM, TIER_HIGH, TIER_REVIEW,
)
from dashboard.data import load_publications, load_authors, get_all_states, get_all_subtopics

PAGE_TITLE = "Expert Finder"
PAGE_HREF  = "/experts"


def layout():
    states = ["All"] + get_all_states()
    subtopics = get_all_subtopics()
    return html.Div([
        html.Div([
            html.Div("Find Experts by Research Topic", className="acd-section-header"),
            dbc.Row([
                dbc.Col([
                    html.Label("Research Topic / Keyword", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Dropdown(
                        id="experts-topic",
                        options=[{"label": s, "value": s} for s in subtopics],
                        placeholder="Select or search a topic...",
                        style={"backgroundColor": BG_CARD},
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("Free-text Keyword", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Input(
                        id="experts-keyword", type="text",
                        placeholder="e.g. melanoma, psoriasis, atopic dermatitis...",
                        debounce=True,
                        style={"width": "100%", "backgroundColor": BG_CARD,
                               "border": f"1px solid {BORDER_COLOR}", "borderRadius": "6px",
                               "color": WARM_CREAM, "padding": "8px 12px"},
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("State", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Dropdown(
                        id="experts-state",
                        options=[{"label": s, "value": s} for s in states],
                        value="All", clearable=False,
                        style={"backgroundColor": BG_CARD},
                    ),
                ], md=2),
                dbc.Col([
                    html.Div(style={"height": "20px"}),
                    html.Button("Find Experts", id="experts-search-btn",
                                className="btn-copper",
                                style={"width": "100%", "padding": "8px"}),
                ], md=2),
            ]),
        ], className="acd-card"),

        html.Div(id="experts-results"),
    ])


@callback(
    Output("experts-results", "children"),
    Input("experts-search-btn", "n_clicks"),
    Input("experts-topic", "value"),
    Input("experts-keyword", "value"),
    Input("experts-state", "value"),
    prevent_initial_call=True,
)
def find_experts(_, topic, keyword, state):
    pubs = load_publications()
    authors = load_authors()

    if pubs.empty:
        return html.Div("No publications data loaded.", style={"color": TEXT_MUTED, "padding": "20px"})

    # Filter publications by topic
    filtered = pubs.copy()
    if topic and "SubTopic" in filtered.columns:
        filtered = filtered[filtered["SubTopic"] == topic]

    if keyword:
        kw = keyword.lower()
        mask = pd.Series(False, index=filtered.index)
        for col in ["Title", "Keywords", "Abstract", "SubTopic", "Topic_Field"]:
            if col in filtered.columns:
                mask |= filtered[col].fillna("").str.lower().str.contains(kw, na=False)
        filtered = filtered[mask]

    if filtered.empty:
        return html.Div("No experts found for this query.", style={"color": TEXT_MUTED, "padding": "20px"})

    # Aggregate by researcher
    cite_col = next((c for c in ["CitedByCount", "cited_by_count"] if c in filtered.columns), None)
    if cite_col:
        agg = filtered.groupby("acd_name").agg(
            pubs=("acd_name", "count"),
            citations=(cite_col, "sum"),
        ).reset_index()
    else:
        agg = filtered.groupby("acd_name").size().reset_index(name="pubs")
        agg["citations"] = 0

    # Merge author metadata
    if not authors.empty and "acd_name" in authors.columns:
        meta_cols = ["acd_name", "state", "confidence", "last_known_institution", "openalex_id"]
        meta_cols = [c for c in meta_cols if c in authors.columns]
        agg = agg.merge(authors[meta_cols], on="acd_name", how="left")

    # Filter by state
    if state and state != "All" and "state" in agg.columns:
        agg = agg[agg["state"] == state]

    agg = agg.sort_values("pubs", ascending=False).head(30)

    if agg.empty:
        return html.Div("No experts found for this query.", style={"color": TEXT_MUTED, "padding": "20px"})

    cards = []
    for rank, (_, row) in enumerate(agg.iterrows(), 1):
        conf = str(row.get("confidence", "")).upper()
        badge_cls = {"HIGH": "badge-high", "REVIEW": "badge-review"}.get(conf, "badge-notfound")
        cards.append(
            dbc.Col(html.Div([
                html.Div([
                    html.Span(f"#{rank}", style={"fontSize": "11px", "color": TEXT_MUTED, "marginRight": "8px"}),
                    html.Span(row.get("acd_name", ""), style={"fontSize": "15px", "fontWeight": "600", "color": WHITE}),
                    html.Span(conf, className=badge_cls, style={"marginLeft": "8px"}),
                ], style={"marginBottom": "8px"}),
                html.Div([
                    html.Span(f"{int(row.get('pubs', 0))} publications", style={"color": COPPER, "fontSize": "13px", "marginRight": "12px"}),
                    html.Span(f"{int(row.get('citations', 0))} citations", style={"color": LIGHT_COPPER, "fontSize": "13px"}),
                ]),
                html.Div(row.get("state", ""), style={"fontSize": "12px", "color": TEXT_MUTED, "marginTop": "4px"}),
                html.Div(str(row.get("last_known_institution", ""))[:60],
                         style={"fontSize": "11px", "color": TEXT_MUTED, "marginTop": "2px"}),
            ], className="acd-card", style={"minHeight": "110px"}), md=4)
        )

    rows = []
    for i in range(0, len(cards), 3):
        rows.append(dbc.Row(cards[i:i+3]))

    return html.Div([
        html.Div(f"Found {len(agg)} experts", style={"color": TEXT_MUTED, "fontSize": "13px", "marginBottom": "12px"}),
        *rows,
    ])
