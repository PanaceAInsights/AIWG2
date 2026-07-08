# ACD Dermatologist Entity Resolution — Design Specification v2

**Status: REVISED DRAFT — Pending final user approval before implementation**

---

## Core Philosophy

> "If you find a perfect name/surname match but they are registered to a non-AU institute,
> country is non-AU, and none of their work is affiliated with Australia — that is probably
> not the right person. If they have a perfect name match but all their papers are in
> ophthalmology or nephrology — also the wrong person."

The resolver treats entity resolution as a **cascade of hard filters followed by soft scoring**.
A candidate must pass the hard filters before soft signals can accumulate points. A single
hard-filter failure (wrong country + wrong specialty) is sufficient to reject a candidate,
regardless of name similarity.

---

## Input Data Available Per Member

| Field | Source | Availability | Use in Resolution |
|-------|--------|-------------|-------------------|
| Full name (cleaned) | AHPRA | 100% | Primary search key |
| State (AU) | AHPRA | 100% | Geography signal |
| AHPRA number | AHPRA | 100% | Identity anchor (not searchable in OA) |
| Hospital affiliations | HealthShare | 42% | Institution matching |
| Bio text | HealthShare | 89% | LLM semantic context |
| Qualifications | HealthShare | 32% | LLM semantic context |
| Special interests | HealthShare | variable | Topic signal |

**Note:** AHPRA numbers are not searchable in OpenAlex. They are used only as a
confirmed-identity anchor for the input list — not as a matching signal against OpenAlex.

---

## Pipeline Architecture: 4 Passes

Each pass processes only members **not yet resolved** by earlier passes.
The pipeline is strictly sequential and crash-resumable.

---

### Pass 1 — Targeted AU/NZ Search with Hard Filters

**Goal:** Resolve clear-cut cases with a single API call per member and no LLM.

**Search strategy:**
- Query: `full_name` + filter `last_known_institutions.country_code:AU|NZ`
- Retrieve top 10 candidates
- **1 API call per member**

**Step 1 — Hard filter (disqualify immediately if ANY of these are true):**

| Hard filter | Condition | Action |
|-------------|-----------|--------|
| Wrong country | Candidate has NO AU or NZ affiliation (current or historical) | REJECT candidate |
| Wrong specialty | Candidate's top-3 OpenAlex topics contain zero dermatology-adjacent terms AND top concepts are exclusively non-derm (e.g. all ophthalmology, nephrology, cardiology) | REJECT candidate |
| Implausible volume | Candidate has > 500 works AND no AU/NZ affiliation ever | REJECT candidate |

**Step 2 — Soft scoring (only for candidates that pass hard filters):**

| Signal | Points | Notes |
|--------|--------|-------|
| Name exact match (normalised) | 40 | Full name after stripping titles, lowercasing, collapsing whitespace |
| Name fuzzy ≥ 92 token_sort_ratio | 30 | Near-exact spelling variant |
| Name fuzzy 80–91 | 15 | Plausible variant (e.g. middle name dropped) |
| Country = AU or NZ (current institution) | 25 | `last_known_institutions.country_code` |
| Country = AU or NZ (historical only) | 15 | In `affiliations[].country_code` but not current |
| State match (city/institution → AU state) | 12 | e.g. "Sydney" or "UNSW" → NSW |
| Institution name fuzzy-matches HealthShare hospital/practice | 15 | rapidfuzz ≥ 80 |
| Dermatology topic in top-5 OpenAlex topics | 15 | `topics[].display_name` contains derm keywords |
| Dermatology concept in `x_concepts` | 10 | Broader concept match |
| Works count 1–50 (clinician-realistic) | 8 | Most ACD members who publish |
| Works count 51–150 (active researcher) | 5 | Still plausible for academic dermatologist |
| Works count 151–300 | 2 | Possible for very prolific (Soyer, Murrell, etc.) |
| Works count > 300 | −20 | Penalty — likely wrong person unless name is exact |
| Works count > 300 AND name exact match | 0 net | Penalty waived for exact name (handles Soyer/Murrell) |
| h-index > 50 | −10 | Penalty — clinician-unrealistic unless name exact |
| h-index > 50 AND name exact match | 0 net | Penalty waived for exact name |

