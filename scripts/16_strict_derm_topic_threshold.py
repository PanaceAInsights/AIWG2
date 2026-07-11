"""
16_strict_derm_topic_threshold.py — Strict derm topic threshold (3/10)
=======================================================================

Previous script (15) required only 1 derm topic out of 10 — far too lenient.
A genuine dermatologist with 20+ papers should have the majority of their
research in dermatology. This script raises the bar to:

  MINIMUM 3 out of top-10 OpenAlex topics must be dermatology-related.

This is still conservative (30%) to account for dermatologists who also
publish in adjacent fields (immunology, oncology, genetics), but it will
catch researchers who happen to have 1 derm paper among 20+ papers in
an unrelated field.

Works threshold: > 20 (same as before)
Exceptions: known high-volume AU dermatologists whose OpenAlex profiles
  may be diluted by broad research (e.g., Soyer, Sinclair, Murrell).
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
log = logging.getLogger("strict_derm_threshold")

RESOLVED_CSV = ROOT / "data" / "processed" / "authors_resolved.csv"
STATS_CSV    = ROOT / "data" / "processed" / "author_summary_stats.csv"

# Minimum number of top-10 topics that must be derm-related
DERM_TOPIC_MIN = 3

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
    "skin pigment", "skin aging", "skin barrier", "skin microbiome",
    "skin infect", "tinea", "fungal skin", "wart", "molluscum",
    "herpes zoster", "impetigo", "cellulitis", "erythema",
])

# Known high-volume AU dermatologists — exempt from strict topic threshold
# because their OpenAlex profiles span broad research areas (e.g., genetics,
# immunology, oncology) while remaining genuine dermatologists
_EXEMPT = frozenset([
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
    "Dr Helen Louise Saunders",
    "Dr Shyamala Claire Huilgol",
    "Dr Christopher John McCormack",
    "Dr Kurt Aaron Josef Gebauer",
    "Dr Margot Julie Whitfeld",
    "Dr Diana Marie Rubel",
    "Dr Orli Wargon",
    "Dr Cathy Yunjia Zhao",
    "Dr Kerry Ann Crotty",
    "Dr Victoria Jane Mar",
    "Dr George Andrew Varigos",
    "Dr Linda Katherine Martin",
    "Dr Patrick David Mahar",
    "Dr Kurosh Parsi",
])

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


def _count_derm(labels: list[str]) -> int:
    return sum(1 for lbl in labels if any(tok in lbl for tok in _DERM_TOKENS))


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

    # Targets: accepted=1, works>20, has openalex_id, not exempt
    targets_mask = (
        (resolved['accepted'] == 1) &
        (resolved['works_count_num'] > 20) &
        (resolved['openalex_id'].notna()) &
        (~resolved['acd_name'].isin(_EXEMPT))
    )
    targets = resolved[targets_mask].copy()
    log.info("Checking %d accepted matches (works>20, non-exempt) with strict 3/10 derm threshold", len(targets))

    cleared = []
    verified = []
    borderline = []  # 1-2 derm topics — cleared but logged separately

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
        derm_count = _count_derm(topic_labels)
        top5 = "; ".join(topic_labels[:5])

        if derm_count >= DERM_TOPIC_MIN:
            log.info("  OK: %s — %d/10 derm topics (top5: %s)", name, derm_count, top5)
            verified.append({
                'acd_name': name, 'openalex_id': oa_id,
                'action': 'verified', 'derm_count': derm_count, 'top5_topics': top5,
            })
        else:
            level = "BORDERLINE" if derm_count in (1, 2) else "CLEAR"
            log.warning("  %s: %s (works=%s, h=%s) — only %d/10 derm topics (top5: %s)",
                        level, name, row['works_count'], row.get('h_index', ''), derm_count, top5)

            resolved.loc[idx, 'accepted']              = 0
            resolved.loc[idx, 'openalex_id']           = None
            resolved.loc[idx, 'openalex_display_name'] = None
            resolved.loc[idx, 'last_known_institution'] = None
            resolved.loc[idx, 'institution_country']   = None
            resolved.loc[idx, 'h_index']               = None
            resolved.loc[idx, 'works_count']           = None
            resolved.loc[idx, 'aunz_ever']             = None
            resolved.loc[idx, 'resolution_method']     = 'cleared_insufficient_derm_topics'
            resolved.loc[idx, 'reject_reason']         = (
                f'only {derm_count}/10 derm topics (threshold={DERM_TOPIC_MIN}): {top5}'
            )

            entry = {
                'acd_name': name, 'openalex_id': oa_id,
                'action': 'cleared', 'derm_count': derm_count,
                'old_works': row['works_count'], 'old_h': row.get('h_index', ''),
                'old_inst': row.get('last_known_institution', ''),
                'old_country': row.get('institution_country', ''),
                'top5_topics': top5,
            }
            cleared.append(entry)
            if derm_count in (1, 2):
                borderline.append(entry)

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
    audit_path = ROOT / "data" / "processed" / f"strict_derm_threshold_audit_{ts}.csv"
    pd.DataFrame(verified + cleared).to_csv(audit_path, index=False)
    log.info("Audit saved to %s", audit_path)

    log.info("\n=== STRICT DERM THRESHOLD (3/10) SUMMARY ===")
    log.info("Checked: %d", len(targets))
    log.info("Verified (>= %d/10 derm topics): %d", DERM_TOPIC_MIN, len(verified))
    log.info("Cleared (< %d/10 derm topics): %d", DERM_TOPIC_MIN, len(cleared))
    log.info("  of which borderline (1-2 derm topics): %d", len(borderline))

    if cleared:
        log.info("\nCLEARED:")
        for r in cleared:
            log.info("  %s (works=%s, h=%s, derm=%s/10, inst=%s [%s])",
                     r['acd_name'], r['old_works'], r['old_h'], r['derm_count'],
                     r['old_inst'], r['old_country'])
            log.info("    top5: %s", r['top5_topics'])

    final_accepted = (pd.read_csv(RESOLVED_CSV)['accepted'] == 1).sum()
    log.info("\nFinal accepted matches: %d", final_accepted)


if __name__ == "__main__":
    main()
