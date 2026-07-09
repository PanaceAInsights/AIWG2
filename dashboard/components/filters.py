"""Cross-dashboard filter bar — collapsible panel below the header.

Provides a unified set of filters (state, speciality, year range,
derm-relevant flag, text search) that apply across all dashboard views
via a dcc.Store("global-filters").

The filter bar renders Mantine controls. A single callback in app.py
reads all inputs and writes a serialised dict to the Store. Each page
callback reads that Store as an Input and applies the filters to the
cached DataFrames.
"""
from __future__ import annotations

from typing import Any

import dash_mantine_components as dmc
import pandas as pd
from dash import dcc, html
from dash_iconify import DashIconify

from .. import data, theme

# --------------------------------------------------------------------- #
# Filter option builders (called once at layout-build time)
# --------------------------------------------------------------------- #

def _unique_sorted(series: pd.Series) -> list[str]:
    return sorted(s for s in series.dropna().unique() if isinstance(s, str) and s.strip())


def _get_state_options() -> list[dict]:
    vals = ["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA", "NZ"]
    return [{"label": v, "value": v} for v in vals]


def _get_speciality_options() -> list[dict]:
    authors = data.load_authors()
    if authors.empty or "speciality_ahpra" not in authors.columns:
        return []
    # Explode semicolon-delimited specialities
    all_specs = (
        authors["speciality_ahpra"]
        .dropna()
        .str.split(";")
        .explode()
        .str.strip()
        .replace("", pd.NA)
        .dropna()
    )
    vals = sorted(all_specs.unique().tolist())
    return [{"label": v, "value": v} for v in vals[:30]]


def _get_year_range() -> tuple[int, int]:
    pubs = data.load_publications()
    if pubs.empty:
        return 2000, 2026
    for col in ("Year", "Publication_Year", "year"):
        if col in pubs.columns:
            years = pd.to_numeric(pubs[col], errors="coerce").dropna()
            if not years.empty:
                return int(years.min()), int(years.max())
    return 2000, 2026


def _get_pub_type_options() -> list[dict]:
    pubs = data.load_publications()
    if pubs.empty or "type" not in pubs.columns:
        return []
    vals = _unique_sorted(pubs["type"])
    return [{"label": v, "value": v} for v in vals[:20]]


def _get_country_options() -> list[dict]:
    authors = data.load_authors()
    if authors.empty or "institution_country" not in authors.columns:
        return []
    vals = _unique_sorted(authors["institution_country"])
    return [{"label": v, "value": v} for v in vals]


# --------------------------------------------------------------------- #
# Filter bar layout
# --------------------------------------------------------------------- #

def build_filter_bar() -> html.Div:
    """Return the collapsible filter bar + the hidden Store."""
    yr_min, yr_max = _get_year_range()

    filters = dmc.SimpleGrid(
        cols={"base": 1, "sm": 2, "md": 3, "lg": 4},
        spacing="sm",
        children=[
            dmc.MultiSelect(
                id="filter-state",
                label="State / Territory",
                placeholder="All",
                data=_get_state_options(),
                clearable=True,
                size="xs",
            ),
            dmc.MultiSelect(
                id="filter-speciality",
                label="Speciality",
                placeholder="All",
                data=_get_speciality_options(),
                clearable=True,
                size="xs",
            ),
            dmc.MultiSelect(
                id="filter-country",
                label="Country",
                placeholder="All",
                data=_get_country_options(),
                clearable=True,
                size="xs",
            ),
            dmc.RangeSlider(
                id="filter-year-range",
                label="Publication year",
                min=yr_min,
                max=yr_max,
                value=[yr_min, yr_max],
                marks=[
                    {"value": yr_min, "label": str(yr_min)},
                    {"value": yr_max, "label": str(yr_max)},
                ],
                size="xs",
                color="acd-copper",
                style={"paddingTop": "0.5rem"},
            ),
            dmc.TextInput(
                id="filter-text-search",
                label="Text search",
                placeholder="Search titles, keywords, members...",
                leftSection=DashIconify(icon="tabler:search", width=16),
                size="xs",
            ),
            dmc.Switch(
                id="filter-derm-only",
                label="Derm-relevant only",
                size="xs",
                color="acd-copper",
            ),
            dmc.MultiSelect(
                id="filter-pub-type",
                label="Publication type",
                placeholder="All",
                data=_get_pub_type_options(),
                clearable=True,
                size="xs",
            ),
        ],
    )

    return html.Div([
        # Toggle button
        dmc.Button(
            "Filters",
            id="filter-toggle-btn",
            variant="subtle",
            color="acd-copper",
            size="xs",
            leftSection=DashIconify(icon="tabler:filter", width=16),
            style={"marginLeft": "0.5rem"},
        ),
        # Collapsible filter panel
        dmc.Collapse(
            html.Div(
                [
                    filters,
                    dmc.Group(
                        [
                            dmc.Button(
                                "Clear all",
                                id="filter-clear-btn",
                                variant="subtle",
                                color="gray",
                                size="xs",
                            ),
                            dmc.Text(
                                id="filter-active-count",
                                size="xs",
                                c="dimmed",
                            ),
                        ],
                        justify="flex-end",
                        gap="sm",
                        mt="xs",
                    ),
                ],
                style={
                    "padding": "0.75rem 1.5rem",
                    "background": "#FAFAFA",
                    "borderBottom": f"1px solid {theme.GRAY_200}",
                },
            ),
            id="filter-collapse",
            opened=False,
        ),
        # Hidden store for serialised filter state
        dcc.Store(id="global-filters", data={}),
    ])


