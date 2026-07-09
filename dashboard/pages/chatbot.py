"""Ask AI — floating chat widget for free-text data exploration.

Builds a fixed-position chat bubble + expandable panel that sits on
every page. Injected into the shell layout (layout.py).
"""
from __future__ import annotations

import os

import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from .. import theme

_HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))

PAGE_TITLE = "AI Assistant"
PAGE_HREF  = "/chatbot"

EXAMPLE_QUESTIONS = [
    "Who are the top dermatology researchers?",
    "Compare NSW vs VIC research strength",
    "Where are the strategic research gaps?",
    "Which members are emerging stars?",
    "Summarise the cohort for a board paper",
]


def render() -> html.Div:
    """Placeholder — chatbot is a floating widget, not a page."""
    return html.Div(
        dmc.Text(
            "The research assistant is available as a floating "
            "chat widget in the bottom-right corner of every page.",
            size="sm", c="dimmed",
        ),
        style={"padding": "3rem", "textAlign": "center"},
    )


def build_widget() -> html.Div:
    """Return the floating chat widget for the layout shell."""
    if not _HAS_KEY:
        return html.Div([
            html.Div(id="ai-fab", style={"display": "none"}),
            html.Div(id="ai-chat-panel", style={"display": "none"}),
            html.Div(id="ai-close-btn", style={"display": "none"}),
            html.Div(id="ai-chat-messages", style={"display": "none"}),
            dcc.Input(id="ai-chat-input", type="hidden"),
            html.Div(id="ai-send-btn", style={"display": "none"}),
            *[html.Div(id=f"ai-ex-{i}", style={"display": "none"}) for i in range(5)],
            dcc.Store(id="ai-chat-history", data=[]),
            dcc.Store(id="ai-panel-open", data=False),
        ], style={"display": "none"})

    fab = dmc.ActionIcon(
        DashIconify(icon="tabler:message-circle-question", width=26),
        id="ai-fab",
        variant="filled",
        color="acd-copper",
        size="xl",
        radius="xl",
        style={
            "position": "fixed", "bottom": "24px", "right": "24px",
            "zIndex": 1100,
            "width": "54px", "height": "54px",
            "boxShadow": "0 4px 16px rgba(184,115,51,0.35)",
        },
    )

    example_row = html.Div(
        [
            dmc.Button(
                q, id=f"ai-ex-{i}",
                variant="light", color="gray", size="compact-xs",
                radius="xl",
                style={"fontSize": "0.7rem"},
            )
            for i, q in enumerate(EXAMPLE_QUESTIONS)
        ],
        style={"display": "flex", "gap": "4px", "flexWrap": "wrap",
               "padding": "6px 12px 8px"},
    )

    messages_area = html.Div(
        id="ai-chat-messages",
        children=[_welcome_bubble()],
        style={"flex": "1 1 0", "overflowY": "auto", "padding": "12px"},
    )

    input_row = html.Div(
        [
            dcc.Input(
                id="ai-chat-input",
                type="text",
                placeholder="Ask me to analyse, compare, or summarise...",
                debounce=False,
                style={
                    "flex": 1, "border": f"1px solid {theme.GRAY_200}",
                    "borderRadius": "8px", "padding": "8px 12px",
                    "fontSize": "0.85rem", "outline": "none",
                    "fontFamily": "Inter, sans-serif",
                },
            ),
            dmc.ActionIcon(
                DashIconify(icon="tabler:send", width=18),
                id="ai-send-btn",
                variant="filled", color="acd-copper", size="lg", radius="md",
            ),
        ],
        style={"display": "flex", "gap": "8px", "padding": "8px 12px 12px",
               "borderTop": f"1px solid {theme.GRAY_200}"},
    )

    panel_header = html.Div(
        [
            html.Div(
                [
                    DashIconify(icon="tabler:sparkles", width=16, color=theme.PRIMARY),
                    html.Span("Research Intelligence Analyst",
                              style={"fontWeight": 600, "fontSize": "0.85rem"}),
                ],
                style={"display": "flex", "alignItems": "center", "gap": "6px"},
            ),
            dmc.ActionIcon(
                DashIconify(icon="tabler:x", width=16),
                id="ai-close-btn",
                variant="subtle", color="gray", size="sm",
            ),
        ],
        style={"display": "flex", "justifyContent": "space-between",
               "alignItems": "center", "padding": "10px 14px",
               "borderBottom": f"1px solid {theme.GRAY_200}"},
    )

    panel = html.Div(
        [panel_header, example_row, messages_area, input_row],
        id="ai-chat-panel",
        style={
            "position": "fixed",
            "bottom": "88px", "right": "24px",
            "width": "440px", "height": "580px",
            "zIndex": 1099,
            "background": theme.WHITE,
            "borderRadius": "16px",
            "border": f"1px solid {theme.GRAY_200}",
            "boxShadow": "0 8px 32px rgba(0,0,0,0.15)",
            "display": "none",
            "flexDirection": "column",
            "fontFamily": "Inter, sans-serif",
        },
    )

    stores = [
        dcc.Store(id="ai-chat-history", data=[]),
        dcc.Store(id="ai-panel-open", data=False),
    ]

    return html.Div([fab, panel, *stores])


def _welcome_bubble() -> html.Div:
    return html.Div(
        html.Div(
            "I'm your Research Intelligence Analyst. I can synthesise data across "
            "all ACD members — compare states, identify strategic gaps, rank "
            "researchers, analyse trends, and prepare evidence summaries. "
            "Ask me anything about the cohort.",
            style={"fontSize": "0.82rem", "lineHeight": 1.6},
        ),
        style={
            "background": theme.GRAY_50,
            "borderRadius": "12px 12px 12px 2px",
            "padding": "8px 12px", "marginBottom": "6px",
            "maxWidth": "90%",
        },
    )


def build_user_bubble(text: str) -> html.Div:
    return html.Div(
        html.Div(text, style={"fontSize": "0.82rem", "lineHeight": 1.6,
                               "color": theme.WHITE}),
        style={
            "background": theme.PRIMARY,
            "borderRadius": "12px 12px 2px 12px",
            "padding": "8px 12px", "marginBottom": "6px",
            "marginLeft": "auto",
            "maxWidth": "80%", "width": "fit-content",
        },
    )


def build_assistant_bubble(text: str) -> html.Div:
    return html.Div(
        dcc.Markdown(text, style={"fontSize": "0.82rem", "lineHeight": 1.6},
                     className="ai-response-md"),
        style={
            "background": theme.GRAY_50,
            "borderRadius": "12px 12px 12px 2px",
            "padding": "8px 12px", "marginBottom": "6px",
            "maxWidth": "90%",
        },
    )


layout = render
