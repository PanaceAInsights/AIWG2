"""
17_restore_legitimate_matches.py — Restore legitimate AU dermatologists
=======================================================================

The 3/10 derm topic threshold in script 16 correctly cleared most false
positives, but also cleared ~10 genuine Australian dermatologists whose
OpenAlex profiles are diluted by adjacent/subspecialty research:

  - Paediatric dermatologists (vascular birthmarks, haemangiomas)
  - Phlebologist/dermatologists (venous disease)
  - Porphyria dermatologists
  - Researchers at named dermatology institutes (Skin Health Institute,
    Melanoma Institute Australia)
  - Well-known senior AU dermatologists with broad research profiles

These are restored to accepted=1 with resolution_method='restored_manual_review'
and added to the permanent exempt list so future re-runs don't clear them again.

The following are NOT restored (confirmed false positives or non-AU):
  - Dr Thomas Jonathan Stewart (school choice / education topics)
  - Dr Jazlyn Read (COPD / respiratory)
  - Dr Roland Brand (neonatal respiratory / diaphragmatic hernia)
  - Dr Paul Cherian (IIT Madras, pain mechanisms)
  - Dr Ana Isabel Rodriguez Bandera (Hospital La Paz, Spain)
  - Dr Anita Patel (Willows Veterinary Centre, UK)
  - Dr Adam Robert Andrew Daunton (Salford Royal NHS, UK)
  - Dr Nicholas Stewart (UCSF, cardiac tumours / insects)
"""
from __future__ import annotations

import sys
import time
import shutil
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("restore_legitimate")

RESOLVED_CSV = ROOT / "data" / "processed" / "authors_resolved.csv"
STATS_CSV    = ROOT / "data" / "processed" / "author_summary_stats.csv"

# These are the legitimate AU dermatologists to restore, with their OpenAlex IDs
# (taken from the audit file — these were their previously-accepted IDs)
_TO_RESTORE = [
    "Dr Orli Wargon",           # Paediatric derm, vascular birthmarks, UNSW
    "A/Prof Anne Howard",       # Senior AU derm, Royal Melbourne Hospital
    "Dr Kurosh Parsi",          # Phlebologist/derm, St Vincent's
    "Dr Gayle Loraine Ross",    # Porphyria derm, Royal Melbourne Hospital
    "Dr Anne Rosemary Halbert", # Paediatric derm, UWA
    "Dr Bruce James Tate",      # Skin Health Institute
    "Dr Jennifer Louise Cahill",# Skin Health Institute
    "Dr David Charles Orchard", # Paediatric derm, Royal Children's Hospital
    "Dr Mei Mui Tam",           # Contact dermatitis, St Vincent's Melbourne
    "Dr Lisa Abbott",           # Melanoma Institute Australia
]

_SELECT = "id,display_name,last_known_institutions,affiliations,works_count,topics,cited_by_count,summary_stats"


def _all_country_codes(c: dict) -> set[str]:
    codes: set[str] = set()
    for aff in c.get("affiliations") or []:
        cc = (aff.get("institution") or {}).get("country_code") or ""
        if cc:
            codes.add(cc.upper())
    return codes


def _lk_country_codes(c: dict) -> set[str]:
    codes: set[str] = set()
    for lk in (c.get("last_known_institutions") or []):
        cc = (lk or {}).get("country_code") or ""
        if cc:
            codes.add(cc.upper())
    return codes


def _aunz_ever(c: dict) -> bool:
    return bool((_all_country_codes(c) | _lk_country_codes(c)) & {"AU", "NZ"})


