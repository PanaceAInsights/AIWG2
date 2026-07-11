"""ACD Research Intelligence Dashboard — Plotly Dash entry point.

Run locally:
    python -m dashboard.app
Production:
    gunicorn dashboard.app:server --bind 0.0.0.0:8050
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

import dash
import pandas as pd
from dash import Input, Output, State, callback, dcc, html, no_update

from . import data, theme
from .layout import build_layout, NAV
from .pages import REGISTRY
from .pages.profiles import build_profile_card
from .pages.experts import build_expert_results
from .pages.publications import build_pub_detail, build_pubs_kpi
from .pages.impact import (
    build_impact_kpi, build_h_index_hist, build_fwci_boxplot,
    build_scatter, build_top_performers,
)
from .pages.funding import (
    build_funding_kpi, build_funders_bar, build_grants_treemap,
)
from .pages.trials import (
    build_trials_kpi, build_status_chart, build_year_chart,
    build_investigator_chart,
)
from .pages.overview import (
    build_overview_kpis, build_publications_trend,
    build_state_chart, build_top_inst_chart,
)
from .pages.benchmarking import build_ridge_chart, build_quantile_bars
from .pages.heatmap import build_topic_heatmap, build_state_topic_heatmap
from .pages.collaboration import build_collab_detail
from .pages.chatbot import build_user_bubble, build_assistant_bubble
from .components.filters import apply_pub_filters, apply_author_filters, get_filtered_names

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("acd.dashboard")

theme.register_plotly_template()

app = dash.Dash(
    __name__,
    title="ACD Research Intelligence Dashboard",
    update_title=None,
    suppress_callback_exceptions=True,
    meta_tags=[
        {"name": "viewport",
         "content": "width=device-width, initial-scale=1, shrink-to-fit=no"},
        {"name": "description",
         "content": "AI-curated research activity dashboard for the "
                    "Australasian College of Dermatologists."},
    ],
)
server = app.server  # WSGI entry
app.layout = build_layout()

# --------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------- #
@callback(Output("page-content", "children"), Input("url", "pathname"))
def render_page(pathname: str):
    page = REGISTRY.get(pathname or "/")
    if page is None:
        return html.Div([
            html.H2("404: page not found"),
            html.P(f"No page registered for {pathname!r}. Use the sidebar."),
        ], className="section-card", style={"marginTop": "1rem"})
    try:
        return page.render()
    except Exception as exc:
        logger.exception("Render failure on %s", pathname)
        return html.Div([
            html.H3("Sorry, this page errored."),
            html.Pre(str(exc), style={"whiteSpace": "pre-wrap",
                                       "background": "#fee", "padding": "1rem",
                                       "borderRadius": "0.5rem"}),
        ], className="section-card", style={"marginTop": "1rem"})


@callback(
    Output({"type": "nav-link", "href": dash.ALL}, "className"),
    Input("url", "pathname"),
)
def highlight_nav(pathname: str):
    classes = []
    for href, _label, _icon in NAV:
        active = (pathname == href) or (pathname == "/" and href == "/")
        classes.append("acd-nav-link is-active" if active else "acd-nav-link")
    return classes


# --------------------------------------------------------------------- #
# Filter bar — toggle open/close
# --------------------------------------------------------------------- #
@callback(
    Output("filter-collapse", "opened"),
    Input("filter-toggle-btn", "n_clicks"),
    State("filter-collapse", "opened"),
    prevent_initial_call=True,
)
def toggle_filter_bar(n_clicks, is_open):
    if not n_clicks:
        return no_update
    return not is_open


# --------------------------------------------------------------------- #
# Global filter store — update when any filter control changes
# --------------------------------------------------------------------- #
@callback(
    Output("global-filters", "data"),
    Output("filter-active-count", "children"),
    Input("filter-state", "value"),
    Input("filter-speciality", "value"),
    Input("filter-country", "value"),
    Input("filter-year-range", "value"),
    Input("filter-text-search", "value"),
    Input("filter-derm-only", "checked"),
    Input("filter-pub-type", "value"),
)
def update_global_filters(state, speciality, country, year_range,
                           text_search, derm_only, pub_type):
    gf: dict[str, Any] = {}
    active = 0
    if state:
        gf["state"] = state
        active += 1
    if speciality:
        gf["speciality"] = speciality
        active += 1
    if country:
        gf["country"] = country
        active += 1
    if year_range:
        gf["year_range"] = year_range
        active += 1
    if text_search and text_search.strip():
        gf["text_search"] = text_search.strip()
        active += 1
    if derm_only:
        gf["derm_only"] = True
        active += 1
    if pub_type:
        gf["pub_type"] = pub_type
        active += 1
    label = f"{active} filter{'s' if active != 1 else ''} active" if active else ""
    return gf, label


# --------------------------------------------------------------------- #
# Clear all filters
# --------------------------------------------------------------------- #
@callback(
    Output("filter-state", "value"),
    Output("filter-speciality", "value"),
    Output("filter-country", "value"),
    Output("filter-year-range", "value"),
    Output("filter-text-search", "value"),
    Output("filter-derm-only", "checked"),
    Output("filter-pub-type", "value"),
    Input("filter-clear-btn", "n_clicks"),
    prevent_initial_call=True,
)
def clear_filters(n_clicks):
    if not n_clicks:
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update
    from .components.filters import _get_year_range
    yr_min, yr_max = _get_year_range()
    return [], [], [], [yr_min, yr_max], "", False, []


# --------------------------------------------------------------------- #
# Profiles — tile click → drawer, tile grid filter, export
# --------------------------------------------------------------------- #
from dash import ALL

@callback(
    Output("profile-detail-drawer", "opened"),
    Output("profile-detail-content", "children"),
    Input({"type": "profile-tile", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def profile_tile_clicked(n_clicks_list):
    from dash import ctx
    if not any(n for n in n_clicks_list if n):
        return no_update, no_update
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return no_update, no_update
    name = triggered.get("index")
    if not name:
        return no_update, no_update
    return True, build_profile_card(name)


@callback(
    Output("profiles-tile-grid", "children"),
    Output("profiles-authors-store", "data"),
    Output("profiles-page", "total"),
    Output("profiles-page", "value"),
    Input("roster-search", "value"),
    Input("roster-scope", "value"),
    Input("global-filters", "data"),
)
def apply_roster_filters(search_value: str, scope: str, gf: dict):
    """Re-render tile grid (page 1) and update pagination on filter change."""
    import math as _math
    from .pages.profiles import _build_tiles, PAGE_SIZE
    authors = data.load_authors().copy()
    if authors.empty:
        return [], "[]", 1, 1
    summary = data.load_summary()
    _want = ["acd_name", "pub_count", "citation_count", "h_index",
             "fwci_mean", "oa_rate", "grants_count", "derm_relevance_rate",
             "intl_collab_rate", "clinical_expertise", "research_expertise"]
    if not summary.empty:
        _available = [c for c in _want if c in summary.columns]
        if "acd_name" in _available and "acd_name" in authors.columns:
            # Drop columns from authors that also exist in summary to avoid _x/_y suffixes
            _overlap = [c for c in _available if c != "acd_name" and c in authors.columns]
            authors = authors.drop(columns=_overlap, errors="ignore")
            authors = authors.merge(summary[_available], on="acd_name", how="left")
    for c in _want[1:]:
        if c not in authors.columns:
            authors[c] = None
    # Scope
    if scope == "resolved":
        authors = authors[authors["accepted"] == True]
    elif scope == "unresolved":
        authors = authors[authors["accepted"] != True]
    # Apply global filters
    if gf:
        authors = apply_author_filters(authors, gf)
    # Free-text search
    q = (search_value or "").strip().lower()
    if q:
        mask = (
            authors["acd_name"].str.lower().str.contains(q, na=False) |
            authors["last_known_institution"].fillna("").str.lower().str.contains(q, na=False) |
            authors["clinical_expertise"].fillna("").str.lower().str.contains(q, na=False) |
            authors["research_expertise"].fillna("").str.lower().str.contains(q, na=False)
        )
        authors = authors[mask]
    authors = authors.sort_values(
        ["accepted", "h_index"], ascending=[False, False], na_position="last"
    ).reset_index(drop=True)
    total_pages = max(1, _math.ceil(len(authors) / PAGE_SIZE))
    store_data  = authors.to_json(orient="records")
    return _build_tiles(authors, 1), store_data, total_pages, 1


@callback(
    Output("profiles-tile-grid", "children", allow_duplicate=True),
    Input("profiles-page", "value"),
    State("profiles-authors-store", "data"),
    prevent_initial_call=True,
)
def paginate_profiles(page: int, store_data: str):
    """Render the requested page of tiles from the cached author store."""
    import json
    from .pages.profiles import _build_tiles, PAGE_SIZE
    if not store_data:
        return no_update
    authors = pd.DataFrame(json.loads(store_data))
    return _build_tiles(authors, page or 1)


@callback(
    Output("roster-download", "data"),
    Input("roster-export-btn", "n_clicks"),
    State("roster-scope", "value"),
    State("roster-search", "value"),
    State("global-filters", "data"),
    prevent_initial_call=True,
)
def export_roster_csv(n_clicks, scope, search_value, gf):
    if not n_clicks:
        return no_update
    authors = data.load_authors().copy()
    summary = data.load_summary()
    _want = ["acd_name", "pub_count", "citation_count", "h_index",
             "fwci_mean", "oa_rate", "grants_count", "derm_relevance_rate",
             "clinical_expertise", "research_expertise"]
    if not summary.empty:
        _available = [c for c in _want if c in summary.columns]
        if "acd_name" in _available:
            _overlap = [c for c in _available if c != "acd_name" and c in authors.columns]
            authors = authors.drop(columns=_overlap, errors="ignore")
            authors = authors.merge(summary[_available], on="acd_name", how="left")
    if scope == "resolved":
        authors = authors[authors["accepted"] == True]
    elif scope == "unresolved":
        authors = authors[authors["accepted"] != True]
    if gf:
        authors = apply_author_filters(authors, gf)
    q = (search_value or "").strip().lower()
    if q:
        mask = (
            authors["acd_name"].str.lower().str.contains(q, na=False) |
            authors["last_known_institution"].fillna("").str.lower().str.contains(q, na=False) |
            authors["clinical_expertise"].fillna("").str.lower().str.contains(q, na=False) |
            authors["research_expertise"].fillna("").str.lower().str.contains(q, na=False)
        )
        authors = authors[mask]
    buf = io.StringIO()
    authors.to_csv(buf, index=False)
    return dict(content=buf.getvalue(), filename="acd_roster_filtered.csv")


# --------------------------------------------------------------------- #
# Expert Finder
# --------------------------------------------------------------------- #
@callback(
    Output("expert-results", "children"),
    Input("expert-search-btn", "n_clicks"),
    State("expert-topic-select", "value"),
    State("expert-keyword-search", "value"),
    prevent_initial_call=True,
)
def expert_search(n_clicks, topic, keyword):
    if not n_clicks:
        return no_update
    return build_expert_results(topic, keyword)


@callback(
    Output("expert-download", "data"),
    Input("expert-export-btn", "n_clicks"),
    State("expert-topic-select", "value"),
    State("expert-keyword-search", "value"),
    prevent_initial_call=True,
)
def export_expert_csv(n_clicks, topic, keyword):
    if not n_clicks:
        return no_update
    from .pages.experts import _build_expertise_index
    idx = _build_expertise_index()
    if idx.empty:
        return no_update
    if topic and topic.strip():
        results = idx[idx["topic"] == topic]
    elif keyword and keyword.strip():
        kw = keyword.strip().lower()
        results = idx[idx["topic"].str.lower().str.contains(kw, na=False)]
    else:
        return no_update
    if results.empty:
        return no_update
    results = results.sort_values("pub_count", ascending=False)
    buf = io.StringIO()
    results.to_csv(buf, index=False)
    return dict(content=buf.getvalue(), filename="acd_expert_results.csv")


# --------------------------------------------------------------------- #
# Data Explorer
# --------------------------------------------------------------------- #
@callback(
    Output("explorer-body", "children"),
    Input("explorer-dataset", "value"),
    prevent_initial_call=True,
)
def explorer_switch(dataset: str):
    from .pages.explorer import _grid_for
    return html.Div(_grid_for(dataset), className="section-card",
                    style={"padding": "0.5rem"})


@callback(
    Output("explorer-download", "data"),
    Input("explorer-export-btn", "n_clicks"),
    State("explorer-dataset", "value"),
    prevent_initial_call=True,
)
def export_explorer_csv(n_clicks, dataset):
    if not n_clicks:
        return no_update
    if dataset == "authors":
        df = data.load_authors()
    elif dataset == "summary":
        df = data.load_summary()
    elif dataset == "pubs":
        df = data.load_publications()
    elif dataset == "funding":
        df = data.load_funding()
    elif dataset == "trials":
        df = data.load_clinical_trials()
    else:
        return no_update
    if df.empty:
        return no_update
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return dict(content=buf.getvalue(), filename=f"acd_{dataset}.csv")


# --------------------------------------------------------------------- #
# Publications — grid + detail panel + export
# --------------------------------------------------------------------- #
@callback(
    Output("pubs-grid", "rowData"),
    Input("global-filters", "data"),
)
def filter_pubs_grid(gf: dict):
    """Reactive publications grid — applies global filters."""
    pubs = data.load_publications().copy()
    keep_cols = [
        "acd_name", "Year", "title", "type",
        "fwci", "citations", "doi", "is_derm_relevant",
    ]
    for c in keep_cols:
        if c not in pubs.columns:
            pubs[c] = None
    pubs = pubs[keep_cols]
    if gf:
        names = get_filtered_names(gf)
        if names is not None and "acd_name" in pubs.columns:
            pubs = pubs[pubs["acd_name"].isin(names)]
        pubs = apply_pub_filters(pubs, gf)
    return pubs.fillna("").to_dict("records")


@callback(
    Output("pubs-kpi-row", "children"),
    Input("pubs-grid", "rowData"),
)
def update_pubs_kpi(row_data):
    return build_pubs_kpi(row_data or [])


@callback(
    Output("pub-detail-panel", "children"),
    Input("pubs-grid", "selectedRows"),
    prevent_initial_call=True,
)
def pub_row_selected(selected):
    if not selected:
        return no_update
    row = selected[0]
    return build_pub_detail(row)


@callback(
    Output("pubs-download", "data"),
    Input("pubs-export-btn", "n_clicks"),
    State("pubs-grid", "rowData"),
    prevent_initial_call=True,
)
def export_pubs_csv(n_clicks, row_data):
    if not n_clicks or not row_data:
        return no_update
    df = pd.DataFrame(row_data)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return dict(content=buf.getvalue(), filename="acd_publications.csv")


# --------------------------------------------------------------------- #
# Download bundle (header button)
# --------------------------------------------------------------------- #
@callback(
    Output("download-data", "data"),
    Input("download-data-btn", "n_clicks"),
    prevent_initial_call=True,
)
def download_bundle(n_clicks):
    if not n_clicks:
        return no_update
    authors = data.load_authors()
    if authors.empty:
        return no_update
    buf = io.StringIO()
    authors.to_csv(buf, index=False)
    return dict(content=buf.getvalue(), filename="acd_authors_roster.csv")


# --------------------------------------------------------------------- #
# Funding — reactive charts, KPIs, grid, export
# --------------------------------------------------------------------- #
def _filtered_funding(gf: dict) -> pd.DataFrame:
    df = data.load_funding().copy()
    if not gf or df.empty:
        return df
    names = get_filtered_names(gf)
    if names is not None and "acd_name" in df.columns:
        df = df[df["acd_name"].isin(names)]
    return df


@callback(
    Output("funding-kpi-row", "children"),
    Input("global-filters", "data"),
)
def update_funding_kpi(gf: dict):
    return build_funding_kpi(_filtered_funding(gf))


@callback(
    Output("funding-funders-bar", "figure"),
    Input("global-filters", "data"),
)
def update_funding_bar(gf: dict):
    return build_funders_bar(_filtered_funding(gf))


@callback(
    Output("funding-treemap", "figure"),
    Input("global-filters", "data"),
)
def update_funding_treemap(gf: dict):
    return build_grants_treemap(_filtered_summary(gf))


@callback(
    Output("funding-grid", "rowData"),
    Input("global-filters", "data"),
)
def update_funding_grid(gf: dict):
    df = _filtered_funding(gf)
    cols = [c for c in ("acd_name", "funder_name", "award_id", "award_name",
                         "funder_ror") if c in df.columns]
    return df[cols].fillna("").to_dict("records") if not df.empty else []


@callback(
    Output("funding-download", "data"),
    Input("funding-export-btn", "n_clicks"),
    State("global-filters", "data"),
    prevent_initial_call=True,
)
def export_funding_csv(n_clicks, gf):
    if not n_clicks:
        return no_update
    df = _filtered_funding(gf)
    if df.empty:
        return no_update
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return dict(content=buf.getvalue(), filename="acd_funding.csv")


# --------------------------------------------------------------------- #
# Impact — reactive charts, KPIs, export
# --------------------------------------------------------------------- #
def _filtered_summary(gf: dict) -> pd.DataFrame:
    """Return author_summary_stats filtered by global author-level filters."""
    df = data.load_summary().copy()
    if not gf or df.empty:
        return df
    names = get_filtered_names(gf)
    if names is not None and "acd_name" in df.columns:
        df = df[df["acd_name"].isin(names)]
    return df


@callback(
    Output("impact-kpi-row", "children"),
    Input("global-filters", "data"),
)
def update_impact_kpi(gf: dict):
    return build_impact_kpi(_filtered_summary(gf))


@callback(
    Output("impact-h-hist", "figure"),
    Input("global-filters", "data"),
)
def update_impact_h_hist(gf: dict):
    return build_h_index_hist(_filtered_summary(gf))


@callback(
    Output("impact-fwci-box", "figure"),
    Input("global-filters", "data"),
)
def update_impact_fwci(gf: dict):
    return build_fwci_boxplot(_filtered_summary(gf))


@callback(
    Output("impact-scatter", "figure"),
    Input("global-filters", "data"),
)
def update_impact_scatter(gf: dict):
    return build_scatter(_filtered_summary(gf))


@callback(
    Output("impact-top10", "children"),
    Input("global-filters", "data"),
)
def update_impact_top10(gf: dict):
    return build_top_performers(_filtered_summary(gf))


@callback(
    Output("impact-download", "data"),
    Input("impact-export-btn", "n_clicks"),
    State("global-filters", "data"),
    prevent_initial_call=True,
)
def export_impact_csv(n_clicks, gf):
    if not n_clicks:
        return no_update
    df = _filtered_summary(gf)
    if df.empty:
        return no_update
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return dict(content=buf.getvalue(), filename="acd_impact_summary.csv")


# --------------------------------------------------------------------- #
# Trials — reactive charts, KPIs, grid, export
# --------------------------------------------------------------------- #
def _filtered_trials(gf: dict) -> pd.DataFrame:
    df = data.load_clinical_trials().copy()
    if not gf or df.empty:
        return df
    names = get_filtered_names(gf)
    if names is not None and "acd_name" in df.columns:
        df = df[df["acd_name"].isin(names)]
    return df


@callback(
    Output("trials-kpi-row", "children"),
    Input("global-filters", "data"),
)
def update_trials_kpi(gf: dict):
    return build_trials_kpi(_filtered_trials(gf))


@callback(
    Output("trials-status-chart", "figure"),
    Input("global-filters", "data"),
)
def update_trials_status(gf: dict):
    return build_status_chart(_filtered_trials(gf))


@callback(
    Output("trials-year-chart", "figure"),
    Input("global-filters", "data"),
)
def update_trials_year(gf: dict):
    return build_year_chart(_filtered_trials(gf))


@callback(
    Output("trials-investigator-wrap", "children"),
    Input("global-filters", "data"),
)
def update_trials_investigator(gf: dict):
    fig = build_investigator_chart(_filtered_trials(gf))
    if fig.data:
        return html.Div(
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
            className="section-card", style={"marginBottom": "1.5rem"},
        )
    return None


@callback(
    Output("trials-grid", "rowData"),
    Input("global-filters", "data"),
)
def update_trials_grid(gf: dict):
    df = _filtered_trials(gf)
    if df.empty:
        return []
    grid_cols = [c for c in ("acd_name", "title", "trial_id", "registry",
                              "status", "phase", "start_date", "condition",
                              "intervention", "url")
                 if c in df.columns]
    return df[grid_cols].fillna("").to_dict("records")


@callback(
    Output("trials-download", "data"),
    Input("trials-export-btn", "n_clicks"),
    State("global-filters", "data"),
    prevent_initial_call=True,
)
def export_trials_csv(n_clicks, gf):
    if not n_clicks:
        return no_update
    df = _filtered_trials(gf)
    if df.empty:
        return no_update
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return dict(content=buf.getvalue(), filename="acd_clinical_trials.csv")


# --------------------------------------------------------------------- #
# Benchmarking — reactive charts + member comparison + export
# --------------------------------------------------------------------- #
@callback(
    Output("bench-ridge-chart", "figure"),
    Input("global-filters", "data"),
)
def update_bench_ridge(gf: dict):
    return build_ridge_chart(_filtered_summary(gf))


@callback(
    Output("bench-quantile-chart", "figure"),
    Input("global-filters", "data"),
)
def update_bench_quantile(gf: dict):
    return build_quantile_bars(_filtered_summary(gf))


@callback(
    Output("bench-comparison-result", "children"),
    Input("bench-compare-btn", "n_clicks"),
    State("bench-member-a", "value"),
    State("bench-member-b", "value"),
    prevent_initial_call=True,
)
def compare_members(n_clicks, member_a, member_b):
    import dash_mantine_components as dmc
    if not n_clicks or not member_a or not member_b:
        return no_update
    summary = data.load_summary()
    if summary.empty:
        return html.Div("No data available.")
    name_col = next((c for c in ("acd_name", "rams_name") if c in summary.columns), None)
    if name_col is None:
        return html.Div("Name column not found.")
    row_a = summary[summary[name_col] == member_a]
    row_b = summary[summary[name_col] == member_b]
    if row_a.empty or row_b.empty:
        return dmc.Alert("One or both members not found in summary data.",
                         color="yellow", variant="light")
    ra = row_a.iloc[0]
    rb = row_b.iloc[0]
    metrics = [
        ("Publications", "pub_count"),
        ("Citations", "citation_count"),
        ("h-index", "h_index"),
        ("Mean FWCI", "fwci_mean"),
        ("OA rate", "oa_rate"),
        ("Grants", "grants_count"),
        ("Derm pubs", "derm_pub_count"),
        ("Clinical trials", "trial_count"),
    ]
    rows = []
    for label, col in metrics:
        va = ra.get(col)
        vb = rb.get(col)
        def fmt(v, c):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return "-"
            if c == "fwci_mean":
                return f"{float(v):.2f}"
            if c == "oa_rate":
                fv = float(v)
                return f"{fv*100:.0f}%" if fv <= 1 else f"{fv:.0f}%"
            return f"{int(v):,}"
        rows.append(html.Tr([
            html.Td(label, style={"fontWeight": 500}),
            html.Td(fmt(va, col), style={"textAlign": "right"}),
            html.Td(fmt(vb, col), style={"textAlign": "right"}),
        ]))
    table = html.Table([
        html.Thead(html.Tr([
            html.Th("Metric"),
            html.Th(member_a, style={"textAlign": "right"}),
            html.Th(member_b, style={"textAlign": "right"}),
        ])),
        html.Tbody(rows),
    ], style={"width": "100%", "borderCollapse": "collapse", "fontSize": "0.85rem"})
    return html.Div([
        dmc.Text(f"Comparing {member_a} vs {member_b}", fw=600, size="sm", mb="xs"),
        table,
    ])


@callback(
    Output("bench-download", "data"),
    Input("bench-export-btn", "n_clicks"),
    State("global-filters", "data"),
    prevent_initial_call=True,
)
def export_bench_csv(n_clicks, gf):
    if not n_clicks:
        return no_update
    df = _filtered_summary(gf)
    if df.empty:
        return no_update
    name_col = next((c for c in ("acd_name", "rams_name") if c in df.columns), None)
    pctile_cols = [c for c in df.columns if c.endswith("_pctile")]
    keep = ([name_col] if name_col else []) + pctile_cols
    buf = io.StringIO()
    df[keep].to_csv(buf, index=False)
    return dict(content=buf.getvalue(), filename="acd_benchmarking.csv")


# --------------------------------------------------------------------- #
# Heatmap — reactive charts + export
# --------------------------------------------------------------------- #
@callback(
    Output("heatmap-topic-chart", "figure"),
    Input("global-filters", "data"),
)
def update_heatmap_topic(gf: dict):
    names = get_filtered_names(gf) if gf else None
    return build_topic_heatmap(names)


@callback(
    Output("heatmap-state-chart", "figure"),
    Input("global-filters", "data"),
)
def update_heatmap_state(gf: dict):
    names = get_filtered_names(gf) if gf else None
    return build_state_topic_heatmap(names)


@callback(
    Output("heatmap-download", "data"),
    Input("heatmap-export-btn", "n_clicks"),
    State("global-filters", "data"),
    prevent_initial_call=True,
)
def export_heatmap_csv(n_clicks, gf):
    if not n_clicks:
        return no_update
    ROOT = Path(__file__).resolve().parent.parent
    pub_path = ROOT / "data" / "processed" / "publications_clean.csv"
    if not pub_path.exists():
        pub_path = ROOT / "data" / "processed" / "publications.csv"
    if not pub_path.exists():
        return no_update
    try:
        topic_df = pd.read_csv(pub_path, low_memory=False)
    except Exception:
        return no_update
    # Detect columns
    author_col = next((c for c in ("acd_name", "RAMS_Author") if c in topic_df.columns), None)
    year_col = next((c for c in ("Year", "Publication_Year", "year") if c in topic_df.columns), None)
    topic_col = next((c for c in ("SubTopic", "topic", "sub_topic") if c in topic_df.columns), None)
    if not author_col or not topic_col:
        return no_update
    keep = [c for c in (author_col, year_col, topic_col) if c]
    topic_df = topic_df[keep]
    accepted = data._accepted_name_set()
    if accepted and author_col:
        topic_df = topic_df[topic_df[author_col].isin(accepted)]
    names = get_filtered_names(gf) if gf else None
    if names is not None and author_col:
        topic_df = topic_df[topic_df[author_col].isin(names)]
    topic_df = topic_df.rename(columns={author_col: "member",
                                         year_col: "year",
                                         topic_col: "topic"} if year_col else
                                        {author_col: "member", topic_col: "topic"})
    buf = io.StringIO()
    topic_df.to_csv(buf, index=False)
    return dict(content=buf.getvalue(), filename="acd_topic_heatmap_data.csv")


# --------------------------------------------------------------------- #
# Collaboration — node click detail panel + export
# --------------------------------------------------------------------- #
@callback(
    Output("collab-detail-panel", "children"),
    Input("coauth-graph", "tapNodeData"),
    prevent_initial_call=True,
)
def collab_node_click(node_data):
    if not node_data:
        return no_update
    name = node_data.get("label") or node_data.get("id")
    if not name:
        return no_update
    return build_collab_detail(name)


@callback(
    Output("collab-download", "data"),
    Input("collab-export-btn", "n_clicks"),
    prevent_initial_call=True,
)
def export_collab_csv(n_clicks):
    if not n_clicks:
        return no_update
    from .pages.collaboration import _build_coauthorship
    _nodes, edges, _stats = _build_coauthorship()
    if not edges:
        return no_update
    rows = [{"member_a": e["data"]["source"], "member_b": e["data"]["target"],
             "shared_works": e["data"]["weight"]} for e in edges]
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return dict(content=buf.getvalue(), filename="acd_collaboration_edges.csv")


# --------------------------------------------------------------------- #
# Overview — reactive charts and KPIs (driven by global filters)
# --------------------------------------------------------------------- #
def _filtered_authors(gf: dict) -> pd.DataFrame:
    """Return authors filtered by global author-level filters."""
    df = data.load_authors().copy()
    if not gf or df.empty:
        return df
    names = get_filtered_names(gf)
    if names is not None and "acd_name" in df.columns:
        df = df[df["acd_name"].isin(names)]
    return df


def _filtered_pubs(gf: dict) -> pd.DataFrame:
    """Return publications filtered by global author-level filters."""
    df = data.load_publications().copy()
    if not gf or df.empty:
        return df
    names = get_filtered_names(gf)
    if names is not None and "acd_name" in df.columns:
        df = df[df["acd_name"].isin(names)]
    return df


def _filtered_cohort_summary(gf: dict) -> dict:
    """Compute cohort_summary dict from filtered data (ACD keys)."""
    authors = _filtered_authors(gf)
    summary = _filtered_summary(gf)
    pubs = _filtered_pubs(gf)
    funding = _filtered_funding(gf)
    trials = _filtered_trials(gf)

    # Resolved / high-confidence members
    if "accepted" in authors.columns and (authors["accepted"].astype(str) == "1").any():
        high = authors[authors["accepted"].astype(str) == "1"]
    elif "confidence" in authors.columns:
        high = authors[authors["confidence"] == "HIGH"]
    else:
        high = authors

    n_total = len(authors)
    n_high = len(high)
    n_pubs = len(pubs)
    n_derm_pubs = (
        int(pubs["is_derm_relevant"].sum())
        if "is_derm_relevant" in pubs.columns else 0
    )
    total_citations = (
        int(summary["citation_count"].sum(skipna=True))
        if "citation_count" in summary.columns else 0
    )
    n_funded = (
        int(summary["grants_count"].sum(skipna=True))
        if "grants_count" in summary.columns else len(funding)
    )
    n_trials = len(trials)

    return {
        "n_total": n_total,
        "n_high": n_high,
        "n_pubs": n_pubs,
        "n_derm_pubs": n_derm_pubs,
        "total_citations": total_citations,
        "n_funded": n_funded,
        "n_trials": n_trials,
    }


@callback(
    Output("overview-kpi-row", "children"),
    Input("global-filters", "data"),
)
def update_overview_kpis(gf: dict):
    return build_overview_kpis(_filtered_cohort_summary(gf))


@callback(
    Output("overview-pub-trend", "figure"),
    Input("global-filters", "data"),
)
def update_overview_pub_trend(gf: dict):
    return build_publications_trend(_filtered_pubs(gf))


@callback(
    Output("overview-state-chart", "figure"),
    Input("global-filters", "data"),
)
def update_overview_state(gf: dict):
    return build_state_chart(_filtered_authors(gf))


@callback(
    Output("overview-inst-chart", "figure"),
    Input("global-filters", "data"),
)
def update_overview_inst(gf: dict):
    return build_top_inst_chart(_filtered_authors(gf))


# --------------------------------------------------------------------- #
# AI Chat — floating widget
# --------------------------------------------------------------------- #
@callback(
    Output("ai-chat-panel", "style"),
    Output("ai-panel-open", "data"),
    Input("ai-fab", "n_clicks"),
    Input("ai-close-btn", "n_clicks"),
    State("ai-panel-open", "data"),
    prevent_initial_call=True,
)
def toggle_chat_panel(fab_clicks, close_clicks, is_open):
    from dash import ctx
    triggered = ctx.triggered_id
    if triggered == "ai-fab":
        new_open = not is_open
    elif triggered == "ai-close-btn":
        new_open = False
    else:
        new_open = is_open
    panel_style = {
        "position": "fixed", "bottom": "5.5rem", "right": "1.5rem",
        "width": "380px", "maxHeight": "520px",
        "display": "flex" if new_open else "none",
        "flexDirection": "column",
        "background": "#fff",
        "borderRadius": "1rem",
        "boxShadow": "0 8px 32px rgba(0,0,0,0.18)",
        "zIndex": 1200,
        "overflow": "hidden",
    }
    return panel_style, new_open


@callback(
    Output("ai-chat-messages", "children"),
    Output("ai-chat-history", "data"),
    Output("ai-chat-input", "value"),
    Input("ai-send-btn", "n_clicks"),
    Input("ai-ex-0", "n_clicks"),
    Input("ai-ex-1", "n_clicks"),
    Input("ai-ex-2", "n_clicks"),
    Input("ai-ex-3", "n_clicks"),
    Input("ai-ex-4", "n_clicks"),
    State("ai-chat-input", "value"),
    State("ai-chat-messages", "children"),
    State("ai-chat-history", "data"),
    prevent_initial_call=True,
)
def handle_chat(send_clicks, ex0, ex1, ex2, ex3, ex4,
                user_input, current_messages, history):
    from dash import ctx
    from .pages.chatbot import EXAMPLE_QUESTIONS
    from .ai_tools import chat as ai_chat

    triggered = ctx.triggered_id
    if triggered and triggered.startswith("ai-ex-"):
        idx = int(triggered.split("-")[-1])
        if idx < len(EXAMPLE_QUESTIONS):
            user_input = EXAMPLE_QUESTIONS[idx]

    if not user_input or not user_input.strip():
        return no_update, no_update, no_update

    user_msg = user_input.strip()
    history = history or []

    # Build updated messages list
    messages = list(current_messages or [])
    messages.append(build_user_bubble(user_msg))

    # Get AI response
    try:
        reply = ai_chat(user_msg, history)
    except Exception as exc:
        logger.exception("AI chat error")
        reply = f"Sorry, I encountered an error: {exc}"

    messages.append(build_assistant_bubble(reply))
    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": reply})

    return messages, history, ""


# --------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------- #
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
