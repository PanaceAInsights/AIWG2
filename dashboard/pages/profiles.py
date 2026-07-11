"""Profiles page — card tiles for all 712 members + detail drawer."""
from __future__ import annotations

import math

import dash_ag_grid as dag
import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html
from dash_iconify import DashIconify

from .. import data, theme

PAGE_TITLE = "Profiles"
PAGE_HREF  = "/profiles"


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt(val, decimals: int = 0) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "—"
    if decimals == 0:
        return f"{int(val):,}"
    return f"{float(val):.{decimals}f}"


def _confidence_badge(conf: str | None, accepted) -> html.Span:
    if accepted and conf == "HIGH":
        return html.Span("✓ Matched", className="profile-tile-badge high")
    if accepted and conf == "REVIEW":
        return html.Span("~ Review", className="profile-tile-badge review")
    return html.Span("No data", className="profile-tile-badge none")


def _build_tile(row: pd.Series) -> html.Div:
    name     = row.get("acd_name", "Unknown")
    # Guard against NaN floats from the merge
    _s = row.get("state"); state = str(_s) if _s and not (isinstance(_s, float) and math.isnan(_s)) else "—"
    _i = row.get("last_known_institution"); inst = str(_i) if _i and not (isinstance(_i, float) and math.isnan(_i)) else "—"
    _sp = row.get("speciality_ahpra"); spec = str(_sp) if _sp and not (isinstance(_sp, float) and math.isnan(_sp)) else "Dermatology"
    conf     = row.get("confidence")
    accepted = bool(row.get("accepted"))

    pub_count = _fmt(row.get("pub_count"))
    h_index   = _fmt(row.get("h_index"))
    citations = _fmt(row.get("citation_count"))
    fwci      = _fmt(row.get("fwci_mean"), 2)

    # Clinical expertise (truncated for tile)
    _ce = row.get("clinical_expertise")
    clinical_exp = str(_ce).split("|")[0].strip()[:80] if _ce and not (isinstance(_ce, float) and math.isnan(_ce)) else ""

    meta_parts = [p for p in [state, inst] if p and p != "—" and isinstance(p, str)]
    meta_str   = " · ".join(meta_parts) if meta_parts else "Location unknown"

    children = [
        _confidence_badge(conf, accepted),
        html.Div(name, className="profile-tile-name"),
        html.Div(meta_str, className="profile-tile-meta"),
        html.Div([html.Span(spec, className="profile-tile-tag")],
                 className="profile-tile-tags"),
        html.Div([
            html.Div([
                html.Div(pub_count, className="profile-tile-metric-value"),
                html.Div("Pubs", className="profile-tile-metric-label"),
            ], className="profile-tile-metric"),
            html.Div([
                html.Div(h_index, className="profile-tile-metric-value"),
                html.Div("h-index", className="profile-tile-metric-label"),
            ], className="profile-tile-metric"),
            html.Div([
                html.Div(citations, className="profile-tile-metric-value"),
                html.Div("Citations", className="profile-tile-metric-label"),
            ], className="profile-tile-metric"),
            html.Div([
                html.Div(fwci, className="profile-tile-metric-value"),
                html.Div("FWCI", className="profile-tile-metric-label"),
            ], className="profile-tile-metric"),
        ], className="profile-tile-metrics"),
    ]

    if clinical_exp:
        children.append(
            html.Div(clinical_exp, className="profile-tile-expertise")
        )

    return html.Div(
        id={"type": "profile-tile", "index": name},
        className="profile-tile",
        children=children,
    )


PAGE_SIZE = 48


def _build_tiles(df: pd.DataFrame, page: int = 1) -> html.Div:
    """Render one page of tiles (PAGE_SIZE per page) to avoid browser hang."""
    if df.empty:
        return html.Div("No members match the current filters.", className="empty-state")
    start = (page - 1) * PAGE_SIZE
    end   = start + PAGE_SIZE
    tiles = [_build_tile(row) for _, row in df.iloc[start:end].iterrows()]
    return html.Div(tiles, className="profile-grid")