# --------------------------------------------------------------------- #
# Filter application helpers (used by page callbacks)
# --------------------------------------------------------------------- #

def apply_author_filters(
    df: pd.DataFrame,
    filters: dict[str, Any],
) -> pd.DataFrame:
    """Apply global filters to an authors-like DataFrame."""
    if not filters:
        return df

    state = filters.get("state", [])
    if state and "state" in df.columns:
        df = df[df["state"].isin(state)]

    speciality = filters.get("speciality", [])
    if speciality and "speciality_ahpra" in df.columns:
        mask = df["speciality_ahpra"].fillna("").apply(
            lambda s: any(sp in s for sp in speciality)
        )
        df = df[mask]

    country = filters.get("country", [])
    if country and "institution_country" in df.columns:
        df = df[df["institution_country"].isin(country)]

    return df


def apply_pub_filters(
    df: pd.DataFrame,
    filters: dict[str, Any],
    *,
    name_col: str = "acd_name",
) -> pd.DataFrame:
    """Apply global filters to a publications-like DataFrame."""
    if not filters:
        return df

    # Year range
    yr = filters.get("year_range")
    if yr:
        lo, hi = yr
        for col in ("Year", "year", "Publication_Year"):
            if col in df.columns:
                years = pd.to_numeric(df[col], errors="coerce")
                df = df[(years >= lo) & (years <= hi)]
                break

    # Derm-relevant flag
    if filters.get("derm_only") and "is_derm_relevant" in df.columns:
        df = df[df["is_derm_relevant"] == True]  # noqa: E712

    # Publication type
    pub_types = filters.get("pub_type", [])
    if pub_types and "type" in df.columns:
        df = df[df["type"].isin(pub_types)]

    # Text search — use full-text search index when available
    q = (filters.get("text_search") or "").strip().lower()
    if q:
        search_idx = data.load_search_index()
        if (
            not search_idx.empty
            and "Unique ID" in df.columns
            and "Unique ID" in search_idx.columns
            and "search_text" in search_idx.columns
        ):
            hits = search_idx[
                search_idx["search_text"].str.contains(q, regex=False, na=False)
            ]
            hit_ids = set(hits["Unique ID"].tolist())
            df = df[df["Unique ID"].isin(hit_ids)]
        elif "title" in df.columns:
            mask = df["title"].fillna("").str.lower().str.contains(q, regex=False)
            if name_col in df.columns:
                mask = mask | df[name_col].fillna("").str.lower().str.contains(q, regex=False)
            df = df[mask]

    return df


def get_filtered_names(filters: dict[str, Any]) -> frozenset[str] | None:
    """Return the set of member names matching author-level filters.

    Returns None if no author filters are active (= all members).
    Pages use this to pre-filter publications, funding etc.
    """
    if not filters:
        return None

    has_author_filter = any(
        filters.get(k) for k in ("state", "speciality", "country")
    )
    if not has_author_filter:
        return None

    authors = data.load_authors()
    if authors.empty:
        return None

    authors = apply_author_filters(authors, filters)
    accepted = data._accepted_name_set()
    name_col = "acd_name" if "acd_name" in authors.columns else authors.columns[0]
    if accepted:
        authors = authors[authors[name_col].isin(accepted)]
    return frozenset(authors[name_col].dropna().unique())
