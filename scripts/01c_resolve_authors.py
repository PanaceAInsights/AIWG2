"""Phase 1 — Advanced ML-assisted entity resolver for ACD dermatologists.

Architecture
============
This resolver replaces the RMSANZ co-authorship bootstrap (which caused
false-positive merges) with a multi-signal Bayesian-style scoring engine
augmented by three ML/AI layers:

  Layer A — Deterministic signals (7 independent evidence signals)
  Layer B — Semantic similarity (TF-IDF cosine over HealthShare bio/interests
             vs OpenAlex abstract corpus for each candidate)
  Layer C — LLM-assisted disambiguation (Claude claude-haiku-4-20250514 called only
             for borderline cases where deterministic score is 55–89, to
             adjudicate with chain-of-thought reasoning)

Uncertainty & manual-review flagging
=====================================
Every accepted match receives one of four confidence tiers:
  HIGH        — score ≥ 90, all hard gates pass, no ambiguity flags
  REVIEW      — score 65–89, or any ambiguity flag raised
  LOW         — score 40–64 (tracked, not accepted in dashboard)
  NOT_FOUND   — no viable candidate

Ambiguity flags (any one raises tier to REVIEW):
  COMMON_NAME         — name appears in >1 accepted match (dedup check)
  HIGH_VOLUME         — candidate has >500 works (suspicious merge risk)
  WEAK_TOPIC          — topic density < 10% dermatology
  COUNTRY_MISMATCH    — last-known institution not AU/NZ
  LLM_UNCERTAIN       — LLM returned confidence < 0.7 for borderline case
  NAME_ONLY           — only name signal fired (no corroborating signals)

Scoring rubric (max 165 pts)
==============================
Signal 1  Name similarity
          exact match (normalised)                          40 pts
          fuzzy ≥ 92 (token_sort_ratio)                    30 pts
          fuzzy ≥ 85                                        20 pts
          fuzzy ≥ 75                                        10 pts

Signal 2  Current AU/NZ institution (last_known)           25 pts

Signal 3  Curated AU/NZ dermatology institution catalog    20 pts
          (substring match against institution names)

Signal 4  Topic density (% of works in dermatology topics)
          ≥ 50 %                                           20 pts
          ≥ 30 %                                           10 pts
          ≥ 15 %                                            5 pts

Signal 5  State / city keyword match                       10 pts

Signal 6  Historical AU/NZ affiliation (any year)          10 pts

Signal 7  Hospital / practice name match                   10 pts
          (from HealthShare Hospitals_Names_HS / Practices_Names_HS)

Signal 8  AHPRA practitioner-number anchor                 20 pts
          (MED prefix confirmed + "Dermatology" in speciality)

Semantic layer (Layer B)
  TF-IDF cosine similarity between HealthShare bio/interests
  and candidate's top-3 abstract snippets.
  cosine ≥ 0.35                                            15 pts
  cosine ≥ 0.20                                             8 pts

LLM layer (Layer C) — borderline only (score 55–89)
  Claude haiku adjudicates with structured JSON output:
  {
    "match": true/false,
    "confidence": 0.0–1.0,
    "reasoning": "...",
    "flags": ["..."]
  }
  LLM match=true + confidence ≥ 0.85                      +20 pts
  LLM match=true + confidence ≥ 0.70                      +10 pts
  LLM match=false                                          -30 pts

Acceptance policy
==================
  accepted = score ≥ 90 AND aunz_ever AND name_fuzzy ≥ 75
  REVIEW   = score 65–89 OR any ambiguity flag
  LOW      = score 40–64
  NOT_FOUND = score < 40 OR no candidates

Manual override
================
  data/input/manual_resolver_overrides.csv  — force a specific OpenAlex ID
  data/input/manual_fp_overrides.csv        — reject a specific OpenAlex ID
  data/input/manual_resolver_blacklist.csv  — blacklist an OpenAlex ID globally

CLI
====
  python scripts/01c_resolve_authors.py [options]
  python scripts/01c_resolve_authors.py --help
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import time
import unicodedata
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
# Constants
# ---------------------------------------------------------------------------
INPUT_CSV   = ROOT / "data" / "input" / "Dermatologists_Consolidated.csv"
INST_CSV    = ROOT / "data" / "input" / "derm_institutions_au_nz.csv"
OVERRIDES   = ROOT / "data" / "input" / "manual_resolver_overrides.csv"
FP_OVERRIDES = ROOT / "data" / "input" / "manual_fp_overrides.csv"
BLACKLIST   = ROOT / "data" / "input" / "manual_resolver_blacklist.csv"
OUT_DIR     = ROOT / "data" / "processed"
LOGS_DIR    = ROOT / "data" / "logs"

_AUNZ_AFF_FILTER = "affiliations.institution.country_code:AU|affiliations.institution.country_code:NZ"
_LOCAL_COUNTRIES = {"AU", "NZ"}
_CANDIDATES_PER_SEARCH = 10
_PER_MEMBER_SLEEP = 0.35   # seconds between OpenAlex calls
_BORDERLINE_LOW  = 55      # lower bound for LLM adjudication
_BORDERLINE_HIGH = 89      # upper bound for LLM adjudication
_ACCEPT_THRESHOLD = 90
_REVIEW_THRESHOLD = 65
_HIGH_VOLUME_THRESHOLD = 500  # works count above which HIGH_VOLUME flag fires

# Scoring weights
_NAME_EXACT   = 40
_NAME_FUZZY92 = 30
_NAME_FUZZY85 = 20
_NAME_FUZZY75 = 10
_COUNTRY_PTS  = 25
_INST_PTS     = 20
_TOPIC_50     = 20
_TOPIC_30     = 10
_TOPIC_15     = 5
_STATE_PTS    = 10
_HIST_PTS     = 10
_HOSP_PTS     = 10
_AHPRA_PTS    = 20
_SEM_35       = 15
_SEM_20       = 8
_LLM_HIGH     = 20
_LLM_MED      = 10
_LLM_NEG      = -30

# Dermatology topic density keywords (OpenAlex topic labels)
_DERM_TOPIC_TOKENS = (
    "dermatol", "melanom", "skin cancer", "psoriasis", "eczema",
    "atopic", "vitiligo", "alopecia", "rosacea", "acne", "cutaneous",
    "mohs", "phototherap", "dermoscop", "urticaria", "pemphigus",
    "pemphigoid", "bullous", "hidradenitis", "ichthyosis", "onychomycosis",
    "hyperhidrosis", "pruritus", "scabies", "herpes zoster",
    "lupus erythematosus", "scleroderma", "vasculitis", "wound heal",
    "basal cell", "squamous cell carcinom", "skin neoplasm",
)

OUTPUT_COLUMNS: list[str] = [
    "acd_name",
    "source",
    "priority",
    "practitioner_no",
    "state",
    "speciality_ahpra",
    "location_ahpra",
    "ahpra_proven",
    "openalex_id",
    "openalex_display_name",
    "last_known_institution",
    "institution_country",
    "aunz_ever",
    "works_count",
    "profile_url",
    "score_name",
    "score_country",
    "score_inst",
    "score_topic",
    "score_state",
    "score_history",
    "score_hospital",
    "score_ahpra",
    "score_semantic",
    "score_llm",
    "total_score",
    "confidence",
    "accepted",
    "reject_reason",
    "resolution_method",
    "ambiguity_flags",
    "llm_reasoning",
    "search_stage",
]

REJECT_COLUMNS: list[str] = [
    "acd_name",
    "acd_state",
    "ahpra_proven",
    "top_candidate_id",
    "top_candidate_name",
    "top_candidate_institution",
    "top_candidate_country",
    "top_candidate_aunz_ever",
    "top_candidate_works_count",
    "score_name",
    "score_country",
    "score_inst",
    "score_topic",
    "score_state",
    "score_history",
    "score_hospital",
    "score_ahpra",
    "score_semantic",
    "score_llm",
    "total_score",
    "confidence",
    "reject_reason",
    "ambiguity_flags",
    "runner_up_id",
    "runner_up_name",
    "runner_up_total_score",
    "top_candidate_profile_url",
]

# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------
def _priority(source: Any) -> str:
    s = str(source or "").strip()
    if s in ("Both", "AHPRA Only"):
        return "must"
    return "nice"


def load_members(input_path: Path) -> pd.DataFrame:
    df = pd.read_csv(input_path, dtype=str).fillna("")
    df["priority"] = df["Source"].map(_priority)
    df["_rank"] = df["priority"].map({"must": 0, "nice": 1})
    df = df.sort_values(by=["_rank", "Name"], kind="stable").reset_index(drop=True)
    return df.drop(columns=["_rank"])


# ---------------------------------------------------------------------------
# Member context dataclass
# ---------------------------------------------------------------------------
@dataclass
class MemberContext:
    """Everything the resolver needs about a single ACD dermatologist."""
    name: str
    source: str
    state: str
    practitioner_no: str
    speciality_ahpra: str
    location_ahpra: str
    hospitals: str          # pipe-joined from Hospitals_Names_HS
    practices: str          # pipe-joined from Practices_Names_HS
    bio_hs: str             # HealthShare biography (rich text)
    interests_hs: str       # HealthShare special interests
    qualifications_hs: str  # HealthShare qualifications
    priority: str

    @property
    def ahpra_proven(self) -> bool:
        """True iff this member has a confirmed AU AHPRA dermatology registration."""
        pno = self.practitioner_no.strip().upper()
        spec = self.speciality_ahpra.lower()
        return pno.startswith("MED") and "dermatology" in spec

    @property
    def hospital_patterns(self) -> list[str]:
        return _extract_pipe_patterns(self.hospitals)

    @property
    def practice_patterns(self) -> list[str]:
        return _extract_pipe_patterns(self.practices)

    @property
    def semantic_text(self) -> str:
        """Combined HealthShare text for TF-IDF semantic matching."""
        parts = [self.bio_hs, self.interests_hs, self.qualifications_hs]
        return " ".join(p for p in parts if p.strip())


def _extract_pipe_patterns(field: str | None) -> list[str]:
    if not field:
        return []
    out, seen = [], set()
    for entry in str(field).split("|"):
        name = re.sub(r"\([^)]*\)", "", entry).strip().lower()
        if not name or len(name) < 5 or name in seen:
            continue
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
        patterns = [r.strip().lower() for r in df[col] if r.strip()]
        return cls(patterns=patterns)

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
    """acd_name → correct_openalex_id"""
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str).fillna("")
    return {
        str(r["acd_name"]).strip(): str(r["correct_openalex_id"]).strip()
        for _, r in df.iterrows()
        if r.get("acd_name") and r.get("correct_openalex_id")
    }


def _load_fp_overrides(path: Path) -> dict[str, set[str]]:
    """acd_name → set of openalex_ids to reject"""
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
    """Global set of OpenAlex IDs to never accept."""
    if not path.exists():
        return set()
    df = pd.read_csv(path, dtype=str).fillna("")
    col = "openalex_id_to_blacklist" if "openalex_id_to_blacklist" in df.columns else df.columns[0]
    return {str(v).strip() for v in df[col] if str(v).strip()}


# ---------------------------------------------------------------------------
# OpenAlex helpers
# ---------------------------------------------------------------------------
def _strip_openalex_id(raw: str | None) -> str:
    if not raw:
        return ""
    return raw.split("/")[-1]


def _all_country_codes(candidate: dict) -> set[str]:
    codes: set[str] = set()
    for aff in candidate.get("affiliations") or []:
        inst = aff.get("institution") or {}
        cc = inst.get("country_code") or ""
        if cc:
            codes.add(cc.upper())
    return codes


def _last_known_country_codes(candidate: dict) -> set[str]:
    lk = candidate.get("last_known_institution") or {}
    cc = lk.get("country_code") or ""
    return {cc.upper()} if cc else set()


def _all_institution_names(candidate: dict) -> list[str]:
    names: list[str] = []
    lk = candidate.get("last_known_institution") or {}
    if lk.get("display_name"):
        names.append(lk["display_name"])
    for aff in candidate.get("affiliations") or []:
        inst = aff.get("institution") or {}
        if inst.get("display_name"):
            names.append(inst["display_name"])
    return names


def _topic_density(candidate: dict) -> float:
    """Fraction of candidate's topic entries that are dermatology-related."""
    topics = candidate.get("topics") or []
    if not topics:
        return 0.0
    derm_count = 0
    for t in topics:
        label = " ".join([
            t.get("display_name") or "",
            t.get("subfield", {}).get("display_name") or "",
            t.get("field", {}).get("display_name") or "",
        ]).lower()
        if any(tok in label for tok in _DERM_TOPIC_TOKENS):
            derm_count += 1
    return derm_count / len(topics)


