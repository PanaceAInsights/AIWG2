"""Expert Finder page — search for researchers by topic/expertise area.

Lets users type a research area (e.g. "melanoma", "psoriasis",
"eczema") and returns ACD members ranked by publication volume in
that topic. Built on the publications + summary data.
"""
from __future__ import annotations

from pathlib import Path

import dash_ag_grid as dag
import dash_mantine_components as dmc
import pandas as pd
from dash import dcc, html
from dash_iconify import DashIconify

from .. import data, theme

PAGE_TITLE = "Expert Finder"
PAGE_HREF  = "/experts"

_ROOT      = Path(__file__).resolve().parents[2]
_PROCESSED = _ROOT / "data" / "processed"


def _build_expertise_index() -> pd.DataFrame:
    """Pre-compute a member x topic matrix from publications."""
    for fname in ("publications_clean.csv", "publications.csv"):
        p = _PROCESSED / fname
        if p.exists():
            break
    else:
        return pd.DataFrame()

    import csv
    with open(p, newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))

    author_col = next((c for c in ("acd_name", "RAMS_Author") if c in header), None)
    topic_col  = next((c for c in ("SubTopic", "Topic_Field") if c in header), None)
    cit_col    = next((c for c in ("citations", "Citations") if c in header), None)
    if author_col is None or topic_col is None:
        return pd.DataFrame()

    usecols = [c for c in [author_col, topic_col, cit_col] if c]
    pubs = pd.read_csv(p, usecols=usecols, low_memory=False)

    accepted = data._accepted_name_set()
    if accepted:
        pubs = pubs[pubs[author_col].isin(accepted)]

    pubs[topic_col] = pubs[topic_col].fillna("Other")
    if cit_col:
        pubs[cit_col] = pd.to_numeric(pubs[cit_col], errors="coerce").fillna(0)
    else:
        pubs["_cit"] = 0
        cit_col = "_cit"

    idx = (
        pubs.groupby([author_col, topic_col])
        .agg(pub_count=(topic_col, "size"), citation_sum=(cit_col, "sum"))
        .reset_index()
        .rename(columns={author_col: "acd_name", topic_col: "topic"})
    )
    return idx


def _get_all_topics() -> list[str]:
    idx = _build_expertise_index()
    if idx.empty:
        return []
    topics = sorted(idx["topic"].unique().tolist())
    if "Other" in topics:
        topics.remove("Other")
        topics.append("Other")
    return topics


def render() -> html.Div:
    topics = _get_all_topics()
    topic_options = [{"label": t, "value": t} for t in topics]

    return html.Div([
        dmc.Title("Expert Finder", order=2, mb="md"),
        dmc.Text(
            "Find ACD members with the highest research output in a "
            "specific topic area. Select a research topic or type a keyword "
            "to search.",
            size="sm", c="dimmed", mb="lg",
        ),
        dmc.Grid([
            dmc.GridCol(
                dmc.Select(
                    id="expert-topic-select",
                    label="Select research topic",
                    placeholder="Choose a topic area...",
                    data=topic_options,
                    searchable=True,
                    clearable=True,
                    size="md",
                ),
                span={"base": 12, "md": 5},
            ),
            dmc.GridCol(
                dmc.TextInput(
                    id="expert-keyword-search",
                    label="Or search by keyword",
                    placeholder="e.g. melanoma, psoriasis, eczema...",
                    size="md",
                ),
                span={"base": 12, "md": 5},
            ),
            dmc.GridCol(
                dmc.Group([
                    dmc.Button("Search", id="expert-search-btn",
                               color="acd-copper", size="md",
                               style={"marginTop": "25px"}),
                    dmc.Button("Export", id="expert-export-btn",
                               leftSection=DashIconify(icon="tabler:download", width=16),
                               variant="light", color="acd-copper", size="md",
                               style={"marginTop": "25px"}),
                ], gap="xs"),
                span={"base": 12, "md": 2},
            ),
        ], gutter="lg", mb="lg"),
        html.Div(id="expert-results", children=_empty_results()),
        dcc.Download(id="expert-download"),
    ])


def _empty_results() -> html.Div:
    return html.Div(
        dmc.Alert(
            "Select a research topic from the dropdown or enter a keyword to "
            "find members with expertise in that area.",
            title="Search for experts",
            color="gray",
            variant="light",
        ),
        style={"marginTop": "1rem"},
    )


