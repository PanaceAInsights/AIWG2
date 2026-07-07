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
    if "Year" in df.columns:
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
    for col in ("CitedByCount", "cited_by_count"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if "is_derm_relevant" in df.columns:
        df["is_derm_relevant"] = df["is_derm_relevant"].astype(str).str.lower().isin(("true", "1", "yes"))
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
    return _safe_read(_PROCESSED / "member_stats.csv")


@lru_cache(maxsize=1)
def load_search_index() -> pd.DataFrame:
    return _safe_read(_PROCESSED / "search_index.csv")


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
        for col in ("CitedByCount", "cited_by_count"):
            if col in pubs.columns:
                total_citations = int(pubs[col].sum())
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
