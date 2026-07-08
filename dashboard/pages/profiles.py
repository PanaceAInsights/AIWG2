"""ACD Dashboard — Profiles page (member directory + per-member detail card).

Design mirrors the RMSANZ profiles page:
  - Left 2/3: AG Grid roster with floating filters, sorting, pagination
  - Right 1/3: Detail card that appears when a row is clicked
"""
from __future__ import annotations

import logging
import os

import dash
import dash_ag_grid as dag
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html, no_update

from dashboard import data, theme
from dashboard.theme import (
    BG_CARD, BORDER_COLOR, COPPER, LIGHT_COPPER, TEXT_MUTED,
    WARM_CREAM, WHITE, DARK_PLUM, TIER_HIGH, TIER_REVIEW,
    TIER_NOT_FOUND, CARD_STYLE, MAUVE_PURPLE,
)

logger = logging.getLogger("acd.profiles")

PAGE_TITLE = "Profiles"
PAGE_HREF  = "/profiles"

# ---------------------------------------------------------------------------
# Helper: build the AG Grid roster
# ---------------------------------------------------------------------------

def _roster_grid() -> dag.AgGrid:
    authors = data.load_authors().copy()
    stats   = data.load_stats()

    # Merge per-author stats into the roster
    _want = ["acd_name", "pub_count", "citation_count", "h_index",
             "fwci_mean", "oa_rate", "grants_count", "trial_count",
             "rehab_relevance_pct"]
    if not authors.empty and not stats.empty:
        available = [c for c in _want if c in stats.columns]
        authors = authors.merge(stats[available], on="acd_name", how="left")

    # Ensure numeric columns exist
    for c in _want[1:]:
        if c not in authors.columns:
            authors[c] = None

    # AHPRA verified flag as a readable label
    if "ahpra_proven" in authors.columns:
        authors["ahpra_label"] = authors["ahpra_proven"].apply(
            lambda v: "✓ AHPRA" if v in (True, 1, "1", "True", "true") else ""
        )
    else:
        authors["ahpra_label"] = ""

    col_defs = [
        {
            "field": "acd_name",
            "headerName": "Member",
            "pinned": "left",
            "minWidth": 210,
            "filter": "agTextColumnFilter",
            "cellStyle": {"fontWeight": "500", "color": WARM_CREAM},
        },
        {
            "field": "state",
            "headerName": "State",
            "maxWidth": 90,
            "filter": "agTextColumnFilter",
        },
        {
            "field": "ahpra_label",
            "headerName": "AHPRA",
            "maxWidth": 100,
            "filter": "agTextColumnFilter",
            "cellStyle": {
                "styleConditions": [
                    {"condition": "params.value == '✓ AHPRA'",
                     "style": {"color": TIER_HIGH, "fontWeight": "600"}},
                ]
            },
        },
        {
            "field": "last_known_institution",
            "headerName": "Institution",
            "minWidth": 220,
            "filter": "agTextColumnFilter",
        },
        {
            "field": "institution_country",
            "headerName": "Country",
            "maxWidth": 90,
        },
        {
            "field": "pub_count",
            "headerName": "Pubs",
            "maxWidth": 85,
            "type": "numericColumn",
            "filter": "agNumberColumnFilter",
        },
        {
            "field": "h_index",
            "headerName": "h-index",
            "maxWidth": 95,
            "type": "numericColumn",
            "filter": "agNumberColumnFilter",
            "headerTooltip": "Number of publications (N) each cited at least N times",
        },
        {
            "field": "citation_count",
            "headerName": "Citations",
            "maxWidth": 105,
            "type": "numericColumn",
            "filter": "agNumberColumnFilter",
            "valueFormatter": {"function": "params.value ? d3.format(',')(params.value) : ''"},
        },
        {
            "field": "fwci_mean",
            "headerName": "FWCI",
            "maxWidth": 90,
            "type": "numericColumn",
            "filter": "agNumberColumnFilter",
            "headerTooltip": "Field-Weighted Citation Impact: >1.0 = above world average",
            "valueFormatter": {"function": "params.value ? params.value.toFixed(2) : ''"},
        },
        {
            "field": "grants_count",
            "headerName": "Grants",
            "maxWidth": 85,
            "type": "numericColumn",
            "filter": "agNumberColumnFilter",
        },
        {
            "field": "trial_count",
            "headerName": "Trials",
            "maxWidth": 80,
            "type": "numericColumn",
            "filter": "agNumberColumnFilter",
        },
        {
            "field": "confidence",
            "headerName": "Match",
            "maxWidth": 105,
            "filter": "agTextColumnFilter",
            "cellStyle": {
                "styleConditions": [
                    {"condition": "params.value == 'HIGH'",
                     "style": {"color": TIER_HIGH, "fontWeight": "600"}},
                    {"condition": "params.value == 'REVIEW'",
                     "style": {"color": TIER_REVIEW, "fontWeight": "600"}},
                    {"condition": "params.value == 'NOT_FOUND'",
                     "style": {"color": TIER_NOT_FOUND}},
                ]
            },
        },
    ]

    return dag.AgGrid(
        id="roster-grid",
        rowData=authors.fillna("").to_dict("records"),
        columnDefs=col_defs,
        defaultColDef={
            "resizable": True,
            "sortable": True,
            "filter": True,
            "floatingFilter": True,

        },
        dashGridOptions={
            "rowSelection": {"mode": "singleRow", "checkboxes": False,
                             "enableClickSelection": True},
            "animateRows": True,
            "pagination": True,
            "paginationPageSize": 25,
            "paginationPageSizeSelector": [25, 50, 100],
            "rowHeight": 40,
            "suppressCellFocus": False,
            "headerHeight": 40,
            "floatingFiltersHeight": 36,
        },
        className="ag-theme-alpine-dark",
        style={"height": "580px", "width": "100%"},
    )


