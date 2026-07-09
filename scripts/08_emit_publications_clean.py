"""Phase 8: Emit publications_clean.csv for ACD dashboard.

Produces two deliverables:

1. ``data/processed/publications_clean.csv`` — all publications from
   accepted HIGH members with a freshly computed ``is_derm_relevant``
   column (True/False). This is the clean file used by the dashboard.

2. ``data/processed/common_name_validation_shortlist.csv`` — members
   whose names are likely ambiguous in OpenAlex (common surnames,
   short/single-token first names, multiple roster entries sharing a
   surname). These are suggested for manual validation.

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

# Re-use the derm vocabulary and vectorized classifier from Phase 6
from scripts.utils.derm_vocab import (
    DERM_FIELD_TOKENS,
    DERM_MESH_TOKENS,
    DERM_TITLE_ABSTRACT_TOKENS,
    vectorized_relevance,
)

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"


def _load_accepted_names() -> set[str]:
    """Return the set of acd_name values with confidence=HIGH."""
    path = PROCESSED / "authors_resolved.csv"
    if path.exists():
        df = pd.read_csv(path, usecols=["acd_name", "confidence"], dtype=str)
        return set(df.loc[df["confidence"] == "HIGH", "acd_name"])
    return set()


def _compute_common_name_risk(
    all_authors: pd.DataFrame,
    accepted_names: set[str],
) -> pd.DataFrame:
    """Build the common-name validation shortlist.

    Risk factors:
    - Surname shared by 2+ members in the full roster
    - First name is <= 4 characters (e.g. "Yan", "Tim", "Su Yi")
    - First name is extremely common (top-100 English/Chinese given names)
    - Member has no AHPRA proof (no external ground-truth anchor)
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

        # Only include if risk_score >= 3 (meaningful ambiguity)
        if risk_score >= 3:
            records.append({
                "acd_name": name,
                "openalex_id": row.get("openalex_id", ""),
                "openalex_display_name": row.get("openalex_display_name", ""),
                "last_known_institution": row.get("last_known_institution", ""),
                "institution_country": row.get("institution_country", ""),
                "confidence": row.get("confidence", ""),
                "risk_score": risk_score,
                "risk_factors": "; ".join(risk_factors),
                "validation_status": "",
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
        logging.error("No accepted HIGH members found. Run resolver first.")
        return 1
    logging.info("Accepted HIGH members: %d", len(accepted_names))

    pubs_path = PROCESSED / "publications.csv"
    if not pubs_path.exists():
        logging.error("publications.csv not found")
        return 1

    pubs = pd.read_csv(pubs_path, low_memory=False)
    logging.info("Total publications loaded: %d", len(pubs))

    # ----------------------------------------------------------- Filter to accepted HIGH members
    pubs_clean = pubs[pubs["RAMS_Author"].isin(accepted_names)].copy()
    logging.info("Publications from HIGH members: %d", len(pubs_clean))

    # ----------------------------------------------------------- Tag derm relevance
    # Drop existing column if present
    for col in ("is_derm_relevant", "is_rehab_relevant"):
        if col in pubs_clean.columns:
            pubs_clean = pubs_clean.drop(columns=[col])

    logging.info("Computing derm relevance tags...")
    relevance = vectorized_relevance(pubs_clean)
    pubs_clean["is_derm_relevant"] = relevance.map({True: "True", False: "False"})

    derm_count = int(relevance.sum())
    total = len(pubs_clean)
    logging.info(
        "Derm relevant: %d / %d (%.1f%%)",
        derm_count, total, (derm_count / total * 100) if total else 0,
    )

    # ----------------------------------------------------------- Filter out pre-1960 data errors
    if "Publication_Year" in pubs_clean.columns:
        year_col = pd.to_numeric(pubs_clean["Publication_Year"], errors="coerce")
        pre_1960 = (year_col < 1960) & year_col.notna()
        if pre_1960.sum() > 0:
            logging.info("Dropping %d pre-1960 data errors", pre_1960.sum())
            pubs_clean = pubs_clean[~pre_1960].copy()
            relevance = relevance[~pre_1960]
            derm_count = int(relevance.sum())
            total = len(pubs_clean)

    # ----------------------------------------------------------- Write publications_clean.csv
    out_path = PROCESSED / "publications_clean.csv"
    pubs_clean.to_csv(out_path, index=False, encoding="utf-8")
    logging.info("Written: %s (%d rows)", out_path.name, len(pubs_clean))

    # ----------------------------------------------------------- Common-name shortlist
    authors_path = PROCESSED / "authors_resolved.csv"
    if authors_path.exists():
        all_authors = pd.read_csv(authors_path, dtype=str).fillna("")
        shortlist = _compute_common_name_risk(all_authors, accepted_names)
        shortlist_path = PROCESSED / "common_name_validation_shortlist.csv"
        shortlist.to_csv(shortlist_path, index=False, encoding="utf-8")
        logging.info("Written: %s (%d members flagged)", shortlist_path.name, len(shortlist))
    else:
        shortlist = pd.DataFrame()
        logging.warning("authors_resolved.csv not found — skipping shortlist")

    # ----------------------------------------------------------- Summary
    print()
    print("=" * 70)
    print("PUBLICATIONS CLEAN - DELIVERY SUMMARY")
    print("=" * 70)
    print(f"Accepted HIGH members:       {len(accepted_names)}")
    print(f"Total publications:          {total:,}")
    print(f"  Derm-relevant:             {derm_count:,} ({derm_count/total*100:.1f}%)" if total else "  Derm-relevant:             0")
    print(f"  Off-topic:                 {total - derm_count:,} ({(total-derm_count)/total*100:.1f}%)" if total else "  Off-topic:                 0")
    print(f"Output file:                 {out_path}")
    print()
    print(f"Common-name validation shortlist: {len(shortlist)} members")
    print()

    # Per-member breakdown (top 20)
    print("Per-member publication counts (top 20 by derm pubs):")
    member_stats = (
        pubs_clean.assign(_rel=relevance.astype(int))
        .groupby("RAMS_Author")
        .agg(total_pubs=("_rel", "count"), derm_pubs=("_rel", "sum"))
        .reset_index()
    )
    member_stats["derm_pct"] = member_stats["derm_pubs"] / member_stats["total_pubs"]
    member_stats = member_stats.sort_values("derm_pubs", ascending=False)
    for _, r in member_stats.head(20).iterrows():
        print(
            f"  {r['RAMS_Author']:<30s}  total={int(r['total_pubs']):>5d}  "
            f"derm={int(r['derm_pubs']):>4d}  ({r['derm_pct']*100:.0f}%)"
        )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