def _fetch_topic_density(
    candidate_id: str,
    client: OpenAlexClient,
    cache: dict[str, float],
) -> float:
    if candidate_id in cache:
        return cache[candidate_id]
    try:
        payload = client.get(
            f"/authors/{candidate_id}",
            params={"select": "id,topics"},
            allow_404=True,
        )
        density = _topic_density(payload or {})
    except Exception:
        density = 0.0
    cache[candidate_id] = density
    return density


def _fetch_abstract_snippets(
    candidate_id: str,
    client: OpenAlexClient,
    n: int = 5,
) -> list[str]:
    """Fetch top-n cited abstracts for a candidate (for semantic matching)."""
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
        results = (payload or {}).get("results") or []
        snippets = []
        for w in results:
            abstract = reconstruct_abstract(w.get("abstract_inverted_index") or {})
            title = w.get("title") or ""
            text = f"{title}. {abstract}".strip()
            if text:
                snippets.append(text)
        return snippets
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Scoring — deterministic signals
# ---------------------------------------------------------------------------
def _name_score(member_norm: str, candidate: dict) -> tuple[int, float]:
    """Return (name_pts, fuzzy_score)."""
    cand_display = candidate.get("display_name") or ""
    cand_norm = normalise_name(cand_display)
    if not cand_norm or not member_norm:
        return 0, 0.0
    if member_norm == cand_norm:
        return _NAME_EXACT, 100.0
    fuzzy = fuzz.token_sort_ratio(member_norm, cand_norm)
    if fuzzy >= 92:
        return _NAME_FUZZY92, float(fuzzy)
    if fuzzy >= 85:
        return _NAME_FUZZY85, float(fuzzy)
    if fuzzy >= 75:
        return _NAME_FUZZY75, float(fuzzy)
    return 0, float(fuzzy)


