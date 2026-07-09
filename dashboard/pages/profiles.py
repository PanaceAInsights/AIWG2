"""ACD Dashboard — Profiles page (searchable card grid).

Design mirrors the RMSANZ profiles page:
  - Search + filter toolbar
  - 3-column card grid: name, location, metrics, topic tags, external link icon
  - Clicking the external-link icon navigates to /profiles/{slug}
"""
from __future__ import annotations

import logging
import pandas as pd
from dash import Input, Output, callback, dcc, html, no_update
from dash_iconify import DashIconify

from dashboard import data, theme
from dashboard.theme import (
    ACCENT_PRIMARY, BG_CARD, BG_CARD_HOVER, BORDER_COLOR, COPPER,
    LIGHT_COPPER, TEXT_MUTED, TEXT_SECONDARY, TIER_HIGH, TIER_NOT_FOUND,
    TIER_REVIEW, WARM_CREAM, WHITE, DARK_PLUM, MAUVE_PURPLE,
    CARD_STYLE, FONT_FAMILY, BG_MAIN,
)

logger = logging.getLogger("acd.profiles")

PAGE_TITLE = "Profiles"
PAGE_HREF  = "/profiles"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conf_color(conf: str) -> str:
    return {
        "HIGH": TIER_HIGH,
        "REVIEW": TIER_REVIEW,
        "NOT_FOUND": TIER_NOT_FOUND,
    }.get(str(conf).upper(), TIER_NOT_FOUND)


def _fmt_metric(value, decimals: int = 0) -> str:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "—"
        if decimals == 0:
            return f"{int(value):,}"
        return f"{float(value):.{decimals}f}"
    except Exception:
        return "—"


def _metric_block(value_str: str, label: str) -> html.Div:
    return html.Div([
        html.Div(
            value_str,
            style={
                "fontSize": "28px",
                "fontWeight": "700",
                "color": COPPER,
                "lineHeight": "1",
                "fontFamily": FONT_FAMILY,
            },
        ),
        html.Div(
            label,
            style={
                "fontSize": "10px",
                "color": TEXT_MUTED,
                "marginTop": "3px",
                "textTransform": "uppercase",
                "letterSpacing": "0.6px",
            },
        ),
    ], style={"textAlign": "center", "flex": "1", "minWidth": "0"})


def _topic_tag(text: str) -> html.Span:
    return html.Span(
        text,
        style={
            "display": "inline-block",
            "padding": "3px 10px",
            "borderRadius": "12px",
            "fontSize": "11px",
            "fontWeight": "400",
            "color": COPPER,
            "backgroundColor": "rgba(194,125,78,0.12)",
            "border": f"1px solid rgba(194,125,78,0.25)",
            "marginRight": "5px",
            "marginBottom": "5px",
        },
    )


def _scope_btn_style(active: bool) -> dict:
    return {
        "padding": "7px 16px",
        "borderRadius": "8px",
        "border": f"1px solid {COPPER if active else BORDER_COLOR}",
        "backgroundColor": "rgba(194,125,78,0.15)" if active else "transparent",
        "color": COPPER if active else TEXT_MUTED,
        "fontSize": "12px",
        "fontWeight": "600" if active else "400",
        "cursor": "pointer",
        "fontFamily": FONT_FAMILY,
        "transition": "all 0.15s ease",
        "whiteSpace": "nowrap",
    }


