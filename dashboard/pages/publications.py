"""Publications tab — filterable AG Grid + DOI click-out + detail panel.

Supports global filters, summary KPI tiles, publication detail panel
on row selection, and per-view CSV export.
"""
from __future__ import annotations

import pandas as pd
import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from .. import data, theme

PAGE_TITLE = "Publications"
PAGE_HREF  = "/publications"


def render() -> html.Div:
    pubs = data.load_publications().copy()

    keep_cols = [
        "acd_name", "Year", "title", "type",
        "fwci", "citations", "doi", "is_derm_relevant",
    ]
    for c in keep_cols:
        if c not in pubs.columns:
            pubs[c] = None
    pubs = pubs[keep_cols]

    col_defs = [
        {"field": "acd_name", "headerName": "Member", "pinned": "left",
         "minWidth": 180, "filter": "agTextColumnFilter"},
        {"field": "Year", "headerName": "Year", "maxWidth": 90,
         "type": "numericColumn", "sort": "desc"},
        {"field": "title", "headerName": "Title", "minWidth": 420,
         "tooltipField": "title", "filter": "agTextColumnFilter",
         "wrapText": True, "autoHeight": True},
        {"field": "type", "headerName": "Type", "maxWidth": 140,
         "filter": "agTextColumnFilter"},
        {"field": "fwci", "headerName": "FWCI", "maxWidth": 100,
         "type": "numericColumn",
         "headerTooltip": "Field-Weighted Citation Impact: >1.0 = above world average",
         "valueFormatter": {"function": "params.value && params.value.toFixed(2)"}},
        {"field": "citations", "headerName": "Citations", "maxWidth": 110,
         "type": "numericColumn",
         "valueFormatter": {"function": "params.value && d3.format(',')(params.value)"}},
        {"field": "is_derm_relevant", "headerName": "Derm",
         "maxWidth": 100, "filter": "agTextColumnFilter",
         "headerTooltip": "Flagged as dermatology-relevant by keyword/MeSH classifier",
         "cellStyle": {
             "styleConditions": [
                 {"condition": "params.value === true || params.value === 'True'",
                  "style": {"color": "#10B981", "fontWeight": 600}},
             ]
         }},
        {"field": "doi", "headerName": "DOI", "minWidth": 220,
         "cellRenderer": "markdown",
         "valueFormatter": {"function":
             "params.value ? '[' + params.value + '](https://doi.org/' + params.value + ')' : ''"}},
    ]

    grid = dag.AgGrid(
        id="pubs-grid",
        rowData=pubs.fillna("").to_dict("records"),
        columnDefs=col_defs,
        defaultColDef={"sortable": True, "filter": True, "floatingFilter": True,
                       "resizable": True},
        dashGridOptions={
            "pagination": True, "paginationPageSize": 50,
            "animateRows": True, "rowHeight": 50,
            "rowSelection": "single",
            "suppressCellFocus": True,
        },
        className="ag-theme-alpine",
        style={"height": "720px", "width": "100%"},
        dangerously_allow_code=True,
    )

    kpi_row = html.Div(id="pubs-kpi-row", style={"marginBottom": "1rem"})

    header = dmc.Group([
        dmc.Stack([
            dmc.Text("Publications", fw=700, size="xl"),
            dmc.Text(
                "Search, filter and explore publications. Click a row to see "
                "details. Use DOI links to access the full text.",
                size="sm", c="dimmed",
            ),
        ], gap=2),
        dmc.Group([
            dmc.Button(
                "Export filtered",
                id="pubs-export-btn",
                leftSection=DashIconify(icon="tabler:download", width=16),
                variant="light",
                color="acd-copper",
                size="xs",
            ),
        ]),
    ], justify="space-between", mb="md")

    detail_panel = html.Div(id="pub-detail-panel", style={"marginTop": "1rem"})

    return html.Div([
        header,
        kpi_row,
        html.Div(grid, className="section-card", style={"padding": "0.5rem"}),
        detail_panel,
        dcc.Download(id="pubs-download"),
    ])