def build_expert_results(topic: str | None, keyword: str | None) -> html.Div:
    """Called by callback when user searches for experts."""
    idx     = _build_expertise_index()
    summary = data.load_summary()
    authors = data.load_authors()

    if idx.empty:
        return _empty_results()

    if topic and topic.strip():
        results = idx[idx["topic"] == topic].copy()
        search_label = f"Topic: {topic}"

    elif keyword and keyword.strip():
        kw = keyword.strip().lower()
        matching_topics = idx[idx["topic"].str.lower().str.contains(kw, na=False)]

        # Also search publication titles
        title_matches = pd.DataFrame()
        for fname in ("publications_clean.csv", "publications.csv"):
            p = _PROCESSED / fname
            if p.exists():
                import csv
                with open(p, newline="", encoding="utf-8") as f:
                    hdr = next(csv.reader(f))
                author_col = next((c for c in ("acd_name", "RAMS_Author") if c in hdr), None)
                title_col  = next((c for c in ("title", "Title") if c in hdr), None)
                cit_col    = next((c for c in ("citations", "Citations") if c in hdr), None)
                if author_col and title_col:
                    usecols = [c for c in [author_col, title_col, cit_col] if c]
                    pubs = pd.read_csv(p, usecols=usecols, low_memory=False)
                    accepted = data._accepted_name_set()
                    if accepted:
                        pubs = pubs[pubs[author_col].isin(accepted)]
                    hits = pubs[pubs[title_col].str.lower().str.contains(kw, na=False)]
                    if not hits.empty:
                        cit_col2 = cit_col or title_col
                        title_matches = (
                            hits.groupby(author_col)
                            .agg(pub_count=(title_col, "size"),
                                 citation_sum=(cit_col2, lambda x:
                                     pd.to_numeric(x, errors="coerce").sum()))
                            .reset_index()
                            .rename(columns={author_col: "acd_name"})
                        )
                        title_matches["topic"] = f"Title match: '{keyword}'"
                break

        results = pd.concat([matching_topics, title_matches], ignore_index=True)
        if results.empty:
            return html.Div(dmc.Alert(
                f"No experts found for keyword '{keyword}'. Try a broader term.",
                title="No results", color="yellow", variant="light",
            ))
        results = (
            results.groupby("acd_name")
            .agg(pub_count=("pub_count", "sum"), citation_sum=("citation_sum", "sum"))
            .reset_index()
        )
        results["topic"] = keyword
        search_label = f"Keyword: {keyword}"
    else:
        return _empty_results()

    if results.empty:
        return html.Div(dmc.Alert(
            "No experts found for this search. Try a different topic.",
            title="No results", color="yellow", variant="light",
        ))

    results = results.sort_values("pub_count", ascending=False).head(25)

    name_col = next((c for c in ("acd_name", "rams_name") if c in authors.columns), None)
    if name_col and not authors.empty:
        member_info = authors[[name_col, "last_known_institution",
                               "institution_country", "state"]].drop_duplicates(name_col)
        member_info = member_info.rename(columns={name_col: "acd_name"})
        results = results.merge(member_info, on="acd_name", how="left")

    if not summary.empty:
        sname = next((c for c in ("acd_name", "rams_name") if c in summary.columns), None)
        if sname:
            stats_cols = [sname, "h_index", "fwci_mean"]
            available = [c for c in stats_cols if c in summary.columns]
            if available:
                s = summary[available].rename(columns={sname: "acd_name"})
                results = results.merge(s, on="acd_name", how="left")

    col_defs = [
        {"field": "acd_name", "headerName": "Member", "minWidth": 200, "pinned": "left"},
        {"field": "pub_count", "headerName": "Pubs in topic", "maxWidth": 140,
         "type": "numericColumn", "sort": "desc"},
        {"field": "citation_sum", "headerName": "Citations", "maxWidth": 120,
         "type": "numericColumn",
         "valueFormatter": {"function": "d3.format(',')(params.value)"}},
        {"field": "h_index", "headerName": "h-index", "maxWidth": 100,
         "type": "numericColumn"},
        {"field": "fwci_mean", "headerName": "Mean FWCI", "maxWidth": 110,
         "type": "numericColumn",
         "valueFormatter": {"function": "params.value && params.value.toFixed(2)"}},
        {"field": "last_known_institution", "headerName": "Institution", "minWidth": 250},
        {"field": "state", "headerName": "State", "maxWidth": 80},
    ]

    grid = dag.AgGrid(
        rowData=results.fillna("").to_dict("records"),
        columnDefs=col_defs,
        defaultColDef={"resizable": True, "sortable": True},
        dashGridOptions={"animateRows": True, "rowHeight": 42, "suppressCellFocus": True},
        className="ag-theme-alpine",
        style={"height": "500px", "width": "100%"},
    )

    return html.Div([
        dmc.Group([
            dmc.Badge(search_label, color="acd-copper", variant="light", size="lg"),
            dmc.Text(f"{len(results)} experts found", size="sm", c="dimmed"),
        ], gap="md", mb="md"),
        html.Div(grid, className="section-card", style={"padding": "0.5rem"}),
    ])


layout = render