def _build_card(row: dict, stats: dict) -> html.Div:
    """Build a single member card."""
    name = str(row.get("acd_name", ""))
    slug = data.make_slug(name)
    display_name = str(row.get("openalex_display_name") or "")
    state_val = str(row.get("state") or "")
    country = str(row.get("institution_country") or "")
    conf = str(row.get("confidence", "NOT_FOUND"))
    ahpra = row.get("ahpra_proven", False)
    source = str(row.get("source") or "")

    # Metrics
    h_disp    = _fmt_metric(stats.get("h_index"), 0)
    pubs_disp = _fmt_metric(stats.get("pub_count"), 0)
    cit_disp  = _fmt_metric(stats.get("citation_count"), 0)
    fwci_disp = _fmt_metric(stats.get("fwci_mean"), 2)

    # Location
    loc_parts = [p for p in [state_val, "Australia" if country == "AU" else country] if p]
    loc_str = ", ".join(loc_parts) if loc_parts else "Unknown"

    # Membership label
    mem_label = "ACD Member" if source in ("Both", "OpenAlex") else ("AHPRA Only" if source == "AHPRA" else "Member")
    mem_color = COPPER if source in ("Both", "OpenAlex") else "#888"

    # Subtopics
    subtopics = data.member_subtopics(name, top_n=4)

    # Confidence badge
    conf_col = _conf_color(conf)
    conf_bg = f"{conf_col}1A"

    # Published-as alias
    alias_shown = display_name and display_name.lower() not in name.lower()

    card = html.Div([
        # Top row: name + external link
        html.Div([
            html.Div([
                html.Div(
                    name,
                    style={
                        "fontWeight": "700",
                        "fontSize": "15px",
                        "color": WHITE,
                        "lineHeight": "1.35",
                        "marginBottom": "2px",
                    },
                ),
                html.Div(
                    f"Published as: {display_name}",
                    style={
                        "fontSize": "11px",
                        "color": TEXT_MUTED,
                        "fontStyle": "italic",
                        "marginBottom": "2px",
                    },
                ) if alias_shown else None,
                html.Div([
                    html.Span(f"{loc_str} · ", style={"color": TEXT_MUTED, "fontSize": "12px"}),
                    html.Span(mem_label, style={"color": mem_color, "fontSize": "12px", "fontWeight": "500"}),
                ], style={"marginTop": "2px"}),
            ], style={"flex": "1", "minWidth": "0"}),

            # External link icon
            dcc.Link(
                DashIconify(icon="tabler:external-link", width=17, color=TEXT_MUTED),
                href=f"/profiles/{slug}",
                style={"flexShrink": "0", "marginLeft": "8px", "marginTop": "2px"},
                title=f"Open {name}'s full profile",
            ),
        ], style={"display": "flex", "alignItems": "flex-start", "marginBottom": "10px"}),

        # Confidence + AHPRA badges
        html.Div([
            html.Span(
                conf,
                style={
                    "display": "inline-block",
                    "padding": "2px 8px",
                    "borderRadius": "10px",
                    "fontSize": "10px",
                    "fontWeight": "600",
                    "color": conf_col,
                    "backgroundColor": conf_bg,
                    "border": f"1px solid {conf_col}44",
                    "marginRight": "4px",
                },
            ),
            html.Span(
                "✓ AHPRA",
                style={
                    "display": "inline-block",
                    "padding": "2px 8px",
                    "borderRadius": "10px",
                    "fontSize": "10px",
                    "fontWeight": "600",
                    "color": TIER_HIGH,
                    "backgroundColor": f"{TIER_HIGH}1A",
                    "border": f"1px solid {TIER_HIGH}44",
                },
            ) if ahpra else None,
        ], style={"marginBottom": "12px", "display": "flex", "flexWrap": "wrap", "gap": "4px"}),

        # Metrics row
        html.Div([
            _metric_block(h_disp, "H-index"),
            html.Div(style={"width": "1px", "backgroundColor": BORDER_COLOR, "alignSelf": "stretch", "margin": "0 2px"}),
            _metric_block(pubs_disp, "Pubs"),
            html.Div(style={"width": "1px", "backgroundColor": BORDER_COLOR, "alignSelf": "stretch", "margin": "0 2px"}),
            _metric_block(cit_disp, "Citations"),
            html.Div(style={"width": "1px", "backgroundColor": BORDER_COLOR, "alignSelf": "stretch", "margin": "0 2px"}),
            _metric_block(fwci_disp, "FWCI"),
        ], style={
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "space-around",
            "padding": "10px 4px",
            "borderTop": f"1px solid {BORDER_COLOR}",
            "borderBottom": f"1px solid {BORDER_COLOR}",
            "marginBottom": "12px",
        }),

        # Topic tags
        html.Div(
            [_topic_tag(st) for st in subtopics],
            style={"minHeight": "28px", "lineHeight": "1.6"},
        ),
    ], style={
        "backgroundColor": BG_CARD,
        "border": f"1px solid {BORDER_COLOR}",
        "borderRadius": "12px",
        "padding": "18px",
        "boxShadow": "0 2px 12px rgba(0,0,0,0.3)",
        "transition": "transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease",
        "cursor": "default",
        "position": "relative",
    })

    return card


