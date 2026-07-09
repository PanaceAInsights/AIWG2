"""Overview page — cohort hero, KPI grid, trend charts.

All charts and KPIs are callback-driven so they react to the global
filter bar.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import dash_mantine_components as dmc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html
from dash_iconify import DashIconify

from .. import data, theme
from ..components import kpi_card

PAGE_TITLE = "Overview"
PAGE_HREF  = "/"


def _data_refresh_date() -> str:
    csv_path = (
        Path(__file__).resolve().parents[2]
        / "data" / "processed" / "publications_clean.csv"
    )
    try:
        mtime = datetime.fromtimestamp(csv_path.stat().st_mtime)
        return (
            f"Data extracted: May 2026 | "
            f"Last refreshed: {mtime.day} {mtime.strftime('%B %Y')}"
        )
    except OSError:
        return "Data extracted: May 2026 | Last refreshed: unknown"


def build_publications_trend(pubs: pd.DataFrame, min_year: int = 2005) -> go.Figure:
    if pubs.empty:
        return go.Figure()
    year_col = next(
        (c for c in ("year", "Year", "Publication_Year") if c in pubs.columns), None
    )
    if year_col is None:
        return go.Figure()
    df = pubs.copy()
    df["_yr"] = pd.to_numeric(df[year_col], errors="coerce")
    df = df[df["_yr"] >= min_year]
    has_derm = "is_derm_relevant" in df.columns
    if has_derm:
        grp = df.groupby("_yr").agg(
            total=("_yr", "size"), derm=("is_derm_relevant", "sum")
        ).reset_index()
    else:
        grp = df.groupby("_yr").agg(total=("_yr", "size")).reset_index()
        grp["derm"] = 0
    grp["other"] = grp["total"] - grp["derm"]
    fig = go.Figure()
    fig.add_bar(x=grp["_yr"], y=grp["other"], name="Other",
                marker_color=theme.GRAY_300,
                hovertemplate="%{y} other<br>%{x}<extra></extra>")
    fig.add_bar(x=grp["_yr"], y=grp["derm"], name="Derm-relevant",
                marker_color=theme.PRIMARY,
                hovertemplate="%{y} derm-relevant<br>%{x}<extra></extra>")
    fig.update_layout(barmode="stack",
                      title="Annual publication output: derm-tagged vs other",
                      yaxis_title="Publications", xaxis_title="", height=320)
    return fig


def build_state_chart(authors: pd.DataFrame) -> go.Figure:
    if authors.empty or "state" not in authors.columns:
        return go.Figure()
    s = authors["state"].fillna("").astype(str)
    s = s.where(s.ne(""), "Unknown")
    df = s.value_counts().rename_axis("state").reset_index(name="count")
    order = ["NSW", "VIC", "QLD", "SA", "WA", "TAS", "ACT", "NT", "NZ", "Unknown"]
    df["sort_key"] = df["state"].map({st: i for i, st in enumerate(order)}).fillna(99)
    df = df.sort_values("sort_key").drop(columns="sort_key")
    fig = go.Figure(go.Bar(x=df["state"], y=df["count"], marker_color=theme.PRIMARY,
                           hovertemplate="%{x}: %{y} members<extra></extra>"))
    fig.update_layout(title="Members by state", yaxis_title="Members",
                      xaxis_title="", height=320, showlegend=False)
    return fig


def build_top_inst_chart(authors: pd.DataFrame) -> go.Figure:
    col = next(
        (c for c in ("last_known_institution", "institution", "affiliation")
         if c in authors.columns), None
    )
    if authors.empty or col is None:
        return go.Figure()
    top = authors[col].fillna("").replace("", np.nan).dropna().value_counts().head(12)
    if top.empty:
        return go.Figure()
    top = top.iloc[::-1]
    fig = go.Figure(go.Bar(x=top.values, y=top.index, orientation="h",
                           marker_color=theme.VIOLET,
                           hovertemplate="%{y}<br>%{x} members<extra></extra>"))
    fig.update_layout(title="Top institutions hosting ACD-aligned authors",
                      xaxis_title="Members", yaxis_title="", height=380,
                      margin=dict(l=240))
    return fig


def build_overview_kpis(s: dict) -> list:
    _link_style = {"textDecoration": "none", "color": "inherit"}
    n_high       = s.get("n_high", 0)
    n_total      = s.get("n_total", 0)
    n_pubs       = s.get("n_pubs", 0)
    n_derm       = s.get("n_derm_pubs", 0)
    derm_pct     = round(n_derm / n_pubs * 100) if n_pubs else 0
    resolved_pct = round(n_high / n_total * 100) if n_total else 0
    return [
        html.A(kpi_card("Resolved dermatologists", f"{n_high}/{n_total}",
                        sub=f"{resolved_pct}% with a verified research profile",
                        icon="tabler:user-check", color=theme.PRIMARY),
               href="/profiles", style=_link_style),
        html.A(kpi_card("Publications", f"{n_pubs:,}",
                        sub=f"{n_derm:,} derm-tagged ({derm_pct}%)",
                        icon="tabler:books", color=theme.VIOLET),
               href="/publications", style=_link_style),
        kpi_card("Total citations", f"{s.get('total_citations', 0):,}",
                 sub="Cumulative across cohort", icon="tabler:quote", color=theme.CYAN),
        html.A(kpi_card("Clinical trials", f"{s.get('n_trials', 0):,}",
                        sub="Registered across AU, NZ and international registries",
                        icon="tabler:activity", color=theme.PINK),
               href="/trials", style=_link_style),
        html.A(kpi_card("Funded members", f"{s.get('n_funded', 0):,}",
                        sub="Members with NHMRC/ARC/other funding",
                        icon="tabler:cash-banknote", color=theme.ACCENT),
               href="/funding", style=_link_style),
    ]


def render() -> html.Div:
    total_members = len(data.load_authors())
    hero = html.Section(
        [
            dmc.Group([
                dmc.Badge("Research Intelligence", color="acd-copper", variant="filled"),
                dmc.Badge(f"{total_members} dermatologists", variant="light",
                          style={"color": "#fff", "borderColor": "rgba(255,255,255,0.4)"}),
            ], gap="xs"),
            html.H1("ACD Research Intelligence Dashboard"),
            html.P(
                "Research activity intelligence for the Australasian College of "
                "Dermatologists. Covers ACD members and AHPRA-registered dermatologists. "
                "Publications are classified for dermatology relevance and matched via an "
                "8-signal identity resolver."
            ),
            dmc.Text(_data_refresh_date(), size="xs", c="dimmed", mt="xs"),
        ],
        className="acd-hero",
    )
    kpis = html.Div(id="overview-kpi-row", className="kpi-grid")
    charts_row = dmc.Grid([
        dmc.GridCol(
            html.Div([
                html.Div("Publication momentum", className="section-title"),
                dcc.Graph(id="overview-pub-trend",
                          config={"displayModeBar": False, "responsive": True},
                          style={"height": "320px"}),
            ], className="section-card", style={"minHeight": "380px"}),
            span={"base": 12, "md": 8},
        ),
        dmc.GridCol(
            html.Div([
                html.Div("Geographic spread", className="section-title"),
                dcc.Graph(id="overview-state-chart",
                          config={"displayModeBar": False, "responsive": True},
                          style={"height": "320px"}),
            ], className="section-card", style={"minHeight": "380px"}),
            span={"base": 12, "md": 4},
        ),
    ], gutter="lg", mt="lg")
    institutions_row = dmc.Grid([
        dmc.GridCol(
            html.Div([
                html.Div("Member-heavy institutions", className="section-title"),
                dcc.Graph(id="overview-inst-chart",
                          config={"displayModeBar": False, "responsive": True},
                          style={"height": "380px"}),
            ], className="section-card", style={"minHeight": "440px"}),
            span={"base": 12, "md": 8},
        ),
        dmc.GridCol(
            html.Div([
                html.Div("How to read this dashboard", className="section-title"),
                dmc.Text(
                    "Every chart respects the confirmed ACD member cohort. "
                    "Authors are the atomic unit; works, funding, and trials "
                    "pivot through the verified research identity each "
                    "member was matched to in the resolver step.",
                    size="sm",
                ),
                dmc.Space(h=12),
                dmc.List([
                    dmc.ListItem([
                        dmc.Text("Resolver confidence", fw=600, size="sm"),
                        dmc.Text("Only HIGH-confidence matches with verified AU/NZ "
                                 "affiliation history are kept. Others are blank.",
                                 size="xs", c="dimmed"),
                    ]),
                    dmc.ListItem([
                        dmc.Text("Derm-relevance tag", fw=600, size="sm"),
                        dmc.Text("Publications flagged by field, MeSH, keyword and "
                                 "title-token rubric.", size="xs", c="dimmed"),
                    ]),
                    dmc.ListItem([
                        dmc.Text("Benchmarking", fw=600, size="sm"),
                        dmc.Text("All percentile ranks are computed within the "
                                 "confirmed ACD member cohort.", size="xs", c="dimmed"),
                    ]),
                ], spacing="sm", size="sm"),
                dmc.Space(h=16),
                dmc.Anchor("View full methodology", href="/methodology"),
            ], className="section-card", style={"height": "100%"}),
            span={"base": 12, "md": 4},
        ),
    ], gutter="lg", mt="lg")
    return html.Div([hero, kpis, charts_row, institutions_row])


layout = render