# ---------------------------------------------------------------------------
# Helper: build the detail card for a selected member
# ---------------------------------------------------------------------------

def build_profile_card(name: str) -> html.Div:
    """Build the right-panel detail card for a clicked member."""
    authors = data.load_authors()
    if authors.empty:
        return _empty_state_card()

    row_df = authors[authors["acd_name"] == name]
    if row_df.empty:
        return _empty_state_card()
    row = row_df.iloc[0].to_dict()

    # Merge stats
    stats = data.stats_for_member(name)
    row.update({k: v for k, v in stats.items() if k not in row or pd.isna(row.get(k))})

    # Extract values
    inst        = row.get("last_known_institution") or "—"
    country     = row.get("institution_country") or ""
    state       = row.get("state") or "—"
    profile_url = row.get("profile_url") or ""
    openalex_id = row.get("openalex_id") or ""
    if not profile_url and openalex_id:
        profile_url = f"https://openalex.org/{openalex_id}"
    confidence  = str(row.get("confidence") or "NOT_FOUND").upper()
    ahpra       = row.get("ahpra_proven") in (True, 1, "1", "True", "true")
    source      = row.get("source") or ""

    pubs        = _safe_val(row.get("pub_count"))
    h           = _safe_val(row.get("h_index"))
    cit         = _safe_val(row.get("citation_count"))
    fwci        = row.get("fwci_mean")
    oa_rate     = row.get("oa_rate")
    derm_pct    = row.get("rehab_relevance_pct")   # derm-relevance %
    intl        = row.get("intl_collab_rate")
    grants      = _safe_val(row.get("grants_count"))
    trials      = _safe_val(row.get("trial_count"))

    # Confidence badge colour
    conf_color = {"HIGH": TIER_HIGH, "REVIEW": TIER_REVIEW,
                  "NOT_FOUND": TIER_NOT_FOUND}.get(confidence, TIER_NOT_FOUND)

    def _badge(label: str, color: str, bg: str = "rgba(0,0,0,0.3)") -> html.Span:
        return html.Span(label, style={
            "backgroundColor": bg,
            "color": color,
            "border": f"1px solid {color}",
            "borderRadius": "4px",
            "padding": "2px 8px",
            "fontSize": "11px",
            "fontWeight": "600",
            "marginRight": "4px",
        })

    def _kv(label: str, value) -> html.Div:
        display = "—" if (value is None or (isinstance(value, float) and pd.isna(value))) else str(value)
        return html.Div([
            html.Div(label, style={"fontSize": "10px", "color": TEXT_MUTED,
                                   "textTransform": "uppercase", "letterSpacing": "0.5px",
                                   "marginBottom": "2px"}),
            html.Div(display, style={"fontSize": "18px", "fontWeight": "700",
                                     "color": COPPER}),
        ], style={"padding": "8px 10px", "backgroundColor": "rgba(0,0,0,0.2)",
                  "borderRadius": "6px"})

    # Publication timeline sparkline
    pubs_df = data.publications_for_member(name)
    if not pubs_df.empty and "Year" in pubs_df.columns:
        years = pubs_df["Year"].dropna().astype(int)
        year_counts = years.value_counts().sort_index()
        spark = go.Figure(go.Bar(
            x=year_counts.index.tolist(),
            y=year_counts.values.tolist(),
            marker_color=COPPER,
            hovertemplate="%{x}: %{y} publications<extra></extra>",
        ))
        spark.update_layout(
            height=160,
            margin=dict(l=32, r=8, t=8, b=28),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=TEXT_MUTED, size=10),
            xaxis=dict(gridcolor=BORDER_COLOR, tickfont=dict(color=TEXT_MUTED, size=9)),
            yaxis=dict(gridcolor=BORDER_COLOR, tickfont=dict(color=TEXT_MUTED, size=9)),
            showlegend=False,
        )
    else:
        spark = go.Figure()
        spark.update_layout(
            height=160, margin=dict(l=32, r=8, t=8, b=28),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            annotations=[dict(text="No publication data", showarrow=False,
                              font=dict(color=TEXT_MUTED, size=11))],
        )

    # Top keywords
    keywords = _member_keywords(name)
    keyword_chips = [
        html.Span(kw, style={
            "backgroundColor": "rgba(194,125,78,0.12)",
            "color": LIGHT_COPPER,
            "border": f"1px solid {BORDER_COLOR}",
            "borderRadius": "12px",
            "padding": "2px 8px",
            "fontSize": "10px",
            "marginRight": "4px",
            "marginBottom": "4px",
            "display": "inline-block",
        }) for kw in keywords[:8]
    ] if keywords else []

    # Top funders
    funding_df = data.funding_for_member(name)
    funder_text = ""
    if not funding_df.empty and "funder_name" in funding_df.columns:
        top_funders = funding_df["funder_name"].dropna().value_counts().head(3)
        if not top_funders.empty:
            funder_text = ", ".join(top_funders.index.tolist())

    # ORCID
    orcid = _member_orcid(name)

    # Derm relevance % display
    derm_display = f"{derm_pct:.0f}%" if derm_pct and not pd.isna(derm_pct) else "—"
    oa_display   = f"{oa_rate*100:.0f}%" if oa_rate and not pd.isna(oa_rate) and oa_rate <= 1 else (
                   f"{oa_rate:.0f}%" if oa_rate and not pd.isna(oa_rate) else "—")
    intl_display = f"{intl*100:.0f}%" if intl and not pd.isna(intl) and intl <= 1 else (
                   f"{intl:.0f}%" if intl and not pd.isna(intl) else "—")
    fwci_display = f"{fwci:.2f}" if fwci and not pd.isna(fwci) else "—"

    # Trials list
    trials_df = data.trials_for_member(name)
    trials_items = []
    if not trials_df.empty:
        for _, t in trials_df.head(4).iterrows():
            title = str(t.get("title", ""))[:80] + ("…" if len(str(t.get("title", ""))) > 80 else "")
            status = str(t.get("status", ""))
            url = t.get("url", "")
            item = html.Div([
                html.A(title, href=url, target="_blank",
                       style={"color": LIGHT_COPPER, "fontSize": "11px",
                              "textDecoration": "none"}) if url else
                html.Span(title, style={"color": WARM_CREAM, "fontSize": "11px"}),
                html.Span(f" ({status})", style={"color": TEXT_MUTED, "fontSize": "10px"}),
            ], style={"marginBottom": "4px"})
            trials_items.append(item)
    else:
        trials_items = [html.Div("No clinical trials found",
                                  style={"color": TEXT_MUTED, "fontSize": "11px"})]

    # Funding list
    funding_items = []
    if not funding_df.empty:
        for _, f in funding_df.head(4).iterrows():
            funder = str(f.get("funder_name", ""))
            award  = str(f.get("award_id", "")) or str(f.get("award_name", ""))
            funding_items.append(html.Div([
                html.Span(funder, style={"color": WARM_CREAM, "fontSize": "11px",
                                         "fontWeight": "500"}),
                html.Span(f" — {award}" if award and award != "nan" else "",
                          style={"color": TEXT_MUTED, "fontSize": "10px"}),
            ], style={"marginBottom": "4px"}))
    else:
        funding_items = [html.Div("No funding records found",
                                   style={"color": TEXT_MUTED, "fontSize": "11px"})]

    card = html.Div([
        # ── Header ──────────────────────────────────────────────────────────
        html.Div([
            html.Div([
                html.Div(name, style={"fontSize": "15px", "fontWeight": "700",
                                      "color": WHITE, "marginBottom": "6px"}),
                html.Div([
                    _badge("AHPRA-verified", TIER_HIGH) if ahpra else None,
                    _badge(confidence, conf_color),
                    _badge(source, "#888") if source else None,
                ], style={"display": "flex", "flexWrap": "wrap", "gap": "4px",
                          "marginBottom": "6px"}),
                html.Div(inst, style={"fontSize": "12px", "color": TEXT_MUTED,
                                      "marginBottom": "6px"}),
                html.Div([
                    html.Span(state, style={"backgroundColor": "rgba(194,125,78,0.15)",
                                            "color": COPPER, "borderRadius": "4px",
                                            "padding": "2px 8px", "fontSize": "11px",
                                            "marginRight": "4px"}),
                    html.Span(country, style={"backgroundColor": "rgba(100,100,100,0.2)",
                                              "color": TEXT_MUTED, "borderRadius": "4px",
                                              "padding": "2px 8px", "fontSize": "11px",
                                              "marginRight": "4px"}) if country else None,
                ], style={"display": "flex", "flexWrap": "wrap", "gap": "2px"}),
            ]),
        ], style={"padding": "16px 16px 12px", "borderBottom": f"1px solid {BORDER_COLOR}"}),

        # ── Metrics grid ────────────────────────────────────────────────────
        html.Div([
            html.Div([
                _kv("Publications", int(pubs) if pubs is not None else None),
                _kv("h-index", int(h) if h is not None else None),
                _kv("Citations", f"{int(cit):,}" if cit is not None else None),
                _kv("FWCI", fwci_display),
                _kv("Grants", int(grants) if grants is not None else None),
                _kv("Trials", int(trials) if trials is not None else None),
            ], style={"display": "grid", "gridTemplateColumns": "repeat(3, 1fr)",
                      "gap": "6px"}),
        ], style={"padding": "12px 16px", "borderBottom": f"1px solid {BORDER_COLOR}"}),

        # ── Rate badges ─────────────────────────────────────────────────────
        html.Div([
            html.Span(f"OA: {oa_display}", style={"color": "#4CAF50", "fontSize": "11px",
                                                    "marginRight": "12px"}),
            html.Span(f"Intl collab: {intl_display}", style={"color": MAUVE_PURPLE,
                                                               "fontSize": "11px",
                                                               "marginRight": "12px"}),
            html.Span(f"Derm-relevant: {derm_display}", style={"color": COPPER,
                                                                 "fontSize": "11px"}),
        ], style={"padding": "8px 16px", "borderBottom": f"1px solid {BORDER_COLOR}"}),

        # ── Publication timeline ─────────────────────────────────────────────
        html.Div([
            html.Div("Publication Timeline", style={"fontSize": "11px", "color": TEXT_MUTED,
                                                     "textTransform": "uppercase",
                                                     "letterSpacing": "0.5px",
                                                     "marginBottom": "4px"}),
            dcc.Graph(figure=spark, config={"displayModeBar": False},
                      style={"height": "160px"}),
        ], style={"padding": "10px 16px 4px", "borderBottom": f"1px solid {BORDER_COLOR}"}),

        # ── Keywords ────────────────────────────────────────────────────────
        html.Div([
            html.Div("Top Keywords", style={"fontSize": "11px", "color": TEXT_MUTED,
                                             "textTransform": "uppercase",
                                             "letterSpacing": "0.5px",
                                             "marginBottom": "6px"}),
            html.Div(keyword_chips if keyword_chips else
                     html.Span("No keyword data", style={"color": TEXT_MUTED,
                                                          "fontSize": "11px"}),
                     style={"display": "flex", "flexWrap": "wrap"}),
        ], style={"padding": "10px 16px", "borderBottom": f"1px solid {BORDER_COLOR}"}),

        # ── Funders ─────────────────────────────────────────────────────────
        html.Div([
            html.Div(f"Funding ({len(funding_df)} grants)",
                     style={"fontSize": "11px", "color": TEXT_MUTED,
                            "textTransform": "uppercase", "letterSpacing": "0.5px",
                            "marginBottom": "6px"}),
            html.Div(funding_items),
        ], style={"padding": "10px 16px", "borderBottom": f"1px solid {BORDER_COLOR}"}),

        # ── Clinical Trials ──────────────────────────────────────────────────
        html.Div([
            html.Div(f"Clinical Trials ({len(trials_df)})",
                     style={"fontSize": "11px", "color": TEXT_MUTED,
                            "textTransform": "uppercase", "letterSpacing": "0.5px",
                            "marginBottom": "6px"}),
            html.Div(trials_items),
        ], style={"padding": "10px 16px", "borderBottom": f"1px solid {BORDER_COLOR}"}),

        # ── Links ────────────────────────────────────────────────────────────
        html.Div([
            html.A(f"ORCID: {orcid}", href=f"https://orcid.org/{orcid}",
                   target="_blank",
                   style={"color": TEXT_MUTED, "fontSize": "11px",
                          "textDecoration": "none", "display": "block",
                          "marginBottom": "6px"}) if orcid else None,
            html.A("View OpenAlex research profile ›", href=profile_url,
                   target="_blank",
                   style={"color": COPPER, "fontSize": "12px", "fontWeight": "500",
                          "textDecoration": "none"}) if profile_url else None,
        ], style={"padding": "10px 16px", "borderBottom": f"1px solid {BORDER_COLOR}"}),

        # ── Report incorrect match ────────────────────────────────────────────
        html.Div([
            html.Button(
                "⚑ Report Incorrect Match",
                id={"type": "report-btn", "index": name},
                style={
                    "backgroundColor": "transparent",
                    "color": TEXT_MUTED,
                    "border": f"1px solid {BORDER_COLOR}",
                    "borderRadius": "6px",
                    "padding": "5px 12px",
                    "fontSize": "11px",
                    "cursor": "pointer",
                },
            ),
        ], style={"padding": "10px 16px"}),

    ], style={
        **CARD_STYLE,
        "padding": "0",
        "maxHeight": "90vh",
        "overflowY": "auto",
    })

    return card


