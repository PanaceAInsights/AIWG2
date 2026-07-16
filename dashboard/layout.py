"""App shell — side nav, header, page content slot.

The shell is built once and wraps every page. Routing is page-level
(dcc.Location -> render_page callback in app.py).
Branding: ACD corporate palette (copper #B87333 sidebar).
"""
from __future__ import annotations

import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from .components.filters import build_filter_bar
from .pages.chatbot import build_widget as build_chat_widget

NAV = [
    ("/",              "Overview",         "tabler:layout-dashboard"),
    ("/profiles",      "Profiles",         "tabler:user-circle"),
    ("/publications",  "Publications",     "tabler:books"),
    ("/impact",        "Impact",           "tabler:trending-up"),
    ("/collaboration", "Collaboration",    "tabler:affiliate"),
    ("/funding",       "Funding",          "tabler:cash-banknote"),
    ("/benchmarking",  "Benchmarking",     "tabler:chart-bar"),
    ("/trials",        "Clinical Trials",  "tabler:stethoscope"),
    ("/heatmap",       "Research Heatmap", "tabler:map-2"),
    ("/experts",       "Expert Finder",    "tabler:user-search"),
    ("/methodology",   "Methodology",      "tabler:file-text"),
    ("/explorer",      "Data Explorer",    "tabler:database-search"),
    ("/compare",       "Compare & Rank",   "tabler:arrows-sort"),
]


def _nav_link(path: str, label: str, icon: str) -> html.A:
    return html.A(
        [DashIconify(icon=icon, width=18), html.Span(label)],
        href=path,
        className="acd-nav-link",
        id={"type": "nav-link", "href": path},
    )


def build_layout() -> dmc.MantineProvider:
    from . import theme

    sidebar = html.Aside(
        [
            html.Div(
                [html.Div("ACD Research", className="acd-shell-title")],
                style={"display": "flex", "alignItems": "center", "gap": "0.6rem",
                       "padding": "0.3rem 0.3rem 1.2rem"},
            ),
            html.Div(
                [_nav_link(p, l, i) for p, l, i in NAV],
                style={"display": "flex", "flexDirection": "column", "gap": "0.15rem"},
            ),
            html.Div(style={"flex": 1}),
            dmc.Divider(my="md", color="rgba(255,255,255,0.15)"),
            dmc.Stack(
                [
                    dmc.Text(
                        "Australasian College of Dermatologists",
                        size="xs",
                        style={"color": "rgba(255,255,255,0.6)"},
                    ),
                ],
                gap=2,
            ),
        ],
        style={
            "width": "240px", "minWidth": "240px",
            "padding": "1.5rem 1rem",
            "background": theme.PRIMARY,
            "display": "flex", "flexDirection": "column",
            "height": "100vh", "position": "sticky", "top": 0,
            "boxShadow": "2px 0 8px rgba(0,0,0,0.12)",
        },
    )

    header = html.Header(
        dmc.Group(
            [
                dmc.Group(
                    [
                        dmc.Badge("Beta", color="acd-copper", variant="light", size="sm"),
                        dmc.Text("Research Intelligence Dashboard",
                                 size="sm", c="dimmed"),
                    ],
                    gap="xs",
                ),
                dmc.Group(
                    [
                        dmc.Button(
                            "Download data",
                            leftSection=DashIconify(icon="tabler:download", width=16),
                            variant="light",
                            color="acd-copper",
                            size="xs",
                            id="download-data-btn",
                        ),
                    ]
                ),
            ],
            justify="space-between",
            align="center",
            style={"padding": "1rem 1.5rem", "background": "#fff",
                   "borderBottom": f"1px solid {theme.GRAY_200}"},
        ),
    )

    filter_bar = build_filter_bar()

    footer = html.Footer(
        dmc.Group(
            [
                dmc.Text("", size="xs"),
                dmc.Group(
                    [
                        dmc.Text("Developed by", size="xs", c="dimmed"),
                        html.A(
                            dmc.Text("Dr Yagiz Aksoy MD PhD", size="xs", fw=500,
                                     style={"color": theme.PRIMARY}),
                            href="https://www.linkedin.com/in/yagizalpaksoy/",
                            target="_blank",
                            style={"textDecoration": "none"},
                        ),
                        dmc.Text("/", size="xs", c="dimmed"),
                        html.A(
                            dmc.Text("PanaceAI", size="xs", fw=600,
                                     style={"color": theme.PRIMARY}),
                            href="https://www.panaceainsights.com.au",
                            target="_blank",
                            style={"textDecoration": "none"},
                        ),
                    ],
                    gap=6,
                ),
            ],
            justify="flex-end",
            style={"padding": "0.75rem 1.5rem",
                   "borderTop": f"1px solid {theme.GRAY_200}",
                   "background": "#fff"},
        ),
    )

    main = html.Main(
        [
            header,
            filter_bar,
            html.Div(id="page-content", className="acd-container"),
            footer,
        ],
        style={"flex": 1, "minWidth": 0, "background": theme.GRAY_100},
    )

    chat_widget = build_chat_widget()

    return dmc.MantineProvider(
        theme=theme.MANTINE_THEME,
        children=html.Div(
            [
                dcc.Location(id="url", refresh=False),
                dcc.Download(id="download-data"),
                html.Div(
                    [sidebar, main],
                    style={"display": "flex", "alignItems": "flex-start",
                           "minHeight": "100vh"},
                ),
                chat_widget,
            ]
        ),
    )


# Legacy alias
build_shell = build_layout
