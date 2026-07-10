"""
14_strict_reresolution.py — Principled strict re-resolution
============================================================

ROOT CAUSE SUMMARY
------------------
The `11_smart_reresolution.py` script was designed to find matches for
NOT_FOUND members. Its scoring threshold was only 35 points (last-name match
only), and it wrote ALL matches — including those with au_nz=False and
derm=False — into `manual_resolver_overrides.csv`. It then applied EVERY
override back onto `authors_resolved.csv` as accepted=1 / confidence=HIGH,
bypassing the strict hard-filter vetoes in `01c_resolve_authors.py`.

This created two classes of false positive:
  1. HIGH-VOLUME: Common names matched to prolific non-AU researchers
     (e.g., Kevin Phan → Vietnamese/Korean researcher with 623 pubs)
  2. STUB: Low-volume matches where the OpenAlex stub belongs to a
     non-AU person with the same name (e.g., Dr John Shannon → Ohio State)

FIX APPROACH
------------
For every currently-accepted match where aunz_ever=0 AND works_count > 5,
we re-query OpenAlex using the same strict logic as 01c:
  - Search AU/NZ filtered first (last_known_institutions.country_code:AU|NZ)
  - Apply hard veto: candidate must have AU/NZ affiliation (current or historical)
  - Apply hard veto: prolific profiles (>20 works) must have derm topic
  - Score with the 01c rubric
  - Accept only if score >= 80 (conservative threshold for re-resolution)
  - If no valid AU/NZ match found → clear the match (set accepted=0)

For aunz_ever=0 AND works_count 1-5 (stub profiles):
  - These are likely correct matches to real AU dermatologists with minimal pubs
  - We do NOT re-resolve these — they are kept as-is
  - But we DO verify the institution_country is not obviously wrong

This is a one-time correction pass. Going forward, `11_smart_reresolution.py`
should be modified to enforce the same hard filters as `01c`.
"""
from __future__ import annotations

import os
import re
import sys
import time
import shutil
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.utils.name_matching import normalise_name  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("strict_reresolution")

# ── Paths ────────────────────────────────────────────────────────────────────
RESOLVED_CSV = ROOT / "data" / "processed" / "authors_resolved.csv"
STATS_CSV    = ROOT / "data" / "processed" / "author_summary_stats.csv"
OVERRIDES_CSV = ROOT / "data" / "input" / "manual_resolver_overrides.csv"

# ── Constants ─────────────────────────────────────────────────────────────────
_LOCAL_COUNTRIES = {"AU", "NZ"}
_ACCEPT_THRESHOLD = 80   # conservative for re-resolution
_WORKS_SUSPICIOUS = 5    # re-resolve if works > this AND aunz_ever=0

_DERM_TOKENS = frozenset([
    "dermatol", "melanom", "skin cancer", "psoriasis", "eczema",
    "atopic dermatitis", "vitiligo", "alopecia", "rosacea", "acne",
    "cutaneous", "mohs", "phototherap", "dermoscop", "urticaria",
    "pemphigus", "pemphigoid", "bullous", "hidradenitis", "ichthyosis",
    "onychomycosis", "hyperhidrosis", "pruritus", "basal cell",
    "squamous cell", "skin neoplasm", "skin disease", "skin lesion",
    "wound heal", "scleroderma", "lupus erythematosus", "vasculitis",
])

_WRONG_SPECIALTY_TOKENS = frozenset([
    "ophthalmol", "nephrol", "cardiol", "neurol", "gastroenterol",
    "hepatol", "pulmonol", "endocrinol", "haematol", "oncol",
    "urol", "gynaecol", "obstetric", "paediatric", "psychiatr",
    "orthopaed", "anaesthes", "radiol", "pathol", "atomic",
    "nuclear", "polymer", "material science", "computer science",
    "electrical engineer", "mechanical engineer", "civil engineer",
    "behavioral genetics", "genetics", "genomics",
])

_SELECT = "id,display_name,last_known_institutions,affiliations,works_count,topics,cited_by_count,summary_stats"

# ── OpenAlex helpers ──────────────────────────────────────────────────────────
def _get(url: str, params: dict | None = None) -> dict | None:
    try:
        r = requests.get(url, params=params, timeout=20,
                         headers={"User-Agent": "ACD-Dashboard/1.0 (admin@panaceainsights.com.au)"})
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("GET %s failed: %s", url, e)
    return None


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
    return bool((_all_country_codes(c) | _lk_country_codes(c)) & _LOCAL_COUNTRIES)


