"""ACD Dashboard — Profiles page (member directory + detail pane)."""
from __future__ import annotations

from dash import html, dcc, callback, Input, Output, State, no_update
import dash_bootstrap_components as dbc
from dash import dash_table
import pandas as pd

from dashboard.theme import (
    COPPER, MAUVE_PURPLE, LIGHT_COPPER, BG_CARD, BORDER_COLOR,
    TEXT_MUTED, WHITE, WARM_CREAM, TIER_HIGH, TIER_REVIEW,
    CARD_STYLE, DARK_PLUM,
)
from dashboard.data import (
    resolved_roster, publications_for_member, trials_for_member,
    funding_for_member, get_all_states,
)

PAGE_TITLE = "Profiles"
PAGE_HREF  = "/profiles"


def _badge(confidence: str) -> html.Span:
    cls = {"HIGH": "badge-high", "REVIEW": "badge-review",
           "LOW": "badge-low", "NOT_FOUND": "badge-notfound"}.get(confidence, "badge-notfound")
    return html.Span(confidence, className=cls, style={"marginLeft": "6px"})


def _flag_chips(flags_str: str) -> list:
    if not flags_str:
        return []
    return [html.Span(f, className=f"flag-chip {f}") for f in flags_str.split("|") if f]


def layout():
    states = ["All"] + get_all_states()
    return html.Div([
        # Filters
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Label("State", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Dropdown(
                        id="profiles-state-filter",
                        options=[{"label": s, "value": s} for s in states],
                        value="All", clearable=False,
                        style={"backgroundColor": BG_CARD, "color": WARM_CREAM},
                    ),
                ], md=3),
                dbc.Col([
                    html.Label("Confidence", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Dropdown(
                        id="profiles-confidence-filter",
                        options=[
                            {"label": "All", "value": "All"},
                            {"label": "HIGH", "value": "HIGH"},
                            {"label": "REVIEW", "value": "REVIEW"},
                            {"label": "NOT_FOUND", "value": "NOT_FOUND"},
                        ],
                        value="All", clearable=False,
                        style={"backgroundColor": BG_CARD, "color": WARM_CREAM},
                    ),
                ], md=3),
                dbc.Col([
                    html.Label("Search", style={"fontSize": "12px", "color": TEXT_MUTED}),
                    dcc.Input(
                        id="profiles-search", type="text",
                        placeholder="Search by name, institution...",
                        debounce=True,
                        style={"width": "100%", "backgroundColor": BG_CARD,
                               "border": f"1px solid {BORDER_COLOR}", "borderRadius": "6px",
                               "color": WARM_CREAM, "padding": "8px 12px"},
                    ),
                ], md=4),
                dbc.Col([
                    html.Div(style={"height": "20px"}),
                    html.Button("Export CSV", id="profiles-export-btn",
                                className="btn-outline-copper",
                                style={"width": "100%", "padding": "8px"}),
                    dcc.Download(id="profiles-download"),
                ], md=2),
            ]),
        ], className="acd-card"),

        # Table
        html.Div([
            html.Div("Dermatologist Directory", className="acd-section-header"),
            html.Div(id="profiles-table-container"),
        ], className="acd-card"),

        # Detail pane
        html.Div(id="profiles-detail-pane"),
    ])


@callback(
    Output("profiles-table-container", "children"),
    Input("profiles-state-filter", "value"),
    Input("profiles-confidence-filter", "value"),
    Input("profiles-search", "value"),
)
def update_table(state, confidence, search):
    conf_filter = None if confidence == "All" else [confidence]
    df = resolved_roster(confidence=conf_filter, state=None if state == "All" else state)
    if df.empty:
        return html.Div("No data loaded yet. Run the ETL pipeline first.",
                        style={"color": TEXT_MUTED, "padding": "20px"})

    if search:
        mask = (
            df.get("acd_name", pd.Series(dtype=str)).str.contains(search, case=False, na=False)
            | df.get("last_known_institution", pd.Series(dtype=str)).str.contains(search, case=False, na=False)
            | df.get("openalex_display_name", pd.Series(dtype=str)).str.contains(search, case=False, na=False)
        )
        df = df[mask]

    display_cols = ["acd_name", "state", "confidence", "works_count",
                    "last_known_institution", "ambiguity_flags", "openalex_id"]
    display_cols = [c for c in display_cols if c in df.columns]

    return dash_table.DataTable(
        id="profiles-table",
        data=df[display_cols].to_dict("records"),
        columns=[{"name": c.replace("_", " ").title(), "id": c} for c in display_cols],
        page_size=25,
        sort_action="native",
        filter_action="native",
        row_selectable="single",
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG_CARD, "color": WARM_CREAM,
                    "border": f"1px solid {BORDER_COLOR}", "fontSize": "13px",
                    "padding": "8px 12px", "textAlign": "left"},
        style_header={"backgroundColor": DARK_PLUM, "color": COPPER,
                      "fontWeight": "600", "fontSize": "12px",
                      "textTransform": "uppercase", "letterSpacing": "0.5px"},
        style_data_conditional=[
            {"if": {"filter_query": '{confidence} = "HIGH"', "column_id": "confidence"},
             "color": TIER_HIGH, "fontWeight": "600"},
            {"if": {"filter_query": '{confidence} = "REVIEW"', "column_id": "confidence"},
             "color": TIER_REVIEW, "fontWeight": "600"},
        ],
    )


