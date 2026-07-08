"""
ACD Dermatologist Entity Resolver — v2
======================================

Architecture (approved design v2, 2026-07-08)
----------------------------------------------

4-pass sequential pipeline. Each pass processes only members not yet resolved.

Pass 1 — Targeted AU/NZ search + deterministic scoring
  - 1 API call per member (AU|NZ country filter combined)
  - Hard filters applied first (wrong country + wrong specialty = hard reject)
  - Score ≥ 110 → HIGH (accepted)
  - Score 60–109 → carry to Pass 2
  - No candidates / no pass → NOT_FOUND

Pass 2 — Global relaxed search + calibrated scoring
  - 1 API call per member (no country filter)
  - Same hard filters + same scoring + global-penalty signals
  - Score ≥ 100 → HIGH
  - Score 60–99 → REVIEW (queued for Pass 3 LLM)
  - Score < 60 → NOT_FOUND

Pass 3 — LLM adjudication (REVIEW queue only, claude-sonnet-4-5)
  - 0 additional OpenAlex calls
  - First call: standard adjudication prompt
  - Second call (if confidence 0.60–0.79): adversarial "find reasons it's NOT the same person"
  - Both calls agree → accept verdict
  - Disagree → keep REVIEW for manual inspection
  - match=true + conf ≥ 0.85 → HIGH
  - match=true + conf 0.65–0.84 → REVIEW
  - match=false or specialty_consistent=false → NOT_FOUND

Pass 4 — Common-name & suspicious-merge audit (in-memory, 0 API calls)
  - COMMON_NAME_RISK: name matches 2+ OpenAlex profiles at fuzzy ≥ 90
  - SUSPICIOUS_VOLUME: works_count > 300 AND name was not exact match
    (waived for high_volume_exceptions.csv entries)
  - NO_AUNZ_HISTORY: accepted profile has zero AU/NZ affiliation
  - SPECIALTY_WEAK: < 20% dermatology topics in top-10 topics

Hard filters (applied before scoring in both Pass 1 and Pass 2)
  - Wrong country: candidate has NO AU/NZ affiliation (current or historical)
    AND member is AHPRA-proven → REJECT
  - Wrong specialty: candidate's top-3 topics contain zero dermatology-adjacent
    terms AND top concepts are exclusively non-derm → REJECT

Scoring rubric (max ~155 pts)
  Name exact match              40
  Name fuzzy ≥ 92               30
  Name fuzzy 80–91              15
  Country = AU/NZ (current)     25
  Country = AU/NZ (historical)  15
  State match                   12
  Institution catalog match     15
  Hospital/practice match       15
  Dermatology topic (top-5)     15
  Dermatology concept           10
  Works 1–50                     8
  Works 51–150                   5
  Works 151–300                  2
  Works > 300 (no exact name)  -20
  h-index > 50 (no exact name) -10
  Non-AU/NZ current+historical -30 (Pass 2 only)

LLM scoring adjustments
  LLM match=true + conf ≥ 0.85  +30
  LLM match=true + conf 0.65–0.84 +15
  LLM match=false               hard reject

Output files
  data/processed/authors_resolved.csv       — all 712 members
  data/processed/resolution_rejects.csv     — non-HIGH with score breakdown
  data/processed/review_queue.csv           — REVIEW tier only
  data/processed/common_name_review.csv     — common-name/suspicious flags
  data/logs/resolution.log                  — per-member evidence trail
  data/logs/resolution_progress.csv         — crash-resume checkpoint
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import requests
from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.utils.openalex_client import OpenAlexClient  # noqa: E402
from scripts.utils.name_matching import normalise_name     # noqa: E402
from scripts.utils.checkpoint import CheckpointWriter      # noqa: E402
from scripts.utils.budget import CreditBudget, BudgetExhausted  # noqa: E402
from scripts.utils.abstract import reconstruct_abstract    # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("acd.resolver")

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
INPUT_CSV    = ROOT / "data" / "input" / "260708_Dermatologists_Consolidated.csv"
INST_CSV     = ROOT / "data" / "input" / "derm_institutions_au_nz.csv"
HV_EXCEPT    = ROOT / "data" / "input" / "high_volume_exceptions.csv"
OVERRIDES    = ROOT / "data" / "input" / "manual_resolver_overrides.csv"
FP_OVERRIDES = ROOT / "data" / "input" / "manual_fp_overrides.csv"
BLACKLIST    = ROOT / "data" / "input" / "manual_resolver_blacklist.csv"

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------
_LOCAL_COUNTRIES        = {"AU", "NZ"}
_CANDIDATES_PER_SEARCH  = 10
_PER_MEMBER_SLEEP       = 0.4   # seconds between members

# Pass thresholds
_P1_ACCEPT   = 110   # Pass 1 → HIGH
_P2_ACCEPT   = 100   # Pass 2 → HIGH
_REVIEW_LOW  = 60    # below this → NOT_FOUND (both passes)

# LLM double-verification trigger range
_LLM_DOUBLE_LOW  = 0.60
_LLM_DOUBLE_HIGH = 0.79

# Works count / h-index calibration
_WORKS_PENALTY_THRESHOLD = 300
_WORKS_PENALTY           = -20
_HINDEX_PENALTY_THRESHOLD = 50
_HINDEX_PENALTY           = -10

# Scoring weights
_NAME_EXACT   = 40
_NAME_FUZZY92 = 30
_NAME_FUZZY80 = 15
_COUNTRY_PTS  = 25
_HIST_PTS     = 15
_STATE_PTS    = 12
_INST_PTS     = 15
_HOSP_PTS     = 15
_TOPIC_PTS    = 15
_CONCEPT_PTS  = 10
_WORKS_1_50   = 8
_WORKS_51_150 = 5
_WORKS_151_300 = 2
_GLOBAL_NOAUNZ = -30  # Pass 2 only: no AU/NZ current or historical

_LLM_HIGH    = 30
_LLM_MED     = 15
_LLM_NEG     = -999  # hard reject

# Dermatology topic/concept tokens
_DERM_TOKENS = frozenset([
    "dermatol", "melanom", "skin cancer", "psoriasis", "eczema",
    "atopic dermatitis", "vitiligo", "alopecia", "rosacea", "acne",
    "cutaneous", "mohs", "phototherap", "dermoscop", "urticaria",
    "pemphigus", "pemphigoid", "bullous", "hidradenitis", "ichthyosis",
    "onychomycosis", "hyperhidrosis", "pruritus", "basal cell",
    "squamous cell", "skin neoplasm", "skin disease", "skin lesion",
    "wound heal", "scleroderma", "lupus erythematosus", "vasculitis",
])

# Specialties that are hard evidence of the WRONG person
_WRONG_SPECIALTY_TOKENS = frozenset([
    "ophthalmol", "nephrol", "cardiol", "neurol", "gastroenterol",
    "hepatol", "pulmonol", "endocrinol", "haematol", "oncol",
    "urol", "gynaecol", "obstetric", "paediatric", "psychiatr",
    "orthopaed", "anaesthes", "radiol", "pathol",
])

# State → geography tokens
_STATE_MAP = {
    "NSW": ["new south wales", "nsw", "sydney", "newcastle", "wollongong"],
    "VIC": ["victoria", "vic", "melbourne", "geelong", "ballarat"],
    "QLD": ["queensland", "qld", "brisbane", "gold coast", "sunshine coast", "townsville"],
    "SA":  ["south australia", " sa ", "adelaide"],
    "WA":  ["western australia", " wa ", "perth"],
    "TAS": ["tasmania", "tas", "hobart", "launceston"],
    "ACT": ["canberra", "act"],
    "NT":  ["northern territory", " nt ", "darwin"],
    "NZ":  ["new zealand", " nz ", "auckland", "wellington", "christchurch", "dunedin"],
}

# Output schemas
OUTPUT_COLUMNS = [
    "acd_name", "source", "priority", "practitioner_no", "state",
    "speciality_ahpra", "location_ahpra", "ahpra_proven",
    "openalex_id", "openalex_display_name", "last_known_institution",
    "institution_country", "aunz_ever", "works_count", "h_index", "profile_url",
    "score_name", "score_country", "score_inst", "score_topic",
    "score_state", "score_history", "score_hospital",
    "score_semantic", "score_llm", "total_score",
    "confidence", "accepted", "reject_reason",
    "resolution_method", "ambiguity_flags", "llm_reasoning", "search_pass",
]

REVIEW_COLUMNS = OUTPUT_COLUMNS + ["openalex_candidate_url"]

REJECT_COLUMNS = [
    "acd_name", "acd_state", "ahpra_proven",
    "top_candidate_id", "top_candidate_name", "top_candidate_institution",
    "top_candidate_country", "top_candidate_aunz_ever", "top_candidate_works_count",
    "score_name", "score_country", "score_inst", "score_topic",
    "score_state", "score_history", "score_hospital",
    "score_semantic", "score_llm", "total_score",
    "confidence", "reject_reason", "ambiguity_flags",
    "runner_up_id", "runner_up_name", "top_candidate_profile_url",
]

COMMON_NAME_COLUMNS = [
    "acd_name", "state", "openalex_id", "openalex_display_name",
    "last_known_institution", "works_count", "ambiguity_flags",
    "total_score", "confidence", "flag_reason",
]


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------
def _priority(source: Any) -> str:
    s = str(source or "").strip()
    return "must" if s in ("Both", "AHPRA Only") else "nice"


def load_members(input_path: Path) -> pd.DataFrame:
    df = pd.read_csv(input_path, dtype=str).fillna("")
    df["priority"] = df["Source"].map(_priority)
    df["_rank"] = df["priority"].map({"must": 0, "nice": 1})
    return df.sort_values(["_rank", "Name"], kind="stable").reset_index(drop=True).drop(columns=["_rank"])


def load_high_volume_exceptions(path: Path) -> set[str]:
    """Load names of known high-volume researchers (works > 300 penalty waived)."""
    if not path.exists():
        return set()
    df = pd.read_csv(path, dtype=str).fillna("")
    col = "name" if "name" in df.columns else df.columns[0]
    return {normalise_name(str(v)) for v in df[col] if str(v).strip()}


# ---------------------------------------------------------------------------
# Member context
# ---------------------------------------------------------------------------
@dataclass
class MemberContext:
    name: str
    source: str
    state: str
    practitioner_no: str
    speciality_ahpra: str
    location_ahpra: str
    hospitals: str
    practices: str
    bio_hs: str
    interests_hs: str
    qualifications_hs: str
    priority: str

    @property
    def ahpra_proven(self) -> bool:
        pno = self.practitioner_no.strip().upper()
        spec = self.speciality_ahpra.lower()
        return pno.startswith("MED") and "dermatology" in spec

    @property
    def hospital_patterns(self) -> list[str]:
        return _pipe_split(self.hospitals)

    @property
    def practice_patterns(self) -> list[str]:
        return _pipe_split(self.practices)

    @property
    def semantic_text(self) -> str:
        return " ".join(p for p in [self.bio_hs, self.interests_hs, self.qualifications_hs] if p.strip())

    @property
    def norm_name(self) -> str:
        return normalise_name(self.name)


def _pipe_split(field: str | None) -> list[str]:
    if not field:
        return []
    out, seen = [], set()
    for entry in str(field).split("|"):
        name = re.sub(r"\([^)]*\)", "", entry).strip().lower()
        if name and len(name) >= 5 and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def build_context(raw: dict[str, Any]) -> MemberContext:
    return MemberContext(
        name=str(raw.get("Name") or "").strip(),
        source=str(raw.get("Source") or "").strip(),
        state=str(raw.get("State") or "").strip(),
        practitioner_no=str(raw.get("Practitioner_No_AHPRA") or "").strip(),
        speciality_ahpra=str(raw.get("Speciality_AHPRA") or "").strip(),
        location_ahpra=str(raw.get("Location_AHPRA") or "").strip(),
        hospitals=str(raw.get("Hospitals_Names_HS") or "").strip(),
        practices=str(raw.get("Practices_Names_HS") or "").strip(),
        bio_hs=str(raw.get("Bio_HS") or "").strip(),
        interests_hs=str(raw.get("Special_Interests_HS") or "").strip(),
        qualifications_hs=str(raw.get("Qualifications_HS") or "").strip(),
        priority=str(raw.get("priority") or "nice").strip(),
    )


# ---------------------------------------------------------------------------
# Institution catalog
# ---------------------------------------------------------------------------
@dataclass
class DermInstitutionCatalog:
    patterns: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "DermInstitutionCatalog":
        if not path.exists():
            logger.warning("Institution catalog not found: %s", path)
            return cls()
        df = pd.read_csv(path, dtype=str).fillna("")
        col = "institution_name" if "institution_name" in df.columns else df.columns[0]
        return cls(patterns=[r.strip().lower() for r in df[col] if r.strip()])

    def match_any(self, names: list[str]) -> bool:
        for name in names:
            nl = name.lower()
            for pat in self.patterns:
                if pat in nl:
                    return True
        return False


# ---------------------------------------------------------------------------
# Override / blacklist loaders
# ---------------------------------------------------------------------------
def _load_overrides(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str).fillna("")
    return {
        str(r["acd_name"]).strip(): str(r["correct_openalex_id"]).strip()
        for _, r in df.iterrows()
        if r.get("acd_name") and r.get("correct_openalex_id")
    }


def _load_fp_overrides(path: Path) -> dict[str, set[str]]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str).fillna("")
    out: dict[str, set[str]] = {}
    for _, r in df.iterrows():
        name = str(r.get("acd_name") or "").strip()
        oid  = str(r.get("openalex_id_to_reject") or "").strip()
        if name and oid:
            out.setdefault(name, set()).add(oid)
    return out


def _load_blacklist(path: Path) -> set[str]:
    if not path.exists():
        return set()
    df = pd.read_csv(path, dtype=str).fillna("")
    col = "openalex_id_to_blacklist" if "openalex_id_to_blacklist" in df.columns else df.columns[0]
    return {str(v).strip() for v in df[col] if str(v).strip()}


# ---------------------------------------------------------------------------
# OpenAlex helpers
# ---------------------------------------------------------------------------
def _strip_id(raw: str | None) -> str:
    return raw.split("/")[-1] if raw else ""


def _all_country_codes(c: dict) -> set[str]:
    codes: set[str] = set()
    for aff in c.get("affiliations") or []:
        cc = (aff.get("institution") or {}).get("country_code") or ""
        if cc:
            codes.add(cc.upper())
    return codes


def _lk_country_codes(c: dict) -> set[str]:
    # last_known_institutions is a list in the filter endpoint response
    lk_list = c.get("last_known_institutions") or []
    codes = set()
    for lk in lk_list:
        cc = (lk or {}).get("country_code") or ""
        if cc:
            codes.add(cc.upper())
    return codes


def _all_inst_names(c: dict) -> list[str]:
    names: list[str] = []
    # last_known_institutions is a list
    for lk in (c.get("last_known_institutions") or []):
        dn = (lk or {}).get("display_name") or ""
        if dn:
            names.append(dn)
    for aff in c.get("affiliations") or []:
        dn = (aff.get("institution") or {}).get("display_name") or ""
        if dn:
            names.append(dn)
    return names


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


def _is_derm_topic(label: str) -> bool:
    return any(tok in label for tok in _DERM_TOKENS)


def _is_wrong_specialty(labels: list[str]) -> bool:
    """True if ALL top-3 topics are exclusively non-derm specialties."""
    if not labels:
        return False
    top3 = labels[:3]
    # If any topic is derm-related, it's NOT wrong specialty
    if any(_is_derm_topic(lbl) for lbl in top3):
        return False
    # If all top-3 are exclusively wrong specialties → hard reject
    return all(any(tok in lbl for tok in _WRONG_SPECIALTY_TOKENS) for lbl in top3)


def _fetch_top_titles(candidate_id: str, client: OpenAlexClient, n: int = 5) -> list[str]:
    try:
        payload = client.get(
            "/works",
            params={
                "filter": f"authorships.author.id:{candidate_id}",
                "sort": "cited_by_count:desc",
                "per-page": n,
                "select": "title",
            },
            allow_404=True,
        )
        return [w.get("title") or "" for w in (payload or {}).get("results") or []]
    except Exception:
        return []


def _fetch_abstract_snippets(candidate_id: str, client: OpenAlexClient, n: int = 5) -> list[str]:
    try:
        payload = client.get(
            "/works",
            params={
                "filter": f"authorships.author.id:{candidate_id}",
                "sort": "cited_by_count:desc",
                "per-page": n,
                "select": "abstract_inverted_index,title",
            },
            allow_404=True,
        )
        snippets = []
        for w in (payload or {}).get("results") or []:
            abstract = reconstruct_abstract(w.get("abstract_inverted_index") or {})
            title = w.get("title") or ""
            text = f"{title}. {abstract}".strip()
            if text:
                snippets.append(text)
        return snippets
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Hard filter
# ---------------------------------------------------------------------------
def hard_filter(ctx: MemberContext, candidate: dict) -> tuple[bool, str]:
    """
    Returns (passes, reason).
    A candidate fails if it has no AU/NZ affiliation AND the member is AHPRA-proven,
    OR if its top topics are exclusively wrong specialties.
    """
    all_codes = _all_country_codes(candidate)
    lk_codes  = _lk_country_codes(candidate)
    aunz_ever = bool((all_codes | lk_codes) & _LOCAL_COUNTRIES)

    # Hard filter 1: AHPRA-proven member but candidate has zero AU/NZ history
    if ctx.ahpra_proven and not aunz_ever:
        return False, "no_aunz_affiliation"

    # Hard filter 2: Wrong specialty (all top-3 topics are non-derm specialties)
    topic_labels = _topic_labels(candidate, n=3)
    if topic_labels and _is_wrong_specialty(topic_labels):
        return False, "wrong_specialty"

    return True, ""


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_candidate(
    ctx: MemberContext,
    candidate: dict,
    catalog: DermInstitutionCatalog,
    hv_exceptions: set[str],
    is_pass2: bool = False,
) -> dict[str, Any]:
    """Compute all deterministic signals. Returns score dict."""
    # Name
    cand_norm = normalise_name(candidate.get("display_name") or "")
    name_pts, fuzzy = 0, 0.0
    if ctx.norm_name and cand_norm:
        if ctx.norm_name == cand_norm:
            name_pts, fuzzy = _NAME_EXACT, 100.0
        else:
            fuzzy = fuzz.token_sort_ratio(ctx.norm_name, cand_norm)
            if fuzzy >= 92:
                name_pts = _NAME_FUZZY92
            elif fuzzy >= 80:
                name_pts = _NAME_FUZZY80

    # Country
    all_codes = _all_country_codes(candidate)
    lk_codes  = _lk_country_codes(candidate)
    aunz_ever = bool((all_codes | lk_codes) & _LOCAL_COUNTRIES)
    lk_aunz   = bool(lk_codes & _LOCAL_COUNTRIES)
    country_pts = _COUNTRY_PTS if lk_aunz else 0
    hist_pts    = _HIST_PTS if (aunz_ever and not lk_aunz) else 0

    # Pass 2 global penalty: no AU/NZ at all
    global_penalty = 0
    if is_pass2 and not aunz_ever:
        global_penalty = _GLOBAL_NOAUNZ

    # Institution catalog
    inst_names = _all_inst_names(candidate)
    inst_pts   = _INST_PTS if catalog.match_any(inst_names) else 0

    # State match
    state_pts = 0
    if ctx.state:
        tokens = _STATE_MAP.get(ctx.state.upper(), [ctx.state.lower()])
        combined = " ".join(inst_names).lower()
        if any(tok in combined for tok in tokens):
            state_pts = _STATE_PTS

    # Hospital / practice match
    hosp_pts = 0
    if ctx.hospital_patterns or ctx.practice_patterns:
        combined = " ".join(inst_names).lower()
        for pat in ctx.hospital_patterns + ctx.practice_patterns:
            if pat and pat in combined:
                hosp_pts = _HOSP_PTS
                break

    # Dermatology topic
    topic_labels_list = _topic_labels(candidate, n=10)
    derm_count = sum(1 for lbl in topic_labels_list if _is_derm_topic(lbl))
    topic_pts = 0
    if derm_count >= 1:
        topic_pts = _TOPIC_PTS
    concept_pts = 0
    for xc in (candidate.get("x_concepts") or [])[:10]:
        lbl = (xc.get("display_name") or "").lower()
        if _is_derm_topic(lbl):
            concept_pts = _CONCEPT_PTS
            break

    # Works count
    works = int(candidate.get("works_count") or 0)
    is_exact = (name_pts == _NAME_EXACT)
    is_hv_exception = (ctx.norm_name in hv_exceptions)
    works_pts = 0
    if 1 <= works <= 50:
        works_pts = _WORKS_1_50
    elif 51 <= works <= 150:
        works_pts = _WORKS_51_150
    elif 151 <= works <= 300:
        works_pts = _WORKS_151_300
    elif works > _WORKS_PENALTY_THRESHOLD:
        if not is_exact and not is_hv_exception:
            works_pts = _WORKS_PENALTY

    # h-index penalty
    hindex = int(candidate.get("summary_stats", {}).get("h_index") or 0)
    hindex_pts = 0
    if hindex > _HINDEX_PENALTY_THRESHOLD and not is_exact and not is_hv_exception:
        hindex_pts = _HINDEX_PENALTY

    return {
        "score_name":    name_pts,
        "score_country": country_pts,
        "score_hist":    hist_pts,
        "score_inst":    inst_pts,
        "score_state":   state_pts,
        "score_hospital": hosp_pts,
        "score_topic":   topic_pts + concept_pts,
        "score_works":   works_pts + hindex_pts,
        "score_global_penalty": global_penalty,
        "score_semantic": 0,
        "score_llm":     0,
        "_fuzzy":        fuzzy,
        "_aunz_ever":    aunz_ever,
        "_works":        works,
        "_hindex":       hindex,
        "_derm_count":   derm_count,
    }


def total_score(sc: dict) -> int:
    return sum(sc.get(k, 0) for k in (
        "score_name", "score_country", "score_hist", "score_inst",
        "score_state", "score_hospital", "score_topic", "score_works",
        "score_global_penalty", "score_semantic", "score_llm",
    ))


# ---------------------------------------------------------------------------
# Semantic similarity
# ---------------------------------------------------------------------------
def compute_semantic(ctx: MemberContext, candidate_id: str, client: OpenAlexClient) -> int:
    member_text = ctx.semantic_text.strip()
    if not member_text:
        return 0
    snippets = _fetch_abstract_snippets(candidate_id, client)
    if not snippets:
        return 0
    try:
        corpus = [member_text] + snippets
        vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), max_features=8000,
                              sublinear_tf=True, min_df=1)
        tfidf = vec.fit_transform(corpus)
        sims = cosine_similarity(tfidf[0:1], tfidf[1:]).flatten()
        best = float(np.max(sims)) if len(sims) else 0.0
        if best >= 0.35:
            return 15
        if best >= 0.20:
            return 8
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------------------
# LLM adjudication (Pass 3)
# ---------------------------------------------------------------------------
_LLM_SYSTEM_STANDARD = """You are an expert biomedical entity resolution specialist.
Your task: determine whether a given OpenAlex researcher profile belongs to a specific
Australian/New Zealand dermatologist.