def _state_match(state: str, inst_names: list[str]) -> bool:
    """Check if any institution name contains the member's state abbreviation or full name."""
    if not state:
        return False
    _STATE_MAP = {
        "NSW": ["new south wales", "nsw", "sydney"],
        "VIC": ["victoria", "vic", "melbourne"],
        "QLD": ["queensland", "qld", "brisbane"],
        "SA":  ["south australia", " sa ", "adelaide"],
        "WA":  ["western australia", " wa ", "perth"],
        "TAS": ["tasmania", "tas", "hobart"],
        "ACT": ["canberra", "act"],
        "NT":  ["northern territory", " nt ", "darwin"],
        "NZ":  ["new zealand", " nz ", "auckland", "wellington", "christchurch"],
    }
    tokens = _STATE_MAP.get(state.upper(), [state.lower()])
    combined = " ".join(inst_names).lower()
    return any(tok in combined for tok in tokens)


def score_candidate_deterministic(
    ctx: MemberContext,
    candidate: dict,
    catalog: DermInstitutionCatalog,
) -> dict[str, Any]:
    """Compute all deterministic signals. Returns score dict."""
    member_norm = normalise_name(ctx.name)
    name_pts, fuzzy = _name_score(member_norm, candidate)

    all_codes = _all_country_codes(candidate)
    lk_codes  = _last_known_country_codes(candidate)
    aunz_ever = bool(all_codes & _LOCAL_COUNTRIES)
    lk_aunz   = bool(lk_codes & _LOCAL_COUNTRIES)

    country_pts = _COUNTRY_PTS if lk_aunz else 0
    hist_pts    = _HIST_PTS if aunz_ever else 0

    inst_names = _all_institution_names(candidate)
    inst_pts   = _INST_PTS if catalog.match_any(inst_names) else 0
    state_pts  = _STATE_PTS if _state_match(ctx.state, inst_names) else 0

    # Hospital / practice name match
    hosp_pts = 0
    if ctx.hospital_patterns or ctx.practice_patterns:
        combined = " ".join(inst_names).lower()
        for pat in ctx.hospital_patterns + ctx.practice_patterns:
            if pat and pat in combined:
                hosp_pts = _HOSP_PTS
                break

    ahpra_pts = _AHPRA_PTS if ctx.ahpra_proven else 0

    return {
        "score_name":    name_pts,
        "score_country": country_pts,
        "score_inst":    inst_pts,
        "score_state":   state_pts,
        "score_history": hist_pts,
        "score_hospital": hosp_pts,
        "score_ahpra":   ahpra_pts,
        "score_topic":   0,   # filled in later
        "score_semantic": 0,  # filled in later
        "score_llm":     0,   # filled in later
        "_name_fuzzy":   fuzzy,
        "_aunz_ever":    aunz_ever,
    }