@callback(
    Output("profiles-detail-pane", "children"),
    Input("profiles-table", "selected_rows"),
    State("profiles-table", "data"),
    prevent_initial_call=True,
)
def show_detail(selected_rows, data):
    if not selected_rows or not data:
        return no_update
    row = data[selected_rows[0]]
    name = row.get("acd_name", "")
    pubs = publications_for_member(name)
    trials = trials_for_member(name)
    funding = funding_for_member(name)

    flags = _flag_chips(str(row.get("ambiguity_flags") or ""))

    return html.Div([
        html.Div([
            html.Div([
                html.H4(name, style={"color": WHITE, "marginBottom": "4px"}),
                _badge(str(row.get("confidence", ""))),
                *flags,
            ], style={"marginBottom": "12px"}),
            dbc.Row([
                dbc.Col([
                    html.Div("State", style={"fontSize": "11px", "color": TEXT_MUTED}),
                    html.Div(row.get("state", "—"), style={"color": WARM_CREAM}),
                ], md=2),
                dbc.Col([
                    html.Div("Institution", style={"fontSize": "11px", "color": TEXT_MUTED}),
                    html.Div(row.get("last_known_institution", "—"), style={"color": WARM_CREAM}),
                ], md=4),
                dbc.Col([
                    html.Div("OpenAlex ID", style={"fontSize": "11px", "color": TEXT_MUTED}),
                    html.A(row.get("openalex_id", "—"),
                           href=f"https://openalex.org/authors/{row.get('openalex_id', '')}",
                           target="_blank",
                           style={"color": LIGHT_COPPER, "textDecoration": "none"}),
                ], md=3),
                dbc.Col([
                    html.Div("Works Count", style={"fontSize": "11px", "color": TEXT_MUTED}),
                    html.Div(str(row.get("works_count", "—")), style={"color": WARM_CREAM}),
                ], md=3),
            ]),
        ], className="acd-card"),

        dbc.Row([
            dbc.Col(html.Div([
                html.Div(f"Publications ({len(pubs)})", className="acd-card-title"),
                html.Div(
                    pubs[["Title", "Year", "CitedByCount"]].head(10).to_dict("records")
                    if not pubs.empty and "Title" in pubs.columns
                    else [{"Title": "No publications found", "Year": "", "CitedByCount": ""}],
                    id="profiles-pubs-list",
                    style={"maxHeight": "250px", "overflowY": "auto"},
                ),
            ], className="acd-card"), md=6),
            dbc.Col([
                html.Div([
                    html.Div(f"Clinical Trials ({len(trials)})", className="acd-card-title"),
                    html.Div(
                        [html.Div(f"• {t.get('title', 'N/A')} ({t.get('status', '')})",
                                  style={"fontSize": "12px", "color": WARM_CREAM, "marginBottom": "4px"})
                         for _, t in trials.head(5).iterrows()] if not trials.empty
                        else [html.Div("No clinical trials found", style={"color": TEXT_MUTED, "fontSize": "12px"})],
                    ),
                ], className="acd-card"),
                html.Div([
                    html.Div(f"Funding Grants ({len(funding)})", className="acd-card-title"),
                    html.Div(
                        [html.Div(f"• {f.get('funder', 'N/A')} — {f.get('title', '')}",
                                  style={"fontSize": "12px", "color": WARM_CREAM, "marginBottom": "4px"})
                         for _, f in funding.head(5).iterrows()] if not funding.empty
                        else [html.Div("No funding records found", style={"color": TEXT_MUTED, "fontSize": "12px"})],
                    ),
                ], className="acd-card"),
            ], md=6),
        ]),

        # Report incorrect match
        html.Div([
            html.Button("⚑ Report Incorrect Match", id="profiles-report-btn",
                        className="btn-outline-copper",
                        style={"fontSize": "12px", "padding": "6px 14px"}),
        ], style={"textAlign": "right", "marginTop": "8px"}),

        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("Report Incorrect Match")),
            dbc.ModalBody([
                html.P(f"Reporting issue for: {name}", style={"color": WARM_CREAM}),
                dcc.Textarea(
                    id="profiles-report-text",
                    placeholder="Describe the issue (e.g. wrong OpenAlex profile matched)...",
                    style={"width": "100%", "minHeight": "100px", "backgroundColor": BG_CARD,
                           "border": f"1px solid {BORDER_COLOR}", "color": WARM_CREAM,
                           "borderRadius": "6px", "padding": "8px"},
                ),
            ]),
            dbc.ModalFooter([
                html.Button("Submit", id="profiles-report-submit", className="btn-copper",
                            style={"padding": "8px 20px"}),
                html.Button("Cancel", id="profiles-report-cancel",
                            className="btn-outline-copper",
                            style={"padding": "8px 20px", "marginLeft": "8px"}),
            ]),
        ], id="profiles-report-modal", is_open=False),
    ])


@callback(
    Output("profiles-report-modal", "is_open"),
    Input("profiles-report-btn", "n_clicks"),
    Input("profiles-report-cancel", "n_clicks"),
    Input("profiles-report-submit", "n_clicks"),
    State("profiles-report-modal", "is_open"),
    prevent_initial_call=True,
)
def toggle_report_modal(open_clicks, cancel_clicks, submit_clicks, is_open):
    return not is_open


@callback(
    Output("profiles-download", "data"),
    Input("profiles-export-btn", "n_clicks"),
    State("profiles-state-filter", "value"),
    State("profiles-confidence-filter", "value"),
    prevent_initial_call=True,
)
def export_profiles(_, state, confidence):
    conf_filter = None if confidence == "All" else [confidence]
    df = resolved_roster(confidence=conf_filter, state=None if state == "All" else state)
    if df.empty:
        return no_update
    return dcc.send_data_frame(df.to_csv, "acd_profiles.csv", index=False)