Key rules:
- A perfect name match with a non-AU/NZ institution and no AU/NZ history = likely WRONG person.
- A perfect name match with publications exclusively in ophthalmology/nephrology/cardiology = WRONG person.
- Most ACD dermatologists are clinical practitioners with modest publication records (1–100 papers).
- Be conservative: false positives (merging wrong people) are far worse than false negatives.

Respond ONLY with valid JSON:
{
  "match": true or false,
  "confidence": 0.0 to 1.0,
  "reasoning": "one or two sentences",
  "specialty_consistent": true or false,
  "geography_consistent": true or false,
  "flags": ["COMMON_NAME", "COUNTRY_MISMATCH", "WEAK_TOPIC", "PLAUSIBLE_CLINICIAN", ...]
}"""

_LLM_SYSTEM_ADVERSARIAL = """You are a critical biomedical entity resolution auditor.
Your task: find ALL reasons why a proposed OpenAlex profile match might be WRONG.
Be adversarial — assume the match is incorrect unless the evidence is overwhelming.

Consider:
- Is the institution in AU/NZ? If not, is there any AU/NZ history?
- Are the publications in dermatology? Or a completely different specialty?
- Is the name common enough that this could be a different person?
- Is the works count realistic for a clinical dermatologist?

Respond ONLY with valid JSON:
{
  "match": true or false,
  "confidence": 0.0 to 1.0,
  "reasoning": "one or two sentences explaining your adversarial assessment",
  "specialty_consistent": true or false,
  "geography_consistent": true or false,
  "flags": ["COMMON_NAME", "COUNTRY_MISMATCH", "WEAK_TOPIC", "WRONG_SPECIALTY", ...]
}"""


def _build_llm_prompt(ctx: MemberContext, candidate: dict, top_titles: list[str]) -> str:
    # last_known_institutions is a list; take the first entry as current
    lk_list = candidate.get("last_known_institutions") or []
    lk = lk_list[0] if lk_list else {}
    all_codes = _all_country_codes(candidate)
    topic_labels_list = _topic_labels(candidate, n=5)
    return f"""DERMATOLOGIST RECORD (from AHPRA + HealthShare):
  Name: {ctx.name}
  State: {ctx.state}
  AHPRA Speciality: {ctx.speciality_ahpra}
  Hospital affiliations: {ctx.hospitals or 'N/A'}
  Bio: {ctx.bio_hs[:400] if ctx.bio_hs else 'N/A'}
  Special interests: {ctx.interests_hs[:300] if ctx.interests_hs else 'N/A'}
  Qualifications: {ctx.qualifications_hs[:300] if ctx.qualifications_hs else 'N/A'}