def total_score(scores: dict[str, Any]) -> int:
    return sum(
        scores.get(k, 0)
        for k in (
            "score_name", "score_country", "score_inst", "score_state",
            "score_history", "score_hospital", "score_ahpra",
            "score_topic", "score_semantic", "score_llm",
        )
    )


# ---------------------------------------------------------------------------
# Semantic similarity (Layer B)
# ---------------------------------------------------------------------------
def compute_semantic_score(
    ctx: MemberContext,
    candidate_id: str,
    client: OpenAlexClient,
) -> int:
    """TF-IDF cosine similarity between HS bio/interests and candidate abstracts."""
    member_text = ctx.semantic_text.strip()
    if not member_text:
        return 0
    snippets = _fetch_abstract_snippets(candidate_id, client, n=5)
    if not snippets:
        return 0
    try:
        corpus = [member_text] + snippets
        vec = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),
            max_features=8000,
            sublinear_tf=True,
            min_df=1,
        )
        tfidf = vec.fit_transform(corpus)
        sims = cosine_similarity(tfidf[0:1], tfidf[1:]).flatten()
        best = float(np.max(sims)) if len(sims) > 0 else 0.0
        if best >= 0.35:
            return _SEM_35
        if best >= 0.20:
            return _SEM_20
        return 0
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# LLM adjudication (Layer C) — borderline cases only
# ---------------------------------------------------------------------------
_LLM_SYSTEM = """You are an expert biomedical entity resolution assistant.
Your task is to determine whether a given OpenAlex researcher profile
belongs to a specific Australian/New Zealand dermatologist.

You will receive:
1. The dermatologist's name, state, AHPRA speciality, and HealthShare bio/interests.
2. The OpenAlex candidate's display name, institution, country, works count, and
   their top publication titles.

Respond ONLY with a valid JSON object in this exact format:
{
  "match": true or false,
  "confidence": 0.0 to 1.0,
  "reasoning": "one or two sentences explaining your decision",
  "flags": ["list of concern flags, e.g. COMMON_NAME, COUNTRY_MISMATCH, or empty list"]
}

Be conservative: if in doubt, set match=false. A false negative is much less
harmful than a false positive (merging two different people's publication records).
"""


def llm_adjudicate(
    ctx: MemberContext,
    candidate: dict,
    top_titles: list[str],
) -> dict[str, Any]:
    """Call Claude haiku to adjudicate a borderline match. Returns structured result."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        lk = candidate.get("last_known_institution") or {}
        prompt = f"""DERMATOLOGIST:
Name: {ctx.name}
State: {ctx.state}
AHPRA Speciality: {ctx.speciality_ahpra}
HealthShare Bio: {ctx.bio_hs[:400] if ctx.bio_hs else 'N/A'}
HealthShare Interests: {ctx.interests_hs[:400] if ctx.interests_hs else 'N/A'}
Qualifications: {ctx.qualifications_hs[:300] if ctx.qualifications_hs else 'N/A'}

OPENALEX CANDIDATE:
Display Name: {candidate.get('display_name', 'N/A')}
Last Known Institution: {lk.get('display_name', 'N/A')} ({lk.get('country_code', 'N/A')})
Works Count: {candidate.get('works_count', 'N/A')}
Top Publication Titles:
{chr(10).join(f'  - {t}' for t in top_titles[:5]) if top_titles else '  (none available)'}

