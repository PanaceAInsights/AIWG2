"""Animated KPI card — value counter, sparkline, trend pill.

Designed to carry the Overview hero. Uses pure Dash/Plotly so there's
no JS bundle to ship.
"""
from __future__ import annotations

from typing import Iterable, Optional

import dash_mantine_components as dmc
import plotly.graph_objects as go
from dash import dcc, html
from dash_iconify import DashIconify

from .. import theme


def sparkline(values: Iterable[float], color: str = theme.PRIMARY) -> go.Figure:
    """Small inline sparkline with smooth area fill."""
    vs = list(values)
    fig = go.Figure(
        data=[
            go.Scatter(
                y=vs,
                mode="lines",
                line=dict(color=color, width=2, shape="spline"),
                fill="tozeroy",
                fillcolor=f"rgba({_hex_rgb(color)}, 0.15)",
                hoverinfo="skip",
            )
        ]
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=48,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        showlegend=False,
    )
    return fig


def _hex_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"


def kpi_card(
    label: str,
    value: str | int | float,
    *,
    sub: Optional[str] = None,
    icon: str = "tabler:chart-line",
    color: str = theme.PRIMARY,
    trend: Optional[str] = None,
    trend_positive: bool = True,
    spark: Optional[list[float]] = None,
) -> dmc.Card:
    """Single KPI card used across Overview and Benchmarking."""
    icon_el = DashIconify(icon=icon, width=20, color=color)
    trend_el = None
    if trend:
        trend_color = theme.SUCCESS if trend_positive else theme.DANGER
        arrow = "tabler:trending-up" if trend_positive else "tabler:trending-down"
        trend_el = dmc.Badge(
            [DashIconify(icon=arrow, width=12, style={"marginRight": 4}), trend],
            color="teal" if trend_positive else "red",
            variant="light",
            size="sm",
        )

    body = [
        dmc.Group(
            [
                dmc.Text(label, size="xs", c="dimmed", tt="uppercase", fw=600,
                         style={"letterSpacing": "0.05em"}),
                icon_el,
            ],
            justify="space-between",
            align="center",
        ),
        dmc.Text(
            f"{value}",
            size="1.9rem",
            fw=700,
            style={"lineHeight": "1.1", "fontFamily": "Inter",
                   "marginTop": "0.5rem", "color": theme.INK},
        ),
    ]
    if sub:
        body.append(dmc.Text(sub, size="xs", c="dimmed", style={"marginTop": "0.15rem"}))
    if trend_el is not None:
        body.append(html.Div(trend_el, style={"marginTop": "0.4rem"}))
    if spark is not None:
        body.append(
            html.Div(
                dcc.Graph(
                    figure=sparkline(spark, color=color),
                    config={"displayModeBar": False, "staticPlot": True},
                    style={"height": "48px", "marginTop": "0.5rem"},
                )
            )
        )
    return dmc.Card(body)