def build_profile_card(name: str) -> html.Div:
    """Build the detail panel for a clicked member (called by callback)."""
    row = data.member_detail(name)
    if not row:
        return html.Div([
            html.Div(name, style={"fontWeight": 700, "fontSize": 16,
                                  "color": theme.TEXT_PRIMARY, "marginBottom": 8}),
            html.Div("No academic publication record found for this member.",
                     style={"color": theme.TEXT_MUTED, "fontSize": 13}),
            html.Div("This member is included in the ACD directory but has not been "
                     "matched to an indexed academic profile.",
                     style={"color": theme.TEXT_MUTED, "fontSize": 12, "marginTop": 6}),
        ])

    # --- Data loading ---
    pubs_df = data.member_publications(name)
    counts_by_year = data.member_counts_by_year(name)
    grants_detail = data.member_grants_detail(name)
    topics_detail = data.member_topics_detail(name)

    # --- Publication timeline chart (from OpenAlex counts_by_year) ---
    pub_chart = go.Figure()
    cite_chart = go.Figure()
    if counts_by_year:
        years = [c["year"] for c in counts_by_year if c.get("year")]
        works = [c.get("works_count", 0) for c in counts_by_year if c.get("year")]
        cites = [c.get("cited_by_count", 0) for c in counts_by_year if c.get("year")]
        pub_chart.add_trace(go.Bar(
            x=years, y=works,
            marker_color=theme.COPPER,
            hovertemplate="%{x}: %{y} publications<extra></extra>",
        ))
        cite_chart.add_trace(go.Bar(
            x=years, y=cites,
            marker_color=theme.COPPER_LIGHT,
            hovertemplate="%{x}: %{y} citations<extra></extra>",
        ))
    elif pubs_df is not None and not pubs_df.empty:
        # Fallback to publications CSV
        year_col = next((c for c in ("year", "Year") if c in pubs_df.columns), None)
        if year_col:
            years = pubs_df[year_col].dropna().astype(int)
            yc = years.value_counts().sort_index()
            pub_chart.add_trace(go.Bar(
                x=yc.index, y=yc.values,
                marker_color=theme.COPPER,
                hovertemplate="%{x}: %{y} pubs<extra></extra>",
            ))

    _chart_layout = dict(
        height=130, margin=dict(l=36, r=8, t=4, b=28),
        paper_bgcolor=theme.BG_CARD, plot_bgcolor=theme.BG_CARD,
        font=dict(color=theme.TEXT_MUTED, size=10),
        xaxis=dict(gridcolor=theme.BORDER, linecolor=theme.BORDER),
        yaxis=dict(gridcolor=theme.BORDER, linecolor=theme.BORDER),
        showlegend=False,
    )
    pub_chart.update_layout(**_chart_layout)
    cite_chart.update_layout(**_chart_layout)

    # --- Recent publications list ---
    pub_rows = []
    if pubs_df is not None and not pubs_df.empty:
        for _, p in pubs_df.head(5).iterrows():
            pub_rows.append(html.Div([
                html.Div(p.get("title", "Untitled"),
                         style={"fontSize": 12, "color": theme.TEXT_SECONDARY,
                                "fontWeight": 500}),
                html.Div(f"{p.get('year', '')}  \u00b7  {p.get('cited_by_count', 0):,} citations",
                         style={"fontSize": 11, "color": theme.TEXT_MUTED}),
            ], style={"marginBottom": 8, "paddingBottom": 8,
                      "borderBottom": f"1px solid {theme.BORDER}"}))

    # --- Helper ---
    def _stat(label, val):
        return html.Div([
            html.Span(label + ": ", style={"color": theme.TEXT_MUTED, "fontSize": 12}),
            html.Span(str(val) if val is not None else "\u2014",
                      style={"color": theme.COPPER, "fontWeight": 700, "fontSize": 13}),
        ], style={"marginBottom": 4})

    inst        = row.get("last_known_institution", "")
    profile_url = row.get("profile_url") or (
        f"https://openalex.org/{row.get('openalex_id')}"
        if row.get("openalex_id") else ""
    )
    oa_rate  = row.get("oa_rate")
    derm_pct = row.get("derm_relevance_rate")
    intl     = row.get("intl_collab_rate")

    # Grants count from new detailed data
    n_funders = len(grants_detail.get("funders", []))
    n_awards = len(grants_detail.get("awards", []))

    funding_df = data.member_funding(name)
    trials_df  = data.member_trials(name)
    trials_count = len(trials_df) if trials_df is not None and not trials_df.empty else 0

    # Expertise fields
    _ce = row.get("clinical_expertise")
    clinical_exp = str(_ce) if _ce and not (isinstance(_ce, float) and math.isnan(_ce)) else ""
    _rex = row.get("research_expertise")
    research_exp = str(_rex) if _rex and not (isinstance(_rex, float) and math.isnan(_rex)) else ""

    # ORCID
    orcid = row.get("orcid", "")
    if orcid and str(orcid) != "nan":
        orcid = str(orcid).strip()
    else:
        orcid = ""

    # --- Build children ---
    children = [
        # Header
        html.Div(name, style={"fontWeight": 700, "fontSize": 16,
                               "color": theme.TEXT_PRIMARY, "marginBottom": 4}),
        html.Div(inst, style={"fontSize": 12, "color": theme.TEXT_MUTED, "marginBottom": 4}),
    ]

    # ORCID link
    if orcid:
        children.append(html.Div(
            html.A(f"ORCID: {orcid}", href=f"https://orcid.org/{orcid}",
                   target="_blank",
                   style={"color": theme.COPPER_LIGHT, "fontSize": 11,
                          "textDecoration": "none"}),
            style={"marginBottom": 12},
        ))
    else:
        children.append(html.Div(style={"marginBottom": 8}))

    # Key metrics grid
    children.append(html.Div([
        _stat("Publications", _fmt(row.get("pub_count"))),
        _stat("h-index", _fmt(row.get("h_index"))),
        _stat("Citations", _fmt(row.get("citation_count"))),
        _stat("Mean FWCI", _fmt(row.get("fwci_mean"), 2)),
        _stat("Open Access", f"{oa_rate*100:.0f}%" if oa_rate is not None else "\u2014"),
        _stat("Funders", n_funders if n_funders else "\u2014"),
        _stat("Awards/Grants", n_awards if n_awards else "\u2014"),
        _stat("Clinical Trials", trials_count if trials_count else "\u2014"),
        _stat("Derm-relevant",
              f"{derm_pct:.0f}%" if derm_pct is not None else "\u2014"),
    ], style={"marginBottom": 16}))

    # Clinical expertise section
    if clinical_exp:
        children.append(html.Div([
            html.Div("Clinical Expertise", className="profile-detail-expertise-title"),
            html.Div(clinical_exp, className="profile-detail-expertise-text"),
        ], className="profile-detail-expertise"))

    # Research topics section (from detailed topics data)
    if topics_detail:
        topic_chips = []
        for t in topics_detail[:8]:
            label = t.get("name", "")
            count = t.get("count", 0)
            field = t.get("field", "")
            chip_text = f"{label} ({count})" if count else label
            topic_chips.append(
                html.Span(chip_text, className="expertise-chip",
                          title=f"Field: {field}")
            )
        children.append(html.Div([
            html.Div("Research Topics (OpenAlex)", className="profile-detail-expertise-title"),
            html.Div(topic_chips),
        ], className="profile-detail-expertise"))
    elif research_exp:
        topics = [t.strip() for t in research_exp.split(";") if t.strip()]
        children.append(html.Div([
            html.Div("Research Topics", className="profile-detail-expertise-title"),
            html.Div([html.Span(t, className="expertise-chip") for t in topics[:6]]),
        ], className="profile-detail-expertise"))

    # Publication timeline chart
    children.extend([
        html.Div("Publications per Year",
                 style={"fontWeight": 600, "fontSize": 13,
                        "color": theme.TEXT_PRIMARY, "marginBottom": 4, "marginTop": 12}),
        dcc.Graph(figure=pub_chart, config={"displayModeBar": False},
                  style={"height": "130px", "marginBottom": 8}),
    ])

    # Citation trend chart
    if counts_by_year and any(c.get("cited_by_count", 0) > 0 for c in counts_by_year):
        children.extend([
            html.Div("Citations per Year",
                     style={"fontWeight": 600, "fontSize": 13,
                            "color": theme.TEXT_PRIMARY, "marginBottom": 4}),
            dcc.Graph(figure=cite_chart, config={"displayModeBar": False},
                      style={"height": "130px", "marginBottom": 12}),
        ])

    # Grants/Funders section
    if n_funders > 0:
        funder_items = []
        for f in grants_detail["funders"][:15]:
            fname = f.get("name", "Unknown funder")
            funder_items.append(
                html.Div(f"\u2022 {fname}",
                         style={"fontSize": 11, "color": theme.TEXT_SECONDARY,
                                "marginBottom": 2})
            )
        if n_funders > 15:
            funder_items.append(
                html.Div(f"... and {n_funders - 15} more",
                         style={"fontSize": 11, "color": theme.TEXT_MUTED,
                                "fontStyle": "italic"})
            )
        children.append(html.Div([
            html.Div(f"Funders ({n_funders})",
                     style={"fontWeight": 600, "fontSize": 13,
                            "color": theme.TEXT_PRIMARY, "marginBottom": 6}),
            html.Div(funder_items),
        ], style={"marginBottom": 12}))

    # Awards section
    if n_awards > 0:
        award_items = []
        for a in grants_detail["awards"][:10]:
            aname = a.get("name") or a.get("award_id", "")
            afunder = a.get("funder", "")
            label = f"{aname}" if aname else f"Award {a.get('award_id', '')}"
            if afunder:
                label += f" ({afunder})"
            award_items.append(
                html.Div(f"\u2022 {label}",
                         style={"fontSize": 11, "color": theme.TEXT_SECONDARY,
                                "marginBottom": 2})
            )
        if n_awards > 10:
            award_items.append(
                html.Div(f"... and {n_awards - 10} more",
                         style={"fontSize": 11, "color": theme.TEXT_MUTED,
                                "fontStyle": "italic"})
            )
        children.append(html.Div([
            html.Div(f"Awards/Grants ({n_awards})",
                     style={"fontWeight": 600, "fontSize": 13,
                            "color": theme.TEXT_PRIMARY, "marginBottom": 6}),
            html.Div(award_items),
        ], style={"marginBottom": 12}))

    # Recent publications
    children.extend([
        html.Div("Recent Publications",
                 style={"fontWeight": 600, "fontSize": 13,
                        "color": theme.TEXT_PRIMARY, "marginBottom": 8}),
        html.Div(pub_rows if pub_rows else
                 [html.Div("No publications on record.",
                           style={"color": theme.TEXT_MUTED, "fontSize": 12})]),
    ])

    # OpenAlex profile link
    if profile_url:
        children.append(html.Div(
            html.A("View OpenAlex profile \u2192", href=profile_url, target="_blank",
                   style={"color": theme.COPPER, "fontSize": 13,
                          "fontWeight": 600, "textDecoration": "none"}),
            style={"marginTop": 16},
        ))

    return html.Div(children)