def _empty_state_card() -> html.Div:
    return html.Div(
        html.Div("Select a member from the grid to view their profile",
                 style={"color": TEXT_MUTED, "textAlign": "center",
                        "padding": "60px 20px", "fontSize": "13px"}),
        style={**CARD_STYLE, "minHeight": "300px",
               "display": "flex", "alignItems": "center",
               "justifyContent": "center"},
    )


# ---------------------------------------------------------------------------
# Helper: keywords and ORCID from publications CSV
# ---------------------------------------------------------------------------

def _member_keywords(name: str) -> list[str]:
    pubs = data.publications_for_member(name)
    if pubs.empty or "Keywords" not in pubs.columns:
        return []
    kw = (pubs["Keywords"].dropna()
          .str.split("|").explode()
          .str.strip().str.lower())
    kw = kw[kw.str.len() > 2]
    if kw.empty:
        return []
    return kw.value_counts().head(10).index.tolist()


def _member_orcid(name: str) -> str | None:
    pubs = data.publications_for_member(name)
    if pubs.empty or "ORCIDs" not in pubs.columns:
        return None
    orcids = (pubs["ORCIDs"].dropna()
              .str.split("|").explode()
              .str.strip())
    orcids = orcids[orcids.str.match(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")]
    if orcids.empty:
        return None
    return orcids.value_counts().index[0]


def _safe_val(v):
    """Return None if NaN/None, else the value."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return v


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def layout():
    return html.Div([
        # ── Toolbar ─────────────────────────────────────────────────────────
        html.Div([
            html.Div([
                dcc.Input(
                    id="roster-search",
                    type="text",
                    placeholder="Search by name, institution, state…",
                    debounce=True,
                    style={
                        "flex": "1",
                        "maxWidth": "420px",
                        "backgroundColor": BG_CARD,
                        "border": f"1px solid {BORDER_COLOR}",
                        "borderRadius": "6px",
                        "color": WARM_CREAM,
                        "padding": "8px 12px",
                        "fontSize": "13px",
                    },
                ),
                html.Div([
                    _scope_btn("All", "all", True),
                    _scope_btn("Resolved (HIGH)", "resolved", False),
                    _scope_btn("AHPRA-verified", "ahpra", False),
                ], id="roster-scope-group",
                   style={"display": "flex", "gap": "6px"}),
                html.Button(
                    "⬇ Export CSV",
                    id="roster-export-btn",
                    style={
                        "backgroundColor": "transparent",
                        "color": COPPER,
                        "border": f"1px solid {COPPER}",
                        "borderRadius": "6px",
                        "padding": "7px 14px",
                        "fontSize": "12px",
                        "cursor": "pointer",
                    },
                ),
                dcc.Download(id="roster-download"),
            ], style={"display": "flex", "alignItems": "center",
                      "gap": "12px", "flexWrap": "wrap"}),
        ], style={**CARD_STYLE, "padding": "12px 16px", "marginBottom": "12px"}),

        # ── Main grid + detail pane ──────────────────────────────────────────
        html.Div([
            # Grid (left, 65%)
            html.Div(
                html.Div(_roster_grid(), style={"padding": "4px"}),
                style={**CARD_STYLE, "flex": "65", "minWidth": "0",
                       "padding": "8px", "marginBottom": "0"},
            ),
            # Detail pane (right, 35%)
            html.Div(
                id="profile-detail",
                children=_empty_state_card(),
                style={"flex": "35", "minWidth": "300px"},
            ),
        ], style={"display": "flex", "gap": "12px", "alignItems": "flex-start"}),

        # ── Report modal ─────────────────────────────────────────────────────
        html.Div(
            id="report-modal-container",
            children=[],
        ),
    ])


def _scope_btn(label: str, value: str, active: bool) -> html.Button:
    return html.Button(
        label,
        id={"type": "scope-btn", "index": value},
        n_clicks=0,
        style={
            "backgroundColor": COPPER if active else "transparent",
            "color": DARK_PLUM if active else TEXT_MUTED,
            "border": f"1px solid {COPPER if active else BORDER_COLOR}",
            "borderRadius": "6px",
            "padding": "6px 12px",
            "fontSize": "12px",
            "cursor": "pointer",
            "fontWeight": "600" if active else "400",
        },
    )


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("profile-detail", "children"),
    Input("roster-grid", "selectedRows"),
    Input("roster-grid", "cellClicked"),
    prevent_initial_call=True,
)
def profile_selected(selected_rows, cell_clicked):
    from dash import ctx
    # Prefer selectedRows (works in most versions); fall back to cellClicked
    triggered = ctx.triggered_id
    name = None
    if triggered == "roster-grid" and selected_rows:
        name = selected_rows[0].get("acd_name")
    elif cell_clicked:
        row = cell_clicked.get("rowData", {})
        name = row.get("acd_name")
    if not name:
        return no_update
    return build_profile_card(name)


@callback(
    Output("roster-grid", "rowData"),
    Input("roster-search", "value"),
    Input({"type": "scope-btn", "index": "all"}, "n_clicks"),
    Input({"type": "scope-btn", "index": "resolved"}, "n_clicks"),
    Input({"type": "scope-btn", "index": "ahpra"}, "n_clicks"),
    prevent_initial_call=False,
)
def apply_roster_filters(search_value, _all, _resolved, _ahpra):
    from dash import ctx
    authors = data.load_authors().copy()
    stats   = data.load_stats()

    _want = ["acd_name", "pub_count", "citation_count", "h_index",
             "fwci_mean", "oa_rate", "grants_count", "trial_count",
             "rehab_relevance_pct"]
    if not authors.empty and not stats.empty:
        available = [c for c in _want if c in stats.columns]
        authors = authors.merge(stats[available], on="acd_name", how="left")
    for c in _want[1:]:
        if c not in authors.columns:
            authors[c] = None

    if "ahpra_proven" in authors.columns:
        authors["ahpra_label"] = authors["ahpra_proven"].apply(
            lambda v: "✓ AHPRA" if v in (True, 1, "1", "True", "true") else ""
        )
    else:
        authors["ahpra_label"] = ""

    # Determine active scope from callback context
    triggered_id = ctx.triggered_id
    scope = "all"
    if isinstance(triggered_id, dict):
        scope = triggered_id.get("index", "all")

    if scope == "resolved":
        authors = authors[authors["confidence"] == "HIGH"]
    elif scope == "ahpra":
        authors = authors[authors["ahpra_proven"].astype(str).isin(("True", "1", "true"))]

    # Free-text search
    q = (search_value or "").strip().lower()
    if q:
        search_cols = ["acd_name", "last_known_institution",
                       "openalex_display_name", "state"]
        mask = pd.Series(False, index=authors.index)
        for col in search_cols:
            if col in authors.columns:
                mask |= authors[col].astype(str).str.lower().str.contains(q, na=False)
        authors = authors[mask]

    return authors.fillna("").to_dict("records")


@callback(
    Output("roster-download", "data"),
    Input("roster-export-btn", "n_clicks"),
    prevent_initial_call=True,
)
def export_roster(n_clicks):
    if not n_clicks:
        return no_update
    df = data.load_authors()
    stats = data.load_stats()
    if not df.empty and not stats.empty:
        _want = ["acd_name", "pub_count", "citation_count", "h_index",
                 "fwci_mean", "oa_rate", "grants_count", "trial_count"]
        available = [c for c in _want if c in stats.columns]
        df = df.merge(stats[available], on="acd_name", how="left")
    return dcc.send_data_frame(df.to_csv, "acd_dermatologists.csv", index=False)


@callback(
    Output("report-modal-container", "children"),
    Input({"type": "report-btn", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def open_report_modal(n_clicks_list):
    from dash import ctx
    import dash
    if not any(n for n in (n_clicks_list or []) if n):
        return no_update
    triggered = ctx.triggered_id
    if not triggered:
        return no_update
    member_name = triggered.get("index", "Unknown")
    return _report_modal(member_name, is_open=True)


def _report_modal(member_name: str, is_open: bool = True) -> html.Div:
    return html.Div([
        html.Div([
            html.Div([
                html.Div("Report Incorrect Match",
                         style={"fontSize": "15px", "fontWeight": "600",
                                "color": WHITE, "marginBottom": "8px"}),
                html.Div(f"Reporting issue for: {member_name}",
                         style={"fontSize": "12px", "color": TEXT_MUTED,
                                "marginBottom": "12px"}),
                dcc.Textarea(
                    id="report-text",
                    placeholder="Describe the issue (e.g. wrong OpenAlex profile matched, incorrect institution)…",
                    style={"width": "100%", "minHeight": "100px",
                           "backgroundColor": BG_CARD,
                           "border": f"1px solid {BORDER_COLOR}",
                           "color": WARM_CREAM, "borderRadius": "6px",
                           "padding": "8px", "fontSize": "12px"},
                ),
                html.Div(id="report-status", style={"marginTop": "8px",
                                                     "fontSize": "12px"}),
                html.Div([
                    html.Button("Submit Report",
                                id={"type": "report-submit", "index": member_name},
                                style={"backgroundColor": COPPER, "color": DARK_PLUM,
                                       "border": "none", "borderRadius": "6px",
                                       "padding": "8px 16px", "fontSize": "12px",
                                       "cursor": "pointer", "fontWeight": "600",
                                       "marginRight": "8px"}),
                    html.Button("Cancel",
                                id="report-cancel",
                                style={"backgroundColor": "transparent",
                                       "color": TEXT_MUTED,
                                       "border": f"1px solid {BORDER_COLOR}",
                                       "borderRadius": "6px",
                                       "padding": "8px 16px", "fontSize": "12px",
                                       "cursor": "pointer"}),
                ], style={"marginTop": "12px", "display": "flex"}),
            ], style={**CARD_STYLE, "maxWidth": "480px", "margin": "auto",
                      "position": "relative", "zIndex": "1001"}),
        ], style={
            "position": "fixed", "top": "0", "left": "0",
            "width": "100vw", "height": "100vh",
            "backgroundColor": "rgba(0,0,0,0.7)",
            "display": "flex" if is_open else "none",
            "alignItems": "center", "justifyContent": "center",
            "zIndex": "1000",
        }),
    ]) if is_open else html.Div()


@callback(
    Output("report-status", "children"),
    Output("report-modal-container", "children", allow_duplicate=True),
    Input({"type": "report-submit", "index": dash.ALL}, "n_clicks"),
    State("report-text", "value"),
    State({"type": "report-submit", "index": dash.ALL}, "id"),
    prevent_initial_call=True,
)
def submit_report(n_clicks_list, report_text, submit_ids):
    from dash import ctx
    import smtplib
    from email.mime.text import MIMEText

    if not any(n for n in (n_clicks_list or []) if n):
        return no_update, no_update

    triggered = ctx.triggered_id
    if not triggered:
        return no_update, no_update

    member_name = triggered.get("index", "Unknown") if isinstance(triggered, dict) else "Unknown"
    text = (report_text or "").strip()
    if not text:
        return html.Span("Please enter a description before submitting.",
                         style={"color": TIER_REVIEW}), no_update

    # Try to send email via SMTP (Render supports environment variable SMTP config)
    try:
        smtp_host = os.environ.get("SMTP_HOST", "")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_pass = os.environ.get("SMTP_PASS", "")
        to_addr   = "yagiz.aksoy@panaceai.com.au"

        if smtp_host and smtp_user:
            msg = MIMEText(
                f"Member: {member_name}\n\nReport:\n{text}\n\n"
                f"Submitted via ACD Research Intelligence Dashboard",
                "plain"
            )
            msg["Subject"] = f"[ACD Dashboard] Incorrect Match Report — {member_name}"
            msg["From"]    = smtp_user
            msg["To"]      = to_addr
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, [to_addr], msg.as_string())
            logger.info("Report email sent for member: %s", member_name)
        else:
            # Log to server logs if no SMTP configured
            logger.warning("REPORT (no SMTP): member=%s | text=%s", member_name, text)

    except Exception as exc:
        logger.error("Failed to send report email: %s", exc)

    return (
        html.Span("✓ Report submitted. Thank you.",
                  style={"color": TIER_HIGH}),
        html.Div(),  # close modal
    )


@callback(
    Output("report-modal-container", "children", allow_duplicate=True),
    Input("report-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cancel_report(n_clicks):
    if not n_clicks:
        return no_update
    return html.Div()


