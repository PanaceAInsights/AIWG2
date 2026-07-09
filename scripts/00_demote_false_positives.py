"""
00_demote_false_positives.py
============================
Demote confirmed false-positive HIGH members back to REVIEW so they are
re-evaluated by the patched 01d_reprocess_review_queue.py.

Also adds their OpenAlex IDs to manual_fp_overrides.csv so the resolver
permanently blocks these profiles from being matched again.

Confirmed false positives (identified by forensic topic audit):
  - Dr Anil Mathew Kurien    → A5010710559 (cardiologist/anaesthesiologist)
  - Dr Gordon James Rennick  → A5078755072 (respiratory/allergy researcher)
  - Dr Karen Margaret Stapleton → A5075237798 (surgical oncologist)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESOLVED_CSV    = ROOT / "data" / "processed" / "authors_resolved.csv"
FP_OVERRIDES    = ROOT / "data" / "input" / "manual_fp_overrides.csv"

# Confirmed false positives: (acd_name, openalex_id_to_block, reason)
FALSE_POSITIVES = [
    (
        "Dr Anil Mathew Kurien",
        "A5010710559",
        "cardiologist/anaesthesiologist — topics: Atrial Fibrillation, Blood Coagulation (5 works, no derm)",
    ),
    (
        "Dr Gordon James Rennick",
        "A5078755072",
        "respiratory/allergy researcher — topics: Air Quality, Neonatal Respiratory (6 works, derm only at position 4)",
    ),
    (
        "Dr Karen Margaret Stapleton",
        "A5075237798",
        "surgical oncologist — topics: Sarcoma, Cardiac tumors (17 works, derm only at position 4)",
    ),
]


def main() -> None:
    print("=" * 60)
    print("00_demote_false_positives.py")
    print("=" * 60)

    # ── Step 1: Demote in authors_resolved.csv ───────────────────────────────
    resolved = pd.read_csv(RESOLVED_CSV, dtype=str).fillna("")
    fp_names = {name for name, _, _ in FALSE_POSITIVES}

    demoted = 0
    for i, row in resolved.iterrows():
        if row["acd_name"] in fp_names and row["confidence"] == "HIGH":
            resolved.at[i, "confidence"]        = "REVIEW"
            resolved.at[i, "accepted"]          = "0"
            resolved.at[i, "resolution_method"] = "demoted_false_positive"
            resolved.at[i, "reject_reason"]     = "coauth_bootstrap_false_positive"
            demoted += 1
            print(f"  DEMOTED: {row['acd_name']} ({row['openalex_id']}) HIGH → REVIEW")

    resolved.to_csv(RESOLVED_CSV, index=False)
    print(f"\n  {demoted} members demoted to REVIEW in {RESOLVED_CSV.name}")

    # ── Step 2: Add to manual_fp_overrides.csv ───────────────────────────────
    if FP_OVERRIDES.exists():
        fp_df = pd.read_csv(FP_OVERRIDES, dtype=str).fillna("")
    else:
        fp_df = pd.DataFrame(columns=["acd_name", "openalex_id_to_reject", "note"])

    existing_pairs = set(
        zip(fp_df["acd_name"].tolist(), fp_df["openalex_id_to_reject"].tolist())
    )

    new_rows = []
    for name, oa_id, note in FALSE_POSITIVES:
        if (name, oa_id) not in existing_pairs:
            new_rows.append({
                "acd_name": name,
                "openalex_id_to_reject": oa_id,
                "note": note,
            })
            print(f"  FP OVERRIDE ADDED: {name} → block {oa_id}")
        else:
            print(f"  FP OVERRIDE ALREADY EXISTS: {name} → {oa_id}")

    if new_rows:
        fp_df = pd.concat([fp_df, pd.DataFrame(new_rows)], ignore_index=True)
        fp_df.to_csv(FP_OVERRIDES, index=False)
        print(f"\n  {len(new_rows)} entries added to {FP_OVERRIDES.name}")

    print("\nDone. Run 01d_reprocess_review_queue.py to re-evaluate demoted members.")


if __name__ == "__main__":
    main()
