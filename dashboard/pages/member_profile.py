"""ACD Dashboard — Individual member profile page (/profiles/{slug}).

Full-page profile modelled on RMSANZ:
  - Back to Profiles breadcrumb + Report Incorrect Match button
  - Name, alias, location, membership, institution
  - Research topic tags
  - 6 large metric cards (h-index, Publications, Citations, FWCI, Funding Awards, Clinical Trials)
  - Publication Timeline bar chart (full-width)
  - Co-Author Network (force-directed graph) + collaborator table
  - Clinical Trials list
"""
from __future__ import annotations

import logging
import math

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html
from dash_iconify import DashIconify

from dashboard import data
from dashboard.theme import (
    BORDER_COLOR, BG_CARD, BG_MAIN, COPPER, FONT_FAMILY,
    LIGHT_COPPER, TEXT_MUTED, TEXT_SECONDARY, TIER_HIGH, TIER_NOT_FOUND,
    TIER_REVIEW, WARM_CREAM, WHITE, DARK_PLUM, MAUVE_PURPLE,
)

logger = logging.getLogger("acd.member_profile")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(value, decimals: int = 0, suffix: str = "") -> str:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "—"
        if decimals == 0:
            return f"{int(value):,}{suffix}"
        return f"{float(value):.{decimals}f}{suffix}"
    except Exception:
        return "—"


def _conf_color(conf: str) -> str:
    return {
        "HIGH": TIER_HIGH,
        "REVIEW": TIER_REVIEW,
        "NOT_FOUND": TIER_NOT_FOUND,
    }.get(str(conf).upper(), TIER_NOT_FOUND)


def _badge(text: str, color: str, bg: str | None = None) -> html.Span:
    bg = bg or f"{color}1A"
    return html.Span(text, style={
        "display": "inline-block",
        "padding": "3px 10px",
        "borderRadius": "10px",
        "fontSize": "11px",
        "fontWeight": "600",
        "color": color,
        "backgroundColor": bg,
        "border": f"1px solid {color}44",
        "marginRight": "5px",
    })


def _topic_tag(text: str) -> html.Span:
    return html.Span(text, style={
        "display": "inline-block",
        "padding": "4px 12px",
        "borderRadius": "14px",
        "fontSize": "12px",
        "fontWeight": "400",
        "color": COPPER,
        "backgroundColor": "rgba(194,125,78,0.12)",
        "border": "1px solid rgba(194,125,78,0.25)",
        "marginRight": "6px",
        "marginBottom": "6px",
    })


def _metric_card(value_str: str, label: str, tooltip: str = "") -> html.Div:
    return html.Div([
        html.Div(
            value_str,
            style={
                "fontSize": "38px",
                "fontWeight": "700",
                "color": COPPER,
                "lineHeight": "1",
                "fontFamily": FONT_FAMILY,
            },
        ),
        html.Div(
            [
                html.Span(label),
                html.Span(
                    " ⓘ",
                    title=tooltip,
                    style={"cursor": "help", "fontSize": "11px", "color": TEXT_MUTED},
                ) if tooltip else None,
            ],
            style={
                "fontSize": "12px",
                "color": TEXT_MUTED,
                "marginTop": "6px",
                "textTransform": "capitalize",
            },
        ),
    ], style={
        "backgroundColor": BG_CARD,
        "border": f"1px solid {BORDER_COLOR}",
        "borderRadius": "12px",
        "padding": "20px 16px",
        "textAlign": "center",
        "flex": "1",
        "minWidth": "120px",
    })


def _section_header(icon: str, title: str) -> html.Div:
    return html.Div([
        DashIconify(icon=icon, width=18, color=COPPER, style={"marginRight": "8px", "verticalAlign": "middle"}),
        html.Span(title, style={"fontSize": "14px", "fontWeight": "600", "color": WARM_CREAM, "verticalAlign": "middle"}),
    ], style={"marginBottom": "14px"})


