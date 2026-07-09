"""
01d_reprocess_review_queue.py
=============================

Targeted re-resolution of the existing REVIEW queue.

This script applies the three new passes to members already in REVIEW:

1. Veto 2 re-check: Re-apply the inverted derm-positive hard filter to all
   REVIEW members. Any prolific profile (>20 works) with no derm topics is
   immediately moved to NOT_FOUND. This catches false positives that passed
   the old wrong-specialty filter.

2. Pass 2b (co-authorship bootstrap): For remaining REVIEW members with an
   OpenAlex ID, check co-authorship with the HIGH seed ring. +30 pts for
   confirmed shared publication.

3. Pass 3 (LLM adjudication): Apply the new single comprehensive prompt to
   all remaining REVIEW members.

4. Update authors_resolved.csv in-place with the new verdicts.

Usage:
    python scripts/01d_reprocess_review_queue.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.utils.openalex_client import OpenAlexClient  # noqa: E402
from scripts.utils.budget import CreditBudget, BudgetExhausted  # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("acd.reprocess")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Import the resolver functions via importlib (module name starts with digit)
import importlib.util as _ilu

def _load_resolver():
    spec = _ilu.spec_from_file_location(
        "resolver",
        ROOT / "scripts" / "01c_resolve_authors.py",
    )
    mod = _ilu.module_from_spec(spec)
    sys.modules["resolver"] = mod
    spec.loader.exec_module(mod)
    return mod

_resolver = _load_resolver()

_DERM_TOKENS                = _resolver._DERM_TOKENS
_is_derm_topic              = _resolver._is_derm_topic
_topic_labels               = _resolver._topic_labels
_P1_ACCEPT                  = _resolver._P1_ACCEPT
build_context               = _resolver.build_context
run_pass2b_coauth_bootstrap = _resolver.run_pass2b_coauth_bootstrap
run_pass3_llm               = _resolver.run_pass3_llm
OUTPUT_COLUMNS              = _resolver.OUTPUT_COLUMNS

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROCESSED = ROOT / "data" / "processed"
LOGS      = ROOT / "data" / "logs"
AUTHORS_CSV = PROCESSED / "authors_resolved.csv"
REVIEW_CSV  = PROCESSED / "review_queue.csv"
EVIDENCE_LOG = LOGS / "01d_reprocess.log"

# ---------------------------------------------------------------------------
# Veto 2 re-check (inverted derm-positive)
# ---------------------------------------------------------------------------
def _reconstruct_candidate_from_row(row: dict) -> dict:
    """
    Reconstruct a minimal candidate dict from a resolved CSV row.
    Used to re-apply hard filters without re-querying OpenAlex.
    Note: topics are NOT stored in the resolved CSV, so we cannot
    re-apply Veto 2 from stored data alone. We must query OpenAlex.
    """
    return {
        "display_name": row.get("openalex_display_name", ""),
        "works_count": int(row.get("works_count") or 0),
        "last_known_institutions": [
            {
                "display_name": row.get("last_known_institution", ""),
                "country_code": row.get("institution_country", ""),
            }
        ],
        "affiliations": [],
        "topics": [],  # Not stored — must fetch from OpenAlex if needed
        "summary_stats": {"h_index": int(row.get("h_index") or 0)},
    }


def _fetch_topics(openalex_id: str, client: OpenAlexClient) -> list[dict]:
    """Fetch the top topics for an OpenAlex author profile."""
    try:
        payload = client.get(
            f"/authors/{openalex_id}",
            params={"select": "topics,works_count"},
            allow_404=True,
        )
        return (payload or {}).get("topics") or []
    except Exception as exc:
        logger.warning("Failed to fetch topics for %s: %s", openalex_id, exc)
        return []


def apply_veto2_recheck(
    review_rows: list[dict],
    client: OpenAlexClient,
    evidence_f,
) -> tuple[list[dict], list[dict]]:
    """
    Re-apply Veto 2 (inverted derm-positive) to all REVIEW rows.
    Returns (remaining_review, newly_rejected).
    Fetches topics from OpenAlex for each candidate.
    """
    remaining = []
    rejected = []
    for row in tqdm(review_rows, desc="Veto 2 re-check", leave=False):
        oa_id = str(row.get("openalex_id") or "").strip()
        works = int(row.get("works_count") or 0)

        if not oa_id or works <= 20:
            # No ID or sparse profile — exempt from Veto 2
            remaining.append(row)
            continue

        # Fetch topics from OpenAlex
        topics = _fetch_topics(oa_id, client)
        topic_labels = _topic_labels({"topics": topics}, n=5)

        if topic_labels:
            has_derm = any(_is_derm_topic(lbl) for lbl in topic_labels)
            if not has_derm:
                evidence_f.write(
                    f"  [Veto 2 recheck] {row['acd_name']}: REJECTED "
                    f"(works={works}, topics={topic_labels[:2]})\n"
                )
                row["confidence"] = "NOT_FOUND"
                row["accepted"] = "0"
                row["reject_reason"] = "no_derm_topic_in_prolific_profile"
                row["resolution_method"] = "veto2_recheck"
                rejected.append(row)
                time.sleep(0.2)
                continue

        remaining.append(row)
        time.sleep(0.2)

    logger.info(
        "Veto 2 re-check: %d rejected, %d remaining in REVIEW",
        len(rejected), len(remaining),
    )
    return remaining, rejected


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(
    *,
    dry_run: bool = False,
    limit: Optional[int] = None,
    budget_limit: int = 50_000,
) -> dict[str, Any]:
    LOGS.mkdir(parents=True, exist_ok=True)
    evidence_f = EVIDENCE_LOG.open("a", encoding="utf-8")
    evidence_f.write(
        f"\n===== 01d reprocess review queue @ {datetime.now().isoformat()} =====\n"
    )

    # Load full resolved CSV
    all_df = pd.read_csv(AUTHORS_CSV, dtype=str).fillna("")
    all_rows = all_df.to_dict("records")
    logger.info("Loaded %d total rows from %s", len(all_rows), AUTHORS_CSV)

    # Extract REVIEW rows
    review_rows = [r for r in all_rows if r.get("confidence") == "REVIEW"]
    logger.info("REVIEW queue: %d members", len(review_rows))

    if limit:
        review_rows = review_rows[:limit]
        logger.info("Limited to %d REVIEW members", len(review_rows))

    # Build HIGH seed ring
    high_ids = {
        str(r["openalex_id"]).strip()
        for r in all_rows
        if r.get("confidence") == "HIGH" and r.get("openalex_id")
    }
    logger.info("HIGH seed ring: %d IDs", len(high_ids))

    # OpenAlex client
    budget = CreditBudget(
        daily_limit=budget_limit,
        state_path=LOGS / "credit_usage.json",
    )
    client = OpenAlexClient(
        email=os.environ.get("OPENALEX_EMAIL", ""),
        api_key=os.environ.get("OPENALEX_API_KEY", ""),
        base_url=os.environ.get("OPENALEX_BASE_URL") or "https://api.openalex.org",
        session=requests.Session(),
        max_retries=2,
        on_success=lambda _: budget.charge(1),
    )

    # ── Step 1: Veto 2 re-check ──────────────────────────────────────────────
    logger.info("Step 1: Veto 2 re-check (inverted derm-positive)")
    review_rows, veto2_rejected = apply_veto2_recheck(review_rows, client, evidence_f)

    # ── Step 2: Co-authorship bootstrap ──────────────────────────────────────
    logger.info("Step 2: Co-authorship bootstrap (%d REVIEW, %d HIGH seeds)",
                len(review_rows), len(high_ids))
    review_rows = run_pass2b_coauth_bootstrap(review_rows, high_ids, client, evidence_f)

    # Update HIGH seed ring with newly elevated members
    newly_high = [r for r in review_rows if r.get("confidence") == "HIGH"]
    high_ids |= {str(r["openalex_id"]).strip() for r in newly_high if r.get("openalex_id")}
    still_review = [r for r in review_rows if r.get("confidence") == "REVIEW"]
    logger.info(
        "After coauth: %d elevated to HIGH, %d still REVIEW",
        len(newly_high), len(still_review),
    )

    # ── Step 3: LLM adjudication ─────────────────────────────────────────────
    logger.info("Step 3: LLM adjudication (%d REVIEW members)", len(still_review))
    if still_review:
        still_review = run_pass3_llm(still_review, client, evidence_f)

    # Merge all updated rows back
    all_updated = veto2_rejected + newly_high + still_review
    updated_map = {r["acd_name"]: r for r in all_updated}

    final_rows = []
    for row in all_rows:
        if row["acd_name"] in updated_map:
            final_rows.append(updated_map[row["acd_name"]])
        else:
            final_rows.append(row)

    # Compute final counts
    final_counts = {
        "HIGH": sum(1 for r in final_rows if r.get("confidence") == "HIGH"),
        "REVIEW": sum(1 for r in final_rows if r.get("confidence") == "REVIEW"),
        "NOT_FOUND": sum(1 for r in final_rows if r.get("confidence") == "NOT_FOUND"),
    }
    logger.info("Final counts: %s", final_counts)

    if not dry_run:
        # Write updated authors_resolved.csv
        final_df = pd.DataFrame([{k: r.get(k, "") for k in OUTPUT_COLUMNS} for r in final_rows])
        final_df.to_csv(AUTHORS_CSV, index=False)
        logger.info("Written %d rows to %s", len(final_df), AUTHORS_CSV)

        # Write updated review_queue.csv
        review_final = [r for r in final_rows if r.get("confidence") == "REVIEW"]
        if review_final:
            pd.DataFrame(review_final).to_csv(REVIEW_CSV, index=False)
    else:
        logger.info("DRY RUN: no files written")

    evidence_f.close()
    return final_counts


def main(argv=None):
    p = argparse.ArgumentParser(description="Re-process REVIEW queue with new passes.")
    p.add_argument("--dry-run", action="store_true", help="Do not write output files")
    p.add_argument("--limit", type=int, default=None, help="Process only N REVIEW members")
    p.add_argument("--budget", type=int, default=50_000)
    args = p.parse_args(argv)

    result = run(dry_run=args.dry_run, limit=args.limit, budget_limit=args.budget)
    print("\n" + "=" * 50)
    print("REPROCESS REVIEW QUEUE SUMMARY")
    print("=" * 50)
    for k, v in result.items():
        print(f"  {k:<12}: {v}")


if __name__ == "__main__":
    main()
