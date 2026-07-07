"""ACD Research Intelligence Platform — Shell layout (sidebar + topbar + footer)."""
from __future__ import annotations

from dash import html, dcc
import dash_bootstrap_components as dbc

from dashboard.theme import (
    BG_MAIN, BG_SIDEBAR, DARK_PLUM, COPPER, BURNT_COPPER, LIGHT_COPPER,
    MAUVE_PURPLE, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, BORDER_COLOR,
    WARM_CREAM, WHITE, FONT_FAMILY, SIDEBAR_WIDTH, TOPBAR_HEIGHT,
    NAV_ACTIVE_BG, NAV_HOVER_BG,
)

NAV = [
    {"label": "Overview",       "href": "/",              "icon": "bi bi-grid-fill"},
    {"label": "Profiles",       "href": "/profiles",      "icon": "bi bi-person-lines-fill"},
    {"label": "Publications",   "href": "/publications",  "icon": "bi bi-journal-text"},
    {"label": "Impact",         "href": "/impact",        "icon": "bi bi-graph-up-arrow"},
    {"label": "Funding",        "href": "/funding",       "icon": "bi bi-cash-coin"},
    {"label": "Clinical Trials","href": "/trials",        "icon": "bi bi-clipboard2-pulse-fill"},
    {"label": "Heatmap",        "href": "/heatmap",       "icon": "bi bi-grid-3x3"},
    {"label": "Collaboration",  "href": "/collaboration", "icon": "bi bi-diagram-3-fill"},
    {"label": "Benchmarking",   "href": "/benchmarking",  "icon": "bi bi-bar-chart-fill"},
    {"label": "Expert Finder",  "href": "/experts",       "icon": "bi bi-search"},
    {"label": "AI Assistant",   "href": "/chatbot",       "icon": "bi bi-robot"},
    {"label": "Methodology",    "href": "/methodology",   "icon": "bi bi-info-circle-fill"},
]


def _nav_link(item: dict) -> html.Div:
    return html.Div(
        dcc.Link(
            html.Div([
                html.I(className=item["icon"], style={"marginRight": "10px", "fontSize": "14px"}),
                html.Span(item["label"], style={"fontSize": "13px"}),
            ], style={"display": "flex", "alignItems": "center", "padding": "9px 16px",
                      "borderRadius": "6px", "cursor": "pointer"}),
            href=item["href"],
            className="acd-nav-link",
            style={"textDecoration": "none", "color": TEXT_SECONDARY},
        ),
        style={"marginBottom": "2px"},
    )


def build_sidebar() -> html.Div:
    return html.Div(
        id="acd-sidebar",
        children=[
            # Logo / brand
            html.Div([
                html.Div("ACD", style={
                    "fontSize": "22px", "fontWeight": "700",
                    "color": COPPER, "letterSpacing": "3px",
                }),
                html.Div("Research Intelligence", style={
                    "fontSize": "10px", "color": TEXT_MUTED,
                    "letterSpacing": "1.5px", "textTransform": "uppercase",
                    "marginTop": "2px",
                }),
            ], style={
                "padding": "20px 16px 18px",
                "borderBottom": f"1px solid {BORDER_COLOR}",
                "marginBottom": "10px",
            }),
            # Navigation
            html.Div(
                [_nav_link(item) for item in NAV],
                style={"padding": "0 8px"},
            ),
            # Footer attribution
            html.Div([
                html.Hr(style={"borderColor": BORDER_COLOR, "margin": "12px 0"}),
                html.Div([
                    "Developed by ",
                    html.A("Dr Yagiz Aksoy MD PhD",
                           href="https://www.linkedin.com/in/yagizalpaksoy/",
                           target="_blank",
                           style={"color": LIGHT_COPPER, "textDecoration": "none"}),
                ], style={"fontSize": "10px", "color": TEXT_MUTED, "marginBottom": "4px"}),
                html.Div([
                    html.A("PanaceaAI",
                           href="https://www.panaceainsights.com.au",
                           target="_blank",
                           style={"color": COPPER, "textDecoration": "none", "fontSize": "10px"}),
                ]),
            ], style={"position": "absolute", "bottom": "16px", "left": "0", "right": "0", "padding": "0 16px"}),
        ],
        style={
            "width": SIDEBAR_WIDTH,
            "minHeight": "100vh",
            "backgroundColor": BG_SIDEBAR,
            "position": "fixed",
            "top": "0",
            "left": "0",
            "zIndex": "1000",
            "display": "flex",
            "flexDirection": "column",
            "fontFamily": FONT_FAMILY,
            "overflowY": "auto",
            "overflowX": "hidden",
        },
    )


def build_topbar(page_title: str = "Overview") -> html.Div:
    return html.Div(
        id="acd-topbar",
        children=[
            html.Div(id="acd-page-title", children=page_title, style={
                "fontSize": "18px", "fontWeight": "600",
                "color": WHITE, "letterSpacing": "0.5px",
            }),
            html.Div([
                html.Span("Australasian College of Dermatologists",
                          style={"fontSize": "12px", "color": TEXT_MUTED}),
            ]),
        ],
        style={
            "marginLeft": SIDEBAR_WIDTH,
            "height": TOPBAR_HEIGHT,
            "backgroundColor": DARK_PLUM,
            "borderBottom": f"1px solid {BORDER_COLOR}",
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "space-between",
            "padding": "0 24px",
            "position": "fixed",
            "top": "0",
            "right": "0",
            "left": SIDEBAR_WIDTH,
            "zIndex": "999",
            "fontFamily": FONT_FAMILY,
        },
    )


def build_shell() -> html.Div:
    """Full app shell with sidebar, topbar, and page content outlet."""
    return html.Div([
        dcc.Location(id="url", refresh=False),
        build_sidebar(),
        build_topbar(),
        html.Div(
            id="page-content",
            style={
                "marginLeft": SIDEBAR_WIDTH,
                "marginTop": TOPBAR_HEIGHT,
                "padding": "24px",
                "backgroundColor": BG_MAIN,
                "minHeight": f"calc(100vh - {TOPBAR_HEIGHT})",
                "fontFamily": FONT_FAMILY,
                "color": TEXT_SECONDARY,
            },
        ),
    ], style={"backgroundColor": BG_MAIN, "minHeight": "100vh"})
