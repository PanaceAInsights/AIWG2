"""ACD Research Intelligence Platform — centralised data loader.

Mirrors the RMSANZ dashboard data.py pattern:
- All loaders are cached with functools.lru_cache (one parse per process).
- _accepted_name_set() returns only HIGH-confidence members (accepted==1 or confidence==HIGH).
- Every downstream loader (publications, stats, funding) filters to this set,
  so REVIEW false-positives never contaminate charts or KPIs.
- usecols on publications keeps memory within Render Starter 512 MB RAM.
"""
from __future__ import annotations

import functools
import json
import logging
import re as _re
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger("acd.data")

_ROOT = Path(__file__).resolve().parent.parent
_PROCESSED = _ROOT / "data" / "processed"


# ---------------------------------------------------------------------------
# Internal CSV reader
# ---------------------------------------------------------------------------

def _read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        logger.warning("CSV missing: %s", path)
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8", low_memory=False, **kwargs)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="latin-1", low_memory=False, **kwargs)
    except Exception as exc:
        logger.error("Failed to load %s: %s", path, exc)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def load_authors() -> pd.DataFrame:
    """Full roster (all 669 members). Used for member count KPIs and resolver stats."""
    df = _read_csv(_PROCESSED / "authors_resolved.csv")
    if df.empty:
        return df
    if "confidence" in df.columns:
        df["confidence"] = df["confidence"].str.upper().fillna("NOT_FOUND")
    for col in ("accepted", "ahpra_proven", "aunz_ever"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().isin(("1", "True", "true", "yes"))
    for col in ("works_count", "total_score", "h_index"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    # Clean speciality_ahpra
    if "speciality_ahpra" in df.columns:
        df["speciality_ahpra"] = (
            df["speciality_ahpra"].astype(str)
            .str.strip("; ")
            .str.strip()
            .replace({"nan": None, "": None})
        )
    return df


@functools.lru_cache(maxsize=1)
def _accepted_name_set() -> frozenset[str]:
    """Names of HIGH-confidence members only.

    All publication/stats/funding loaders filter through this set so that
    REVIEW false-positives never appear in charts or KPIs.
    """
    authors = load_authors()
    if authors.empty:
        return frozenset()
    # Prefer explicit accepted==1 flag; fall back to confidence==HIGH
    if "accepted" in authors.columns and authors["accepted"].any():
        sel = authors["accepted"] == True  # noqa: E712
    elif "confidence" in authors.columns:
        sel = authors["confidence"] == "HIGH"
    else:
        sel = pd.Series(True, index=authors.index)
    col = "acd_name" if "acd_name" in authors.columns else authors.columns[0]
    return frozenset(n for n in authors.loc[sel, col].tolist() if isinstance(n, str))


@functools.lru_cache(maxsize=1)
def load_publications() -> pd.DataFrame:
    """Publications for HIGH-confidence members only (filtered at load time).

    Uses usecols to keep the in-memory DataFrame small (~20 MB vs ~75 MB full).
    """
    p = _PROCESSED / "publications_clean.csv"
    if not p.exists():
        p = _PROCESSED / "publications.csv"
    # Read header to build tolerant usecols
    try:
        header = pd.read_csv(p, encoding="utf-8", nrows=0).columns.tolist()
    except Exception:
        return pd.DataFrame()
    wanted = {
        "Unique ID", "RAMS_Author", "DOI", "Title", "Publication_Year",
        "Publication_Date", "Type", "FWCI", "Citations", "Retracted",
        "Language", "PMID", "Author_Names", "ORCIDs", "Keywords",
        "SubTopic", "Topic", "Topic_Field", "Topic_Domain",
        "Open_Access", "OA_Type", "is_derm_relevant",
        "Top_1%", "Top_10%",
    }
    usecols = [c for c in header if c in wanted]
    df = _read_csv(p, usecols=usecols if usecols else None)
    if df.empty:
        return df
    # Rename to canonical names
    rename = {
        "RAMS_Author": "acd_name",
        "Publication_Year": "Year",
        "FWCI": "fwci",
        "Citations": "citations",
        "Type": "type",
        "DOI": "doi",
        "Title": "title",
        "Retracted": "retracted",
        "Language": "language",
        "PMID": "pmid",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    # Coerce numerics
    for c in ("Year",):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("citations", "fwci"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Boolean flags
    for c in ("retracted", "is_derm_relevant"):
        if c in df.columns:
            df[c] = df[c].astype(str).str.lower().isin(("true", "1", "yes"))
    # Alias for backward compatibility
    if "citations" in df.columns:
        df["Citations"] = df["citations"]
        df["CitedByCount"] = df["citations"]
    if "Year" in df.columns:
        df["Publication_Year"] = df["Year"]
    # Filter to HIGH-confidence members only
    accepted = _accepted_name_set()
    if accepted and "acd_name" in df.columns:
        df = df[df["acd_name"].isin(accepted)].reset_index(drop=True)
    # Join state from authors
    if "state" not in df.columns and "acd_name" in df.columns:
        authors = load_authors()
        if not authors.empty and "state" in authors.columns:
            state_map = authors.set_index("acd_name")["state"].to_dict()
            df["state"] = df["acd_name"].map(state_map)
    return df


@functools.lru_cache(maxsize=1)
def load_stats() -> pd.DataFrame:
    """Per-author stats, filtered to HIGH-confidence members only."""
    p = _PROCESSED / "author_summary_stats.csv"
    if not p.exists():
        p = _PROCESSED / "member_stats.csv"
    df = _read_csv(p)
    if df.empty:
        return df
    numeric_cols = [
        "pub_count", "citation_count", "h_index", "fwci_mean", "fwci_median",
        "oa_rate", "intl_collab_rate", "grants_count", "trial_count",
        "derm_relevance_rate", "first_year", "last_year",
    ] + [c for c in df.columns if c.endswith("_pctile") or c.endswith("_percentile")]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Column aliases for backward compatibility (both directions)
    if "citation_count" in df.columns and "total_citations" not in df.columns:
        df["total_citations"] = df["citation_count"]
    if "pub_count" in df.columns and "total_works" not in df.columns:
        df["total_works"] = df["pub_count"]
    # Reverse aliases: works_count/total_citations → pub_count/citation_count
    if "works_count" in df.columns and "pub_count" not in df.columns:
        df["pub_count"] = df["works_count"]
    if "total_citations" in df.columns and "citation_count" not in df.columns:
        df["citation_count"] = df["total_citations"]
    # Join state
    if "state" not in df.columns and "acd_name" in df.columns:
        authors = load_authors()
        if not authors.empty and "state" in authors.columns:
            state_map = authors.set_index("acd_name")["state"].to_dict()
            df["state"] = df["acd_name"].map(state_map)
    # Filter to HIGH-confidence members only
    accepted = _accepted_name_set()
    if accepted and "acd_name" in df.columns:
        df = df[df["acd_name"].isin(accepted)].reset_index(drop=True)
    return df


@functools.lru_cache(maxsize=1)
def load_funding() -> pd.DataFrame:
    """Funding data, filtered to HIGH-confidence members only."""
    df = _read_csv(_PROCESSED / "funding.csv")
    if df.empty:
        return df
    for col in ("amount", "Amount", "award_amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    accepted = _accepted_name_set()
    if accepted and "acd_name" in df.columns:
        df = df[df["acd_name"].isin(accepted)].reset_index(drop=True)
    return df


@functools.lru_cache(maxsize=1)
def load_clinical_trials() -> pd.DataFrame:
    """Clinical trials — not filtered (trials are matched by name, not OpenAlex ID)."""
    df = _read_csv(_PROCESSED / "clinical_trials.csv")
    if df.empty:
        return df
    for col in ("start_date", "completion_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@functools.lru_cache(maxsize=1)
def load_search_index() -> pd.DataFrame:
    p1 = _PROCESSED / "publications_search_index.csv"
    p2 = _PROCESSED / "search_index.csv"
    df = _read_csv(p1 if p1.exists() else p2)
    if not df.empty and "RAMS_Author" in df.columns:
        df = df.rename(columns={"RAMS_Author": "acd_name"})
    return df


@functools.lru_cache(maxsize=1)
def _load_json(filename: str) -> dict:
    """Load a JSON file from the processed data directory."""
    p = _PROCESSED / filename
    if not p.exists():
        logger.warning("JSON missing: %s", p)
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Failed to load %s: %s", p, exc)
        return {}


@functools.lru_cache(maxsize=1)
def load_counts_by_year() -> dict:
    """Load per-author yearly publication/citation counts."""
    return _load_json("author_counts_by_year.json")


@functools.lru_cache(maxsize=1)
def load_grants() -> dict:
    """Load per-author grants/funders/awards data."""
    return _load_json("author_grants.json")


@functools.lru_cache(maxsize=1)
def load_topics_detail() -> dict:
    """Load per-author detailed topic breakdown."""
    return _load_json("author_topics_detail.json")


def member_counts_by_year(acd_name: str) -> list[dict]:
    """Return yearly publication/citation counts for a member."""
    # Lookup by openalex_id
    stats = load_stats()
    if stats.empty or "acd_name" not in stats.columns:
        return []
    row = stats[stats["acd_name"] == acd_name]
    if row.empty or "openalex_id" not in row.columns:
        return []
    oa_id = str(row.iloc[0].get("openalex_id", "")).strip()
    if not oa_id or oa_id == "nan":
        return []
    data_dict = load_counts_by_year()
    entry = data_dict.get(oa_id, {})
    return entry.get("counts_by_year", [])


def member_grants_detail(acd_name: str) -> dict:
    """Return grants/funders/awards for a member."""
    stats = load_stats()
    if stats.empty or "acd_name" not in stats.columns:
        return {"funders": [], "awards": []}
    row = stats[stats["acd_name"] == acd_name]
    if row.empty or "openalex_id" not in row.columns:
        return {"funders": [], "awards": []}
    oa_id = str(row.iloc[0].get("openalex_id", "")).strip()
    if not oa_id or oa_id == "nan":
        return {"funders": [], "awards": []}
    data_dict = load_grants()
    entry = data_dict.get(oa_id, {})
    return {"funders": entry.get("funders", []), "awards": entry.get("awards", [])}


def member_topics_detail(acd_name: str) -> list[dict]:
    """Return detailed topic breakdown for a member."""
    stats = load_stats()
    if stats.empty or "acd_name" not in stats.columns:
        return []
    row = stats[stats["acd_name"] == acd_name]
    if row.empty or "openalex_id" not in row.columns:
        return []
    oa_id = str(row.iloc[0].get("openalex_id", "")).strip()
    if not oa_id or oa_id == "nan":
        return []
    data_dict = load_topics_detail()
    entry = data_dict.get(oa_id, {})
    return entry.get("topics", [])


def reload() -> None:
    """Invalidate all loader caches (useful in debug mode)."""
    for fn in (load_authors, _accepted_name_set, load_publications, load_stats,
               load_funding, load_clinical_trials, load_search_index,
               _subtopics_map, _keywords_map, _orcid_map,
               load_counts_by_year, load_grants, load_topics_detail, _load_json):
        fn.cache_clear()


# ---------------------------------------------------------------------------
# Public view helpers
# ---------------------------------------------------------------------------

def resolved_roster(
    confidence: Optional[list[str]] = None,
    state: Optional[str] = None,
    priority: Optional[str] = None,
) -> pd.DataFrame:
    """Return HIGH-confidence members only (the accepted cohort).

    Passing confidence=['HIGH','REVIEW'] will include REVIEW members for
    admin/debug views, but the default (None) returns HIGH only.
    """
    df = load_authors()
    if df.empty:
        return df
    if confidence:
        df = df[df["confidence"].isin([c.upper() for c in confidence])]
    else:
        # Default: HIGH only
        df = df[df["confidence"] == "HIGH"]
    if state and state != "All":
        df = df[df["state"] == state]
    if priority and priority != "All":
        df = df[df["priority"] == priority]
    return df.reset_index(drop=True)


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
    """Return top-level KPI values for the overview page.

    Member counts use the full roster; publication/citation KPIs use
    the HIGH-only filtered publications.
    """
    authors = load_authors()
    pubs    = load_publications()   # already filtered to HIGH
    trials  = load_clinical_trials()
    funding = load_funding()        # already filtered to HIGH

    n_total     = len(authors)
    n_high      = int((authors["confidence"] == "HIGH").sum()) if not authors.empty else 0
    n_review    = int((authors["confidence"] == "REVIEW").sum()) if not authors.empty else 0
    n_not_found = int((authors["confidence"] == "NOT_FOUND").sum()) if not authors.empty else 0
    n_pubs      = len(pubs)
    n_derm_pubs = int(pubs["is_derm_relevant"].sum()) if not pubs.empty and "is_derm_relevant" in pubs.columns else 0
    n_trials    = len(trials)
    n_funded    = int(funding["acd_name"].nunique()) if not funding.empty and "acd_name" in funding.columns else 0

    total_citations = 0
    if not pubs.empty:
        for col in ("citations", "Citations", "CitedByCount"):
            if col in pubs.columns:
                total_citations = int(pubs[col].fillna(0).sum())
                break

    return {
        "n_total":         n_total,
        "n_high":          n_high,
        "n_review":        n_review,
        "n_not_found":     n_not_found,
        "n_pubs":          n_pubs,
        "n_derm_pubs":     n_derm_pubs,
        "n_trials":        n_trials,
        "n_funded":        n_funded,
        "total_citations": total_citations,
    }


# ---------------------------------------------------------------------------
# RMSANZ-compatible aliases (used by pages that mirror the RMSANZ pattern)
# ---------------------------------------------------------------------------

def load_summary() -> pd.DataFrame:
    """Alias for load_stats() — matches RMSANZ data.py API."""
    return load_stats()


def member_publications(acd_name: str) -> pd.DataFrame:
    """Alias for publications_for_member() — matches RMSANZ data.py API."""
    return publications_for_member(acd_name)


def member_funding(acd_name: str) -> pd.DataFrame:
    """Alias for funding_for_member() — matches RMSANZ data.py API."""
    return funding_for_member(acd_name)


def member_trials(acd_name: str) -> pd.DataFrame:
    """Alias for trials_for_member() — matches RMSANZ data.py API."""
    return trials_for_member(acd_name)


# ---------------------------------------------------------------------------
# Per-member helpers for profile pages
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Pre-computed per-member lookup maps  (built once, O(1) per lookup)
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _subtopics_map(top_n: int = 8) -> dict[str, list[str]]:
    """Pre-compute top SubTopics for every member in a single groupby pass.

    Replaces the O(N) per-member scan with a single O(1) dictionary lookup.
    Called once on first access; result is cached for the process lifetime.
    """
    pubs = load_publications()
    if pubs.empty or "acd_name" not in pubs.columns or "SubTopic" not in pubs.columns:
        return {}
    result: dict[str, list[str]] = {}
    for name, grp in pubs.groupby("acd_name", sort=False):
        st = grp["SubTopic"].dropna()
        if not st.empty:
            result[name] = st.value_counts().head(top_n).index.tolist()
        else:
            result[name] = []
    return result


@functools.lru_cache(maxsize=1)
def _keywords_map(top_n: int = 12) -> dict[str, list[str]]:
    """Pre-compute top Keywords for every member in a single groupby pass."""
    pubs = load_publications()
    if pubs.empty or "acd_name" not in pubs.columns or "Keywords" not in pubs.columns:
        return {}
    result: dict[str, list[str]] = {}
    for name, grp in pubs.groupby("acd_name", sort=False):
        kw = (
            grp["Keywords"].dropna()
            .str.split("|")
            .explode()
            .str.strip()
            .str.lower()
        )
        kw = kw[kw.str.len() > 2]
        result[name] = kw.value_counts().head(top_n).index.tolist() if not kw.empty else []
    return result


@functools.lru_cache(maxsize=1)
def _orcid_map() -> dict[str, str | None]:
    """Pre-compute most common ORCID for every member in a single groupby pass."""
    pubs = load_publications()
    if pubs.empty or "acd_name" not in pubs.columns or "ORCIDs" not in pubs.columns:
        return {}
    result: dict[str, str | None] = {}
    for name, grp in pubs.groupby("acd_name", sort=False):
        orcids = (
            grp["ORCIDs"].dropna()
            .str.split("|")
            .explode()
            .str.strip()
        )
        orcids = orcids[(orcids.str.len() > 5) & (orcids.str.lower() != "none")]
        result[name] = orcids.value_counts().index[0] if not orcids.empty else None
    return result


def member_keywords(acd_name: str, top_n: int = 12) -> list[str]:
    """Return top keywords for a member — O(1) via pre-computed map."""
    return _keywords_map(top_n).get(acd_name, [])


def member_subtopics(acd_name: str, top_n: int = 8) -> list[str]:
    """Return top SubTopics for a member — O(1) via pre-computed map."""
    return _subtopics_map(top_n).get(acd_name, [])


def member_orcid(acd_name: str) -> str | None:
    """Return the most common ORCID for a member — O(1) via pre-computed map."""
    return _orcid_map().get(acd_name)


def member_coauthors(acd_name: str, top_n: int = 30) -> pd.DataFrame:
    """Return top co-authors for a member with shared publication counts."""
    pubs = load_publications()
    if pubs.empty or "acd_name" not in pubs.columns or "Author_Names" not in pubs.columns:
        return pd.DataFrame(columns=["coauthor_name", "shared_pubs"])
    p = pubs[pubs["acd_name"] == acd_name]
    if p.empty:
        return pd.DataFrame(columns=["coauthor_name", "shared_pubs"])
    coauthors = (
        p["Author_Names"].dropna()
        .str.split("|")
        .explode()
        .str.strip()
    )
    last_name = acd_name.split()[-1].lower()
    coauthors = coauthors[~coauthors.str.lower().str.contains(last_name, na=False)]
    coauthors = coauthors[coauthors.str.len() > 2]
    if coauthors.empty:
        return pd.DataFrame(columns=["coauthor_name", "shared_pubs"])
    counts = coauthors.value_counts().head(top_n).reset_index()
    counts.columns = ["coauthor_name", "shared_pubs"]
    return counts


def member_detail(acd_name: str) -> dict | None:
    """Return a merged dict of author + stats for a member.

    Stats values override authors values for computed metrics (h_index, etc.)
    because the stats CSV is computed from the actual publications, while the
    authors CSV may have stale values from the resolver.
    """
    authors = load_authors()
    if authors.empty:
        return None
    row = authors[authors["acd_name"] == acd_name]
    if row.empty:
        return None
    d = row.iloc[0].to_dict()
    stats = stats_for_member(acd_name)
    if stats:
        _STATS_OVERRIDE_KEYS = {
            "h_index", "citation_count", "pub_count", "fwci_mean",
            "grants_count", "trial_count", "oa_rate", "intl_collab_rate",
            "derm_relevance_rate", "percentile_citations", "percentile_fwci",
            "total_citations", "total_works",
        }
        for k, v in stats.items():
            if k in _STATS_OVERRIDE_KEYS or k not in d:
                d[k] = v
    # Clean speciality_ahpra
    if d.get("speciality_ahpra"):
        sp = str(d["speciality_ahpra"]).strip("; ").strip()
        d["speciality_ahpra"] = sp if sp and sp != "nan" else None
    return d
