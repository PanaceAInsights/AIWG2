"""ACD Dashboard — AI Assistant (chatbot) page."""
from __future__ import annotations

import time
from dash import html, dcc, callback, Input, Output, State, no_update
import dash_bootstrap_components as dbc

from dashboard.theme import (
    COPPER, MAUVE_PURPLE, LIGHT_COPPER, BG_CARD, BORDER_COLOR,
    TEXT_MUTED, WHITE, WARM_CREAM, DARK_PLUM,
)
from dashboard.ai_tools import SUGGESTED_QUESTIONS, stream_response, build_context_snapshot

PAGE_TITLE = "AI Assistant"
PAGE_HREF  = "/chatbot"

_SNAPSHOT_CACHE: dict[str, str] = {}


def layout():
    return html.Div([
        dbc.Row([
            # Chat panel
            dbc.Col([
                html.Div([
                    html.Div("ACD Research Intelligence Assistant", className="acd-section-header"),
                    html.P(
                        "Ask me anything about the ACD dermatology research dataset — "
                        "publications, citations, funding, clinical trials, or expert identification.",
                        style={"fontSize": "13px", "color": TEXT_MUTED, "marginBottom": "16px"},
                    ),
                    # Message history
                    html.Div(
                        id="chatbot-messages",
                        style={
                            "minHeight": "400px", "maxHeight": "500px",
                            "overflowY": "auto", "marginBottom": "16px",
                            "padding": "8px",
                        },
                    ),
                    # Input area
                    html.Div([
                        dcc.Textarea(
                            id="chatbot-input",
                            placeholder="Ask a question about the ACD research data...",
                            style={
                                "width": "100%", "minHeight": "60px",
                                "backgroundColor": BG_CARD,
                                "border": f"1px solid {BORDER_COLOR}",
                                "borderRadius": "6px", "color": WARM_CREAM,
                                "padding": "10px", "resize": "none",
                                "fontFamily": "Inter, sans-serif", "fontSize": "13px",
                            },
                        ),
                        html.Div([
                            html.Button("Send", id="chatbot-send-btn",
                                        className="btn-copper",
                                        style={"padding": "8px 24px", "marginTop": "8px"}),
                            html.Button("Clear", id="chatbot-clear-btn",
                                        className="btn-outline-copper",
                                        style={"padding": "8px 16px", "marginTop": "8px", "marginLeft": "8px"}),
                        ]),
                    ], className="chat-input-area"),
                    # Loading indicator
                    dcc.Loading(
                        id="chatbot-loading",
                        type="dot",
                        color=COPPER,
                        children=html.Div(id="chatbot-loading-output"),
                    ),
                    # Store for conversation history
                    dcc.Store(id="chatbot-history", data=[]),
                    dcc.Store(id="chatbot-snapshot", data=""),
                ], className="acd-card"),
            ], md=8),

            # Suggestions panel
            dbc.Col([
                html.Div([
                    html.Div("Suggested Questions", className="acd-card-title"),
                    html.Div([
                        html.Div(
                            q,
                            id={"type": "suggestion-btn", "index": i},
                            n_clicks=0,
                            style={
                                "padding": "10px 12px",
                                "backgroundColor": DARK_PLUM,
                                "border": f"1px solid {BORDER_COLOR}",
                                "borderRadius": "6px",
                                "marginBottom": "8px",
                                "cursor": "pointer",
                                "fontSize": "13px",
                                "color": WARM_CREAM,
                                "transition": "background-color 0.2s",
                            },
                        )
                        for i, q in enumerate(SUGGESTED_QUESTIONS)
                    ]),
                ], className="acd-card"),

                html.Div([
                    html.Div("Data Coverage", className="acd-card-title"),
                    html.Div(id="chatbot-coverage-info",
                             style={"fontSize": "12px", "color": TEXT_MUTED}),
                ], className="acd-card"),
            ], md=4),
        ]),
    ])


@callback(
    Output("chatbot-messages", "children"),
    Output("chatbot-history", "data"),
    Output("chatbot-input", "value"),
    Output("chatbot-loading-output", "children"),
    Input("chatbot-send-btn", "n_clicks"),
    State("chatbot-input", "value"),
    State("chatbot-history", "data"),
    State("chatbot-snapshot", "data"),
    prevent_initial_call=True,
)
def send_message(n_clicks, user_input, history, snapshot):
    if not user_input or not user_input.strip():
        return no_update, no_update, no_update, no_update

    history = history or []
    history.append({"role": "user", "content": user_input.strip()})

    # Get snapshot if not cached
    if not snapshot:
        snapshot = build_context_snapshot()

    # Stream response (collect full response for display)
    response_parts = []
    for chunk in stream_response(history, snapshot):
        response_parts.append(chunk)
    response = "".join(response_parts)

    history.append({"role": "assistant", "content": response})

    # Build message bubbles
    bubbles = []
    for msg in history:
        if msg["role"] == "user":
            bubbles.append(html.Div(msg["content"], className="chat-bubble-user"))
        else:
            bubbles.append(html.Div(
                dcc.Markdown(msg["content"],
                             style={"color": WARM_CREAM, "fontSize": "13px"}),
                className="chat-bubble-assistant",
            ))

    return bubbles, history, "", ""


@callback(
    Output("chatbot-messages", "children", allow_duplicate=True),
    Output("chatbot-history", "data", allow_duplicate=True),
    Input("chatbot-clear-btn", "n_clicks"),
    prevent_initial_call=True,
)
def clear_chat(_):
    return [], []


@callback(
    Output("chatbot-input", "value", allow_duplicate=True),
    Input({"type": "suggestion-btn", "index": 0}, "n_clicks"),
    Input({"type": "suggestion-btn", "index": 1}, "n_clicks"),
    Input({"type": "suggestion-btn", "index": 2}, "n_clicks"),
    Input({"type": "suggestion-btn", "index": 3}, "n_clicks"),
    Input({"type": "suggestion-btn", "index": 4}, "n_clicks"),
    Input({"type": "suggestion-btn", "index": 5}, "n_clicks"),
    Input({"type": "suggestion-btn", "index": 6}, "n_clicks"),
    Input({"type": "suggestion-btn", "index": 7}, "n_clicks"),
    prevent_initial_call=True,
)
def fill_suggestion(*args):
    from dash import ctx
    if not ctx.triggered_id:
        return no_update
    idx = ctx.triggered_id.get("index", 0)
    return SUGGESTED_QUESTIONS[idx]


@callback(
    Output("chatbot-snapshot", "data"),
    Input("chatbot-send-btn", "id"),
)
def load_snapshot(_):
    return build_context_snapshot()


@callback(
    Output("chatbot-coverage-info", "children"),
    Input("chatbot-send-btn", "id"),
)
def show_coverage(_):
    from dashboard.data import get_summary_kpis
    kpis = get_summary_kpis()
    return html.Div([
        html.Div(f"Dermatologists: {kpis.get('n_total', 0)}", style={"marginBottom": "4px"}),
        html.Div(f"Resolved: {kpis.get('n_resolved', 0)}", style={"marginBottom": "4px"}),
        html.Div(f"Publications: {kpis.get('n_pubs', 0):,}", style={"marginBottom": "4px"}),
        html.Div(f"Clinical Trials: {kpis.get('n_trials', 0)}", style={"marginBottom": "4px"}),
    ])