def _build_timeline(pubs_df: pd.DataFrame) -> go.Figure:
    """Build the publication timeline bar chart."""
    if pubs_df.empty or "Year" not in pubs_df.columns:
        fig = go.Figure()
        fig.add_annotation(text="No publication data", showarrow=False,
                           font=dict(color=TEXT_MUTED, size=12))
        fig.update_layout(
            height=200, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=40, r=20, t=20, b=40),
        )
        return fig

    years = pubs_df["Year"].dropna().astype(int)
    year_counts = years.value_counts().sort_index()

    fig = go.Figure(go.Bar(
        x=year_counts.index.tolist(),
        y=year_counts.values.tolist(),
        marker_color=COPPER,
        marker_line_width=0,
        hovertemplate="<b>%{x}</b>: %{y} publications<extra></extra>",
    ))
    fig.update_layout(
        height=220,
        margin=dict(l=40, r=20, t=10, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT_MUTED, size=11, family=FONT_FAMILY),
        xaxis=dict(
            gridcolor=BORDER_COLOR,
            tickfont=dict(color=TEXT_MUTED, size=10),
            tickmode="linear",
            dtick=1,
        ),
        yaxis=dict(
            gridcolor=BORDER_COLOR,
            tickfont=dict(color=TEXT_MUTED, size=10),
        ),
        showlegend=False,
        bargap=0.25,
    )
    return fig


def _build_coauthor_network(coauthors_df: pd.DataFrame, member_name: str) -> go.Figure:
    """Build a force-directed co-author network graph."""
    if coauthors_df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No co-author data available", showarrow=False,
                           font=dict(color=TEXT_MUTED, size=12))
        fig.update_layout(
            height=360, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=10, r=10, t=10, b=10),
        )
        return fig

    G = nx.Graph()
    short_name = member_name.split()[-1]  # last name as center node label
    G.add_node(short_name, size=30, is_center=True)

    for _, row in coauthors_df.iterrows():
        coauthor = str(row["coauthor_name"])
        shared = int(row["shared_pubs"])
        # Shorten to last name + first initial
        parts = coauthor.split(",")
        if len(parts) >= 2:
            display = f"{parts[0].strip()}"
        else:
            parts2 = coauthor.split()
            display = parts2[-1] if parts2 else coauthor
        G.add_node(display, size=max(8, min(20, shared * 2)), is_center=False, shared=shared)
        G.add_edge(short_name, display, weight=shared)

    # Spring layout
    pos = nx.spring_layout(G, seed=42, k=2.5 / math.sqrt(len(G.nodes())))

    # Edges
    edge_x, edge_y = [], []
    for u, v in G.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        mode="lines",
        line=dict(width=1, color=BORDER_COLOR),
        hoverinfo="none",
    )

    # Nodes
    node_x, node_y, node_text, node_size, node_color = [], [], [], [], []
    for node in G.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_text.append(node)
        is_center = G.nodes[node].get("is_center", False)
        node_size.append(G.nodes[node].get("size", 10))
        node_color.append(COPPER if is_center else f"rgba(194,125,78,0.55)")

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        marker=dict(
            size=node_size,
            color=node_color,
            line=dict(width=1, color=BORDER_COLOR),
        ),
        text=node_text,
        textposition="top center",
        textfont=dict(size=9, color=TEXT_MUTED, family=FONT_FAMILY),
        hoverinfo="text",
        hovertext=[
            f"{n}: {G.nodes[n].get('shared', '—')} shared pubs"
            if not G.nodes[n].get("is_center") else member_name
            for n in G.nodes()
        ],
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        height=360,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
    )
    return fig


# ---------------------------------------------------------------------------
# Main profile page builder
# ---------------------------------------------------------------------------

