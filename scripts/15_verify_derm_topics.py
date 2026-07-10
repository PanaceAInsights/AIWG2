"""
15_verify_derm_topics.py — Verify dermatology topic consistency for all accepted matches
========================================================================================

For every accepted match with works_count > 20, fetch the OpenAlex topic data
and verify at least one of the top-10 topics is dermatology-related.

If a match has zero derm topics AND works > 20 → it is a false positive (wrong person
matched by name/institution alone). Clear it.

This catches cases like Kevin Phan (spinal surgeon at RPA, AU institution but
zero derm topics) that passed the aunz_ever check but are clearly wrong.
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
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("verify_derm_topics")

RESOLVED_CSV = ROOT / "data" / "processed" / "authors_resolved.csv"
STATS_CSV    = ROOT / "data" / "processed" / "author_summary_stats.csv"

_DERM_TOKENS = frozenset([
    "dermatol", "melanom", "skin cancer", "psoriasis", "eczema",
    "atopic dermatitis", "vitiligo", "alopecia", "rosacea", "acne",
    "cutaneous", "mohs", "phototherap", "dermoscop", "urticaria",
    "pemphigus", "pemphigoid", "bullous", "hidradenitis", "ichthyosis",
    "onychomycosis", "hyperhidrosis", "pruritus", "basal cell",
    "squamous cell", "skin neoplasm", "skin disease", "skin lesion",
    "wound heal", "scleroderma", "lupus erythematosus", "vasculitis",
    "photosensit", "photoprotect", "sunscreen", "sunburn",
    "nail", "hair loss", "hair disorder", "sebaceous",
])

# Known high-volume researchers who are genuinely AU dermatologists
# (their OpenAlex profile may have mixed topics due to broad research)
_HIGH_VOLUME_EXCEPTIONS = {
    "Dr Hans Peter Soyer",
    "Prof Rodney Daniel Sinclair",
    "Prof Deirdre Frances Murrell",
    "Prof Ingrid Margaret Winship",
    "Dr Peter Anthony Foley",
    "Dr Simone Goldinger",
    "A/Prof Gayle Fischer",
    "Dr Diona Lee Damian",
    "Dr Helmut Schaider",
    "Dr Rosemary Louise Nixon",
    "Dr Sarah Louise Smithson",
    "Dr Steven Kossard",
    "Dr Johannes Steffen Kern",
    "Dr John Walter Frew",
    "Dr Deshan Sebaratnam",
    "Dr Lynda Jane Spelman",
}

_SELECT = "id,display_name,topics,works_count,last_known_institutions"


def _topic_labels(data: dict, n: int = 10) -> list[str]:
    labels = []
    for t in (data.get("topics") or [])[:n]:
        label = " ".join([
            t.get("display_name") or "",
            (t.get("subfield") or {}).get("display_name") or "",
            (t.get("field") or {}).get("display_name") or "",
        ]).lower()
        labels.append(label)
    return labels


def _has_derm(labels: list[str]) -> bool:
    return any(any(tok in lbl for tok in _DERM_TOKENS) for lbl in labels)


def fetch_topics(openalex_id: str) -> dict | None:
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
    shutil.copy(STATS_CSV,    str(STATS_CSV).replace('.csv',    f'_backup_{ts}.csv'))
    log.info("Backed up with timestamp %s", ts)

    resolved = pd.read_csv(RESOLVED_CSV)
    stats    = pd.read_csv(STATS_CSV)

    resolved['works_count_num'] = pd.to_numeric(resolved['works_count'], errors='coerce').fillna(0)

    # Targets: accepted=1, works>20, has an openalex_id, not in exceptions
    targets_mask = (
        (resolved['accepted'] == 1) &
        (resolved['works_count_num'] > 20) &
        (resolved['openalex_id'].notna()) &
        (~resolved['acd_name'].isin(_HIGH_VOLUME_EXCEPTIONS))
    )
    targets = resolved[targets_mask].copy()
    log.info("Checking %d accepted matches with works>20 for derm topic consistency", len(targets))

    cleared = []
    verified = []

    for idx, row in targets.iterrows():
        name = row['acd_name']
        oa_id = str(row['openalex_id']).strip()
        if not oa_id or oa_id == 'nan':
            continue

        data = fetch_topics(oa_id)
        time.sleep(0.3)

        if not data:
            log.warning("  Could not fetch topics for %s (%s) — skipping", name, oa_id)
            continue

        topic_labels = _topic_labels(data, n=10)
        has_derm = _has_derm(topic_labels)
        top3 = "; ".join(topic_labels[:3])

        if has_derm:
            log.info("  OK: %s — derm topics found (top3: %s)", name, top3)
            verified.append({'acd_name': name, 'openalex_id': oa_id, 'action': 'verified', 'top3_topics': top3})
        else:
            log.warning("  CLEAR: %s (works=%s, h=%s) — NO derm topics (top3: %s)",
                        name, row['works_count'], row.get('h_index', ''), top3)
            resolved.loc[idx, 'accepted']             = 0
            resolved.loc[idx, 'openalex_id']          = None
            resolved.loc[idx, 'openalex_display_name'] = None
            resolved.loc[idx, 'last_known_institution'] = None
            resolved.loc[idx, 'institution_country']   = None
            resolved.loc[idx, 'h_index']               = None
            resolved.loc[idx, 'works_count']           = None
            resolved.loc[idx, 'aunz_ever']             = None
            resolved.loc[idx, 'resolution_method']     = 'cleared_no_derm_topics'
            resolved.loc[idx, 'reject_reason']         = f'no_derm_topics_in_prolific_profile (top3: {top3})'
            cleared.append({
                'acd_name': name,
                'openalex_id': oa_id,
                'action': 'cleared',
                'old_works': row['works_count'],
                'old_h': row.get('h_index', ''),
                'old_inst': row.get('last_known_institution', ''),
                'old_country': row.get('institution_country', ''),
                'top3_topics': top3,
            })

    # Save
    resolved.drop(columns=['works_count_num'], errors='ignore', inplace=True)
    resolved.to_csv(RESOLVED_CSV, index=False)
    log.info("Saved updated authors_resolved.csv")

    # Zero out stats for cleared members
    cleared_names = [r['acd_name'] for r in cleared]
    if cleared_names:
        stat_mask = stats['acd_name'].isin(cleared_names)
        zero_cols = ['pub_count', 'citation_count', 'h_index', 'i10_index',
                     'fwci_mean', 'fwci_median', 'oa_rate', 'intl_collab_rate',
                     'first_author_pct', 'last_author_pct', 'grants_count',
                     'first_year', 'last_year', 'trial_count', 'derm_pub_count',
                     'derm_relevance_rate', 'pub_count_pctile', 'citation_count_pctile',
                     'h_index_pctile', 'oa_rate_pctile', 'intl_collab_rate_pctile',
                     'grants_count_pctile', 'total_citations', 'total_works']
        for col in zero_cols:
            if col in stats.columns:
                stats.loc[stat_mask, col] = None
        stats.to_csv(STATS_CSV, index=False)
        log.info("Zeroed stats for %d cleared members", len(cleared_names))

    # Save audit
    audit_path = ROOT / "data" / "processed" / f"derm_topic_audit_{ts}.csv"
    pd.DataFrame(verified + cleared).to_csv(audit_path, index=False)
    log.info("Audit saved to %s", audit_path)

    log.info("\n=== DERM TOPIC VERIFICATION SUMMARY ===")
    log.info("Checked: %d", len(targets))
    log.info("Verified (derm topics confirmed): %d", len(verified))
    log.info("Cleared (no derm topics): %d", len(cleared))

    if cleared:
        log.info("\nCLEARED:")
        for r in cleared:
            log.info("  %s (works=%s, h=%s, inst=%s, country=%s)",
                     r['acd_name'], r['old_works'], r['old_h'], r['old_inst'], r['old_country'])
            log.info("    top3 topics: %s", r['top3_topics'])

    final_accepted = (pd.read_csv(RESOLVED_CSV)['accepted'] == 1).sum()
    log.info("\nFinal accepted matches: %d", final_accepted)


if __name__ == "__main__":
    main()