**Acceptance:** Score ≥ 110 → **HIGH** (accepted, no further processing)
**Rejection:** No candidates pass hard filter → **NOT_FOUND**
**Borderline:** Score 60–109 → carry forward to Pass 2

**Expected API calls:** ~649 (one per remaining member)
**Expected yield:** ~35–45% resolved as HIGH or NOT_FOUND

---

### Pass 2 — Global Relaxed Search

**Goal:** Catch members missed by Pass 1 due to name variations, outdated country
affiliations, or members who trained overseas and returned to AU.

**Search strategy:**
- Query: `full_name` only, no country filter
- Retrieve top 10 candidates
- **1 API call per member**

**Same hard filters and scoring rubric as Pass 1**, with these additions:

| Additional Signal | Points | Notes |
|------------------|--------|-------|
| AU/NZ affiliation ever (historical, not current) | +5 bonus | Stacks with the 15-pt historical signal |
| Non-AU/NZ current AND non-AU/NZ historical | −30 | Hard penalty — strong evidence of wrong person |

**Acceptance:** Score ≥ 100 → **HIGH**
**REVIEW:** Score 60–99 → flagged for Pass 3 LLM adjudication
**NOT_FOUND:** Score < 60 or no candidates pass hard filter

**Expected API calls:** ~350 (only unresolved members)
**Expected yield:** ~20% additional HIGH, ~15% flagged as REVIEW

---

### Pass 3 — Multi-LLM Semantic Verification (REVIEW queue only)

**Goal:** Use Claude Sonnet to make a final determination on all REVIEW-flagged members
using the full richness of available context. The LLM acts as a **specialist forensic
analyst**, not just a name matcher.

**Model:** `claude-sonnet-4-5`

**For each REVIEW member, Claude receives:**

```
DERMATOLOGIST RECORD (from AHPRA + HealthShare):
  Name: Dr Jane Elizabeth Smith
  State: NSW
  Hospital affiliations: Royal Prince Alfred Hospital, Sydney
  Bio: "Dr Smith is a consultant dermatologist specialising in skin cancer..."
  Qualifications: "FACD 2008, MBBS University of Sydney 1998"
  Special interests: "Melanoma, skin cancer surgery, dermoscopy"

OPENALEX CANDIDATE:
  Display name: Jane E. Smith
  Current institution: University of Sydney, AU
  Country history: AU (2005–present)
  Works count: 34
  h-index: 12
  Top 5 topics: Dermatology, Melanoma, Skin Cancer, Dermoscopy, Mohs Surgery
  Top 5 publications:
    1. "Dermoscopy of melanocytic lesions" (2019)
    2. "Sentinel node biopsy in melanoma" (2017)
    ...

SCORING SUMMARY:
  Name fuzzy score: 88 | Country: AU (current) | Institution: partial match
  Total deterministic score: 87 (REVIEW tier)

TASK: Is this OpenAlex profile the same person as the dermatologist record above?
```

**Claude returns structured JSON:**
```json
{
  "match": true,
  "confidence": 0.92,
  "reasoning": "Name variant (middle initial only), same institution, same state, publications are exclusively dermatology-focused and match stated interests in melanoma and skin cancer.",
  "flags": ["NAME_VARIANT_MIDDLE_INITIAL"],
  "specialty_consistent": true,
  "geography_consistent": true
}
```