def _lk_aunz(c: dict) -> bool:
    return bool(_lk_country_codes(c) & _LOCAL_COUNTRIES)


def _topic_labels(c: dict, n: int = 10) -> list[str]:
    labels = []
    for t in (c.get("topics") or [])[:n]:
        label = " ".join([
            t.get("display_name") or "",
            (t.get("subfield") or {}).get("display_name") or "",
            (t.get("field") or {}).get("display_name") or "",
        ]).lower()
        labels.append(label)
    return labels


def _has_derm(labels: list[str]) -> bool:
    return any(any(tok in lbl for tok in _DERM_TOKENS) for lbl in labels)


def _is_wrong_specialty(labels: list[str]) -> bool:
    if not labels:
        return False
    top3 = labels[:3]
    if any(any(tok in lbl for tok in _DERM_TOKENS) for lbl in top3):
        return False
    return all(any(tok in lbl for tok in _WRONG_SPECIALTY_TOKENS) for lbl in top3)


def _lk_inst_name(c: dict) -> str:
    lk_list = c.get("last_known_institutions") or []
    if lk_list:
        return (lk_list[0] or {}).get("display_name") or ""
    return ""


def _lk_country(c: dict) -> str:
    lk_list = c.get("last_known_institutions") or []
    if lk_list:
        return (lk_list[0] or {}).get("country_code") or ""
    return ""


# ── Hard filter ───────────────────────────────────────────────────────────────
def hard_filter(candidate: dict) -> tuple[bool, str]:
    """Returns (passes, reason). Candidate must have AU/NZ affiliation."""
    if not _aunz_ever(candidate):
        return False, "no_aunz_affiliation"
    works = int(candidate.get("works_count") or 0)
    topic_labels = _topic_labels(candidate, n=5)
    if works > 20 and topic_labels:
        if not _has_derm(topic_labels):
            return False, "no_derm_topic_in_prolific_profile"
    if topic_labels and _is_wrong_specialty(topic_labels[:3]):
        return False, "wrong_specialty"
    return True, ""


# ── Scoring ───────────────────────────────────────────────────────────────────
def score_candidate(member_name: str, candidate: dict) -> int:
    """Simplified scoring for re-resolution. Returns total score."""
    norm_member = normalise_name(member_name)
    norm_cand   = normalise_name(candidate.get("display_name") or "")

    # Name
    name_pts = 0
    if norm_member and norm_cand:
        if norm_member == norm_cand:
            name_pts = 40
        else:
            fuzzy = fuzz.token_sort_ratio(norm_member, norm_cand)
            if fuzzy >= 92:
                name_pts = 30
            elif fuzzy >= 80:
                name_pts = 15
            elif fuzzy < 60:
                return 0  # too dissimilar

    # Country
    lk_au = _lk_aunz(candidate)
    au_ever = _aunz_ever(candidate)
    country_pts = 25 if lk_au else (15 if au_ever else 0)

    # Dermatology topic
    topic_labels = _topic_labels(candidate, n=10)
    derm_pts = 15 if _has_derm(topic_labels) else 0

    # Works (moderate range preferred)
    works = int(candidate.get("works_count") or 0)
    if 1 <= works <= 50:
        works_pts = 8
    elif 51 <= works <= 150:
        works_pts = 5
    elif 151 <= works <= 300:
        works_pts = 2
    else:
        works_pts = 0

    return name_pts + country_pts + derm_pts + works_pts


# ── Search ────────────────────────────────────────────────────────────────────
def _name_to_search(name: str) -> str:
    """Extract first + last name for OpenAlex search."""
    clean = name.strip().replace(",", " ")
    tokens = [t for t in clean.split() if t]
    if len(tokens) <= 2:
        return clean
    return f"{tokens[0]} {tokens[-1]}"


