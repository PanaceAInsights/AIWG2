"""Research Heatmap page — topic-based research intensity visualization.
Charts are callback-driven so they react to the global filter bar.
"""
from __future__ import annotations

from pathlib import Path

import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html
from dash_iconify import DashIconify

from .. import data, theme

PAGE_TITLE = "Research Heatmap"
PAGE_HREF  = "/heatmap"

_ROOT      = Path(__file__).resolve().parents[2]
_PROCESSED = _ROOT / "data" / "processed"


def _load_pub_topics(names: set | None = None) -> pd.DataFrame:
    """Load publications with topic columns, filtered to accepted members."""
    for fname in ("publications_clean.csv", "publications.csv"):
        p = _PROCESSED / fname
        if p.exists():
            break
    else:
        return pd.DataFrame()

    # Determine available columns
    import csv
    with open(p, newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))

    author_col = next((c for c in ("acd_name", "RAMS_Author") if c in header), None)
    year_col   = next((c for c in ("Year", "Publication_Year") if c in header), None)
    topic_cols = [c for c in ("SubTopic", "Topic_Field") if c in header]
    if author_col is None:
        return pd.DataFrame()

    usecols = [c for c in [author_col, year_col] + topic_cols if c]
    df = pd.read_csv(p, usecols=usecols, low_memory=False)

    accepted = data._accepted_name_set()
    if accepted:
        df = df[df[author_col].isin(accepted)]
    if names is not None:
        df = df[df[author_col].isin(names)]
    df["_author"] = df[author_col]
    if year_col:
        df["_year"] = pd.to_numeric(df[year_col], errors="coerce")
    else:
        df["_year"] = None
    return df


def build_topic_heatmap(names: set | None = None) -> go.Figure:
    df = _load_pub_topics(names)
    if df.empty:
        return go.Figure()

    df = df[df["_year"] >= 2010].copy() if "_year" in df.columns else df.copy()
    topic_col = next((c for c in ("SubTopic", "Topic_Field") if c in df.columns), None)
    if topic_col is None:
        return go.Figure()
    df["topic"] = df[topic_col].fillna("Unknown")

    top_topics = df["topic"].value_counts().head(15).index.tolist()
    df = df[df["topic"].isin(top_topics)]

    pivot = df.groupby(["topic", "_year"]).size().reset_index(name="count")
    matrix = pivot.pivot(index="topic", columns="_year", values="count").fillna(0)
    if matrix.empty:
        return go.Figure()

    matrix["_total"] = matrix.sum(axis=1)
    matrix = matrix.sort_values("_total", ascending=True).drop(columns=["_total"])

    fig = go.Figure(go.Heatmap(
        z=matrix.values,
        x=[str(int(y)) for y in matrix.columns],
        y=matrix.index.tolist(),
        colorscale=[
            [0, "#FFFFFF"],
            [0.2, "#FDE8E8"],
            [0.4, "#FACACA"],
            [0.6, "#C2773E"],
            [1.0, "#7A3B0E"],
        ],
        hoverongaps=False,
        hovertemplate="Topic: %{y}<br>Year: %{x}<br>Publications: %{z}<extra></extra>",
    ))
    fig.update_layout(
        title="Research Intensity by Topic and Year (Top 15 subjects)",
        height=550,
        margin=dict(l=250, r=20, t=60, b=50),
        xaxis_title="Year",
        yaxis=dict(tickfont=dict(size=11)),
    )
    return fig


def build_state_topic_heatmap(names: set | None = None) -> go.Figure:
    df = _load_pub_topics(names)
    if df.empty:
        return go.Figure()

    authors = data.load_authors()
    if authors.empty:
        return go.Figure()

    name_col = next((c for c in ("acd_name", "rams_name") if c in authors.columns), None)
    if name_col is None:
        return go.Figure()
    state_map = dict(zip(authors[name_col], authors["state"].fillna("Unknown")))
    df["state"] = df["_author"].map(state_map).fillna("Unknown")

    topic_col = next((c for c in ("SubTopic", "Topic_Field") if c in df.columns), None)
    if topic_col is None:
        return go.Figure()
    df["topic"] = df[topic_col].fillna("Other")

    top_topics = df["topic"].value_counts().head(10).index.tolist()
    top_states = df["state"].value_counts().head(8).index.tolist()
    df = df[df["topic"].isin(top_topics) & df["state"].isin(top_states)]

    pivot  = df.groupby(["state", "topic"]).size().reset_index(name="count")
    matrix = pivot.pivot(index="topic", columns="state", values="count").fillna(0)
    if matrix.empty:
        return go.Figure()

    fig = go.Figure(go.Heatmap(
        z=matrix.values,
        x=matrix.columns.tolist(),
        y=matrix.index.tolist(),
        colorscale=[
            [0, "#FFFFFF"],
            [0.3, "#D6EAF8"],
            [0.6, "#2980B9"],
            [1.0, "#1B4F72"],
        ],
        hoverongaps=False,
        hovertemplate="State: %{x}<br>Topic: %{y}<br>Publications: %{z}<extra></extra>",
    ))
    fig.update_layout(
        title="Research Focus by State (Top 10 topics)",
        height=420,
        margin=dict(l=250, r=20, t=60, b=50),
        yaxis=dict(tickfont=dict(size=11)),
    )
    return fig


def render() -> html.Div:
    header = dmc.Group([
        dmc.Stack([
            dmc.Title("Research Heatmap", order=2),
            dmc.Text("Research intensity across topics, years, and states",
                     size="sm", c="dimmed"),
        ], gap=2),
        dmc.Button(
            "Export heatmap data",
            id="heatmap-export-btn",
            leftSection=DashIconify(icon="tabler:download", width=16),
            variant="light",
            color="acd-copper",
            size="xs",
        ),
    ], justify="space-between", mb="lg")

    return html.Div([
        header,
        html.Div(
            dcc.Graph(id="heatmap-topic-chart",
                      config={"displayModeBar": False},
                      style={"height": "550px"}),
            className="section-card",
            style={"marginBottom": "1.5rem", "minHeight": "600px"},
        ),
        html.Div(
            dcc.Graph(id="heatmap-state-chart",
                      config={"displayModeBar": False},
                      style={"height": "420px"}),
            className="section-card",
            style={"minHeight": "470px"},
        ),
        dcc.Download(id="heatmap-download"),
    ])


layout = render