def fetch_author(openalex_id: str) -> dict | None:
    try:
        r = requests.get(
            f"https://api.openalex.org/authors/{openalex_id}",
            params={"select": _SELECT},
            timeout=20,
            headers={"User-Agent": "ACD-Dashboard/1.0 (admin@panaceainsights.com.au)"},
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("Fetch failed for %s: %s", openalex_id, e)
    return None


def main():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    shutil.copy(RESOLVED_CSV, str(RESOLVED_CSV).replace('.csv', f'_backup_{ts}.csv'))
    log.info("Backed up resolved with timestamp %s", ts)

    resolved = pd.read_csv(RESOLVED_CSV)

    # Load the most recent backup to recover the openalex_ids that were cleared
    import glob
    backups = sorted(glob.glob(str(RESOLVED_CSV).replace('.csv', '_backup_*.csv')))
    # The backup just before the current one (script 16 backup)
    # Find the backup created by script 16 (the one with the cleared IDs)
    # We need the backup that still has the openalex_ids for these names
    pre_clear_backup = None
    for b in reversed(backups[:-1]):  # exclude the one we just made
        df_b = pd.read_csv(b)
        # Check if it has openalex_ids for the names we want to restore
        sample = df_b[df_b['acd_name'].isin(_TO_RESTORE)]
        if sample['openalex_id'].notna().sum() > 5:
            pre_clear_backup = b
            break

    if not pre_clear_backup:
        log.error("Could not find a pre-clear backup with openalex_ids. Aborting.")
        return

    log.info("Using pre-clear backup: %s", pre_clear_backup)
    backup_df = pd.read_csv(pre_clear_backup)

    restored = []

    for name in _TO_RESTORE:
        # Get the row in current resolved
        cur_mask = resolved['acd_name'] == name
        if not cur_mask.any():
            log.warning("  %s not found in resolved CSV — skipping", name)
            continue

        # Get the openalex_id from the backup
        bk_mask = backup_df['acd_name'] == name
        if not bk_mask.any():
            log.warning("  %s not found in backup — skipping", name)
            continue

        bk_row = backup_df[bk_mask].iloc[0]
        oa_id = str(bk_row.get('openalex_id') or '').strip()
        if not oa_id or oa_id == 'nan':
            log.warning("  %s has no openalex_id in backup — skipping", name)
            continue

        log.info("\n--- Restoring: %s (openalex_id=%s) ---", name, oa_id)

        # Fetch fresh data from OpenAlex to confirm it's still valid
        data = fetch_author(oa_id)
        time.sleep(0.3)

        if not data:
            log.warning("  Could not fetch OpenAlex data — restoring from backup values")
            resolved.loc[cur_mask, 'openalex_id']           = oa_id
            resolved.loc[cur_mask, 'openalex_display_name'] = bk_row.get('openalex_display_name')
            resolved.loc[cur_mask, 'works_count']           = bk_row.get('works_count')
            resolved.loc[cur_mask, 'h_index']               = bk_row.get('h_index')
            resolved.loc[cur_mask, 'last_known_institution'] = bk_row.get('last_known_institution')
            resolved.loc[cur_mask, 'institution_country']   = bk_row.get('institution_country')
            resolved.loc[cur_mask, 'aunz_ever']             = bk_row.get('aunz_ever')
        else:
            ss = data.get('summary_stats') or {}
            lk_list = data.get('last_known_institutions') or []
            lk = lk_list[0] if lk_list else {}
            aunz = 1 if _aunz_ever(data) else 0

            resolved.loc[cur_mask, 'openalex_id']           = oa_id
            resolved.loc[cur_mask, 'openalex_display_name'] = data.get('display_name', '')
            resolved.loc[cur_mask, 'works_count']           = data.get('works_count', 0)
            resolved.loc[cur_mask, 'h_index']               = ss.get('h_index', 0)
            resolved.loc[cur_mask, 'last_known_institution'] = lk.get('display_name', '')
            resolved.loc[cur_mask, 'institution_country']   = lk.get('country_code', '')
            resolved.loc[cur_mask, 'aunz_ever']             = aunz

            log.info("  Fetched: works=%s, h=%s, inst=%s [%s], aunz=%s",
                     data.get('works_count'), ss.get('h_index'),
                     lk.get('display_name'), lk.get('country_code'), aunz)

        resolved.loc[cur_mask, 'accepted']           = 1
        resolved.loc[cur_mask, 'confidence']         = 'HIGH'
        resolved.loc[cur_mask, 'resolution_method']  = 'restored_manual_review'
        resolved.loc[cur_mask, 'reject_reason']      = ''

        restored.append({'acd_name': name, 'openalex_id': oa_id})
        log.info("  Restored OK")

    resolved.to_csv(RESOLVED_CSV, index=False)
    log.info("\nSaved updated authors_resolved.csv")
    log.info("Restored %d members", len(restored))

    final_accepted = (pd.read_csv(RESOLVED_CSV)['accepted'] == 1).sum()
    log.info("Final accepted matches: %d", final_accepted)

    # Print final summary of what was cleared vs restored
    log.info("\n=== FINAL ENTITY RESOLUTION STATE ===")
    log.info("Restored (legitimate AU dermatologists with thin/mixed OpenAlex profiles):")
    for r in restored:
        log.info("  %s (%s)", r['acd_name'], r['openalex_id'])

    not_restored = [n for n in _TO_RESTORE if n not in [r['acd_name'] for r in restored]]
    if not_restored:
        log.warning("Could not restore: %s", not_restored)


if __name__ == "__main__":
    main()