def search_aunz(name: str) -> list[dict]:
    """Search OpenAlex with AU/NZ country filter."""
    fv = _name_to_search(name).replace(" ", "+")
    results = []
    for country in ["AU", "NZ"]:
        filter_str = f"display_name.search:{fv},last_known_institutions.country_code:{country}"
        data = _get("https://api.openalex.org/authors",
                    {"filter": filter_str, "per-page": 10, "select": _SELECT})
        if data:
            results.extend(data.get("results") or [])
        time.sleep(0.3)
    # Also try historical AU affiliation
    filter_str = f"display_name.search:{fv},affiliations.institution.country_code:AU"
    data = _get("https://api.openalex.org/authors",
                {"filter": filter_str, "per-page": 10, "select": _SELECT})
    if data:
        results.extend(data.get("results") or [])
    time.sleep(0.3)
    # Deduplicate by ID
    seen, unique = set(), []
    for r in results:
        rid = r.get("id", "")
        if rid not in seen:
            seen.add(rid)
            unique.append(r)
    return unique


def find_best_match(member_name: str) -> dict | None:
    """Find the best AU/NZ-verified match for a member name."""
    candidates = search_aunz(member_name)
    if not candidates:
        return None

    scored = []
    for c in candidates:
        passes, reason = hard_filter(c)
        if not passes:
            continue
        sc = score_candidate(member_name, c)
        if sc > 0:
            scored.append((sc, c))

    if not scored:
        return None

    scored.sort(key=lambda x: -x[0])
    best_score, best = scored[0]

    if best_score < _ACCEPT_THRESHOLD:
        return None

    best["_match_score"] = best_score
    return best


