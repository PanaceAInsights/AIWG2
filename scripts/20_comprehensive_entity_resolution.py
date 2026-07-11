"""
20_comprehensive_entity_resolution.py
=====================================

Implements the multi-stage entity resolution pipeline for ACD dermatologists.

Stages:
1. Multi-source candidate retrieval (OpenAlex name, ORCID, AU/NZ filters)
2. Hard-filter veto layer (Geography, Proportional Specialty, Wrong-Specialty)
3. Scoring, ranking, and confidence assignment

Note: Stage 4 (Web search cross-validation) is implemented as a separate
enrichment script to avoid rate-limiting issues during the main resolution pass.
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
log = logging.getLogger("entity_resolution")

RESOLVED_CSV  = ROOT / "data" / "processed" / "authors_resolved.csv"
STATS_CSV     = ROOT / "data" / "processed" / "author_summary_stats.csv"
ROSTER_CSV    = ROOT / "data" / "input" / "Dermatologists_Consolidated.csv"

_LOCAL_COUNTRIES = {"AU", "NZ"}
_ACCEPT_THRESHOLD = 70

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
    if works <= 50: required = 1
    elif works <= 100: required = 2
    else: required = 3
    return min(required, max(1, total_topics))

def _get(url: str, params: dict | None = None) -> dict | None:
    try:
        r = requests.get(url, params=params, timeout=20,
                         headers={"User-Agent": "ACD-Dashboard/2.0 (admin@panaceainsights.com.au)"})
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

# ── Stage 2: Hard Filter Veto ─────────────────────────────────────────────────
def hard_filter(candidate: dict) -> tuple[bool, str]:
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
            if derm_count == 0:
                return False, f"zero_derm_topics (works={works})"
                
    return True, ""

# ── Stage 3: Scoring ──────────────────────────────────────────────────────────
def score_candidate(member_name: str, candidate: dict, roster_inst: str = "") -> int:
    norm_member = normalise_name(member_name)
    norm_cand   = normalise_name(candidate.get("display_name") or "")
    if not norm_member or not norm_cand: return 0
    
    # Name Score (0-40)
    if norm_member == norm_cand: name_pts = 40
    else:
        fuzzy = fuzz.token_sort_ratio(norm_member, norm_cand)
        if fuzzy >= 92: name_pts = 35
        elif fuzzy >= 85: name_pts = 25
        elif fuzzy >= 75: name_pts = 15
        else: return 0  # Veto bad name match
        
    # Geo Score (0-25)
    lk_au = bool(_lk_country_codes(candidate) & _LOCAL_COUNTRIES)
    au_ever = _aunz_ever(candidate)
    geo_pts = 25 if lk_au else (15 if au_ever else 0)
    
    # Derm Score (0-20)
    topic_labels = _topic_labels(candidate, n=10)
    derm_count = _count_derm(topic_labels)
    if derm_count >= 3: derm_pts = 20
    elif derm_count >= 1: derm_pts = 10
    else: derm_pts = 0
    
    # Inst Score (0-15)
    inst_pts = 0
    if roster_inst:
        lk_list = candidate.get("last_known_institutions") or []
        lk_name = (lk_list[0] or {}).get("display_name") or "" if lk_list else ""
        if lk_name and fuzz.partial_ratio(roster_inst.lower(), lk_name.lower()) > 80:
            inst_pts = 15

    return name_pts + geo_pts + derm_pts + inst_pts

# ── Stage 1: Retrieval ────────────────────────────────────────────────────────
def retrieve_candidates(name: str, orcid: str | None = None) -> list[dict]:
    results = []
    clean = name.strip().replace(",", " ")
    tokens = [t for t in clean.split() if t and t.lower() not in
              {'dr', 'prof', 'a/prof', 'adj', 'mr', 'ms', 'mrs', 'assoc'}]
    search_name = f"{tokens[0]} {tokens[-1]}" if len(tokens) >= 2 else " ".join(tokens)
    fv = search_name.replace(" ", "+")

    # ORCID
    if orcid and str(orcid) != 'nan':
        data = _get("https://api.openalex.org/authors", {"filter": f"orcid:{orcid}", "per-page": 5, "select": _SELECT})
        if data: results.extend(data.get("results") or [])
        time.sleep(0.2)

    # AU/NZ Current
    for country in ["AU", "NZ"]:
        data = _get("https://api.openalex.org/authors", {"filter": f"display_name.search:{fv},last_known_institutions.country_code:{country}", "per-page": 5, "select": _SELECT})
        if data: results.extend(data.get("results") or [])
        time.sleep(0.2)

    # AU Historical
    data = _get("https://api.openalex.org/authors", {"filter": f"display_name.search:{fv},affiliations.institution.country_code:AU", "per-page": 5, "select": _SELECT})
    if data: results.extend(data.get("results") or [])
    time.sleep(0.2)

    seen, unique = set(), []
    for r in results:
        rid = r.get("id", "")
        if rid not in seen:
            seen.add(rid)
            unique.append(r)
    return unique

def resolve_member(name: str, orcid: str | None = None, roster_inst: str = "") -> dict | None:
    candidates = retrieve_candidates(name, orcid)
    if not candidates: return None
    
    scored = []
    for c in candidates:
        passes, reason = hard_filter(c)
        if not passes: continue
        sc = score_candidate(name, c, roster_inst)
        if sc >= _ACCEPT_THRESHOLD:
            scored.append((sc, c))
            
    if not scored: return None
    scored.sort(key=lambda x: -x[0])
    best_score, best = scored[0]
    best["_match_score"] = best_score
    best["_confidence"] = "HIGH" if best_score >= 85 else "MEDIUM"
    return best

def main():
    log.info("Pipeline module loaded. Ready for integration.")

if __name__ == "__main__":
    main()