Is this OpenAlex profile the same person as the dermatologist listed above?"""

        response = client.messages.create(
            model="claude-haiku-4-20250514",
            max_tokens=512,
            system=_LLM_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Extract JSON from response
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as exc:
        logger.warning("LLM adjudication failed: %s", exc)
    return {"match": None, "confidence": 0.5, "reasoning": "LLM call failed", "flags": []}


# ---------------------------------------------------------------------------
# Acceptance policy
# ---------------------------------------------------------------------------
def apply_acceptance_policy(
    ctx: MemberContext,
    scores: dict[str, Any],
    t_score: int,
    candidate: dict,
    llm_result: dict | None = None,
) -> tuple[str, str, list[str]]:
    """Return (confidence_tier, reject_reason, ambiguity_flags)."""
    flags: list[str] = []
    fuzzy = scores.get("_name_fuzzy", 0.0)
    aunz_ever = scores.get("_aunz_ever", False)
    works_count = int(candidate.get("works_count") or 0)

    # Hard gates
    if fuzzy < 75:
        return "NOT_FOUND", "below_name_fuzzy_75", flags
    if not aunz_ever and ctx.ahpra_proven:
        return "NOT_FOUND", "ahpra_proven_but_no_aunz_affiliation", flags

    # Ambiguity flags
    if works_count > _HIGH_VOLUME_THRESHOLD:
        flags.append("HIGH_VOLUME")
    if scores.get("score_topic", 0) == 0 and scores.get("score_semantic", 0) == 0:
        flags.append("WEAK_TOPIC")
    if scores.get("score_country", 0) == 0:
        flags.append("COUNTRY_MISMATCH")
    if (scores.get("score_name", 0) > 0 and
            scores.get("score_country", 0) == 0 and
            scores.get("score_inst", 0) == 0 and
            scores.get("score_hospital", 0) == 0 and
            scores.get("score_ahpra", 0) == 0):
        flags.append("NAME_ONLY")
    if llm_result and llm_result.get("confidence", 1.0) < 0.7:
        flags.append("LLM_UNCERTAIN")
    if llm_result:
        for f in (llm_result.get("flags") or []):
            if f and f not in flags:
                flags.append(f)

    if t_score >= _ACCEPT_THRESHOLD and not flags:
        return "HIGH", "", flags
    if t_score >= _ACCEPT_THRESHOLD and flags:
        return "REVIEW", f"flags:{','.join(flags)}", flags
    if t_score >= _REVIEW_THRESHOLD:
        return "REVIEW", f"score_{t_score}_flags:{','.join(flags)}", flags
    return "LOW", f"score_below_review:{t_score}", flags


# ---------------------------------------------------------------------------
# Candidate summary helper
# ---------------------------------------------------------------------------
def candidate_summary(candidate: dict) -> dict[str, Any]:
    lk = candidate.get("last_known_institution") or {}
    return {
        "openalex_id":    _strip_openalex_id(candidate.get("id")),
        "display_name":   candidate.get("display_name") or "",
        "institution":    lk.get("display_name") or "",
        "country":        lk.get("country_code") or "",
        "works_count":    candidate.get("works_count") or 0,
        "profile_url":    candidate.get("id") or "",
        "aunz_ever":      bool(_all_country_codes(candidate) & _LOCAL_COUNTRIES),
    }


# ---------------------------------------------------------------------------
# Two-stage search
# ---------------------------------------------------------------------------
def _search(
    client: OpenAlexClient,
    search_name: str,
    country_filter: bool,
) -> list[dict[str, Any]]:
    if not search_name:
        return []
    params: dict[str, Any] = {
        "search": search_name,
        "per-page": _CANDIDATES_PER_SEARCH,
    }
    if country_filter:
        params["filter"] = _AUNZ_AFF_FILTER
    try:
        payload = client.get("/authors", params=params, allow_404=True)
        return payload.get("results") or []
    except BudgetExhausted:
        raise
    except Exception as exc:
        logger.warning("search failed (country=%s) for %s: %s", country_filter, search_name, exc)
        return []


# ---------------------------------------------------------------------------
# Per-member resolution
# ---------------------------------------------------------------------------
def resolve_member(
    ctx: MemberContext,
    client: OpenAlexClient,
    catalog: DermInstitutionCatalog,
    topic_cache: dict[str, float],
    overrides: dict[str, str],
    fp_overrides: dict[str, set[str]],
    blacklist: set[str],
    evidence_f,
) -> dict[str, Any]:
    """Full resolution pipeline for a single dermatologist."""
    search_name = normalise_name(ctx.name)
    evidence_f.write(f"\n--- {ctx.name} ({ctx.state}) ---\n")

    # ── Manual override ──────────────────────────────────────────────────────
    if ctx.name in overrides:
        forced_id = overrides[ctx.name]
        evidence_f.write(f"  MANUAL OVERRIDE → {forced_id}\n")
        try:
            payload = client.get(f"/authors/{forced_id}", params={"select": "id,display_name,last_known_institution,affiliations,works_count,topics"}, allow_404=True)
            if payload:
                summ = candidate_summary(payload)
                return _build_accepted_row(ctx, summ, {
                    "score_name": _NAME_EXACT, "score_country": _COUNTRY_PTS,
                    "score_inst": 0, "score_topic": 0, "score_state": 0,
                    "score_history": 0, "score_hospital": 0, "score_ahpra": 0,
                    "score_semantic": 0, "score_llm": 0,
                    "_name_fuzzy": 100.0, "_aunz_ever": summ["aunz_ever"],
                }, "manual_override", [], "", "aunz")
        except Exception:
            pass

    # ── Stage 1: AU/NZ-filtered search ──────────────────────────────────────
    stage = "aunz"
    candidates = _search(client, search_name, country_filter=True)
    if not candidates:
        candidates = _search(client, search_name, country_filter=False)
        stage = "global"

    evidence_f.write(f"  stage={stage} candidates={len(candidates)}\n")

    # ── Apply blacklist + per-member FP overrides ────────────────────────────
    fp_set = fp_overrides.get(ctx.name, set())
    candidates = [
        c for c in candidates
        if _strip_openalex_id(c.get("id")) not in blacklist
        and _strip_openalex_id(c.get("id")) not in fp_set
    ]

    if not candidates:
        return _build_not_found_row(ctx, stage)

    # ── Deterministic scoring ────────────────────────────────────────────────
    scored: list[dict[str, Any]] = []
    for cand in candidates:
        sc = score_candidate_deterministic(ctx, cand, catalog)
        if sc["score_name"] == 0:
            continue  # zero name signal → skip entirely

        # Topic density (cached)
        cand_id = _strip_openalex_id(cand.get("id"))
        if cand_id:
            density = _fetch_topic_density(cand_id, client, topic_cache)
            if density >= 0.50:
                sc["score_topic"] = _TOPIC_50
            elif density >= 0.30:
                sc["score_topic"] = _TOPIC_30
            elif density >= 0.15:
                sc["score_topic"] = _TOPIC_15

        scored.append({"candidate": cand, "scores": sc})

    if not scored:
        return _build_not_found_row(ctx, stage)

    # Sort by provisional total (without semantic/LLM)
    scored.sort(key=lambda r: total_score(r["scores"]), reverse=True)
    winner_row = scored[0]
    winner = winner_row["candidate"]
    winner_scores = winner_row["scores"]
    winner_id = _strip_openalex_id(winner.get("id"))
    prov_total = total_score(winner_scores)

    # ── Semantic similarity (Layer B) ────────────────────────────────────────
    if winner_id and ctx.semantic_text:
        sem_pts = compute_semantic_score(ctx, winner_id, client)
        winner_scores["score_semantic"] = sem_pts
        evidence_f.write(f"  semantic_score={sem_pts}\n")

    # ── LLM adjudication (Layer C) — borderline only ─────────────────────────
    llm_result: dict | None = None
    llm_reasoning = ""
    current_total = total_score(winner_scores)
    if _BORDERLINE_LOW <= current_total <= _BORDERLINE_HIGH:
        evidence_f.write(f"  borderline score={current_total} → LLM adjudication\n")
        top_titles = []
        try:
            works_payload = client.get(
                "/works",
                params={
                    "filter": f"authorships.author.id:{winner_id}",
                    "sort": "cited_by_count:desc",
                    "per-page": 5,
                    "select": "title",
                },
                allow_404=True,
            )
            top_titles = [w.get("title") or "" for w in (works_payload or {}).get("results") or []]
        except Exception:
            pass

        llm_result = llm_adjudicate(ctx, winner, top_titles)
        llm_reasoning = llm_result.get("reasoning") or ""
        evidence_f.write(f"  LLM: match={llm_result.get('match')} conf={llm_result.get('confidence'):.2f} flags={llm_result.get('flags')}\n")

        if llm_result.get("match") is True:
            conf = llm_result.get("confidence", 0.0)
            if conf >= 0.85:
                winner_scores["score_llm"] = _LLM_HIGH
            elif conf >= 0.70:
                winner_scores["score_llm"] = _LLM_MED
        elif llm_result.get("match") is False:
            winner_scores["score_llm"] = _LLM_NEG

    final_total = total_score(winner_scores)
    evidence_f.write(f"  final_score={final_total}\n")

    # ── Acceptance policy ────────────────────────────────────────────────────
    conf_tier, reject_reason, flags = apply_acceptance_policy(
        ctx, winner_scores, final_total, winner, llm_result
    )

    # Common-name flag: checked post-hoc by caller, so we just record name
    evidence_f.write(f"  confidence={conf_tier} reason={reject_reason} flags={flags}\n")

    summ = candidate_summary(winner)
    runner_up = scored[1]["candidate"] if len(scored) > 1 else None

    accepted = "1" if conf_tier == "HIGH" else "0"
    method = "exact_name+signals" if winner_scores["score_name"] == _NAME_EXACT else "fuzzy_name+signals"

    row = {
        "acd_name":              ctx.name,
        "source":                ctx.source,
        "priority":              ctx.priority,
        "practitioner_no":       ctx.practitioner_no,
        "state":                 ctx.state,
        "speciality_ahpra":      ctx.speciality_ahpra,
        "location_ahpra":        ctx.location_ahpra,
        "ahpra_proven":          "1" if ctx.ahpra_proven else "0",
        "openalex_id":           summ["openalex_id"] if accepted == "1" else "",
        "openalex_display_name": summ["display_name"] if accepted == "1" else "",
        "last_known_institution": summ["institution"],
        "institution_country":   summ["country"],
        "aunz_ever":             "1" if summ["aunz_ever"] else "0",
        "works_count":           summ["works_count"],
        "profile_url":           summ["profile_url"] if accepted == "1" else "",
        "score_name":            winner_scores["score_name"],
        "score_country":         winner_scores["score_country"],
        "score_inst":            winner_scores["score_inst"],
        "score_topic":           winner_scores["score_topic"],
        "score_state":           winner_scores["score_state"],
        "score_history":         winner_scores["score_history"],
        "score_hospital":        winner_scores["score_hospital"],
        "score_ahpra":           winner_scores["score_ahpra"],
        "score_semantic":        winner_scores["score_semantic"],
        "score_llm":             winner_scores["score_llm"],
        "total_score":           final_total,
        "confidence":            conf_tier,
        "accepted":              accepted,
        "reject_reason":         reject_reason,
        "resolution_method":     method,
        "ambiguity_flags":       "|".join(flags),
        "llm_reasoning":         llm_reasoning,
        "search_stage":          stage,
        "_runner_up":            runner_up,
    }
    return row


def _build_not_found_row(ctx: MemberContext, stage: str) -> dict[str, Any]:
    return {
        "acd_name": ctx.name, "source": ctx.source, "priority": ctx.priority,
        "practitioner_no": ctx.practitioner_no, "state": ctx.state,
        "speciality_ahpra": ctx.speciality_ahpra, "location_ahpra": ctx.location_ahpra,
        "ahpra_proven": "1" if ctx.ahpra_proven else "0",
        "openalex_id": "", "openalex_display_name": "", "last_known_institution": "",
        "institution_country": "", "aunz_ever": "0", "works_count": 0, "profile_url": "",
        "score_name": 0, "score_country": 0, "score_inst": 0, "score_topic": 0,
        "score_state": 0, "score_history": 0, "score_hospital": 0, "score_ahpra": 0,
        "score_semantic": 0, "score_llm": 0, "total_score": 0,
        "confidence": "NOT_FOUND", "accepted": "0", "reject_reason": "no_candidates",
        "resolution_method": "not_found", "ambiguity_flags": "", "llm_reasoning": "",
        "search_stage": stage, "_runner_up": None,
    }


def _build_accepted_row(
    ctx: MemberContext,
    summ: dict,
    scores: dict,
    method: str,
    flags: list[str],
    llm_reasoning: str,
    stage: str,
) -> dict[str, Any]:
    return {
        "acd_name": ctx.name, "source": ctx.source, "priority": ctx.priority,
        "practitioner_no": ctx.practitioner_no, "state": ctx.state,
        "speciality_ahpra": ctx.speciality_ahpra, "location_ahpra": ctx.location_ahpra,
        "ahpra_proven": "1" if ctx.ahpra_proven else "0",
        "openalex_id": summ["openalex_id"], "openalex_display_name": summ["display_name"],
        "last_known_institution": summ["institution"], "institution_country": summ["country"],
        "aunz_ever": "1" if summ["aunz_ever"] else "0", "works_count": summ["works_count"],
        "profile_url": summ["profile_url"],
        "score_name": scores.get("score_name", 0), "score_country": scores.get("score_country", 0),
        "score_inst": scores.get("score_inst", 0), "score_topic": scores.get("score_topic", 0),
        "score_state": scores.get("score_state", 0), "score_history": scores.get("score_history", 0),
        "score_hospital": scores.get("score_hospital", 0), "score_ahpra": scores.get("score_ahpra", 0),
        "score_semantic": scores.get("score_semantic", 0), "score_llm": scores.get("score_llm", 0),
        "total_score": total_score(scores), "confidence": "HIGH", "accepted": "1",
        "reject_reason": "", "resolution_method": method,
        "ambiguity_flags": "|".join(flags), "llm_reasoning": llm_reasoning,
        "search_stage": stage, "_runner_up": None,
    }


# ---------------------------------------------------------------------------
# Common-name deduplication post-processing
# ---------------------------------------------------------------------------
def flag_common_names(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag members whose accepted match is shared by another member (common name merge)."""
    accepted_ids: dict[str, list[str]] = {}
    for row in rows:
        if row.get("accepted") == "1" and row.get("openalex_id"):
            accepted_ids.setdefault(row["openalex_id"], []).append(row["acd_name"])

    for row in rows:
        oid = row.get("openalex_id")
        if oid and len(accepted_ids.get(oid, [])) > 1:
            flags = row.get("ambiguity_flags") or ""
            flag_list = [f for f in flags.split("|") if f]
            if "COMMON_NAME" not in flag_list:
                flag_list.append("COMMON_NAME")
            row["ambiguity_flags"] = "|".join(flag_list)
            # Downgrade to REVIEW
            if row.get("confidence") == "HIGH":
                row["confidence"] = "REVIEW"
                row["accepted"] = "0"
                row["reject_reason"] = "common_name_merge"
            logger.warning(
                "COMMON_NAME: OpenAlex ID %s matched to multiple members: %s",
                oid, accepted_ids[oid],
            )
    return rows


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------
def run(
    *,
    input_path: Path = INPUT_CSV,
    institutions_path: Path = INST_CSV,
    overrides_path: Path = OVERRIDES,
    fp_overrides_path: Path = FP_OVERRIDES,
    blacklist_path: Path = BLACKLIST,
    out_dir: Path = ROOT / "data",
    must_only: bool = True,
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

    out_csv    = processed_dir / "authors_resolved.csv"
    reject_csv = processed_dir / "resolution_rejects.csv"
    evidence_log_path = logs_dir / "resolution.log"
    credit_state      = logs_dir / "credit_usage.json"

    fh = logging.FileHandler(evidence_log_path, mode="a", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(fh)

    evidence_f = evidence_log_path.open("a", encoding="utf-8")
    evidence_f.write(f"\n===== ACD resolver run @ {datetime.now().isoformat()} =====\n")

    catalog    = DermInstitutionCatalog.load(institutions_path)
    overrides  = _load_overrides(overrides_path)
    fp_overrides = _load_fp_overrides(fp_overrides_path)
    blacklist  = _load_blacklist(blacklist_path)
    logger.info("Loaded %d institution patterns, %d overrides, %d FP overrides, %d blacklisted IDs",
                len(catalog.patterns), len(overrides), sum(len(v) for v in fp_overrides.values()), len(blacklist))

    df = load_members(input_path)
    if must_only:
        df = df[df["priority"] == "must"].reset_index(drop=True)
    if limit is not None:
        df = df.head(limit).reset_index(drop=True)
    logger.info("Processing %d members", len(df))

    budget = CreditBudget(daily_limit=budget_limit, state_path=credit_state)
    client = OpenAlexClient(
        email=email or os.environ.get("OPENALEX_EMAIL", ""),
        api_key=api_key or os.environ.get("OPENALEX_API_KEY", ""),
        base_url=base_url or os.environ.get("OPENALEX_BASE_URL") or "https://api.openalex.org",
        session=session if session is not None else requests.Session(),
        on_success=lambda _payload: budget.charge(1),
    )

    topic_cache: dict[str, float] = {}
    all_rows: list[dict[str, Any]] = []
    exhausted = False

    pbar = tqdm(df.to_dict("records"), desc="resolving", disable=None)
    try:
        for raw in pbar:
            ctx = build_context(raw)
            if not ctx.name:
                continue
            try:
                row = resolve_member(
                    ctx, client, catalog, topic_cache,
                    overrides, fp_overrides, blacklist, evidence_f,
                )
            except BudgetExhausted:
                logger.warning("Budget exhausted at %s", ctx.name)
                exhausted = True
                break
            all_rows.append(row)
            time.sleep(_PER_MEMBER_SLEEP)
    finally:
        pbar.close()

    # Post-processing: flag common-name merges
    all_rows = flag_common_names(all_rows)

    # Write outputs
    accepted_writer = CheckpointWriter(
        csv_path=out_csv, columns=OUTPUT_COLUMNS,
        key_column="acd_name", progress_log=logs_dir / "resolution_progress.csv",
    )
    reject_writer = CheckpointWriter(
        csv_path=reject_csv, columns=REJECT_COLUMNS,
        key_column="acd_name", progress_log=logs_dir / "resolution_rejects_progress.csv",
    )

    counts = {"HIGH": 0, "REVIEW": 0, "LOW": 0, "NOT_FOUND": 0}
    for row in all_rows:
        out_row = {k: row.get(k, "") for k in OUTPUT_COLUMNS}
        accepted_writer.write_row(out_row)
        tier = row.get("confidence", "NOT_FOUND")
        counts[tier] = counts.get(tier, 0) + 1

        if row.get("confidence") not in ("HIGH",):
            runner_up = row.get("_runner_up")
            ru_summ = candidate_summary(runner_up) if runner_up else {}
            reject_row = {
                "acd_name": row["acd_name"],
                "acd_state": row["state"],
                "ahpra_proven": row["ahpra_proven"],
                "top_candidate_id": row.get("openalex_id") or ru_summ.get("openalex_id", ""),
                "top_candidate_name": row.get("openalex_display_name") or ru_summ.get("display_name", ""),
                "top_candidate_institution": row.get("last_known_institution") or ru_summ.get("institution", ""),
                "top_candidate_country": row.get("institution_country") or ru_summ.get("country", ""),
                "top_candidate_aunz_ever": row.get("aunz_ever", "0"),
                "top_candidate_works_count": row.get("works_count", 0),
                "score_name": row.get("score_name", 0),
                "score_country": row.get("score_country", 0),
                "score_inst": row.get("score_inst", 0),
                "score_topic": row.get("score_topic", 0),
                "score_state": row.get("score_state", 0),
                "score_history": row.get("score_history", 0),
                "score_hospital": row.get("score_hospital", 0),
                "score_ahpra": row.get("score_ahpra", 0),
                "score_semantic": row.get("score_semantic", 0),
                "score_llm": row.get("score_llm", 0),
                "total_score": row.get("total_score", 0),
                "confidence": row.get("confidence", "NOT_FOUND"),
                "reject_reason": row.get("reject_reason", ""),
                "ambiguity_flags": row.get("ambiguity_flags", ""),
                "runner_up_id": ru_summ.get("openalex_id", ""),
                "runner_up_name": ru_summ.get("display_name", ""),
                "runner_up_total_score": "",
                "top_candidate_profile_url": row.get("profile_url") or ru_summ.get("profile_url", ""),
            }
            reject_writer.write_row(reject_row)

    evidence_f.close()
    logger.info("Resolution complete: %s", counts)

    return {
        "processed": len(all_rows),
        "counts": counts,
        "exhausted": exhausted,
        "out_csv": out_csv,
        "reject_csv": reject_csv,
        "log_path": evidence_log_path,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ACD dermatologist entity resolver.")
    p.add_argument("--input", type=Path, default=INPUT_CSV)
    p.add_argument("--institutions", type=Path, default=INST_CSV)
    p.add_argument("--out-dir", type=Path, default=ROOT / "data")
    p.add_argument("--must-only", action="store_true", default=True)
    p.add_argument("--include-nice", dest="must_only", action="store_false")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--budget", type=int, default=100_000)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
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
    print("ACD AUTHOR RESOLVER SUMMARY")
    print("=" * 60)
    print(f"Processed members : {result['processed']}")
    for k, v in result["counts"].items():
        print(f"  {k:<12}: {v}")
    print(f"Budget exhausted  : {result['exhausted']}")
    print(f"Output CSV        : {result['out_csv']}")
    print(f"Rejects CSV       : {result['reject_csv']}")
    print(f"Evidence log      : {result['log_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