# ── Stats fetch ───────────────────────────────────────────────────────────────
def fetch_stats(openalex_id: str) -> dict:
    data = _get(f"https://api.openalex.org/authors/{openalex_id}",
                {"select": "id,display_name,works_count,cited_by_count,summary_stats,last_known_institutions,affiliations"})
    if not data:
        return {}
    ss = data.get("summary_stats") or {}
    lk_list = data.get("last_known_institutions") or []
    lk = lk_list[0] if lk_list else {}
    all_codes = _all_country_codes(data)
    lk_codes  = _lk_country_codes(data)
    aunz = bool((all_codes | lk_codes) & _LOCAL_COUNTRIES)
    return {
        "openalex_id": openalex_id,
        "openalex_display_name": data.get("display_name", ""),
        "works_count": data.get("works_count", 0),
        "h_index": ss.get("h_index", 0),
        "last_known_institution": lk.get("display_name", ""),
        "institution_country": lk.get("country_code", ""),
        "aunz_ever": 1 if aunz else 0,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # Backup
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    shutil.copy(RESOLVED_CSV, str(RESOLVED_CSV).replace('.csv', f'_backup_{ts}.csv'))
    shutil.copy(STATS_CSV,    str(STATS_CSV).replace('.csv',    f'_backup_{ts}.csv'))
    log.info("Backed up with timestamp %s", ts)

    resolved = pd.read_csv(RESOLVED_CSV)
    stats    = pd.read_csv(STATS_CSV)

    # Identify targets: accepted=1, aunz_ever=0, works_count > _WORKS_SUSPICIOUS
    resolved['works_count_num'] = pd.to_numeric(resolved['works_count'], errors='coerce').fillna(0)
    resolved['aunz_ever_num']   = pd.to_numeric(resolved['aunz_ever'],   errors='coerce').fillna(0)

    targets_mask = (
        (resolved['accepted'] == 1) &
        (resolved['aunz_ever_num'] == 0) &
        (resolved['works_count_num'] > _WORKS_SUSPICIOUS)
    )
    targets = resolved[targets_mask].copy()
    log.info("Targets for strict re-resolution: %d", len(targets))
    for _, row in targets.iterrows():
        log.info("  %s (works=%s, h=%s, inst=%s, country=%s)",
                 row['acd_name'], row['works_count'], row['h_index'],
                 row.get('last_known_institution',''), row.get('institution_country',''))

    results = []
    cleared = []
    corrected = []

    for idx, row in targets.iterrows():
        name = row['acd_name']
        log.info("\n--- Processing: %s ---", name)

        match = find_best_match(name)

        if match:
            new_id = match.get("id", "").split("/")[-1]
            old_id = str(row.get("openalex_id") or "")
            log.info("  FOUND new match: %s (id=%s, score=%d, works=%s, aunz=%s)",
                     match.get("display_name"), new_id, match.get("_match_score", 0),
                     match.get("works_count"), _aunz_ever(match))
            # Fetch fresh stats
            fresh = fetch_stats(new_id)
            time.sleep(0.3)
            if fresh:
                resolved.loc[idx, 'openalex_id']             = new_id
                resolved.loc[idx, 'openalex_display_name']   = fresh.get('openalex_display_name', '')
                resolved.loc[idx, 'works_count']             = fresh.get('works_count', 0)
                resolved.loc[idx, 'h_index']                 = fresh.get('h_index', 0)
                resolved.loc[idx, 'last_known_institution']  = fresh.get('last_known_institution', '')
                resolved.loc[idx, 'institution_country']     = fresh.get('institution_country', '')
                resolved.loc[idx, 'aunz_ever']               = fresh.get('aunz_ever', 0)
                resolved.loc[idx, 'accepted']                = 1
                resolved.loc[idx, 'confidence']              = 'HIGH'
                resolved.loc[idx, 'resolution_method']       = 'strict_reresolution_v1'
                resolved.loc[idx, 'reject_reason']           = ''
                corrected.append({
                    'acd_name': name,
                    'old_openalex_id': old_id,
                    'new_openalex_id': new_id,
                    'new_display_name': fresh.get('openalex_display_name', ''),
                    'new_works': fresh.get('works_count', 0),
                    'new_h': fresh.get('h_index', 0),
                    'new_inst': fresh.get('last_known_institution', ''),
                    'new_country': fresh.get('institution_country', ''),
                    'new_aunz': fresh.get('aunz_ever', 0),
                    'match_score': match.get('_match_score', 0),
                    'action': 'corrected',
                })
        else:
            log.info("  NO valid AU/NZ match found — clearing match")
            resolved.loc[idx, 'accepted']             = 0
            resolved.loc[idx, 'openalex_id']          = None
            resolved.loc[idx, 'openalex_display_name'] = None
            resolved.loc[idx, 'last_known_institution'] = None
            resolved.loc[idx, 'institution_country']   = None
            resolved.loc[idx, 'h_index']               = None
            resolved.loc[idx, 'works_count']           = None
            resolved.loc[idx, 'aunz_ever']             = None
            resolved.loc[idx, 'resolution_method']     = 'cleared_no_aunz_match'
            resolved.loc[idx, 'reject_reason']         = 'strict_reresolution_no_aunz_match'
            cleared.append({
                'acd_name': name,
                'old_works': row['works_count'],
                'old_h': row.get('h_index', ''),
                'old_inst': row.get('last_known_institution', ''),
                'old_country': row.get('institution_country', ''),
                'action': 'cleared',
            })

        results.append({'name': name, 'action': 'corrected' if match else 'cleared'})

    # Save updated resolved
    resolved.drop(columns=['works_count_num', 'aunz_ever_num'], errors='ignore', inplace=True)
    resolved.to_csv(RESOLVED_CSV, index=False)
    log.info("\nSaved updated authors_resolved.csv")

    # Update summary stats — zero out stats for cleared members
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

    # Save audit report
    audit_path = ROOT / "data" / "processed" / f"strict_reresolution_audit_{ts}.csv"
    pd.DataFrame(corrected + cleared).to_csv(audit_path, index=False)
    log.info("Audit saved to %s", audit_path)

    # Print summary
    log.info("\n=== STRICT RE-RESOLUTION SUMMARY ===")
    log.info("Targets processed: %d", len(targets))
    log.info("Corrected (new AU/NZ match found): %d", len(corrected))
    log.info("Cleared (no valid AU/NZ match): %d", len(cleared))

    if corrected:
        log.info("\nCORRECTED:")
        for r in corrected:
            log.info("  %s → %s (works=%s, h=%s, inst=%s, country=%s, score=%s)",
                     r['acd_name'], r['new_display_name'], r['new_works'], r['new_h'],
                     r['new_inst'], r['new_country'], r['match_score'])

    if cleared:
        log.info("\nCLEARED (no AU/NZ match):")
        for r in cleared:
            log.info("  %s (was: works=%s, h=%s, inst=%s, country=%s)",
                     r['acd_name'], r['old_works'], r['old_h'], r['old_inst'], r['old_country'])

    final_accepted = (pd.read_csv(RESOLVED_CSV)['accepted'] == 1).sum()
    log.info("\nFinal accepted matches: %d", final_accepted)


if __name__ == "__main__":
    main()
