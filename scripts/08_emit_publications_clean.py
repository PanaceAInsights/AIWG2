"""Phase 8: Emit publications_clean.csv for client validation.

Produces two deliverables for HealthConsult/RMSANZ:

1. ``data/processed/publications_clean.csv`` — all publications from
   accepted v4 members with a freshly computed ``is_rehab_relevant``
   column (True/False). This is the file sent to RMSANZ for their
   validity-check exercise.

2. ``data/processed/common_name_validation_shortlist.csv`` — members
   whose names are likely ambiguous in OpenAlex (common surnames,
   short/single-token first names, multiple roster entries sharing a
   surname). These are suggested for manual validation by RMSANZ
   contacts.

CLI::

    python scripts/08_emit_publications_clean.py
"""
from __future__ import annotations

import logging
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Re-use the rehab vocabulary and vectorized classifier from Phase 6
from scripts.utils.rehab_vocab import (
    REHAB_FIELD_TOKENS,
    REHAB_MESH_TOKENS,
    REHAB_TITLE_ABSTRACT_TOKENS,
    vectorized_relevance,
)

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"


def _load_accepted_names() -> set[str]:
    """Return the set of acd_name values accepted in v4."""
    for fname in ("authors_resolved_v4.csv", "authors_resolved_v3.csv"):
        path = PROCESSED / fname
        if path.exists():
            df = pd.read_csv(path, usecols=["acd_name", "accepted"], dtype=str)
            return set(df.loc[df["accepted"] == "1", "acd_name"])
    return set()


def _compute_common_name_risk(
    all_authors: pd.DataFrame,
    accepted_names: set[str],
) -> pd.DataFrame:
    """Build the common-name validation shortlist.

    Risk factors:
    - Surname shared by 2+ members in the full 600 roster
    - First name is <= 4 characters (e.g. "Yan", "Tim", "Su Yi")
    - First name is extremely common (top-100 English/Chinese given names)
    - Member has no AHPRA proof (no external ground-truth anchor)
    - Member's confidence is HIGH but with a low score_name signal
    """
    # Common first names that are globally ambiguous
    COMMON_FIRST_NAMES = {
        "james", "john", "david", "michael", "peter", "paul", "mark",
        "andrew", "ian", "adam", "sarah", "kate", "emma", "jessica",
        "elizabeth", "jason", "daniel", "stephen", "steven",
        "wei", "yan", "yi", "yu", "chen", "li", "lin", "jun", "jie",
        "hui", "hong", "lei", "ming", "ying", "yong", "xin", "fang",
        "tim", "tom", "ben", "sam", "amy", "kim", "lee", "jack",
        "grace", "sharon", "alan", "ryan", "jane", "anna",
    }

    records = []
    # Surname frequency across full roster
    surname_counts = Counter()
    for name in all_authors["acd_name"]:
        parts = str(name).strip().split()
        if parts:
            surname_counts[parts[-1]] += 1

    for _, row in all_authors.iterrows():
        name = str(row["acd_name"]).strip()
        if name not in accepted_names:
            continue

        parts = name.split()
        if not parts:
            continue

        surname = parts[-1]
        first_name = parts[0].lower() if len(parts) > 1 else ""
        full_first = " ".join(parts[:-1]).lower() if len(parts) > 1 else ""

        # Risk signals
        risk_factors = []
        risk_score = 0

        # Shared surname
        if surname_counts[surname] >= 3:
            risk_factors.append(f"surname '{surname}' shared by {surname_counts[surname]} members")
            risk_score += 3
        elif surname_counts[surname] == 2:
            risk_factors.append(f"surname '{surname}' shared by 2 members")
            risk_score += 1

        # Short first name
        if len(full_first) <= 3:
            risk_factors.append(f"very short first name '{full_first}'")
            risk_score += 2

        # Globally common first name
        if first_name in COMMON_FIRST_NAMES:
            risk_factors.append(f"common first name '{first_name}'")
            risk_score += 2

        # No AHPRA proof
        ahpra = str(row.get("ahpra_proven", "")).strip()
        if ahpra not in ("1", "True", "true"):
            risk_factors.append("no AHPRA proof")
            risk_score += 1

        # Only include if risk_score >= 3 (meaningful ambiguity)
        if risk_score >= 3:
            records.append({
                "acd_name": name,
                "openalex_id": row.get("openalex_id", ""),
                "openalex_display_name": row.get("openalex_display_name", ""),
                "last_known_institution": row.get("last_known_institution", ""),
                "institution_country": row.get("institution_country", ""),
                "confidence": row.get("confidence", ""),
                "ahpra_proven": ahpra,
                "risk_score": risk_score,
                "risk_factors": "; ".join(risk_factors),
                "suggested_validator": "",  # RMSANZ fills this
                "validation_status": "",    # RMSANZ fills this
            })

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values("risk_score", ascending=False).reset_index(drop=True)
    return df


