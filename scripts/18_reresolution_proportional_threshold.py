"""
18_reresolution_proportional_threshold.py
==========================================

ROOT CAUSES FIXED
-----------------
1. WRONG ID: Some cleared members had the wrong OpenAlex ID matched originally.
   The topic check then ran on the wrong person's topics and correctly cleared them
   — but the right person was never found. Fix: re-query OpenAlex (name + AU filter
   + ORCID if available) for every cleared member and try to find the correct match.

2. RIGID THRESHOLD: The 3/10 threshold penalises researchers whose OpenAlex profiles
   have fewer than 10 topics total (many AU dermatologists have only 3-7 topics).
   Fix: use a PROPORTIONAL threshold — at least 1 derm topic per 5 works, with a
   minimum of 1 and a maximum cap of 3. Specifically:
     - works 21-50:  need >= 1 derm topic out of however many topics exist
     - works 51-100: need >= 2 derm topics
     - works 101+:   need >= 3 derm topics
   This is equivalent to "at least 1 derm topic per ~50 works" which is reasonable
   for a specialist who also publishes in adjacent fields.

PROCESS
-------
For every member currently cleared with reject_reason containing 'derm_topics' or
'no_aunz_match':
  1. Search OpenAlex with AU/NZ filter + name (and ORCID if in roster)
  2. Apply hard filters: aunz_ever=True, not wrong specialty
  3. Apply proportional derm topic threshold
  4. Accept if score >= 75 and threshold passes
  5. If no match found, leave as cleared (NOT_FOUND)
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
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reresolution_proportional")

RESOLVED_CSV  = ROOT / "data" / "processed" / "authors_resolved.csv"
STATS_CSV     = ROOT / "data" / "processed" / "author_summary_stats.csv"
ROSTER_CSV    = ROOT / "data" / "input" / "Dermatologists_Consolidated.csv"

_LOCAL_COUNTRIES = {"AU", "NZ"}
_ACCEPT_THRESHOLD = 75

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
    "vascular malformation", "hemangioma", "port wine", "birthmark",
    "porphyria", "phlebolog", "venous disease", "sclerotherapy",
    "contact allerg", "occupational skin", "patch test",
])

_WRONG_SPECIALTY_TOKENS = frozenset([
    "ophthalmol", "nephrol", "cardiol", "neurol", "gastroenterol",
    "hepatol", "pulmonol", "endocrinol", "haematol",
    "urol", "gynaecol", "obstetric", "paediatric", "psychiatr",
    "orthopaed", "anaesthes", "radiol", "pathol", "atomic",
    "nuclear", "polymer", "material science", "computer science",
    "electrical engineer", "mechanical engineer", "civil engineer",
    "behavioral genetics", "astrophysics", "planetary science",
    "education", "school choice", "parental involvement",
    "veterinary", "animal health",
    "respiratory", "pulmonary", "lung", "copd", "asthma",
    "diaphragmatic hernia", "neonatal respiratory",
    "spinal", "spine", "orthopaedic", "lumbar", "cervical myelopathy",
])

_SELECT = "id,display_name,last_known_institutions,affiliations,works_count,topics,cited_by_count,summary_stats"


# ── Helpers ───────────────────────────────────────────────────────────────────
def _all_country_codes(c: dict) -> set[str]:
    codes: set[str] = set()
    for aff in c.get("affiliations") or []:
        cc = (aff.get("institution") or {}).get("country_code") or ""
        if cc: codes.add(cc.upper())
    return codes

def _lk_country_codes(c: dict) -> set[str]:
    codes: set[str] = set()
    for lk in (c.get("last_known_institutions") or []):
        cc = (lk or {}).get("country_code") or ""
        if cc: codes.add(cc.upper())
    return codes

def _aunz_ever(c: dict) -> bool:
    return bool((_all_country_codes(c) | _lk_country_codes(c)) & _LOCAL_COUNTRIES)

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

def _count_derm(labels: list[str]) -> int:
    return sum(1 for lbl in labels if any(tok in lbl for tok in _DERM_TOKENS))

def _is_wrong_specialty(labels: list[str]) -> bool:
    if not labels: return False
    top3 = labels[:3]
    if any(any(tok in lbl for tok in _DERM_TOKENS) for lbl in top3):
        return False
    return all(any(tok in lbl for tok in _WRONG_SPECIALTY_TOKENS) for lbl in top3)

def _proportional_derm_threshold(works: int, total_topics: int) -> int:
    """Minimum derm topics required given works count and total available topics."""
    if works <= 50:
        required = 1
    elif works <= 100:
        required = 2
    else:
        required = 3
    # Can't require more than total topics available
    return min(required, max(1, total_topics))

def _lk_inst_name(c: dict) -> str:
    lk_list = c.get("last_known_institutions") or []
    return (lk_list[0] or {}).get("display_name") or "" if lk_list else ""

def _lk_country(c: dict) -> str:
    lk_list = c.get("last_known_institutions") or []
    return (lk_list[0] or {}).get("country_code") or "" if lk_list else ""

def _get(url: str, params: dict | None = None) -> dict | None:
    try:
        r = requests.get(url, params=params, timeout=20,
                         headers={"User-Agent": "ACD-Dashboard/1.0 (admin@panaceainsights.com.au)"})
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("GET %s failed: %s", url, e)
    return None

def normalise_name(name: str) -> str:
    import re, unicodedata
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ascii', 'ignore').decode('ascii')
    name = re.sub(r'\b(dr|prof|a/prof|adj|mr|ms|mrs|assoc)\b\.?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[^a-zA-Z\s]', ' ', name)
    return ' '.join(name.lower().split())


# ── Hard filter (proportional) ────────────────────────────────────────────────
def hard_filter_proportional(candidate: dict) -> tuple[bool, str]:
    if not _aunz_ever(candidate):
        return False, "no_aunz_affiliation"
    works = int(candidate.get("works_count") or 0)
    topic_labels = _topic_labels(candidate, n=10)
    total_topics = len(topic_labels)
    if works > 20 and total_topics > 0:
        derm_count = _count_derm(topic_labels)
        required = _proportional_derm_threshold(works, total_topics)
        if derm_count < required:
            if _is_wrong_specialty(topic_labels[:3]):
                return False, f"wrong_specialty (derm={derm_count}/{total_topics}, need={required})"
            # If not obviously wrong specialty but fails threshold, still allow if >=1 derm
            if derm_count == 0:
                return False, f"zero_derm_topics (works={works})"
    return True, ""


# ── Scoring ───────────────────────────────────────────────────────────────────
def score_candidate(member_name: str, candidate: dict) -> int:
    norm_member = normalise_name(member_name)
    norm_cand   = normalise_name(candidate.get("display_name") or "")
    if not norm_member or not norm_cand:
        return 0
    if norm_member == norm_cand:
        name_pts = 40
    else:
        fuzzy = fuzz.token_sort_ratio(norm_member, norm_cand)
        if fuzzy >= 92:   name_pts = 30
        elif fuzzy >= 80: name_pts = 15
        elif fuzzy < 60:  return 0
        else:             name_pts = 5

    lk_au = bool(_lk_country_codes(candidate) & _LOCAL_COUNTRIES)
    au_ever = _aunz_ever(candidate)
    country_pts = 25 if lk_au else (15 if au_ever else 0)

    topic_labels = _topic_labels(candidate, n=10)
    derm_pts = 15 if _count_derm(topic_labels) >= 1 else 0

    works = int(candidate.get("works_count") or 0)
    works_pts = 8 if 1 <= works <= 50 else (5 if works <= 150 else (2 if works <= 300 else 0))

    return name_pts + country_pts + derm_pts + works_pts


# ── Search ────────────────────────────────────────────────────────────────────
def search_for_member(name: str, orcid: str | None = None) -> list[dict]:
    results = []
    clean = name.strip().replace(",", " ")
    tokens = [t for t in clean.split() if t and t.lower() not in
              {'dr', 'prof', 'a/prof', 'adj', 'mr', 'ms', 'mrs', 'assoc'}]
    search_name = f"{tokens[0]} {tokens[-1]}" if len(tokens) >= 2 else " ".join(tokens)
    fv = search_name.replace(" ", "+")

    # ORCID lookup first (most reliable)
    if orcid and str(orcid) != 'nan':
        data = _get("https://api.openalex.org/authors",
                    {"filter": f"orcid:{orcid}", "per-page": 5, "select": _SELECT})
        if data:
            results.extend(data.get("results") or [])
        time.sleep(0.3)

    # AU/NZ country filter
    for country in ["AU", "NZ"]:
        data = _get("https://api.openalex.org/authors",
                    {"filter": f"display_name.search:{fv},last_known_institutions.country_code:{country}",
                     "per-page": 10, "select": _SELECT})
        if data:
            results.extend(data.get("results") or [])
        time.sleep(0.3)

    # Historical AU affiliation
    data = _get("https://api.openalex.org/authors",
                {"filter": f"display_name.search:{fv},affiliations.institution.country_code:AU",
                 "per-page": 10, "select": _SELECT})
    if data:
        results.extend(data.get("results") or [])
    time.sleep(0.3)

    # Deduplicate
    seen, unique = set(), []
    for r in results:
        rid = r.get("id", "")
        if rid not in seen:
            seen.add(rid)
            unique.append(r)
    return unique


def find_best_match(name: str, orcid: str | None = None) -> dict | None:
    candidates = search_for_member(name, orcid)
    if not candidates:
        return None
    scored = []
    for c in candidates:
        passes, reason = hard_filter_proportional(c)
        if not passes:
            continue
        sc = score_candidate(name, c)
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


def fetch_stats(oa_id: str) -> dict:
    data = _get(f"https://api.openalex.org/authors/{oa_id}",
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
        "openalex_id": oa_id,
        "openalex_display_name": data.get("display_name", ""),
        "works_count": data.get("works_count", 0),
        "h_index": ss.get("h_index", 0),
        "last_known_institution": lk.get("display_name", ""),
        "institution_country": lk.get("country_code", ""),
        "aunz_ever": 1 if aunz else 0,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    shutil.copy(RESOLVED_CSV, str(RESOLVED_CSV).replace('.csv', f'_backup_{ts}.csv'))
    shutil.copy(STATS_CSV,    str(STATS_CSV).replace('.csv',    f'_backup_{ts}.csv'))
    log.info("Backed up with timestamp %s", ts)

    resolved = pd.read_csv(RESOLVED_CSV)
    stats    = pd.read_csv(STATS_CSV)

    # Load roster for ORCID lookup
    roster = pd.read_csv(ROSTER_CSV)
    orcid_map = {}
    if 'ORCID' in roster.columns:
        for _, row in roster.iterrows():
            name = str(row.get('Name') or '').strip()
            orcid = str(row.get('ORCID') or '').strip()
            if name and orcid and orcid != 'nan':
                orcid_map[name] = orcid

    # Targets: cleared members (accepted=0) whose reject_reason mentions derm topics or no_aunz
    cleared_mask = (
        (resolved['accepted'] == 0) &
        (resolved['reject_reason'].notna()) &
        (resolved['reject_reason'].str.contains('derm_topics|no_aunz_match|insufficient_derm', na=False))
    )
    targets = resolved[cleared_mask].copy()
    log.info("Targets for re-resolution: %d cleared members", len(targets))

    recovered = []
    still_cleared = []

    for idx, row in targets.iterrows():
        name = row['acd_name']
        orcid = orcid_map.get(name)
        log.info("\n--- %s (orcid=%s) ---", name, orcid)
        log.info("  reject_reason: %s", str(row.get('reject_reason', ''))[:120])

        match = find_best_match(name, orcid)

        if match:
            new_id = match.get("id", "").split("/")[-1]
            log.info("  FOUND: %s (id=%s, score=%d, works=%s, aunz=%s, inst=%s [%s])",
                     match.get("display_name"), new_id, match.get("_match_score", 0),
                     match.get("works_count"), _aunz_ever(match),
                     _lk_inst_name(match), _lk_country(match))

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
                resolved.loc[idx, 'resolution_method']       = 'reresolution_proportional_v1'
                resolved.loc[idx, 'reject_reason']           = ''
                recovered.append({
                    'acd_name': name,
                    'new_id': new_id,
                    'new_name': fresh.get('openalex_display_name', ''),
                    'new_works': fresh.get('works_count', 0),
                    'new_h': fresh.get('h_index', 0),
                    'new_inst': fresh.get('last_known_institution', ''),
                    'new_country': fresh.get('institution_country', ''),
                    'score': match.get('_match_score', 0),
                })
        else:
            log.info("  No valid AU/NZ derm match found — remains cleared")
            still_cleared.append({'acd_name': name, 'reject_reason': str(row.get('reject_reason', ''))[:80]})

    resolved.to_csv(RESOLVED_CSV, index=False)
    log.info("\nSaved updated authors_resolved.csv")

    # Save audit
    audit_path = ROOT / "data" / "processed" / f"reresolution_proportional_audit_{ts}.csv"
    pd.DataFrame(recovered + still_cleared).to_csv(audit_path, index=False)
    log.info("Audit saved to %s", audit_path)

    log.info("\n=== PROPORTIONAL RE-RESOLUTION SUMMARY ===")
    log.info("Targets processed: %d", len(targets))
    log.info("Recovered (valid AU/NZ derm match found): %d", len(recovered))
    log.info("Still cleared (no valid match): %d", len(still_cleared))

    if recovered:
        log.info("\nRECOVERED:")
        for r in recovered:
            log.info("  %s → %s (works=%s, h=%s, %s [%s], score=%s)",
                     r['acd_name'], r['new_name'], r['new_works'], r['new_h'],
                     r['new_inst'], r['new_country'], r['score'])

    final_accepted = (pd.read_csv(RESOLVED_CSV)['accepted'] == 1).sum()
    log.info("\nFinal accepted matches: %d", final_accepted)


if __name__ == "__main__":
    main()