def build_member_profile_page(slug: str) -> html.Div:
    """Build the full individual profile page for a member identified by slug."""
    acd_name = data.slug_to_name(slug)

    if acd_name is None:
        return html.Div([
            html.H2("Member not found", style={"color": WARM_CREAM}),
            html.P(f"No member found for: {slug}", style={"color": TEXT_MUTED}),
            dcc.Link("← Back to Profiles", href="/profiles", style={"color": COPPER}),
        ], style={"padding": "40px"})

    # Load all data
    detail = data.member_detail(acd_name) or {}
    pubs_df = data.publications_for_member(acd_name)
    trials_df = data.trials_for_member(acd_name)
    funding_df = data.funding_for_member(acd_name)
    coauthors_df = data.member_coauthors(acd_name, top_n=30)
    keywords = data.member_keywords(acd_name, top_n=10)
    subtopics = data.member_subtopics(acd_name, top_n=8)
    orcid = data.member_orcid(acd_name)

    # Extract fields
    display_name = str(detail.get("openalex_display_name") or "")
    state_val    = str(detail.get("state") or "")
    country      = str(detail.get("institution_country") or "")
    institution  = str(detail.get("last_known_institution") or "")
    speciality   = str(detail.get("speciality_ahpra") or "")
    conf         = str(detail.get("confidence", "NOT_FOUND")).upper()
    ahpra        = detail.get("ahpra_proven", False)
    source       = str(detail.get("source") or "")
    openalex_id  = str(detail.get("openalex_id") or "")

    # Metrics
    h_index    = _fmt(detail.get("h_index"), 0)
    pub_count  = _fmt(detail.get("pub_count"), 0)
    citations  = _fmt(detail.get("citation_count"), 0)
    fwci       = _fmt(detail.get("fwci_mean"), 2)
    grants     = _fmt(detail.get("grants_count"), 0)
    trials_n   = _fmt(detail.get("trial_count"), 0)

    # Location string
    loc_parts = [p for p in [state_val, "Australia" if country == "AU" else country] if p]
    loc_str = ", ".join(loc_parts) if loc_parts else "Unknown"

    # Membership label
    mem_label = "ACD Member" if source in ("Both", "OpenAlex") else ("AHPRA Only" if source == "AHPRA" else "Member")
    mem_color = COPPER if source in ("Both", "OpenAlex") else "#888"

    # Confidence
    conf_col = _conf_color(conf)

    # External links
    openalex_url = f"https://openalex.org/{openalex_id}" if openalex_id and openalex_id != "nan" else None
    orcid_url = f"https://orcid.org/{orcid}" if orcid else None

    # Alias
    alias_shown = display_name and display_name.lower() not in acd_name.lower()

    # All topics (subtopics + keywords, deduplicated)
    all_topics = list(dict.fromkeys(subtopics + [k.title() for k in keywords if k.lower() not in [s.lower() for s in subtopics]]))[:12]

    # ── Build figures ──────────────────────────────────────────────────────
    timeline_fig = _build_timeline(pubs_df)
    network_fig  = _build_coauthor_network(coauthors_df, acd_name)

    # ── Collaborator table rows ────────────────────────────────────────────
    collab_rows = []
    if not coauthors_df.empty:
        max_shared = int(coauthors_df["shared_pubs"].max()) if len(coauthors_df) > 0 else 1
        for _, cr in coauthors_df.head(10).iterrows():
            coauthor_name = str(cr["coauthor_name"])
            shared = int(cr["shared_pubs"])
            bar_pct = int(shared / max_shared * 100)
            # Check if this co-author is also an ACD member
            coauthor_slug = data.make_slug(coauthor_name)
            authors = data.load_authors()
            is_member = not authors[authors["acd_name"].str.lower() == coauthor_name.lower()].empty if not authors.empty else False

            collab_rows.append(html.Tr([
                html.Td(coauthor_name, style={"color": WARM_CREAM, "fontSize": "13px", "padding": "8px 12px"}),
                html.Td([
                    html.Div(style={
                        "width": f"{bar_pct}%",
                        "minWidth": "20px",
                        "height": "6px",
                        "backgroundColor": COPPER,
                        "borderRadius": "3px",
                        "display": "inline-block",
                        "verticalAlign": "middle",
                        "marginRight": "8px",
                    }),
                    html.Span(str(shared), style={"color": TEXT_MUTED, "fontSize": "12px"}),
                ], style={"padding": "8px 12px"}),
                html.Td(
                    dcc.Link("View →", href=f"/profiles/{data.make_slug(coauthor_name)}", style={"color": COPPER, "fontSize": "12px"})
                    if is_member else html.Span("—", style={"color": TEXT_MUTED, "fontSize": "12px"}),
                    style={"padding": "8px 12px"},
                ),
            ], style={"borderBottom": f"1px solid {BORDER_COLOR}"}))

    # ── Clinical trials list ───────────────────────────────────────────────
    trial_items = []
    if not trials_df.empty:
        for _, t in trials_df.iterrows():
            title  = str(t.get("title", "Untitled"))
            actrn  = str(t.get("actrn", t.get("trial_id", "")))
            status = str(t.get("status", "Unknown"))
            url    = str(t.get("url", ""))
            status_color = {
                "Completed": TIER_HIGH,
                "Active": COPPER,
                "Recruiting": LIGHT_COPPER,
                "Withdrawn": TIER_NOT_FOUND,
            }.get(status, TEXT_MUTED)

            trial_items.append(html.Div([
                html.Div([
                    html.A(
                        title,
                        href=url,
                        target="_blank",
                        style={
                            "color": WARM_CREAM,
                            "fontSize": "13px",
                            "fontWeight": "500",
                            "textDecoration": "none",
                            "flex": "1",
                        },
                    ) if url and url != "nan" else html.Span(
                        title,
                        style={"color": WARM_CREAM, "fontSize": "13px", "fontWeight": "500", "flex": "1"},
                    ),
                    DashIconify(icon="tabler:external-link", width=13, color=TEXT_MUTED) if url and url != "nan" else None,
                ], style={"display": "flex", "alignItems": "flex-start", "gap": "6px", "marginBottom": "4px"}),
                html.Div([
                    html.Span(actrn, style={"color": TEXT_MUTED, "fontSize": "11px", "marginRight": "8px", "fontFamily": "'JetBrains Mono', monospace"}),
                    html.Span(
                        status,
                        style={
                            "fontSize": "10px",
                            "fontWeight": "600",
                            "color": status_color,
                            "backgroundColor": f"{status_color}1A",
                            "border": f"1px solid {status_color}44",
                            "borderRadius": "8px",
                            "padding": "1px 7px",
                        },
                    ),
                ]),
            ], style={
                "backgroundColor": BG_CARD,
                "border": f"1px solid {BORDER_COLOR}",
                "borderRadius": "8px",
                "padding": "12px 14px",
                "marginBottom": "8px",
            }))
    else:
        trial_items = [html.Div("No clinical trials found for this member.",
                                style={"color": TEXT_MUTED, "fontSize": "13px", "padding": "12px 0"})]

    # ── Assemble the full page ─────────────────────────────────────────────
    return html.Div([
        # ── Top bar ──────────────────────────────────────────────────────
        html.Div([
            dcc.Link(
                [DashIconify(icon="tabler:arrow-left", width=16, style={"marginRight": "6px", "verticalAlign": "middle"}),
                 "Back to Profiles"],
                href="/profiles",
                style={"color": TEXT_MUTED, "fontSize": "13px", "textDecoration": "none",
                       "display": "inline-flex", "alignItems": "center"},
            ),
            html.A(
                [DashIconify(icon="tabler:flag", width=14, style={"marginRight": "5px", "verticalAlign": "middle"}),
                 "Report Incorrect Match"],
                href=f"mailto:yagiz.aksoy@panaceainsights.com.au?subject=Incorrect Match: {acd_name}&body=Member: {acd_name}%0AOpenAlex ID: {openalex_id}%0A%0APlease describe the issue:",
                style={
                    "color": COPPER,
                    "fontSize": "12px",
                    "textDecoration": "none",
                    "border": f"1px solid {COPPER}44",
                    "borderRadius": "8px",
                    "padding": "6px 14px",
                    "backgroundColor": "rgba(194,125,78,0.08)",
                    "display": "inline-flex",
                    "alignItems": "center",
                },
            ),
        ], style={
            "display": "flex",
            "justifyContent": "space-between",
            "alignItems": "center",
            "marginBottom": "28px",
        }),

        # ── Name + identity ───────────────────────────────────────────────
        html.Div([
            html.Div([
                html.H1(acd_name, style={
                    "fontSize": "28px",
                    "fontWeight": "800",
                    "color": WHITE,
                    "margin": "0 0 4px 0",
                    "fontFamily": FONT_FAMILY,
                }),
                html.Div(
                    f"Published as: {display_name}",
                    style={"fontSize": "13px", "color": TEXT_MUTED, "fontStyle": "italic", "marginBottom": "8px"},
                ) if alias_shown else None,
                html.Div([
                    html.Span(f"{loc_str} · ", style={"color": TEXT_MUTED, "fontSize": "13px"}),
                    html.Span(mem_label, style={"color": mem_color, "fontSize": "13px", "fontWeight": "600"}),
                    html.Span(f" · {speciality}", style={"color": TEXT_MUTED, "fontSize": "13px"}) if speciality and speciality != "nan" else None,
                ], style={"marginBottom": "8px"}),
                html.Div(
                    f"Institution(s): {institution}" if institution and institution != "nan" else "",
                    style={"fontSize": "12px", "color": TEXT_MUTED, "marginBottom": "10px"},
                ) if institution and institution != "nan" else None,
                # Badges
                html.Div([
                    _badge(conf, conf_col),
                    _badge("✓ AHPRA-verified", TIER_HIGH) if ahpra else None,
                ], style={"display": "flex", "flexWrap": "wrap", "gap": "4px", "marginBottom": "14px"}),
                # Topic tags
                html.Div(
                    [_topic_tag(t) for t in all_topics],
                    style={"lineHeight": "2"},
                ) if all_topics else None,
            ], style={"flex": "1"}),

            # External profile links
            html.Div([
                html.A(
                    [DashIconify(icon="tabler:external-link", width=14, style={"marginRight": "5px"}), "Research Profile"],
                    href=openalex_url,
                    target="_blank",
                    style={
                        "display": "inline-flex",
                        "alignItems": "center",
                        "padding": "7px 14px",
                        "border": f"1px solid {BORDER_COLOR}",
                        "borderRadius": "8px",
                        "color": WARM_CREAM,
                        "fontSize": "12px",
                        "textDecoration": "none",
                        "backgroundColor": BG_CARD,
                        "marginBottom": "8px",
                    },
                ) if openalex_url else None,
                html.A(
                    [DashIconify(icon="tabler:external-link", width=14, style={"marginRight": "5px"}), "ORCID"],
                    href=orcid_url,
                    target="_blank",
                    style={
                        "display": "inline-flex",
                        "alignItems": "center",
                        "padding": "7px 14px",
                        "border": f"1px solid {BORDER_COLOR}",
                        "borderRadius": "8px",
                        "color": WARM_CREAM,
                        "fontSize": "12px",
                        "textDecoration": "none",
                        "backgroundColor": BG_CARD,
                    },
                ) if orcid_url else None,
            ], style={"display": "flex", "flexDirection": "column", "alignItems": "flex-end", "gap": "4px", "flexShrink": "0", "marginLeft": "20px"}),
        ], style={"display": "flex", "alignItems": "flex-start", "marginBottom": "28px"}),

        # ── 6 Metric cards ────────────────────────────────────────────────
        html.Div([
            _metric_card(h_index, "H-index", "Number of publications (N) each cited at least N times"),
            _metric_card(pub_count, "Publications", "Total publications in OpenAlex"),
            _metric_card(citations, "Citations", "Total citations received"),
            _metric_card(fwci, "FWCI", "Field-Weighted Citation Impact (>1.0 = above world average)"),
            _metric_card(grants, "Funding Awards", "Number of funding awards extracted from publications"),
            _metric_card(trials_n, "Clinical Trials", "Clinical trials registered in ANZCTR"),
        ], style={
            "display": "flex",
            "gap": "12px",
            "flexWrap": "wrap",
            "marginBottom": "28px",
        }),

        # ── Publication Timeline ──────────────────────────────────────────
        html.Div([
            _section_header("tabler:chart-bar", "Publication Timeline"),
            html.P("Publications per year from OpenAlex",
                   style={"fontSize": "11px", "color": TEXT_MUTED, "marginBottom": "8px", "marginTop": "-8px"}),
            dcc.Graph(
                figure=timeline_fig,
                config={"displayModeBar": False, "responsive": True},
                style={"width": "100%"},
            ),
        ], style={
            "backgroundColor": BG_CARD,
            "border": f"1px solid {BORDER_COLOR}",
            "borderRadius": "12px",
            "padding": "20px",
            "marginBottom": "20px",
        }),

        # ── Co-Author Network + Collaborator Table ────────────────────────
        html.Div([
            _section_header("tabler:users", f"Co-Author Network"),
            html.P(
                f"{len(coauthors_df)} collaborators · Node size = shared publications",
                style={"fontSize": "11px", "color": TEXT_MUTED, "marginBottom": "12px", "marginTop": "-8px"},
            ) if not coauthors_df.empty else None,
            dcc.Graph(
                figure=network_fig,
                config={"displayModeBar": False, "responsive": True},
                style={"width": "100%"},
            ),
            # Collaborator table
            html.Table([
                html.Thead(html.Tr([
                    html.Th("Collaborator", style={"color": TEXT_MUTED, "fontSize": "11px", "fontWeight": "500",
                                                   "textTransform": "uppercase", "letterSpacing": "0.5px",
                                                   "padding": "8px 12px", "borderBottom": f"1px solid {BORDER_COLOR}"}),
                    html.Th("Shared Pubs", style={"color": TEXT_MUTED, "fontSize": "11px", "fontWeight": "500",
                                                   "textTransform": "uppercase", "letterSpacing": "0.5px",
                                                   "padding": "8px 12px", "borderBottom": f"1px solid {BORDER_COLOR}"}),
                    html.Th("Profile", style={"color": TEXT_MUTED, "fontSize": "11px", "fontWeight": "500",
                                              "textTransform": "uppercase", "letterSpacing": "0.5px",
                                              "padding": "8px 12px", "borderBottom": f"1px solid {BORDER_COLOR}"}),
                ])),
                html.Tbody(collab_rows),
            ], style={"width": "100%", "borderCollapse": "collapse", "marginTop": "12px"}) if collab_rows else None,
        ], style={
            "backgroundColor": BG_CARD,
            "border": f"1px solid {BORDER_COLOR}",
            "borderRadius": "12px",
            "padding": "20px",
            "marginBottom": "20px",
        }) if not coauthors_df.empty else None,

        # ── Clinical Trials ───────────────────────────────────────────────
        html.Div([
            _section_header("tabler:flask", f"Clinical Trials ({len(trials_df) if not trials_df.empty else 0})"),
            html.Div(trial_items),
        ], style={
            "backgroundColor": BG_CARD,
            "border": f"1px solid {BORDER_COLOR}",
            "borderRadius": "12px",
            "padding": "20px",
            "marginBottom": "20px",
        }),

    ], style={"padding": "0"})