def main() -> int:
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # ------------------------------------------------------------------ Load
    logging.info("Loading data...")
    accepted_names = _load_accepted_names()
    if not accepted_names:
        logging.error("No accepted members found. Run resolver first.")
        return 1
    logging.info("Accepted members: %d", len(accepted_names))

    pubs_path = PROCESSED / "publications.csv"
    if not pubs_path.exists():
        logging.error("publications.csv not found")
        return 1

    pubs = pd.read_csv(pubs_path, low_memory=False)
    logging.info("Total publications loaded: %d", len(pubs))

    # ----------------------------------------------------------- Filter to accepted
    pubs_clean = pubs[pubs["RAMS_Author"].isin(accepted_names)].copy()
    logging.info("Publications from accepted members: %d", len(pubs_clean))

    # ----------------------------------------------------------- Re-tag rehab relevance
    # Drop existing column if present (handles NaN from override enrichment)
    if "is_rehab_relevant" in pubs_clean.columns:
        pubs_clean = pubs_clean.drop(columns=["is_rehab_relevant"])

    logging.info("Computing rehab relevance tags...")
    relevance = vectorized_relevance(pubs_clean)
    pubs_clean["is_rehab_relevant"] = relevance.map({True: "True", False: "False"})

    rehab_count = int(relevance.sum())
    total = len(pubs_clean)
    logging.info(
        "Rehab relevant: %d / %d (%.1f%%)",
        rehab_count, total, (rehab_count / total * 100) if total else 0,
    )

    # ----------------------------------------------------------- Write publications_clean.csv
    out_path = PROCESSED / "publications_clean.csv"
    pubs_clean.to_csv(out_path, index=False, encoding="utf-8")
    logging.info("Written: %s (%d rows)", out_path.name, len(pubs_clean))

    # ----------------------------------------------------------- Common-name shortlist
    authors_path = PROCESSED / "authors_resolved_v4.csv"
    if not authors_path.exists():
        authors_path = PROCESSED / "authors_resolved_v3.csv"
    all_authors = pd.read_csv(authors_path, dtype=str).fillna("")

    shortlist = _compute_common_name_risk(all_authors, accepted_names)
    shortlist_path = PROCESSED / "common_name_validation_shortlist.csv"
    shortlist.to_csv(shortlist_path, index=False, encoding="utf-8")
    logging.info("Written: %s (%d members flagged)", shortlist_path.name, len(shortlist))

    # ----------------------------------------------------------- Summary
    print()
    print("=" * 70)
    print("PUBLICATIONS CLEAN - DELIVERY SUMMARY")
    print("=" * 70)
    print(f"Accepted members:            {len(accepted_names)}")
    print(f"Total publications:          {total:,}")
    print(f"  Rehab-relevant:            {rehab_count:,} ({rehab_count/total*100:.1f}%)")
    print(f"  Off-topic:                 {total - rehab_count:,} ({(total-rehab_count)/total*100:.1f}%)")
    print(f"Output file:                 {out_path}")
    print()
    print(f"Common-name validation shortlist: {len(shortlist)} members")
    print(f"Output file:                 {shortlist_path}")
    print()

    if not shortlist.empty:
        print("Top 15 highest-risk names for RMSANZ validation:")
        for _, r in shortlist.head(15).iterrows():
            print(
                f"  {r['acd_name']:<28s}  score={int(r['risk_score'])}  "
                f"inst={str(r['last_known_institution'])[:35]:<35s}  "
                f"risk: {r['risk_factors'][:60]}"
            )
        print()

    # Per-member breakdown
    print("Per-member publication counts (top 20 by rehab pubs):")
    member_stats = (
        pubs_clean.assign(_rel=relevance.astype(int))
        .groupby("RAMS_Author")
        .agg(total_pubs=("_rel", "count"), rehab_pubs=("_rel", "sum"))
        .reset_index()
    )
    member_stats["rehab_pct"] = member_stats["rehab_pubs"] / member_stats["total_pubs"]
    member_stats = member_stats.sort_values("rehab_pubs", ascending=False)
    for _, r in member_stats.head(20).iterrows():
        print(
            f"  {r['RAMS_Author']:<30s}  total={int(r['total_pubs']):>5d}  "
            f"rehab={int(r['rehab_pubs']):>4d}  ({r['rehab_pct']*100:.0f}%)"
        )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