def render(
    state_filter: list | None = None,
    speciality_filter: list | None = None,
    country_filter: list | None = None,
    year_range: list | None = None,
    search_text: str | None = None,
    scope: str = "all",
) -> html.Div:
    # ── Load and merge ────────────────────────────────────────────────────────
    authors  = data.load_authors().copy()
    summary  = data.load_summary()

    merge_cols = ["acd_name", "pub_count", "citation_count", "h_index",
                  "fwci_mean", "oa_rate", "grants_count", "derm_relevance_rate",
                  "intl_collab_rate", "clinical_expertise", "research_expertise"]
    if not summary.empty:
        avail = [c for c in merge_cols if c in summary.columns]
        if "acd_name" in avail:
            # Drop overlapping columns from authors to avoid _x/_y suffixes after merge
            _overlap = [c for c in avail if c != "acd_name" and c in authors.columns]
            authors = authors.drop(columns=_overlap, errors="ignore")
            authors = authors.merge(summary[avail], on="acd_name", how="left")

    for c in merge_cols[1:]:
        if c not in authors.columns:
            authors[c] = None

    # ── Scope filter ──────────────────────────────────────────────────────────
    if scope == "resolved":
        authors = authors[authors["accepted"] == True]
    elif scope == "unresolved":
        authors = authors[authors["accepted"] != True]

    # ── Global filters ────────────────────────────────────────────────────────
    if state_filter:
        authors = authors[authors["state"].isin(state_filter)]
    if speciality_filter:
        authors = authors[authors["speciality_ahpra"].isin(speciality_filter)]
    if country_filter:
        authors = authors[authors["institution_country"].isin(country_filter)]
    if search_text:
        q = search_text.lower()
        mask = (
            authors["acd_name"].str.lower().str.contains(q, na=False) |
            authors["last_known_institution"].fillna("").str.lower().str.contains(q, na=False) |
            authors["clinical_expertise"].fillna("").str.lower().str.contains(q, na=False) |
            authors["research_expertise"].fillna("").str.lower().str.contains(q, na=False)
        )
        authors = authors[mask]

    # Sort: resolved + high h-index first
    authors = authors.sort_values(
        ["accepted", "h_index"], ascending=[False, False], na_position="last",
    ).reset_index(drop=True)

    total    = len(authors)
    resolved = int(authors["accepted"].sum()) if "accepted" in authors.columns else 0
    all_raw  = data.load_authors()

    return html.Div([
        # ── Header row ────────────────────────────────────────────────────────
        html.Div([
            html.Div([
                html.Div("Member Profiles", className="section-title"),
                html.Div(
                    f"{total:,} members shown · {resolved:,} with academic profiles",
                    className="section-subtitle",
                ),
            ], style={"flex": 1}),
            dmc.Group([
                dmc.SegmentedControl(
                    id="roster-scope",
                    value=scope,
                    data=[
                        {"value": "all",
                         "label": f"All ({len(all_raw):,})"},
                        {"value": "resolved",
                         "label": "With publications"},
                        {"value": "unresolved",
                         "label": "No publications"},
                    ],
                    size="sm",
                    color="copper",
                    styles={"root": {"backgroundColor": theme.BG_SIDEBAR}},
                ),
                dmc.TextInput(
                    id="roster-search",
                    placeholder="Search name or institution…",
                    leftSection=DashIconify(icon="tabler:search", width=16),
                    value=search_text or "",
                    size="sm",
                    style={"width": 260},
                ),
                dmc.Button(
                    "Export CSV",
                    id="roster-export-btn",
                    leftSection=DashIconify(icon="tabler:download", width=16),
                    variant="outline",
                    color="copper",
                    size="sm",
                ),
                dcc.Download(id="roster-download"),
            ], gap="sm"),
        ], style={"display": "flex", "alignItems": "flex-start",
                  "justifyContent": "space-between",
                  "marginBottom": 16, "flexWrap": "wrap", "gap": 12}),

        # ── Tile grid ─────────────────────────────────────────────────────────
        html.Div(id="profiles-tile-grid", children=_build_tiles(authors, 1)),
        # ── Pagination ────────────────────────────────────────────────────────
        html.Div(
            dmc.Pagination(
                id="profiles-page",
                total=max(1, math.ceil(total / PAGE_SIZE)),
                value=1,
                siblings=2,
                color="copper",
                size="sm",
            ),
            style={"display": "flex", "justifyContent": "center",
                   "marginTop": 24, "marginBottom": 8},
        ),
        # Store the serialised author list for the pagination callback
        dcc.Store(id="profiles-authors-store",
                  data=authors[["acd_name"] + [c for c in authors.columns
                                               if c != "acd_name"]].to_json(orient="records")),

        # ── Detail drawer ─────────────────────────────────────────────────────
        dmc.Drawer(
            id="profile-detail-drawer",
            title="",
            position="right",
            size="lg",
            padding="xl",
            overlayProps={"opacity": 0.4},
            styles={
                "content": {"backgroundColor": theme.BG_CARD},
                "header": {"backgroundColor": theme.BG_CARD,
                           "borderBottom": f"1px solid {theme.BORDER}"},
                "title": {"color": theme.TEXT_PRIMARY},
                "close": {"color": theme.TEXT_MUTED},
            },
            children=[html.Div(id="profile-detail-content")],
        ),
    ])


layout = render