**Multi-verification approach:**
For members where Claude's first call returns confidence 0.60–0.79 (uncertain), a **second
independent LLM call** is made with a different prompt framing (adversarial — "find reasons
this is NOT the same person"). If both calls agree → accept verdict. If they disagree →
keep as REVIEW for manual inspection.

**Acceptance rules:**
- `match=true` AND `confidence ≥ 0.85` (both calls if double-verified) → **HIGH**
- `match=true` AND `confidence 0.65–0.84` → **REVIEW** (manual check required)
- `match=false` OR `specialty_consistent=false` → **NOT_FOUND**
- `geography_consistent=false` AND `confidence < 0.80` → **NOT_FOUND**

**Expected API calls:** ~100 LLM calls (first pass) + ~30 second-pass calls = ~130 total
**Zero additional OpenAlex calls**

---

### Pass 4 — Common Name & Suspicious Merge Audit

**Goal:** Post-processing sweep to catch false positives that slipped through.

**Flags applied in-memory (no API calls):**

| Flag | Condition |
|------|-----------|
| `COMMON_NAME_RISK` | Name token_sort_ratio ≥ 90 against 2+ different OpenAlex profiles |
| `SUSPICIOUS_VOLUME` | Accepted profile has works_count > 300 AND name was not exact match |
| `NO_AUNZ_HISTORY` | Accepted profile has zero AU/NZ affiliation (current or historical) |
| `SPECIALTY_WEAK` | Accepted profile has < 20% dermatology topics in top-10 topics |

Members with any flag → written to `common_name_review.csv` AND `confidence` downgraded to
REVIEW in the main output.

**Known high-volume exceptions** (waive `SUSPICIOUS_VOLUME` flag):
- Peter Soyer, Dedee Murrell, Ron Sinclair, Diona Damian
- These are pre-loaded in `data/input/high_volume_exceptions.csv`

---

## API Call Budget

| Pass | Members | OA calls | LLM calls |
|------|---------|----------|-----------|
| Pass 1 | 649 remaining | ~649 | 0 |
| Pass 2 | ~380 unresolved | ~380 | 0 |
| Pass 3 | ~100 REVIEW | 0 | ~130 |
| Pass 4 | All | 0 | 0 |
| **Total** | | **~1,030** | **~130** |

Fits within one day's OpenAlex quota. LLM cost is negligible (~$0.50 at Sonnet pricing).

---

## Output Files

| File | Contents |
|------|---------|
| `data/processed/authors_resolved.csv` | All 712 members — full resolution result |
| `data/processed/resolution_rejects.csv` | Non-HIGH members with full score breakdown |
| `data/processed/review_queue.csv` | REVIEW-tier only — for manual inspection |
| `data/processed/common_name_review.csv` | Common-name/suspicious-merge flags |
| `data/logs/resolution.log` | Per-member evidence trail |
| `data/logs/resolution_progress.csv` | Crash-resume checkpoint |

---

## Confidence Tier Definitions

| Tier | Meaning | Dashboard treatment |
|------|---------|-------------------|
| **HIGH** | Resolver is confident this is the correct OpenAlex profile | Included in all analytics |
| **REVIEW** | Match found but uncertain — needs manual verification | Included but flagged with ⚠ |
| **LOW** | Weak match found, likely wrong person | Excluded from analytics by default |
| **NOT_FOUND** | No OpenAlex profile found | Shown as "no publications data" |

---

## Changes from v1 Design

| Item | v1 | v2 |
|------|----|----|
| AHPRA as matching signal | Yes (25 pts) | Removed — not searchable in OpenAlex |
| Hard filters | None | Added (wrong country + wrong specialty = hard reject) |
| Works count penalty | −20 for >300 | −20 but waived for exact name match (handles Soyer/Murrell) |
| LLM model | claude-haiku-4-5 | claude-sonnet-4-5 |
| LLM verification | Single call | Double-call for uncertain cases (adversarial second prompt) |
| REVIEW threshold | 70–99 | 60–99 (Pass 1), 60–99 (Pass 2) |
| Specialty hard filter | None | Added — wrong specialty = reject regardless of name |

---

## Remaining Questions for Your Approval

1. **High-volume exceptions list** — I have pre-loaded Soyer, Murrell, Sinclair, Damian.
   Are there other ACD members you know have large publication records (>300 works)?

2. **Double-LLM verification** — For uncertain cases (confidence 0.60–0.79), I propose
   running a second adversarial LLM call. Is this the right approach, or would you prefer
   a different verification strategy?

3. **REVIEW in dashboard** — Should REVIEW-tier members be included in the dashboard
   analytics by default (with a warning flag), or excluded until manually verified?

4. **Manual review workflow** — After the resolver runs, I will produce a
   `review_queue.csv`. Would you like me to build a simple review interface (a small
   web page or Excel-friendly format) to make the manual verification easier?
