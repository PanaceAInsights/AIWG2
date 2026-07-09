"""Profiles page — searchable roster + per-member detail pane."""
from __future__ import annotations

import dash_ag_grid as dag
import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html
from dash_iconify import DashIconify

from .. import data, theme

PAGE_TITLE = "Profiles"
PAGE_HREF  = "/profiles"


def _roster_grid() -> dag.AgGrid:
    authors = data.load_authors().copy()
    summary = data.load_summary()
    _merge_cols = [
        "acd_name", "pub_count", "citation_count", "h_index",
        "fwci_mean", "oa_rate", "grants_count", "derm_relevance_rate",
    ]
    if not authors.empty and not summary.empty:
        available = [c for c in _merge_cols if c in summary.columns]
        if "acd_name" in available:
            authors = authors.merge(summary[available], on="acd_name", how="left")
    for c in _merge_cols[1:]:
        if c not in authors.columns:
            authors[c] = None

    col_defs = [
        {"field": "acd_name", "headerName": "Member", "pinned": "left",
         "minWidth": 200, "filter": "agTextColumnFilter"},
        {"field": "state", "headerName": "State", "maxWidth": 110,
         "filter": "agTextColumnFilter"},
        {"field": "last_known_institution", "headerName": "Institution",
         "minWidth": 260, "filter": "agTextColumnFilter"},
        {"field": "institution_country", "headerName": "Country", "maxWidth": 100},
        {"field": "pub_count", "headerName": "Pubs", "maxWidth": 100,
         "type": "numericColumn", "filter": "agNumberColumnFilter"},
        {"field": "h_index", "headerName": "h-index", "maxWidth": 110,
         "type": "numericColumn",
         "headerTooltip": "Number of publications (N) each cited at least N times"},
        {"field": "citation_count", "headerName": "Citations", "maxWidth": 120,
         "type": "numericColumn",
         "valueFormatter": {"function": "d3.format(',')(params.value)"}},
        {"field": "fwci_mean", "headerName": "Mean FWCI", "maxWidth": 120,
         "type": "numericColumn",
         "headerTooltip": "Field-Weighted Citation Impact: >1.0 = above world average",
         "valueFormatter": {"function": "params.value && params.value.toFixed(2)"}},
        {"field": "grants_count", "headerName": "Grants", "maxWidth": 100,
         "type": "numericColumn"},
        {"field": "confidence", "headerName": "Match", "maxWidth": 110,
         "cellStyle": {
             "styleConditions": [
                 {"condition": "params.value == 'HIGH'",
                  "style": {"color": theme.SUCCESS, "fontWeight": 600}},
                 {"condition": "params.value == 'REVIEW'",
                  "style": {"color": theme.WARNING, "fontWeight": 600}},
                 {"condition": "params.value == 'LOW' || params.value == 'NOT_FOUND'",
                  "style": {"color": theme.GRAY_500}},
             ]
         }},
    ]

    return dag.AgGrid(
        id="roster-grid",
        rowData=authors.fillna("").to_dict("records"),
        columnDefs=col_defs,
        defaultColDef={
            "resizable": True, "sortable": True, "filter": True,
            "floatingFilter": True,
        },
        dashGridOptions={
            "rowSelection": {"mode": "singleRow", "checkboxes": False,
                             "enableClickSelection": True},
            "animateRows": True,
            "pagination": True,
            "paginationPageSize": 25,
            "rowHeight": 42,
            "suppressCellFocus": True,
        },
        className="ag-theme-alpine",
        style={"height": "540px", "width": "100%"},
    )


def _empty_state_card() -> html.Div:
    return html.Div(
        html.Div(
            dmc.Text("Select a member from the grid to view their profile",
                     size="sm", c="dimmed", ta="center"),
            className="empty-state",
        ),
        className="section-card",
        style={"minHeight": "540px"},
    )


def render() -> html.Div:
    return html.Div([
        dmc.Group([
            dmc.TextInput(
                id="roster-search",
                placeholder="Search by name, institution, state...",
                leftSection=DashIconify(icon="tabler:search", width=16),
                style={"flex": 1, "maxWidth": "480px"},
            ),
            dmc.Group([
                dmc.SegmentedControl(
                    id="roster-scope",
                    data=[
                        {"label": "All", "value": "all"},
                        {"label": "Resolved", "value": "resolved"},
                    ],
                    value="all",
                    size="sm",
                ),
                dmc.Button(
                    "Export roster",
                    id="roster-export-btn",
                    leftSection=DashIconify(icon="tabler:download", width=16),
                    variant="light",
                    color="acd-copper",
                    size="xs",
                ),
            ], gap="sm"),
        ], justify="space-between", align="center", mb="md"),
        dmc.Grid([
            dmc.GridCol(
                html.Div(_roster_grid(), className="section-card",
                         style={"padding": "0.5rem"}),
                span={"base": 12, "md": 8},
            ),
            dmc.GridCol(
                html.Div(id="profile-detail", children=_empty_state_card()),
                span={"base": 12, "md": 4},
            ),
        ], gutter="lg"),
        dcc.Download(id="roster-download"),
    ])


