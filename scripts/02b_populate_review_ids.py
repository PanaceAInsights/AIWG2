#!/usr/bin/env python3
"""
Populate openalex_id for REVIEW-tier members in authors_resolved.csv.

The resolver intentionally blanks openalex_id for REVIEW members (accepted=0).
Stage 2 needs the openalex_id to download publications for REVIEW members.
This script re-searches OpenAlex for each REVIEW member using their
openalex_display_name and populates the openalex_id column.
"""
from __future__ import annotations
import os
import sys
import time
import logging
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from scripts.utils.openalex_client import OpenAlexClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("acd.populate_review_ids")

PROCESSED = ROOT / "data" / "processed"
AUTHORS_CSV = PROCESSED / "authors_resolved.csv"

EMAIL = os.environ.get("OPENALEX_EMAIL", "dr.biohacker@gmail.com")
API_KEY = os.environ.get("OPENALEX_API_KEY", "ds37d6AdeCWZKI9CuRE8z0")

_SELECT = "id,display_name,works_count,last_known_institutions"


def _strip_id(raw: str) -> str:
    """Strip OpenAlex URL prefix."""
    for prefix in ("https://openalex.org/", "http://openalex.org/"):
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw


def search_author_by_name(client: OpenAlexClient, display_name: str) -> str | None:
    """Search OpenAlex for an author by display name and return their ID."""
    query = display_name.strip().replace(' ', '+')
    if not query:
        return None
    
    try:
        rq = f"filter=display_name.search:{query}&per-page=5&select={_SELECT}"
        results = client.get("/authors", allow_404=True, raw_query=rq)
        items = results.get("results", [])
        if not items:
            return None
        
        # Find best match by display_name similarity
        query_lower = display_name.strip().lower()
        for item in items:
            item_name = (item.get("display_name") or "").lower()
            # Exact or very close match
            if item_name == query_lower:
                return _strip_id(item.get("id", ""))
        
        # Return first result if no exact match
        raw_id = items[0].get("id", "")
        return _strip_id(raw_id) if raw_id else None
        
    except Exception as e:
        logger.warning(f"Search failed for '{display_name}': {e}")
        return None


def main():
    df = pd.read_csv(AUTHORS_CSV, dtype=str).fillna("")
    
    # Find REVIEW members without openalex_id but with openalex_display_name
    review_mask = (
        (df["confidence"] == "REVIEW") & 
        (df["openalex_id"].str.strip() == "") & 
        (df["openalex_display_name"].str.strip() != "")
    )
    review_df = df[review_mask]
    
    logger.info(f"REVIEW members without openalex_id: {len(review_df)}")
    
    if len(review_df) == 0:
        logger.info("No REVIEW members need ID population")
        return
    
    client = OpenAlexClient(email=EMAIL, api_key=API_KEY)
    
    updated = 0
    failed = 0
    
    for idx, row in review_df.iterrows():
        display_name = row["openalex_display_name"].strip()
        acd_name = row["acd_name"]
        
        openalex_id = search_author_by_name(client, display_name)
        
        if openalex_id:
            df.at[idx, "openalex_id"] = openalex_id
            df.at[idx, "profile_url"] = f"https://openalex.org/{openalex_id}"
            updated += 1
            logger.info(f"  {acd_name} → {openalex_id} ({display_name})")
        else:
            failed += 1
            logger.warning(f"  {acd_name}: no ID found for '{display_name}'")
        
        time.sleep(0.5)  # polite delay
    
    logger.info(f"Updated: {updated}, Failed: {failed}")
    
    # Save back
    df.to_csv(AUTHORS_CSV, index=False)
    logger.info(f"Saved to {AUTHORS_CSV}")
    
    # Summary
    df2 = pd.read_csv(AUTHORS_CSV, dtype=str).fillna("")
    review_with_id = ((df2["confidence"] == "REVIEW") & (df2["openalex_id"].str.strip() != "")).sum()
    logger.info(f"REVIEW members with openalex_id after update: {review_with_id}")


if __name__ == "__main__":
    main()
