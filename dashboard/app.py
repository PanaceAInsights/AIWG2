"""ACD Research Intelligence Platform — Dash application entry point."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, html

from dashboard.layout import build_shell
from dashboard.pages import PAGE_MAP, REGISTRY
from dashboard.pages.member_profile import build_member_profile_page
from dashboard.theme import BG_MAIN, FONT_FAMILY, WARM_CREAM

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("acd.app")

# ---------------------------------------------------------------------------
# App initialisation
# ---------------------------------------------------------------------------
app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
    ],
    suppress_callback_exceptions=True,
    title="ACD Research Intelligence",
    update_title=None,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        {"name": "description", "content": "ACD Research Intelligence Platform — Australasian College of Dermatologists"},
    ],
)

server = app.server  # Expose Flask server for gunicorn / Render

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
app.layout = build_shell()

# ---------------------------------------------------------------------------
# Page routing callback
# ---------------------------------------------------------------------------
@app.callback(
    Output("page-content", "children"),
    Output("acd-page-title", "children"),
    Input("url", "pathname"),
)
def route(pathname: str):
    pathname = pathname or "/"
    # Normalise trailing slash
    if pathname != "/" and pathname.endswith("/"):
        pathname = pathname.rstrip("/")

    # Handle dynamic /profiles/{slug} routes
    if pathname.startswith("/profiles/"):
        slug = pathname[len("/profiles/"):].strip("/")
        if slug:
            return build_member_profile_page(slug), "Member Profile"

    page = PAGE_MAP.get(pathname)
    if page is None:
        # 404
        return (
            html.Div([
                html.H2("404 — Page not found", style={"color": WARM_CREAM}),
                html.P(f"No page registered for path: {pathname}",
                       style={"color": "#A89DB8"}),
            ]),
            "Not Found",
        )

    return page.layout(), page.PAGE_TITLE


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    debug = os.environ.get("DASH_DEBUG", "false").lower() == "true"
    logger.info("Starting ACD Research Intelligence Platform on port %d (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug)