def build_profile_card(name: str) -> html.Div:
    """Called by callback when a row is selected."""
    row = data.member_detail(name)
    if not row:
        return _empty_state_card()

    inst       = row.get("last_known_institution") or "-"
    country    = row.get("institution_country") or ""
    state      = row.get("state") or "-"
    profile_id = row.get("openalex_id") or ""
    profile_url = row.get("profile_url") or (
        f"https://openalex.org/{profile_id}" if profile_id else ""
    )
    pubs    = row.get("pub_count")
    h       = row.get("h_index")
    cit     = row.get("citation_count")
    fwci    = row.get("fwci_mean")
    oa_rate = row.get("oa_rate")
    derm_pct = row.get("derm_relevance_rate")
    intl    = row.get("intl_collab_rate")

    def _kv(label: str, value):
        return html.Div([
            html.Div(label, className="metric-label"),
            html.Div(
                "-" if pd.isna(value) or value in (None, "") else f"{value}",
                className="metric-value",
            ),
        ], style={"marginRight": "1.5rem"})

    conf_badge = dmc.Badge(
        row.get("confidence") or "-",
        color={"HIGH": "teal", "REVIEW": "yellow", "LOW": "gray",
               "NOT_FOUND": "gray"}.get(row.get("confidence"), "gray"),
        variant="light",
    )
    ahpra_badge = dmc.Badge("AHPRA-verified", color="acd-copper", variant="filled") \
        if str(row.get("ahpra_proven", "")) in ("1", "True", "true") else None

    # Pub-year sparkline
    pubs_df = data.member_publications(name)
    if not pubs_df.empty:
        year_col = next((c for c in ("year", "Year") if c in pubs_df.columns), None)
        if year_col:
            years = pubs_df[year_col].dropna().astype(int)
            year_counts = years.value_counts().sort_index()
            spark = go.Figure(go.Bar(
                x=year_counts.index, y=year_counts.values,
                marker_color=theme.PRIMARY,
                hovertemplate="%{x}: %{y} publications<extra></extra>",
            ))
            spark.update_layout(
                height=170, margin=dict(l=36, r=8, t=8, b=30),
                xaxis_title="", yaxis_title="", showlegend=False,
            )
        else:
            spark = go.Figure()
    else:
        spark = go.Figure()

    funding_df = data.member_funding(name)
    trials_df  = data.member_trials(name)
    grants_count = len(funding_df) if not funding_df.empty else 0
    trials_count = len(trials_df) if not trials_df.empty else 0

    pub_types = ""
    if not pubs_df.empty and "type" in pubs_df.columns:
        top_types = pubs_df["type"].dropna().value_counts().head(3)
        pub_types = ", ".join(f"{t} ({c})" for t, c in top_types.items())

    sections = [
        dmc.Group([
            dmc.Text(name, fw=700, size="lg"),
            html.Div([ahpra_badge, conf_badge] if ahpra_badge else [conf_badge],
                     style={"display": "flex", "gap": "0.3rem"}),
        ], justify="space-between", align="center"),
        dmc.Text(inst, size="sm", c="dimmed"),
        dmc.Group([
            dmc.Badge(state, variant="light", size="sm"),
            dmc.Badge(country, variant="light", color="gray", size="sm") if country else None,
        ], gap="xs"),
        dmc.Divider(my="md"),
        html.Div(
            [
                _kv("Publications", int(pubs) if pubs and not pd.isna(pubs) else "-"),
                _kv("h-index", int(h) if h and not pd.isna(h) else "-"),
                _kv("Citations", f"{int(cit):,}" if cit and not pd.isna(cit) else "-"),
                _kv("FWCI", f"{fwci:.2f}" if fwci and not pd.isna(fwci) else "-"),
                _kv("Grants", grants_count),
                _kv("Clinical trials", trials_count),
            ],
            style={"display": "grid", "gridTemplateColumns": "repeat(2, 1fr)",
                   "gap": "0.75rem"},
        ),
        dmc.Divider(my="md"),
        html.Div("Publication timeline", className="section-title"),
        dcc.Graph(figure=spark, config={"displayModeBar": False},
                  style={"height": "170px"}),
        dmc.Divider(my="md"),
        dmc.Group([
            dmc.Badge(
                f"{oa_rate*100:.0f}% OA" if oa_rate and oa_rate <= 1 else
                (f"{oa_rate:.0f}% OA" if oa_rate else "OA -"),
                color="teal", variant="light",
            ),
            dmc.Badge(
                f"{intl*100:.0f}% intl. collab" if intl and intl <= 1 else
                (f"{intl:.0f}% intl" if intl else ""),
                color="violet", variant="light",
            ) if intl else None,
            dmc.Badge(
                f"{derm_pct*100:.0f}% derm-relevant" if derm_pct and derm_pct <= 1 else
                (f"{derm_pct:.0f}% derm" if derm_pct else ""),
                color="indigo", variant="light",
            ) if derm_pct else None,
        ], gap="xs"),
    ]

    if pub_types:
        sections.append(dmc.Space(h=8))
        sections.append(dmc.Text(f"Top types: {pub_types}", size="xs", c="dimmed"))

    if not funding_df.empty and "funder_name" in funding_df.columns:
        top_funders = funding_df["funder_name"].dropna().value_counts().head(3)
        if not top_funders.empty:
            funder_str = ", ".join(top_funders.index.tolist())
            sections.append(dmc.Text(f"Funders: {funder_str}", size="xs", c="dimmed"))

    keywords = data.member_keywords(name)
    if keywords:
        sections.append(dmc.Space(h=8))
        sections.append(
            dmc.Group(
                [dmc.Badge(kw, variant="outline", color="gray", size="xs")
                 for kw in keywords[:8]],
                gap=4, style={"flexWrap": "wrap"},
            )
        )

    orcid = data.member_orcid(name)
    if orcid:
        sections.append(dmc.Space(h=4))
        sections.append(
            dmc.Anchor(f"ORCID: {orcid}", href=f"https://orcid.org/{orcid}",
                       target="_blank", size="xs", c="dimmed")
        )

    if profile_url:
        sections.append(dmc.Space(h=12))
        sections.append(
            dmc.Anchor("View research profile \u203a", href=profile_url,
                       target="_blank", size="sm", fw=500, c="acd-copper")
        )

    return html.Div(sections, className="section-card", style={"minHeight": "540px"})


layout = render
