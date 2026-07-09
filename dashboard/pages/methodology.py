"""Methodology page — plain-English explanation of the dashboard data pipeline."""
from __future__ import annotations

import dash_mantine_components as dmc
from dash import html

from .. import data

PAGE_TITLE = "Methodology"
PAGE_HREF  = "/methodology"


def render() -> html.Div:
    """Static methodology content for non-technical stakeholders."""
    authors  = data.load_authors()
    resolved = data.resolved_roster()
    pubs     = data.load_publications()

    total_members  = len(authors)
    total_resolved = len(resolved)
    resolved_pct   = round(100 * total_resolved / total_members, 0) if total_members else 0
    total_pubs     = len(pubs)
    derm_count     = (
        int(pubs["is_derm_relevant"].apply(
            lambda x: 1 if x is True or str(x).strip().lower() in ("true", "1") else 0
        ).sum())
        if "is_derm_relevant" in pubs.columns else 0
    )
    derm_pct = round(100 * derm_count / total_pubs, 1) if total_pubs else 0

    return html.Div([
        html.Div([
            dmc.Title("Methodology", order=2, mb="md"),
            dmc.Text(
                "This page explains how the Research Intelligence Dashboard "
                "identifies ACD members' research profiles and classifies "
                "their publications.",
                size="sm", c="dimmed", mb="lg",
            ),
        ]),
        html.Div([
            # Section 1: Data Sources
            html.H2("Data Sources"),
            html.P("The dashboard draws on four primary data sources:"),
            dmc.List([
                dmc.ListItem(
                    f"ACD membership register ({total_members:,} members and "
                    f"non-member dermatologists)"
                ),
                dmc.ListItem("AHPRA practitioner register (practitioner numbers, specialties)"),
                dmc.ListItem("OpenAlex open research database (publications, citations, funding)"),
                dmc.ListItem("Survey respondents (self-reported contacts for validation)"),
            ], mb="lg"),

            # Section 2: Scope
            html.H2("Who Is Included"),
            html.P(
                "The dashboard includes all ACD members and non-members registered "
                "with AHPRA as dermatology specialists. Anyone identified through "
                "HealthShare only is excluded."
            ),
            dmc.Alert(
                f"Current roster: {total_members:,} physicians. Of these, "
                f"{total_resolved:,} ({resolved_pct:.0f}%) have been matched to a "
                f"research profile with high confidence. The remainder are clinicians "
                f"without detectable research output or could not be matched with "
                f"sufficient certainty.",
                title="Current Coverage",
                color="acd-copper",
                variant="light",
                mb="lg",
            ),

            # Section 3: Matching
            html.H2("How Members Are Matched to Research Profiles"),
            html.P(
                "For each member, the system searches the OpenAlex database and scores "
                "candidates against eight independent signals:"
            ),
            dmc.Table(
                data={
                    "head": ["Signal", "What it checks"],
                    "body": [
                        ["Name similarity",
                         "How closely the registered name matches the profile name"],
                        ["Country",
                         "Whether the researcher's institution is in AU/NZ"],
                        ["Institution type",
                         "Whether the institution is a known health/dermatology service"],
                        ["Research topics",
                         "Whether publications relate to dermatology"],
                        ["Co-authorship",
                         "Whether the researcher has published with other ACD members"],
                        ["State match",
                         "Whether the institution state matches AHPRA registration"],
                        ["Historical affiliation",
                         "Whether there is any historical AU/NZ connection"],
                        ["Hospital match",
                         "Whether the institution is a specific dermatology hospital"],
                    ],
                },
                striped=True,
                highlightOnHover=True,
                mb="lg",
            ),
            html.P(
                "A match is accepted only when multiple signals converge "
                "(typically 5-6 must agree). This prevents false positives "
                "from common names."
            ),

            # Section 4: Derm Relevance
            html.H2("Dermatology Relevance Classification"),
            html.P(
                "Not all publications by dermatologists relate directly to the specialty. "
                "Each publication is classified as 'derm-relevant' if its subject field, "
                "keywords, MeSH terms, or title/abstract contain dermatology-related "
                "terminology."
            ),
            dmc.Alert(
                f"Of {total_pubs:,} publications from matched members, {derm_count:,} "
                f"({derm_pct}%) are classified as derm-relevant. The dashboard allows "
                f"filtering by this flag.",
                title="Classification Results",
                color="teal",
                variant="light",
                mb="lg",
            ),

            # Section 5: Quality Measures
            html.H2("Data Quality Measures"),
            dmc.List([
                dmc.ListItem(
                    "Common-name validation shortlist: members with ambiguous names "
                    "flagged for ACD manual review"
                ),
                dmc.ListItem(
                    "AHPRA verification: confirmed practitioner numbers anchor identity"
                ),
                dmc.ListItem(
                    "Manual override mechanism: known corrections applied without "
                    "re-running the full process"
                ),
                dmc.ListItem(
                    "Survey cross-reference: respondents' email domains compared "
                    "to resolved institutions"
                ),
            ], mb="lg"),

            # Section 6: Limitations
            html.H2("Limitations"),
            dmc.List([
                dmc.ListItem(
                    "OpenAlex may not capture all publications (some grey literature, "
                    "recent papers may be missing)"
                ),
                dmc.ListItem(
                    "Common names retain some ambiguity despite eight matching signals"
                ),
                dmc.ListItem(
                    "Many trainees and early-career fellows have no publications yet"
                ),
                dmc.ListItem(
                    "Institutional affiliations reflect time of publication, not "
                    "necessarily current employer"
                ),
            ], mb="lg"),

            # Section 7: Glossary
            html.H2("Glossary"),
            dmc.Table(
                data={
                    "head": ["Term", "Definition"],
                    "body": [
                        ["AHPRA", "Australian Health Practitioner Regulation Agency"],
                        ["FACD", "Fellow of the Australasian College of Dermatologists"],
                        ["FWCI", "Field-Weighted Citation Impact (1.0 = world average)"],
                        ["h-index", "N papers each cited at least N times"],
                        ["MeSH", "Medical Subject Headings (biomedical vocabulary)"],
                        ["OpenAlex", "Open-access database of 200M+ research profiles"],
                    ],
                },
                striped=True,
                highlightOnHover=True,
            ),
        ], className="methodology-content"),
    ])


layout = render
