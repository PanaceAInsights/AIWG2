"""Collaboration tab — co-authorship graph (Cytoscape) + summary stats.

Builds the graph from the publications table: two members are connected
if they share an OpenAlex work. Edge weight = shared-work count.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import dash_cytoscape as cyto
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from .. import data, theme

PAGE_TITLE = "Collaboration"
PAGE_HREF  = "/collaboration"


def _build_coauthorship() -> tuple[list[dict], list[dict], dict]:
    """Return (nodes, edges, stats)."""
    pubs    = data.load_publications()
    authors = data.resolved_roster()
    if pubs.empty or authors.empty:
        return [], [], {"members": 0, "pairs": 0, "max_weight": 0, "density": 0.0}

    name_col = next((c for c in ("acd_name", "rams_name") if c in authors.columns), None)
    if name_col is None:
        return [], [], {"members": 0, "pairs": 0, "max_weight": 0, "density": 0.0}

    resolved_names  = {n for n in authors[name_col].tolist() if isinstance(n, str)}

    # Author_Names uses "Firstname Initials Lastname" (pipe-separated), not full names.
    # Build last-name + first-initial lookup for fuzzy matching.
    def _strip_title(parts: list[str]) -> list[str]:
        while parts and parts[0].lower() in ("dr", "prof", "assoc", "a/prof", "mr", "ms", "mrs"):
            parts = parts[1:]
        return parts

    last_to_resolved: dict[str, list[tuple[str, str]]] = {}
    for n in resolved_names:
        parts = _strip_title(n.strip().split())
        if not parts:
            continue
        last = parts[-1].lower()
        finit = parts[0][0].lower()
        last_to_resolved.setdefault(last, []).append((finit, n))

    work_col = "Unique ID" if "Unique ID" in pubs.columns else None
    if work_col is None:
        return [], [], {"members": 0, "pairs": 0, "max_weight": 0, "density": 0.0}

    work_to_members: dict[str, set[str]] = defaultdict(set)
    seen_works: set[str] = set()
    for _idx, row in pubs[[work_col, "Author_Names"]].dropna().iterrows():
        wid = str(row[work_col])
        if wid in seen_works:
            continue
        seen_works.add(wid)
        names_field = str(row["Author_Names"] or "")
        if not names_field:
            continue
        for raw in names_field.split("|"):
            raw = raw.strip()
            if not raw:
                continue
            raw_parts = raw.split()
            if not raw_parts:
                continue
            raw_last  = raw_parts[-1].lower()
            raw_finit = raw_parts[0][0].lower()
            if raw_last in last_to_resolved:
                for (finit, full_name) in last_to_resolved[raw_last]:
                    if finit == raw_finit:
                        work_to_members[wid].add(full_name)
                        break

    pair_counts: Counter = Counter()
    for members in work_to_members.values():
        if len(members) < 2:
            continue
        mem_list = sorted(members)
        for i in range(len(mem_list)):
            for j in range(i + 1, len(mem_list)):
                pair_counts[(mem_list[i], mem_list[j])] += 1

    MIN_WEIGHT = 2
    active_members: set[str] = set()
    for (a, b), w in pair_counts.items():
        if w >= MIN_WEIGHT:
            active_members.add(a)
            active_members.add(b)

    degree: Counter = Counter()
    for (a, b), w in pair_counts.items():
        if w >= MIN_WEIGHT:
            degree[a] += w
            degree[b] += w

    nodes = []
    for m in active_members:
        d = degree[m]
        nodes.append({
            "data": {"id": m, "label": m, "weight": d},
            "classes": "hub" if d >= 15 else ("strong" if d >= 6 else "normal"),
        })

    edges = []
    for (a, b), w in pair_counts.items():
        if w >= MIN_WEIGHT:
            edges.append({"data": {"source": a, "target": b, "weight": w}})

    n_members = len(active_members)
    max_pairs = n_members * (n_members - 1) / 2 if n_members > 1 else 1
    stats = {
        "members":    n_members,
        "pairs":      sum(1 for w in pair_counts.values() if w >= MIN_WEIGHT),
        "max_weight": max(pair_counts.values()) if pair_counts else 0,
        "density":    round(
            100.0 * sum(1 for w in pair_counts.values() if w >= MIN_WEIGHT) / max_pairs, 2
        ),
    }
    return nodes, edges, stats


CYTO_STYLE = [
    {"selector": "node", "style": {
        "background-color": theme.PRIMARY,
        "label": "data(label)",
        "width":  "mapData(weight, 0, 30, 14, 48)",
        "height": "mapData(weight, 0, 30, 14, 48)",
        "color": theme.GRAY_700,
        "font-size": "9px",
        "text-valign": "bottom", "text-halign": "center",
        "text-margin-y": 6,
        "text-outline-width": 2, "text-outline-color": "#ffffff",
        "border-width": 1, "border-color": "#ffffff",
    }},
    {"selector": "node.hub", "style": {
        "background-color": theme.VIOLET,
        "border-color": theme.ACCENT, "border-width": 3,
        "font-size": "11px", "font-weight": "bold",
    }},
    {"selector": "node.strong", "style": {"background-color": theme.CYAN}},
    {"selector": "edge", "style": {
        "width": "mapData(weight, 2, 20, 0.5, 4)",
        "line-color": theme.GRAY_300, "opacity": 0.55,
        "curve-style": "bezier",
    }},
    {"selector": "node:selected", "style": {
        "background-color": theme.ACCENT,
        "border-width": 3, "border-color": theme.ACCENT,
    }},
    {"selector": "edge:selected", "style": {
        "line-color": theme.ACCENT, "opacity": 1, "width": 3,
    }},
]


def build_collab_detail(name: str) -> html.Div:
    """Build a detail card for a clicked node in the co-authorship graph."""
    detail = data.member_detail(name)
    if not detail:
        return dmc.Alert(f"No data found for {name}.", color="yellow", variant="light")

    children = [dmc.Text(name, fw=700, size="lg")]
    inst = detail.get("last_known_institution")
    if inst and str(inst) not in ("", "nan"):
        children.append(dmc.Text(str(inst), size="sm", c="dimmed"))
    state_val = detail.get("state")
    if state_val and str(state_val) not in ("", "nan"):
        children.append(dmc.Badge(str(state_val), color="blue", variant="light", size="sm"))

    stats = []
    for label, key, fmt in [
        ("Publications", "pub_count",      "{:,.0f}"),
        ("Citations",    "citation_count", "{:,.0f}"),
        ("h-index",      "h_index",        "{:.0f}"),
        ("Mean FWCI",    "fwci_mean",      "{:.2f}"),
        ("Grants",       "grants_count",   "{:,.0f}"),
    ]:
        val = detail.get(key)
        if val is not None and str(val) not in ("", "nan"):
            try:
                formatted = fmt.format(float(val))
            except (ValueError, TypeError):
                formatted = str(val)
            stats.append(
                dmc.Group([
                    dmc.Text(label, size="xs", c="dimmed", style={"minWidth": "90px"}),
                    dmc.Text(formatted, size="sm", fw=600),
                ], gap="xs")
            )
    if stats:
        children.append(dmc.Divider(my="xs"))
        children.append(dmc.Stack(stats, gap="xs"))

    children.append(dmc.Space(h=8))
    children.append(dmc.Anchor("View full profile", href="/profiles", size="sm"))

    return dmc.Card(
        children,
        shadow="md", radius="md", withBorder=True, padding="md",
        style={"maxWidth": "360px", "marginTop": "0.5rem"},
    )


def _stat_chip(label: str, value, icon: str) -> dmc.Card:
    return dmc.Card(
        dmc.Group([
            DashIconify(icon=icon, width=20, color=theme.PRIMARY),
            dmc.Stack([
                dmc.Text(label, size="xs", c="dimmed", tt="uppercase",
                         fw=600, style={"letterSpacing": "0.05em"}),
                dmc.Text(f"{value}", fw=700, size="md"),
            ], gap=0),
        ], gap="sm"),
        shadow="xs", radius="lg", withBorder=True, padding="md",
        style={"minWidth": "170px"},
    )


def render() -> html.Div:
    nodes, edges, stats = _build_coauthorship()

    header = dmc.Group([
        dmc.Stack([
            dmc.Text("Collaboration", fw=700, size="xl"),
            dmc.Text(
                "Members are nodes; edges are shared publications (\u22652). "
                "Hub nodes (violet) sit above 15 shared works. Drag, zoom, "
                "click any node to isolate its neighbourhood.",
                size="sm", c="dimmed",
            ),
        ], gap=2),
        dmc.Button(
            "Export network data",
            id="collab-export-btn",
            leftSection=DashIconify(icon="tabler:download", width=16),
            variant="light",
            color="acd-copper",
            size="xs",
        ),
    ], justify="space-between", mb="md")

    explanation_box = dmc.Alert(
        [
            dmc.Text(
                "This network shows co-authorship relationships between "
                "dermatologists included in the dashboard. Each node "
                "represents a researcher. A link between two nodes means they "
                "have co-authored at least one publication. Larger nodes indicate "
                "more publications. The network is based on publications indexed "
                "in OpenAlex.",
                size="sm",
            ),
            dmc.Space(h=8),
            dmc.Text(
                "The collaboration view includes co-authorship between researchers "
                "included in this dashboard only. External collaborators are not shown.",
                size="xs", c="dimmed", fs="italic",
            ),
        ],
        color="blue", variant="light", mb="md",
    )

    stats_row = dmc.Group([
        _stat_chip("Members in graph", stats["members"], "tabler:users"),
        _stat_chip("Edges (\u22652 shared)", stats["pairs"], "tabler:link"),
        _stat_chip(
            "Strongest edge",
            f"{stats['max_weight']} works" if stats["max_weight"] else "-",
            "tabler:flame",
        ),
        _stat_chip("Graph density", f"{stats['density']}%", "tabler:chart-dots"),
    ], gap="sm", mb="md")

    empty = stats["members"] == 0
    if empty:
        graph_card = html.Div(
            dmc.Stack([
                dmc.Text("No co-authorship edges found yet.", fw=600),
                dmc.Text(
                    "Once publications are fully ingested and members "
                    "share works, they will appear here.",
                    size="sm", c="dimmed",
                ),
            ], align="center"),
            className="empty-state section-card",
            style={"minHeight": "560px"},
        )
    else:
        graph_card = html.Div(
            cyto.Cytoscape(
                id="coauth-graph",
                elements=nodes + edges,
                layout={
                    "name": "cose",
                    "animate": False,
                    "nodeRepulsion": 9000,
                    "gravity": 0.6,
                    "componentSpacing": 60,
                    "padding": 30,
                },
                style={"width": "100%", "height": "100%"},
                stylesheet=CYTO_STYLE,
                minZoom=0.25, maxZoom=2.5,
            ),
            className="cy-container",
        )

    return html.Div([
        header,
        explanation_box,
        stats_row,
        graph_card,
        html.Div(id="collab-detail-panel", style={"marginTop": "1rem"}),
        dcc.Download(id="collab-download"),
    ])


layout = render
