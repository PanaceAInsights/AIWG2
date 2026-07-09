"""ACD Research Intelligence Platform — centralised data loader.

All dashboard pages import from this module. Data is loaded once at startup
and cached in module-level variables. Pages call the public functions below.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger("acd.data")

_ROOT = Path(__file__).resolve().parent.parent
_PROCESSED = _ROOT / "data" / "processed"

# ---------------------------------------------------------------------------
# Internal loaders (called once at startup)
# ---------------------------------------------------------------------------

def _safe_read(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        logger.warning("Data file not found: %s", path)
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False, **kwargs)
    except Exception as exc:
        logger.error("Failed to load %s: %s", path, exc)
        return pd.DataFrame()


@lru_cache(maxsize=1)
def load_authors() -> pd.DataFrame:
    df = _safe_read(_PROCESSED / "authors_resolved.csv")
    if df.empty:
        return df
    # Normalise confidence tier capitalisation
    if "confidence" in df.columns:
        df["confidence"] = df["confidence"].str.upper().fillna("NOT_FOUND")
    # Boolean helpers
    for col in ("accepted", "ahpra_proven", "aunz_ever"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().isin(("1", "True", "true", "yes"))
    # Ensure numeric
    if "works_count" in df.columns:
        df["works_count"] = pd.to_numeric(df["works_count"], errors="coerce").fillna(0).astype(int)
    if "total_score" in df.columns:
        df["total_score"] = pd.to_numeric(df["total_score"], errors="coerce").fillna(0)
    return df


@lru_cache(maxsize=1)
def load_publications() -> pd.DataFrame:
    df = _safe_read(_PROCESSED / "publications_clean.csv")
    if df.empty:
        return df
    # Normalise year column name
    if "Publication_Year" in df.columns and "Year" not in df.columns:
        df["Year"] = pd.to_numeric(df["Publication_Year"], errors="coerce")
    elif "Year" in df.columns:
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
    # Normalise author column name
    if "RAMS_Author" in df.columns and "acd_name" not in df.columns:
        df["acd_name"] = df["RAMS_Author"]
    # Normalise citations column name
    for col in ("Citations", "CitedByCount", "cited_by_count"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            if col != "CitedByCount":
                df["CitedByCount"] = df[col]
            break
    if "is_derm_relevant" in df.columns:
        df["is_derm_relevant"] = df["is_derm_relevant"].astype(str).str.lower().isin(("true", "1", "yes"))
    # Join state from authors if not present
    if "state" not in df.columns and "acd_name" in df.columns:
        authors = _safe_read(_PROCESSED / "authors_resolved.csv")
        if not authors.empty and "state" in authors.columns:
            state_map = authors.set_index("acd_name")["state"].to_dict()
            df["state"] = df["acd_name"].map(state_map)
    return df


@lru_cache(maxsize=1)
def load_funding() -> pd.DataFrame:
    df = _safe_read(_PROCESSED / "funding.csv")
    if df.empty:
        return df
    for col in ("amount", "Amount", "award_amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@lru_cache(maxsize=1)
def load_clinical_trials() -> pd.DataFrame:
    df = _safe_read(_PROCESSED / "clinical_trials.csv")
    if df.empty:
        return df
    for col in ("start_date", "completion_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@lru_cache(maxsize=1)
def load_stats() -> pd.DataFrame:
    # Try both filenames for backward compatibility
    p1 = _PROCESSED / "author_summary_stats.csv"
    p2 = _PROCESSED / "member_stats.csv"
    df = _safe_read(p1 if p1.exists() else p2)
    if df.empty:
        return df
    # Add column aliases for backward compatibility with dashboard pages
    if "citation_count" in df.columns and "total_citations" not in df.columns:
        df["total_citations"] = df["citation_count"]
    if "pub_count" in df.columns and "total_works" not in df.columns:
        df["total_works"] = df["pub_count"]
    # Join state from authors if not present
    if "state" not in df.columns and "acd_name" in df.columns:
        authors = _safe_read(_PROCESSED / "authors_resolved.csv")
        if not authors.empty and "state" in authors.columns:
            state_map = authors.set_index("acd_name")["state"].to_dict()
            df["state"] = df["acd_name"].map(state_map)
    return df


@lru_cache(maxsize=1)
def load_search_index() -> pd.DataFrame:
    # Try both filenames for backward compatibility
    p1 = _PROCESSED / "publications_search_index.csv"
    p2 = _PROCESSED / "search_index.csv"
    return _safe_read(p1 if p1.exists() else p2)


# ---------------------------------------------------------------------------
# Public helpers used by pages
# ---------------------------------------------------------------------------

def resolved_roster(
    confidence: Optional[list[str]] = None,
    state: Optional[str] = None,
    priority: Optional[str] = None,
) -> pd.DataFrame:
    """Return filtered authors frame."""
    df = load_authors()
    if df.empty:
        return df
    if confidence:
        df = df[df["confidence"].isin([c.upper() for c in confidence])]
    if state and state != "All":
        df = df[df["state"] == state]
    if priority and priority != "All":
        df = df[df["priority"] == priority]
    return df


def publications_for_member(acd_name: str) -> pd.DataFrame:
    pubs = load_publications()
    if pubs.empty or "acd_name" not in pubs.columns:
        return pd.DataFrame()
    return pubs[pubs["acd_name"] == acd_name].copy()


def trials_for_member(acd_name: str) -> pd.DataFrame:
    trials = load_clinical_trials()
    if trials.empty or "acd_name" not in trials.columns:
        return pd.DataFrame()
    return trials[trials["acd_name"] == acd_name].copy()


def funding_for_member(acd_name: str) -> pd.DataFrame:
    fund = load_funding()
    if fund.empty or "acd_name" not in fund.columns:
        return pd.DataFrame()
    return fund[fund["acd_name"] == acd_name].copy()


def stats_for_member(acd_name: str) -> dict:
    stats = load_stats()
    if stats.empty or "acd_name" not in stats.columns:
        return {}
    row = stats[stats["acd_name"] == acd_name]
    if row.empty:
        return {}
    return row.iloc[0].to_dict()


def get_all_states() -> list[str]:
    df = load_authors()
    if df.empty or "state" not in df.columns:
        return []
    return sorted(df["state"].dropna().unique().tolist())


def get_all_subtopics() -> list[str]:
    pubs = load_publications()
    if pubs.empty or "SubTopic" not in pubs.columns:
        return []
    return sorted(pubs["SubTopic"].dropna().unique().tolist())


def get_summary_kpis() -> dict:
    """Return top-level KPI values for the overview page."""
    authors = load_authors()
    pubs    = load_publications()
    trials  = load_clinical_trials()
    funding = load_funding()

    n_resolved  = int(authors["accepted"].sum()) if not authors.empty and "accepted" in authors.columns else 0
    n_total     = len(authors)
    n_review    = int((authors.get("confidence", pd.Series()) == "REVIEW").sum()) if not authors.empty else 0
    n_pubs      = len(pubs)
    n_derm_pubs = int(pubs["is_derm_relevant"].sum()) if not pubs.empty and "is_derm_relevant" in pubs.columns else 0
    n_trials    = len(trials)
    n_funded    = int(funding["acd_name"].nunique()) if not funding.empty and "acd_name" in funding.columns else 0

    total_citations = 0
    if not pubs.empty:
        for col in ("Citations", "CitedByCount", "cited_by_count"):
            if col in pubs.columns:
                total_citations = int(pubs[col].fillna(0).sum())
                break

    return {
        "n_total":         n_total,
        "n_resolved":      n_resolved,
        "n_review":        n_review,
        "n_pubs":          n_pubs,
        "n_derm_pubs":     n_derm_pubs,
        "n_trials":        n_trials,
        "n_funded":        n_funded,
        "total_citations": total_citations,
    }


# ---------------------------------------------------------------------------
# Per-member helper functions for profile pages
# ---------------------------------------------------------------------------

import re as _re


def make_slug(name: str) -> str:
    """Convert an ACD member name to a URL-safe slug."""
    return _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def slug_to_name(slug: str) -> str | None:
    """Reverse-lookup: find the acd_name matching a URL slug."""
    authors = load_authors()
    if authors.empty:
        return None
    for name in authors["acd_name"]:
        if make_slug(str(name)) == slug:
            return name
    return None


def member_keywords(acd_name: str, top_n: int = 12) -> list[str]:
    """Return top keywords for a member from the publications CSV."""
    pubs = load_publications()
    if pubs.empty or "acd_name" not in pubs.columns:
        return []
    p = pubs[pubs["acd_name"] == acd_name]
    if "Keywords" not in p.columns:
        return []
    kw = (
        p["Keywords"].dropna()
        .str.split("|")
        .explode()
        .str.strip()
        .str.lower()
    )
    kw = kw[kw.str.len() > 2]
    if kw.empty:
        return []
    return kw.value_counts().head(top_n).index.tolist()


def member_subtopics(acd_name: str, top_n: int = 8) -> list[str]:
    """Return top SubTopics for a member from the publications CSV."""
    pubs = load_publications()
    if pubs.empty or "acd_name" not in pubs.columns:
        return []
    p = pubs[pubs["acd_name"] == acd_name]
    if "SubTopic" not in p.columns:
        return []
    st = p["SubTopic"].dropna()
    if st.empty:
        return []
    return st.value_counts().head(top_n).index.tolist()


def member_orcid(acd_name: str) -> str | None:
    """Return the most common ORCID for a member from the publications CSV."""
    pubs = load_publications()
    if pubs.empty or "acd_name" not in pubs.columns:
        return None
    p = pubs[pubs["acd_name"] == acd_name]
    if "ORCIDs" not in p.columns:
        return None
    orcids = (
        p["ORCIDs"].dropna()
        .str.split("|")
        .explode()
        .str.strip()
    )
    orcids = orcids[orcids.str.len() > 5]
    orcids = orcids[orcids.str.lower() != "none"]
    if orcids.empty:
        return None
    return orcids.value_counts().index[0]


def member_coauthors(acd_name: str, top_n: int = 30) -> pd.DataFrame:
    """Return top co-authors for a member with shared publication counts.

    Returns a DataFrame with columns: coauthor_name, shared_pubs.
    """
    pubs = load_publications()
    if pubs.empty or "acd_name" not in pubs.columns or "Author_Names" not in pubs.columns:
        return pd.DataFrame(columns=["coauthor_name", "shared_pubs"])
    p = pubs[pubs["acd_name"] == acd_name]
    if p.empty:
        return pd.DataFrame(columns=["coauthor_name", "shared_pubs"])
    # Explode Author_Names (pipe-separated)
    coauthors = (
        p["Author_Names"].dropna()
        .str.split("|")
        .explode()
        .str.strip()
    )
    # Remove the member themselves (fuzzy: last name match)
    last_name = acd_name.split()[-1].lower()
    coauthors = coauthors[~coauthors.str.lower().str.contains(last_name, na=False)]
    coauthors = coauthors[coauthors.str.len() > 2]
    if coauthors.empty:
        return pd.DataFrame(columns=["coauthor_name", "shared_pubs"])
    counts = coauthors.value_counts().head(top_n).reset_index()
    counts.columns = ["coauthor_name", "shared_pubs"]
    return counts


def member_detail(acd_name: str) -> dict | None:
    """Return a merged dict of author + stats for a member."""
    authors = load_authors()
    if authors.empty:
        return None
    row = authors[authors["acd_name"] == acd_name]
    if row.empty:
        return None
    d = row.iloc[0].to_dict()
    stats = stats_for_member(acd_name)
    if stats:
        # Stats values override authors values for computed metrics
        _STATS_OVERRIDE_KEYS = {"h_index", "citation_count", "pub_count", "fwci_mean",
                                "grants_count", "trial_count", "oa_rate", "intl_collab_rate",
                                "derm_relevance_rate", "percentile_citations", "percentile_fwci"}
        for k, v in stats.items():
            if k in _STATS_OVERRIDE_KEYS or k not in d:
                d[k] = v
    # Clean speciality_ahpra — strip leading/trailing semicolons and spaces
    if d.get("speciality_ahpra"):
        sp = str(d["speciality_ahpra"]).strip("; ").strip()
        d["speciality_ahpra"] = sp if sp else None
    return d
