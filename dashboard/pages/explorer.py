"""Data Explorer tab — raw CSV drill-down with dataset switcher."""
from __future__ import annotations

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from .. import data

PAGE_TITLE = "Data Explorer"
PAGE_HREF  = "/explorer"

DATASETS = [
    {"value": "authors",  "label": "Authors roster"},
    {"value": "summary",  "label": "Per-member statistics"},
    {"value": "pubs",     "label": "Publications"},
    {"value": "funding",  "label": "Funding (awards)"},
    {"value": "trials",   "label": "Clinical trials"},
]


def _grid_for(dataset: str) -> dag.AgGrid:
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
        df = data.load_authors()

    col_defs = [{"field": c, "filter": True} for c in df.columns]
    return dag.AgGrid(
        id={"type": "explorer-grid", "dataset": dataset},
        rowData=df.fillna("").to_dict("records"),
        columnDefs=col_defs,
        defaultColDef={"sortable": True, "filter": True, "resizable": True,
                       "floatingFilter": True},
        dashGridOptions={"pagination": True, "paginationPageSize": 50,
                         "animateRows": False, "rowHeight": 36},
        className="ag-theme-alpine",
        style={"height": "720px", "width": "100%"},
    )


def render() -> html.Div:
    header = dmc.Group([
        dmc.Stack([
            dmc.Text("Data Explorer", fw=700, size="xl"),
            dmc.Text(
                "Raw CSV view with column filters, sort, and pagination "
                "for analysts who want the primary source.",
                size="sm", c="dimmed",
            ),
        ], gap=2),
        dmc.Button(
            "Export current view",
            id="explorer-export-btn",
            leftSection=DashIconify(icon="tabler:download", width=16),
            variant="light",
            color="acd-copper",
            size="xs",
        ),
    ], justify="space-between", mb="md")

    controls = dmc.Group([
        dmc.SegmentedControl(
            id="explorer-dataset",
            data=DATASETS, value="authors", size="sm",
        ),
    ], mb="md")

    return html.Div([
        header,
        controls,
        html.Div(
            id="explorer-body",
            children=html.Div(
                _grid_for("authors"),
                className="section-card",
                style={"padding": "0.5rem"},
            ),
        ),
        dcc.Download(id="explorer-download"),
    ])


layout = render