def build_pubs_kpi(row_data: list[dict]) -> dmc.SimpleGrid:
    """Build reactive KPI tiles from the current (possibly filtered) grid data."""
    df = pd.DataFrame(row_data) if row_data else pd.DataFrame()
    total_pubs = len(df)
    total_citations = int(
        pd.to_numeric(df.get("citations", pd.Series()), errors="coerce").sum()
    ) if total_pubs else 0
    derm_count = 0
    if "is_derm_relevant" in df.columns and total_pubs:
        derm_count = int(df["is_derm_relevant"].apply(
            lambda x: 1 if x is True or str(x).strip().lower() in ("true", "1") else 0
        ).sum())
    derm_pct = round(100 * derm_count / total_pubs, 1) if total_pubs else 0
    fwci_vals = pd.to_numeric(df.get("fwci", pd.Series()), errors="coerce")
    mean_fwci = round(float(fwci_vals.mean()), 2) if fwci_vals.notna().any() else 0

    return dmc.SimpleGrid(
        cols={"base": 2, "sm": 4},
        spacing="sm",
        children=[
            dmc.Card([
                dmc.Text("Total publications", size="xs", c="dimmed", tt="uppercase"),
                dmc.Text(f"{total_pubs:,}", size="xl", fw=700),
            ]),
            dmc.Card([
                dmc.Text("Total citations", size="xs", c="dimmed", tt="uppercase"),
                dmc.Text(f"{total_citations:,}", size="xl", fw=700),
            ]),
            dmc.Card([
                dmc.Text("Derm-relevant", size="xs", c="dimmed", tt="uppercase"),
                dmc.Text(f"{derm_count:,} ({derm_pct}%)", size="xl", fw=700),
            ]),
            dmc.Card([
                dmc.Text("Mean FWCI", size="xs", c="dimmed", tt="uppercase"),
                dmc.Text(f"{mean_fwci}", size="xl", fw=700),
            ]),
        ],
    )


def build_pub_detail(row: dict) -> html.Div:
    """Build a detail card for a selected publication."""
    title    = row.get("title", "Untitled")
    doi      = row.get("doi", "")
    year     = row.get("Year", "")
    pub_type = row.get("type", "")
    fwci     = row.get("fwci", "")
    citations = row.get("citations", "")
    member   = row.get("acd_name", "")
    derm     = row.get("is_derm_relevant", False)

    doi_link = None
    if doi:
        doi_link = dmc.Anchor(doi, href=f"https://doi.org/{doi}",
                              target="_blank", size="sm")

    derm_badge = dmc.Badge(
        "Derm-relevant" if derm else "Not flagged",
        color="green" if derm else "gray",
        variant="light", size="sm",
    )

    return dmc.Card([
        dmc.Group([
            dmc.Text("Publication Detail", fw=600, size="md"),
            derm_badge,
        ], justify="space-between"),
        dmc.Text(title, fw=500, size="sm", mt="xs", style={"lineHeight": 1.4}),
        dmc.SimpleGrid(
            cols={"base": 2, "sm": 4},
            spacing="xs", mt="sm",
            children=[
                dmc.Stack([dmc.Text("Member", size="xs", c="dimmed"),
                           dmc.Text(str(member), size="sm", fw=500)], gap=2),
                dmc.Stack([dmc.Text("Year", size="xs", c="dimmed"),
                           dmc.Text(str(year), size="sm", fw=500)], gap=2),
                dmc.Stack([dmc.Text("Type", size="xs", c="dimmed"),
                           dmc.Text(str(pub_type), size="sm", fw=500)], gap=2),
                dmc.Stack([dmc.Text("FWCI", size="xs", c="dimmed"),
                           dmc.Text(str(fwci) if fwci else "N/A", size="sm", fw=500)], gap=2),
            ],
        ),
        dmc.Group([
            dmc.Stack([dmc.Text("Citations", size="xs", c="dimmed"),
                       dmc.Text(str(citations), size="sm", fw=500)], gap=2),
            dmc.Stack([dmc.Text("DOI", size="xs", c="dimmed"),
                       doi_link or dmc.Text("N/A", size="sm")], gap=2),
        ], gap="xl", mt="sm"),
    ], withBorder=True, mt="md", className="section-card")


layout = render
