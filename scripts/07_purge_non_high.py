"""
07_purge_non_high.py
====================

Removes non-HIGH member data from all downstream processed CSVs.

This script is needed because the previous ETL run downloaded publications
for both HIGH and REVIEW members. Now that the resolver has been re-run and
the final HIGH set is known (348 members), we must purge all REVIEW/NOT_FOUND
contamination from:

  - publications.csv
  - publications_clean.csv
  - author_works_link.csv
  - _completed_authors.csv
  - author_summary_stats.csv (if it exists)

Also downloads publications for the 1 HIGH member not yet covered.

Usage:
    python scripts/07_purge_non_high.py [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("acd.purge")


def run(*, dry_run: bool = False) -> dict:
    # Load the authoritative HIGH set
    resolved = pd.read_csv(PROCESSED / "authors_resolved.csv", dtype=str).fillna("")
    high = resolved[resolved["confidence"] == "HIGH"]
    high_names = set(high["acd_name"].str.strip())
    high_ids = set(high["openalex_id"].str.strip())
    logger.info("HIGH set: %d members, %d OpenAlex IDs", len(high_names), len(high_ids))

    results = {}

    # ── 1. publications.csv ────────────────────────────────────────────────
    pubs_path = PROCESSED / "publications.csv"
    if pubs_path.exists():
        pubs = pd.read_csv(pubs_path)
        before = len(pubs)
        # Determine the author column name
        author_col = None
        for col in ("acd_name", "RAMS_Author", "author_name"):
            if col in pubs.columns:
                author_col = col
                break
        if author_col:
            pubs_clean = pubs[pubs[author_col].isin(high_names)].reset_index(drop=True)
        else:
            logger.warning("No author column found in publications.csv — skipping purge")
            pubs_clean = pubs
        after = len(pubs_clean)
        logger.info(
            "publications.csv: %d -> %d rows (removed %d non-HIGH rows)",
            before, after, before - after,
        )
        results["publications_purged"] = before - after
        if not dry_run:
            pubs_clean.to_csv(pubs_path, index=False)
            logger.info("Written %s", pubs_path)
    else:
        logger.warning("publications.csv not found — skipping")

    # ── 2. publications_clean.csv ──────────────────────────────────────────
    pubs_clean_path = PROCESSED / "publications_clean.csv"
    if pubs_clean_path.exists():
        pubs_c = pd.read_csv(pubs_clean_path)
        before = len(pubs_c)
        author_col = None
        for col in ("acd_name", "RAMS_Author", "author_name"):
            if col in pubs_c.columns:
                author_col = col
                break
        if author_col:
            pubs_c_clean = pubs_c[pubs_c[author_col].isin(high_names)].reset_index(drop=True)
        else:
            pubs_c_clean = pubs_c
        after = len(pubs_c_clean)
        logger.info(
            "publications_clean.csv: %d -> %d rows (removed %d non-HIGH rows)",
            before, after, before - after,
        )
        results["publications_clean_purged"] = before - after
        if not dry_run:
            pubs_c_clean.to_csv(pubs_clean_path, index=False)
            logger.info("Written %s", pubs_clean_path)
    else:
        logger.warning("publications_clean.csv not found — skipping")

    # ── 3. author_works_link.csv ───────────────────────────────────────────
    links_path = PROCESSED / "author_works_link.csv"
    if links_path.exists():
        links = pd.read_csv(links_path, dtype=str).fillna("")
        before = len(links)
        links_clean = links[links["acd_name"].isin(high_names)].reset_index(drop=True)
        after = len(links_clean)
        logger.info(
            "author_works_link.csv: %d -> %d rows (removed %d non-HIGH rows)",
            before, after, before - after,
        )
        results["links_purged"] = before - after
        if not dry_run:
            links_clean.to_csv(links_path, index=False)
            logger.info("Written %s", links_path)
    else:
        logger.warning("author_works_link.csv not found — skipping")

    # ── 4. _completed_authors.csv ──────────────────────────────────────────
    completed_path = PROCESSED / "_completed_authors.csv"
    if completed_path.exists():
        completed = pd.read_csv(completed_path, dtype=str).fillna("")
        before = len(completed)
        # Keep only HIGH OpenAlex IDs
        id_col = "openalex_author_id" if "openalex_author_id" in completed.columns else completed.columns[0]
        completed_clean = completed[completed[id_col].isin(high_ids)].reset_index(drop=True)
        after = len(completed_clean)
        logger.info(
            "_completed_authors.csv: %d -> %d rows (removed %d non-HIGH rows)",
            before, after, before - after,
        )
        results["completed_purged"] = before - after
        if not dry_run:
            completed_clean.to_csv(completed_path, index=False)
            logger.info("Written %s", completed_path)
    else:
        logger.warning("_completed_authors.csv not found — skipping")

    # ── 5. author_summary_stats.csv ───────────────────────────────────────
    stats_path = PROCESSED / "author_summary_stats.csv"
    if stats_path.exists():
        stats = pd.read_csv(stats_path, dtype=str).fillna("")
        before = len(stats)
        stats_clean = stats[stats["acd_name"].isin(high_names)].reset_index(drop=True)
        after = len(stats_clean)
        logger.info(
            "author_summary_stats.csv: %d -> %d rows (removed %d non-HIGH rows)",
            before, after, before - after,
        )
        results["stats_purged"] = before - after
        if not dry_run:
            stats_clean.to_csv(stats_path, index=False)
            logger.info("Written %s", stats_path)

    # ── 6. publications_search_index.csv ──────────────────────────────────
    search_path = PROCESSED / "publications_search_index.csv"
    if search_path.exists():
        search = pd.read_csv(search_path, dtype=str).fillna("")
        before = len(search)
        author_col = None
        for col in ("acd_name", "RAMS_Author", "author_name"):
            if col in search.columns:
                author_col = col
                break
        if author_col:
            search_clean = search[search[author_col].isin(high_names)].reset_index(drop=True)
        else:
            search_clean = search
        after = len(search_clean)
        logger.info(
            "publications_search_index.csv: %d -> %d rows (removed %d non-HIGH rows)",
            before, after, before - after,
        )
        results["search_purged"] = before - after
        if not dry_run:
            search_clean.to_csv(search_path, index=False)
            logger.info("Written %s", search_path)

    if dry_run:
        logger.info("DRY RUN: no files written")

    return results


def main(argv=None):
    p = argparse.ArgumentParser(description="Purge non-HIGH data from processed CSVs.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    results = run(dry_run=args.dry_run)
    print("\n" + "=" * 50)
    print("PURGE SUMMARY")
    print("=" * 50)
    for k, v in results.items():
        print(f"  {k:<30}: {v} rows removed")


if __name__ == "__main__":
    main()