def _build_grid(scope: str = "all", search: str = "") -> html.Div:
    """Build the full card grid."""
    authors = data.load_authors()
    stats_df = data.load_stats()

    if authors.empty:
        return html.Div("No member data available.", style={"color": TEXT_MUTED})

    # Scope filter
    if scope == "resolved":
        authors = authors[authors["confidence"] == "HIGH"]
    elif scope == "ahpra":
        authors = authors[authors["ahpra_proven"] == True]

    # Search filter
    if search and search.strip():
        q = search.strip().lower()
        str_cols = ["acd_name", "state", "last_known_institution", "speciality_ahpra"]
        mask = pd.Series(False, index=authors.index)
        for col in str_cols:
            if col in authors.columns:
                mask |= authors[col].fillna("").str.lower().str.contains(q, na=False)
        authors = authors[mask]

    # Only show members with publications
    if not stats_df.empty and "acd_name" in stats_df.columns:
        has_pubs = set(stats_df[stats_df["pub_count"] > 0]["acd_name"].tolist())
        no_pubs_count = len(authors[~authors["acd_name"].isin(has_pubs)])
        authors = authors[authors["acd_name"].isin(has_pubs)]
    else:
        no_pubs_count = 0

    # Sort by citation_count descending
    if not stats_df.empty and "acd_name" in stats_df.columns:
        merged = authors.merge(
            stats_df[["acd_name", "citation_count"]],
            on="acd_name", how="left"
        )
        merged = merged.sort_values("citation_count", ascending=False, na_position="last")
        authors = merged

    if authors.empty:
        return html.Div(
            "No members match the current filter.",
            style={"color": TEXT_MUTED, "padding": "40px", "textAlign": "center"},
        )

    # Build stats lookup
    stats_lookup: dict[str, dict] = {}
    if not stats_df.empty and "acd_name" in stats_df.columns:
        for _, sr in stats_df.iterrows():
            stats_lookup[str(sr["acd_name"])] = sr.to_dict()

    # Build cards
    cards = []
    for _, row in authors.iterrows():
        name = str(row.get("acd_name", ""))
        s = stats_lookup.get(name, {})
        cards.append(_build_card(row.to_dict(), s))

    return html.Div([
        html.Div(
            f"Showing {len(cards)} members with research profiles"
            + (f" · {no_pubs_count} additional members have no publications in OpenAlex" if no_pubs_count > 0 else ""),
            style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "20px"},
        ),
        html.Div(
            cards,
            style={
                "display": "grid",
                "gridTemplateColumns": "repeat(auto-fill, minmax(340px, 1fr))",
                "gap": "16px",
            },
        ),
    ])


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

def layout() -> html.Div:
    return html.Div([
        # Toolbar
        html.Div([
            # Search input
            html.Div([
                html.I(
                    className="bi bi-search",
                    style={
                        "position": "absolute",
                        "left": "12px",
                        "top": "50%",
                        "transform": "translateY(-50%)",
                        "color": TEXT_MUTED,
                        "fontSize": "14px",
                        "pointerEvents": "none",
                    },
                ),
                dcc.Input(
                    id="profiles-search",
                    type="text",
                    placeholder="Search by name, institution, state, specialty…",
                    debounce=True,
                    style={
                        "width": "100%",
                        "padding": "9px 12px 9px 38px",
                        "backgroundColor": BG_CARD,
                        "border": f"1px solid {BORDER_COLOR}",
                        "borderRadius": "8px",
                        "color": WHITE,
                        "fontSize": "13px",
                        "outline": "none",
                        "fontFamily": FONT_FAMILY,
                        "boxSizing": "border-box",
                    },
                ),
            ], style={"position": "relative", "flex": "1", "maxWidth": "500px"}),

            # Scope buttons
            html.Div([
                html.Button(
                    "All",
                    id={"type": "profiles-scope-btn", "value": "all"},
                    n_clicks=0,
                    style=_scope_btn_style(True),
                ),
                html.Button(
                    "Resolved (HIGH)",
                    id={"type": "profiles-scope-btn", "value": "resolved"},
                    n_clicks=0,
                    style=_scope_btn_style(False),
                ),
                html.Button(
                    "AHPRA-verified",
                    id={"type": "profiles-scope-btn", "value": "ahpra"},
                    n_clicks=0,
                    style=_scope_btn_style(False),
                ),
            ], style={"display": "flex", "gap": "6px", "flexWrap": "wrap"}),
        ], style={
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "space-between",
            "marginBottom": "24px",
            "flexWrap": "wrap",
            "gap": "12px",
        }),

        # Scope store
        dcc.Store(id="profiles-scope-store", data="all"),

        # Card grid container
        html.Div(id="profiles-grid-container", children=_build_grid()),
    ])


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("profiles-scope-store", "data"),
    Input({"type": "profiles-scope-btn", "value": "all"}, "n_clicks"),
    Input({"type": "profiles-scope-btn", "value": "resolved"}, "n_clicks"),
    Input({"type": "profiles-scope-btn", "value": "ahpra"}, "n_clicks"),
    prevent_initial_call=True,
)
def update_scope(n_all, n_resolved, n_ahpra):
    from dash import ctx
    if not ctx.triggered:
        return no_update
    triggered_id = ctx.triggered_id
    if isinstance(triggered_id, dict):
        return triggered_id.get("value", "all")
    return "all"


@callback(
    Output("profiles-grid-container", "children"),
    Input("profiles-scope-store", "data"),
    Input("profiles-search", "value"),
)
def update_grid(scope, search):
    return _build_grid(scope or "all", search or "")