OPENALEX CANDIDATE:
  Display name: {candidate.get('display_name', 'N/A')}
  Current institution: {lk.get('display_name', 'N/A')} ({lk.get('country_code', 'N/A')})
  All country history: {', '.join(sorted(all_codes)) or 'N/A'}
  Works count: {candidate.get('works_count', 'N/A')}
  Top topics: {'; '.join(topic_labels_list[:5]) or 'N/A'}
  Top publications:
{chr(10).join(f'    - {t}' for t in top_titles[:5]) if top_titles else '    (none available)'}

Is this OpenAlex profile the same person as the dermatologist listed above?"""


def _call_llm(system: str, prompt: str, model: str = "claude-sonnet-4-6") -> dict[str, Any]:
    try:
        from openai import OpenAI
        oai = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            base_url=os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
        )
        response = oai.chat.completions.create(
            model=model,
            max_tokens=512,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        text = response.choices[0].message.content.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
    return {"match": None, "confidence": 0.5, "reasoning": "LLM call failed",
            "specialty_consistent": None, "geography_consistent": None, "flags": []}


def llm_adjudicate(
    ctx: MemberContext,
    candidate: dict,
    top_titles: list[str],
    evidence_f,
) -> dict[str, Any]:
    """
    Pass 3 LLM adjudication with optional adversarial double-verification.
    Returns merged verdict dict.
    """
    model = os.environ.get("LLM_DISAMBIG_MODEL", "claude-sonnet-4-6")
    prompt = _build_llm_prompt(ctx, candidate, top_titles)

    # First call: standard adjudication
    result1 = _call_llm(_LLM_SYSTEM_STANDARD, prompt, model)
    conf1 = float(result1.get("confidence") or 0.5)
    evidence_f.write(f"  LLM-1: match={result1.get('match')} conf={conf1:.2f} "
                     f"spec={result1.get('specialty_consistent')} "
                     f"geo={result1.get('geography_consistent')}\n")
    evidence_f.write(f"  LLM-1 reasoning: {result1.get('reasoning', '')}\n")

    # Double-verification: adversarial second call if confidence is uncertain
    if _LLM_DOUBLE_LOW <= conf1 <= _LLM_DOUBLE_HIGH:
        evidence_f.write(f"  → Confidence {conf1:.2f} in uncertain range, running adversarial call\n")
        result2 = _call_llm(_LLM_SYSTEM_ADVERSARIAL, prompt, model)
        conf2 = float(result2.get("confidence") or 0.5)
        evidence_f.write(f"  LLM-2 (adversarial): match={result2.get('match')} conf={conf2:.2f}\n")
        evidence_f.write(f"  LLM-2 reasoning: {result2.get('reasoning', '')}\n")

        # If both calls agree on match=true, average confidence
        if result1.get("match") is True and result2.get("match") is True:
            merged_conf = (conf1 + conf2) / 2
            result1["confidence"] = merged_conf
            result1["reasoning"] = (
                f"[Dual-verified] {result1.get('reasoning', '')} "
                f"Adversarial check: {result2.get('reasoning', '')}"
            )
            result1["flags"] = list(set(
                (result1.get("flags") or []) + (result2.get("flags") or [])
            ))
        elif result1.get("match") is True and result2.get("match") is False:
            # Disagreement: keep as REVIEW
            result1["match"] = None  # None = uncertain
            result1["confidence"] = 0.60
            result1["reasoning"] = (
                f"[DISAGREEMENT] Standard: {result1.get('reasoning', '')} | "
                f"Adversarial: {result2.get('reasoning', '')}"
            )
            result1["flags"] = list(set(
                (result1.get("flags") or []) + (result2.get("flags") or []) + ["LLM_DISAGREEMENT"]
            ))
        else:
            # Both say false or first said false
            result1["confidence"] = min(conf1, conf2)
            result1["reasoning"] = (
                f"[Both reject] {result1.get('reasoning', '')} | "
                f"{result2.get('reasoning', '')}"
            )

    return result1


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def _name_to_filter_value(name: str) -> str:
    """
    Convert a full name to a search term for display_name.search filter.
    OpenAlex only stores first + last name (not middle names), so we always
    extract just the first token (given name) and last token (surname).
    This gives the best recall — full middle names return 0 results.
    The full name is still used for fuzzy scoring after candidates are fetched.
    """
    clean = name.strip().replace(",", " ")
    # Normalise multiple spaces
    tokens = [t for t in clean.split() if t]
    if len(tokens) <= 2:
        return clean
    # Use first given name + last surname only
    return f"{tokens[0]} {tokens[-1]}"


_SELECT_FIELDS = "id,display_name,last_known_institutions,affiliations,works_count,topics,cited_by_count,orcid,ids"


def _build_raw_query(filter_str: str, per_page: int = 10, api_key: str = "") -> str:
    """Build a raw query string for OpenAlex filter= requests.
    NOTE: api_key is intentionally NOT included — filter-based searches are free
    and rate-limit-free without the key. Including the key routes through the
    paid quota system and triggers 429 errors.
    The filter value contains colons and commas which must NOT be URL-encoded.
    The select fields also use commas which must remain unencoded.
    The api_key is required for display_name.search (costs $0.001/call).
    """
    # Do NOT include api_key — filter searches are free and unlimited without it.
    # Including the key routes through the paid quota and causes 429 rate limits.
    return f"filter={filter_str}&per-page={per_page}&select={_SELECT_FIELDS}"


def _search_aunz(client: OpenAlexClient, name: str) -> list[dict]:
    """
    Pass 1: AU/NZ targeted search using free filter=display_name.search: endpoint.
    Uses raw_query to avoid URL-encoding the colon in filter values (400 error).
    Strategy:
      - AU last_known_institutions filter
      - NZ fallback
      - Historical AU affiliations fallback
    """
    if not name:
        return []
    fv = _name_to_filter_value(name)
    # Replace spaces with + for URL compatibility in raw query
    fv_url = fv.replace(" ", "+")
    try:
        # AU-filtered search (no api_key = free, unlimited)
        rq = _build_raw_query(
            f"display_name.search:{fv_url},last_known_institutions.country_code:AU",
            per_page=_CANDIDATES_PER_SEARCH,
        )
        payload = client.get("/authors", allow_404=True, raw_query=rq)
        results = (payload or {}).get("results") or []
        if results:
            return results

        # NZ fallback
        rq = _build_raw_query(
            f"display_name.search:{fv_url},last_known_institutions.country_code:NZ",
            per_page=_CANDIDATES_PER_SEARCH,
        )
        payload = client.get("/authors", allow_404=True, raw_query=rq)
        results = (payload or {}).get("results") or []
        if results:
            return results

        # Historical AU affiliation fallback
        rq = _build_raw_query(
            f"display_name.search:{fv_url},affiliations.institution.country_code:AU",
            per_page=_CANDIDATES_PER_SEARCH,
        )
        payload = client.get("/authors", allow_404=True, raw_query=rq)
        return (payload or {}).get("results") or []

    except BudgetExhausted:
        raise
    except Exception as exc:
        logger.warning("Pass 1 search failed for %s: %s", name, exc)
        return []


def _search_global(client: OpenAlexClient, name: str) -> list[dict]:
    """
    Pass 2: global search using filter=display_name.search: endpoint.
    No country restriction. Returns top _CANDIDATES_PER_SEARCH candidates.
    The scoring rubric applies a -30 penalty for no AU/NZ history (Pass 2 only).
    """
    if not name:
        return []
    fv = _name_to_filter_value(name)
    fv_url = fv.replace(" ", "+")
    try:
        rq = _build_raw_query(
            f"display_name.search:{fv_url}",
            per_page=_CANDIDATES_PER_SEARCH,
        )
        payload = client.get("/authors", allow_404=True, raw_query=rq)
        return (payload or {}).get("results") or []
    except BudgetExhausted:
        raise
    except Exception as exc:
        logger.warning("Pass 2 search failed for %s: %s", name, exc)
        return []


# ---------------------------------------------------------------------------
# Per-member resolution (Pass 1 + 2 combined)
# ---------------------------------------------------------------------------
def resolve_member(
    ctx: MemberContext,
    client: OpenAlexClient,
    catalog: DermInstitutionCatalog,
    hv_exceptions: set[str],
    overrides: dict[str, str],
    fp_overrides: dict[str, set[str]],
    blacklist: set[str],
    evidence_f,
) -> dict[str, Any]:
    evidence_f.write(f"\n--- {ctx.name} ({ctx.state}) priority={ctx.priority} ---\n")

    # Manual override
    if ctx.name in overrides:
        forced_id = overrides[ctx.name]
        evidence_f.write(f"  MANUAL OVERRIDE → {forced_id}\n")
        try:
            payload = client.get(
                f"/authors/{forced_id}",
                params={"select": "id,display_name,last_known_institutions,affiliations,works_count,topics,cited_by_count,orcid,ids"},
                allow_404=True,
            )
            if payload:
                return _build_row(ctx, payload, {
                    "score_name": _NAME_EXACT, "score_country": _COUNTRY_PTS,
                    "score_hist": 0, "score_inst": 0, "score_topic": 0,
                    "score_state": 0, "score_history": 0, "score_hospital": 0,
                    "score_works": 0, "score_global_penalty": 0,
                    "score_semantic": 0, "score_llm": 0,
                    "_fuzzy": 100.0, "_aunz_ever": True, "_works": 0, "_hindex": 0, "_derm_count": 0,
                }, "HIGH", "manual_override", [], "", "override")
        except Exception:
            pass

    fp_set = fp_overrides.get(ctx.name, set())

    # ── Pass 1: AU/NZ targeted search ────────────────────────────────────────
    evidence_f.write("  [Pass 1] AU/NZ targeted search\n")
    candidates = _search_aunz(client, ctx.norm_name)
    candidates = [c for c in candidates
                  if _strip_id(c.get("id")) not in blacklist
                  and _strip_id(c.get("id")) not in fp_set]

    best_p1 = _score_candidates(ctx, candidates, catalog, hv_exceptions, is_pass2=False, evidence_f=evidence_f)

    if best_p1 and best_p1["_total"] >= _P1_ACCEPT:
        evidence_f.write(f"  Pass 1 ACCEPTED: score={best_p1['_total']}\n")
        return _build_row(ctx, best_p1["_cand"], best_p1["_sc"], "HIGH",
                          "pass1_targeted", best_p1["_flags"], "", "pass1")

    # ── Pass 2: Global relaxed search ────────────────────────────────────────
    evidence_f.write("  [Pass 2] Global relaxed search\n")
    candidates2 = _search_global(client, ctx.norm_name)
    candidates2 = [c for c in candidates2
                   if _strip_id(c.get("id")) not in blacklist
                   and _strip_id(c.get("id")) not in fp_set]

    # Merge Pass 1 + Pass 2 candidates (deduplicate by ID)
    seen_ids = {_strip_id(c.get("id")) for c in candidates}
    for c in candidates2:
        if _strip_id(c.get("id")) not in seen_ids:
            candidates.append(c)

    best_p2 = _score_candidates(ctx, candidates, catalog, hv_exceptions, is_pass2=True, evidence_f=evidence_f)

    if not best_p2:
        evidence_f.write("  NOT_FOUND: no candidates passed hard filter\n")
        return _build_not_found(ctx, "pass2")

    t = best_p2["_total"]
    if t >= _P2_ACCEPT:
        evidence_f.write(f"  Pass 2 ACCEPTED: score={t}\n")
        return _build_row(ctx, best_p2["_cand"], best_p2["_sc"], "HIGH",
                          "pass2_global", best_p2["_flags"], "", "pass2")
    elif t >= _REVIEW_LOW:
        evidence_f.write(f"  Pass 2 REVIEW: score={t} → queued for Pass 3 LLM\n")
        return _build_row(ctx, best_p2["_cand"], best_p2["_sc"], "REVIEW",
                          "pass2_review", best_p2["_flags"], "", "pass2")
    else:
        evidence_f.write(f"  NOT_FOUND: best score={t} below review threshold\n")
        return _build_not_found(ctx, "pass2")


def _score_candidates(
    ctx: MemberContext,
    candidates: list[dict],
    catalog: DermInstitutionCatalog,
    hv_exceptions: set[str],
    is_pass2: bool,
    evidence_f,
) -> dict | None:
    """Score all candidates, apply hard filters, return best or None."""
    scored = []
    for cand in candidates:
        passes, reason = hard_filter(ctx, cand)
        if not passes:
            cid = _strip_id(cand.get("id"))
            evidence_f.write(f"  HARD REJECT {cid}: {reason}\n")
            continue
        if (fuzz.token_sort_ratio(ctx.norm_name, normalise_name(cand.get("display_name") or "")) < 60):
            continue  # name too dissimilar to even score
        sc = score_candidate(ctx, cand, catalog, hv_exceptions, is_pass2=is_pass2)
        t = total_score(sc)
        flags = _compute_flags(ctx, cand, sc)
        scored.append({"_cand": cand, "_sc": sc, "_total": t, "_flags": flags})

    if not scored:
        return None
    scored.sort(key=lambda r: r["_total"], reverse=True)
    best = scored[0]
    evidence_f.write(
        f"  Best candidate: {best['_cand'].get('display_name')} "
        f"score={best['_total']} fuzzy={best['_sc']['_fuzzy']:.0f} "
        f"aunz={best['_sc']['_aunz_ever']} works={best['_sc']['_works']}\n"
    )
    return best


def _compute_flags(ctx: MemberContext, candidate: dict, sc: dict) -> list[str]:
    flags = []
    works = sc.get("_works", 0)
    is_exact = sc.get("score_name", 0) == _NAME_EXACT
    is_hv = ctx.norm_name in set()  # populated at runtime

    if works > _WORKS_PENALTY_THRESHOLD and not is_exact:
        flags.append("SUSPICIOUS_VOLUME")
    if not sc.get("_aunz_ever"):
        flags.append("NO_AUNZ_HISTORY")
    if sc.get("_derm_count", 0) == 0:
        flags.append("SPECIALTY_WEAK")
    if sc.get("score_country", 0) == 0 and sc.get("score_hist", 0) == 0:
        flags.append("COUNTRY_MISMATCH")
    return flags


# ---------------------------------------------------------------------------
# Pass 3: LLM adjudication of REVIEW queue
# ---------------------------------------------------------------------------
def run_pass3_llm(
    review_rows: list[dict],
    client: OpenAlexClient,
    evidence_f,
) -> list[dict]:
    """Adjudicate all REVIEW-tier rows with Claude Sonnet."""
    updated = []
    for row in tqdm(review_rows, desc="Pass 3 LLM", leave=False):
        ctx_dict = {
            "Name": row["acd_name"], "Source": row.get("source", ""),
            "State": row.get("state", ""), "Practitioner_No_AHPRA": row.get("practitioner_no", ""),
            "Speciality_AHPRA": row.get("speciality_ahpra", ""),
            "Location_AHPRA": row.get("location_ahpra", ""),
            "Hospitals_Names_HS": row.get("_hospitals", ""),
            "Practices_Names_HS": row.get("_practices", ""),
            "Bio_HS": row.get("_bio", ""),
            "Special_Interests_HS": row.get("_interests", ""),
            "Qualifications_HS": row.get("_qualifications", ""),
            "priority": row.get("priority", "must"),
        }
        ctx = build_context(ctx_dict)

        # Reconstruct candidate dict from row
        candidate = {
            "display_name": row.get("openalex_display_name", ""),
            "last_known_institutions": [{"display_name": row.get("last_known_institution", ""),
                                         "country_code": row.get("institution_country", "")}],
            "affiliations": [],
            "works_count": int(row.get("works_count") or 0),
            "summary_stats": {"h_index": int(row.get("h_index") or 0)},
            "topics": [],
        }

        # Fetch top titles for LLM context
        cand_id = row.get("openalex_id", "")
        top_titles = []
        if cand_id:
            top_titles = _fetch_top_titles(cand_id, client)

        evidence_f.write(f"\n[Pass 3 LLM] {ctx.name}\n")
        llm_result = llm_adjudicate(ctx, candidate, top_titles, evidence_f)
        conf = float(llm_result.get("confidence") or 0.5)
        match = llm_result.get("match")
        reasoning = llm_result.get("reasoning") or ""

        # Apply LLM verdict
        if match is True and conf >= 0.85:
            row["confidence"] = "HIGH"
            row["accepted"] = "1"
            row["score_llm"] = _LLM_HIGH
            row["total_score"] = int(row.get("total_score") or 0) + _LLM_HIGH
            row["resolution_method"] = "pass3_llm_high"
        elif match is True and conf >= 0.65:
            row["confidence"] = "REVIEW"
            row["accepted"] = "0"
            row["score_llm"] = _LLM_MED
            row["total_score"] = int(row.get("total_score") or 0) + _LLM_MED
            row["resolution_method"] = "pass3_llm_review"
        elif match is False or (
            llm_result.get("specialty_consistent") is False or
            llm_result.get("geography_consistent") is False
        ):
            row["confidence"] = "NOT_FOUND"
            row["accepted"] = "0"
            row["openalex_id"] = ""
            row["openalex_display_name"] = ""
            row["profile_url"] = ""
            row["score_llm"] = 0
            row["reject_reason"] = "llm_rejected"
            row["resolution_method"] = "pass3_llm_rejected"
        else:
            # Uncertain (LLM disagreement or None)
            row["confidence"] = "REVIEW"
            row["accepted"] = "0"
            row["resolution_method"] = "pass3_llm_uncertain"

        # Merge LLM flags
        existing_flags = [f for f in (row.get("ambiguity_flags") or "").split("|") if f]
        llm_flags = [f for f in (llm_result.get("flags") or []) if f]
        all_flags = list(dict.fromkeys(existing_flags + llm_flags))
        row["ambiguity_flags"] = "|".join(all_flags)
        row["llm_reasoning"] = reasoning

        evidence_f.write(f"  → Final: {row['confidence']} ({reasoning[:80]})\n")
        updated.append(row)
        time.sleep(0.3)  # brief pause between LLM calls

    return updated


# ---------------------------------------------------------------------------
# Pass 4: Common-name & suspicious-merge audit
# ---------------------------------------------------------------------------
def run_pass4_audit(rows: list[dict], hv_exceptions: set[str]) -> tuple[list[dict], list[dict]]:
    """
    Flag common-name risks and suspicious merges.
    Returns (updated_rows, common_name_rows).
    """
    # Build name → [openalex_ids] map for common-name detection
    name_to_ids: dict[str, list[str]] = {}
    for row in rows:
        if row.get("openalex_id"):
            norm = normalise_name(row["acd_name"])
            name_to_ids.setdefault(norm, []).append(row["openalex_id"])

    # Build openalex_id → [acd_names] map for duplicate-ID detection
    id_to_names: dict[str, list[str]] = {}
    for row in rows:
        oid = row.get("openalex_id")
        if oid:
            id_to_names.setdefault(oid, []).append(row["acd_name"])

    common_name_rows = []

    for row in rows:
        flags = [f for f in (row.get("ambiguity_flags") or "").split("|") if f]
        flag_reasons = []

        # Duplicate OpenAlex ID (two ACD members matched to same profile)
        oid = row.get("openalex_id")
        if oid and len(id_to_names.get(oid, [])) > 1:
            flags.append("COMMON_NAME_RISK")
            flag_reasons.append(f"OpenAlex ID {oid} matched to {len(id_to_names[oid])} members")

        # Suspicious volume (works > 300, not exact name match, not HV exception)
        works = int(row.get("works_count") or 0)
        is_exact = int(row.get("score_name") or 0) == _NAME_EXACT
        norm = normalise_name(row.get("acd_name") or "")
        if works > _WORKS_PENALTY_THRESHOLD and not is_exact and norm not in hv_exceptions:
            flags.append("SUSPICIOUS_VOLUME")
            flag_reasons.append(f"works_count={works} but name not exact match")

        # No AU/NZ history
        if row.get("accepted") == "1" and row.get("aunz_ever") == "0":
            flags.append("NO_AUNZ_HISTORY")
            flag_reasons.append("accepted profile has no AU/NZ affiliation history")

        if flag_reasons:
            # Downgrade HIGH → REVIEW
            if row.get("confidence") == "HIGH":
                row["confidence"] = "REVIEW"
                row["accepted"] = "0"
                row["reject_reason"] = "pass4_audit:" + ";".join(flag_reasons)

            row["ambiguity_flags"] = "|".join(dict.fromkeys(flags))
            common_name_rows.append({
                "acd_name": row["acd_name"],
                "state": row.get("state", ""),
                "openalex_id": row.get("openalex_id", ""),
                "openalex_display_name": row.get("openalex_display_name", ""),
                "last_known_institution": row.get("last_known_institution", ""),
                "works_count": works,
                "ambiguity_flags": row["ambiguity_flags"],
                "total_score": row.get("total_score", 0),
                "confidence": row.get("confidence", ""),
                "flag_reason": "; ".join(flag_reasons),
            })

    return rows, common_name_rows


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------
def _build_row(
    ctx: MemberContext,
    candidate: dict,
    sc: dict,
    confidence: str,
    method: str,
    flags: list[str],
    llm_reasoning: str,
    search_pass: str,
) -> dict[str, Any]:
    lk_list = candidate.get("last_known_institutions") or []
    lk = lk_list[0] if lk_list else {}
    all_codes = _all_country_codes(candidate)
    lk_codes  = _lk_country_codes(candidate)
    aunz_ever = bool((all_codes | lk_codes) & _LOCAL_COUNTRIES)
    cand_id = _strip_id(candidate.get("id"))
    accepted = "1" if confidence == "HIGH" else "0"
    t = total_score(sc)
    return {
        "acd_name": ctx.name,
        "source": ctx.source,
        "priority": ctx.priority,
        "practitioner_no": ctx.practitioner_no,
        "state": ctx.state,
        "speciality_ahpra": ctx.speciality_ahpra,
        "location_ahpra": ctx.location_ahpra,
        "ahpra_proven": "1" if ctx.ahpra_proven else "0",
        "openalex_id": cand_id if accepted == "1" else "",
        "openalex_display_name": candidate.get("display_name") or "",
        "last_known_institution": lk.get("display_name") or "",
        "institution_country": lk.get("country_code") or "",
        "aunz_ever": "1" if aunz_ever else "0",
        "works_count": int(candidate.get("works_count") or 0),
        "h_index": int((candidate.get("summary_stats") or {}).get("h_index") or 0),
        "profile_url": candidate.get("id") or "" if accepted == "1" else "",
        "score_name": sc.get("score_name", 0),
        "score_country": sc.get("score_country", 0) + sc.get("score_hist", 0),
        "score_inst": sc.get("score_inst", 0),
        "score_topic": sc.get("score_topic", 0),
        "score_state": sc.get("score_state", 0),
        "score_history": sc.get("score_hist", 0),
        "score_hospital": sc.get("score_hospital", 0),
        "score_semantic": sc.get("score_semantic", 0),
        "score_llm": sc.get("score_llm", 0),
        "total_score": t,
        "confidence": confidence,
        "accepted": accepted,
        "reject_reason": "",
        "resolution_method": method,
        "ambiguity_flags": "|".join(flags),
        "llm_reasoning": llm_reasoning,
        "search_pass": search_pass,
        # Hidden fields for Pass 3 context (not written to CSV)
        "_hospitals": ctx.hospitals,
        "_practices": ctx.practices,
        "_bio": ctx.bio_hs,
        "_interests": ctx.interests_hs,
        "_qualifications": ctx.qualifications_hs,
    }


def _build_not_found(ctx: MemberContext, search_pass: str) -> dict[str, Any]:
    return {
        "acd_name": ctx.name, "source": ctx.source, "priority": ctx.priority,
        "practitioner_no": ctx.practitioner_no, "state": ctx.state,
        "speciality_ahpra": ctx.speciality_ahpra, "location_ahpra": ctx.location_ahpra,
        "ahpra_proven": "1" if ctx.ahpra_proven else "0",
        "openalex_id": "", "openalex_display_name": "", "last_known_institution": "",
        "institution_country": "", "aunz_ever": "0", "works_count": 0, "h_index": 0,
        "profile_url": "",
        "score_name": 0, "score_country": 0, "score_inst": 0, "score_topic": 0,
        "score_state": 0, "score_history": 0, "score_hospital": 0,
        "score_semantic": 0, "score_llm": 0, "total_score": 0,
        "confidence": "NOT_FOUND", "accepted": "0", "reject_reason": "no_viable_candidate",
        "resolution_method": "not_found", "ambiguity_flags": "", "llm_reasoning": "",
        "search_pass": search_pass,
        "_hospitals": ctx.hospitals, "_practices": ctx.practices,
        "_bio": ctx.bio_hs, "_interests": ctx.interests_hs,
        "_qualifications": ctx.qualifications_hs,
    }


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------
def run(
    *,
    input_path: Path = INPUT_CSV,
    institutions_path: Path = INST_CSV,
    hv_exceptions_path: Path = HV_EXCEPT,
    overrides_path: Path = OVERRIDES,
    fp_overrides_path: Path = FP_OVERRIDES,
    blacklist_path: Path = BLACKLIST,
    out_dir: Path = ROOT / "data",
    must_only: bool = True,
    include_nice: bool = False,
    limit: Optional[int] = None,
    budget_limit: int = 100_000,
    session: Optional[requests.Session] = None,
    email: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    processed_dir = out_dir / "processed"
    logs_dir = out_dir / "logs"
    processed_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    out_csv          = processed_dir / "authors_resolved.csv"
    reject_csv       = processed_dir / "resolution_rejects.csv"
    review_csv       = processed_dir / "review_queue.csv"
    common_name_csv  = processed_dir / "common_name_review.csv"
    evidence_log     = logs_dir / "resolution.log"
    credit_state     = logs_dir / "credit_usage.json"

    # Logging setup
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.FileHandler(logs_dir / "01c_resolver.log", mode="a", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(fh)

    evidence_f = evidence_log.open("a", encoding="utf-8")
    evidence_f.write(f"\n===== ACD resolver v2 @ {datetime.now().isoformat()} =====\n")

    # Load reference data
    catalog      = DermInstitutionCatalog.load(institutions_path)
    hv_exceptions = load_high_volume_exceptions(hv_exceptions_path)
    overrides    = _load_overrides(overrides_path)
    fp_overrides = _load_fp_overrides(fp_overrides_path)
    blacklist    = _load_blacklist(blacklist_path)
    logger.info("Loaded %d institution patterns, %d HV exceptions, %d overrides",
                len(catalog.patterns), len(hv_exceptions), len(overrides))

    # Load members
    df = load_members(input_path)
    if must_only and not include_nice:
        df = df[df["priority"] == "must"].reset_index(drop=True)
    if limit is not None:
        df = df.head(limit).reset_index(drop=True)
    logger.info("Processing %d members", len(df))

    # OpenAlex client
    budget = CreditBudget(daily_limit=budget_limit, state_path=credit_state)
    client = OpenAlexClient(
        email=email or os.environ.get("OPENALEX_EMAIL", ""),
        api_key=api_key or os.environ.get("OPENALEX_API_KEY", ""),
        base_url=base_url or os.environ.get("OPENALEX_BASE_URL") or "https://api.openalex.org",
        session=session if session is not None else requests.Session(),
        max_retries=2,
        on_success=lambda _payload: budget.charge(1),
    )

    # Checkpoint writer (crash-safe incremental writes)
    accepted_writer = CheckpointWriter(
        csv_path=out_csv, columns=OUTPUT_COLUMNS,
        key_column="acd_name", progress_log=logs_dir / "resolution_progress.csv",
    )
    already_done = accepted_writer._seen  # set of acd_name strings already written
    logger.info("Resuming: %d already resolved, %d remaining",
                len(already_done), len(df) - len(already_done))

    all_rows: list[dict] = []
    counts = {"HIGH": 0, "REVIEW": 0, "LOW": 0, "NOT_FOUND": 0}
    exhausted = False

    # ── Pass 1 + 2 ────────────────────────────────────────────────────────────
    pbar = tqdm(df.to_dict("records"), desc="Pass 1+2", unit="member")
    try:
        for raw in pbar:
            ctx = build_context(raw)
            if not ctx.name or ctx.name in already_done:
                continue
            try:
                row = resolve_member(
                    ctx, client, catalog, hv_exceptions,
                    overrides, fp_overrides, blacklist, evidence_f,
                )
            except BudgetExhausted:
                logger.warning("Budget exhausted at %s", ctx.name)
                exhausted = True
                break

            all_rows.append(row)
            out_row = {k: row.get(k, "") for k in OUTPUT_COLUMNS}
            accepted_writer.write_row(out_row)
            tier = row.get("confidence", "NOT_FOUND")
            counts[tier] = counts.get(tier, 0) + 1
            pbar.set_postfix(HIGH=counts["HIGH"], REVIEW=counts["REVIEW"],
                             NOT_FOUND=counts["NOT_FOUND"])
            time.sleep(_PER_MEMBER_SLEEP)
    finally:
        pbar.close()

    # ── Pass 3: LLM adjudication of REVIEW queue ──────────────────────────────
    review_rows = [r for r in all_rows if r.get("confidence") == "REVIEW"]
    logger.info("Pass 3: %d REVIEW members queued for LLM adjudication", len(review_rows))

    if review_rows and not exhausted:
        review_rows = run_pass3_llm(review_rows, client, evidence_f)
        # Update all_rows with LLM results
        review_map = {r["acd_name"]: r for r in review_rows}
        for i, row in enumerate(all_rows):
            if row["acd_name"] in review_map:
                all_rows[i] = review_map[row["acd_name"]]
        # Update counts
        counts["REVIEW"] = sum(1 for r in all_rows if r.get("confidence") == "REVIEW")
        counts["HIGH"] = sum(1 for r in all_rows if r.get("confidence") == "HIGH")
        counts["NOT_FOUND"] = sum(1 for r in all_rows if r.get("confidence") == "NOT_FOUND")

    # ── Pass 4: Common-name & suspicious-merge audit ──────────────────────────
    logger.info("Pass 4: running common-name and suspicious-merge audit")
    all_rows, common_name_rows = run_pass4_audit(all_rows, hv_exceptions)

    # ── Write final outputs ───────────────────────────────────────────────────
    # Rewrite full accepted CSV (with Pass 3 + 4 updates)
    final_writer = CheckpointWriter(
        csv_path=out_csv, columns=OUTPUT_COLUMNS,
        key_column="acd_name", progress_log=logs_dir / "resolution_progress_final.csv",
    )
    for row in all_rows:
        final_writer.write_row({k: row.get(k, "") for k in OUTPUT_COLUMNS})

    # Write review queue
    if review_rows:
        review_df = pd.DataFrame([{k: r.get(k, "") for k in OUTPUT_COLUMNS} for r in review_rows])
        review_df.to_csv(review_csv, index=False)
        logger.info("Review queue written: %d rows → %s", len(review_rows), review_csv)

    # Write common-name review
    if common_name_rows:
        pd.DataFrame(common_name_rows).to_csv(common_name_csv, index=False)
        logger.info("Common-name review written: %d rows → %s", len(common_name_rows), common_name_csv)

    # Write rejects
    reject_rows = [r for r in all_rows if r.get("confidence") not in ("HIGH",)]
    if reject_rows:
        reject_df = pd.DataFrame([{k: r.get(k, "") for k in REJECT_COLUMNS if k in r} for r in reject_rows])
        reject_df.to_csv(reject_csv, index=False)

    evidence_f.close()

    final_counts = {
        "HIGH": sum(1 for r in all_rows if r.get("confidence") == "HIGH"),
        "REVIEW": sum(1 for r in all_rows if r.get("confidence") == "REVIEW"),
        "NOT_FOUND": sum(1 for r in all_rows if r.get("confidence") == "NOT_FOUND"),
        "LOW": sum(1 for r in all_rows if r.get("confidence") == "LOW"),
    }
    logger.info("Resolution complete: %s", final_counts)

    return {
        "processed": len(all_rows),
        "counts": final_counts,
        "exhausted": exhausted,
        "out_csv": out_csv,
        "reject_csv": reject_csv,
        "review_csv": review_csv,
        "common_name_csv": common_name_csv,
        "log_path": evidence_log,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ACD dermatologist entity resolver v2.")
    p.add_argument("--input", type=Path, default=INPUT_CSV)
    p.add_argument("--institutions", type=Path, default=INST_CSV)
    p.add_argument("--out-dir", type=Path, default=ROOT / "data")
    p.add_argument("--must-only", action="store_true", default=True)
    p.add_argument("--include-nice", dest="must_only", action="store_false")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--budget", type=int, default=100_000)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    result = run(
        input_path=args.input,
        institutions_path=args.institutions,
        out_dir=args.out_dir,
        must_only=args.must_only,
        limit=args.limit,
        budget_limit=args.budget,
    )
    print("\n" + "=" * 60)
    print("ACD AUTHOR RESOLVER v2 SUMMARY")
    print("=" * 60)
    print(f"Processed : {result['processed']}")
    for k, v in result["counts"].items():
        print(f"  {k:<12}: {v}")
    print(f"Budget exhausted: {result['exhausted']}")
    print(f"Resolved CSV    : {result['out_csv']}")
    print(f"Review queue    : {result['review_csv']}")
    print(f"Common-name     : {result['common_name_csv']}")
    print(f"Evidence log    : {result['log_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
