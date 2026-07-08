# ACD Dermatologist Entity Resolution — Design Specification

**Status: DRAFT — Pending user approval before implementation**

---

## Overview

The goal is to match each of the **712 ACD dermatologists** in the input CSV to their correct
OpenAlex author profile — or definitively determine that no profile exists — with forensic
accuracy and minimal wasted API calls.

### Key constraints and realities of this cohort

| Fact | Implication |
|------|-------------|
| All are AU/NZ-registered dermatologists (AHPRA confirmed) | Country filter is a hard prior — AU or NZ affiliation is near-certain |
| Most are clinical practitioners, not academic researchers | Many will have **zero or very few** publications; NOT_FOUND is a valid and expected outcome |
| Dermatology is a small, specialist field | Topic density signal is meaningful but not decisive |
| 669 have AHPRA numbers (strong identity anchor) | AHPRA number pattern in OpenAlex bio/affiliation is a near-certain match signal |
| 300 have hospital affiliations from HealthShare | Institution name matching is a strong secondary signal |
| 633 have bios from HealthShare | Bio text can be used for LLM semantic matching |
| Common names (e.g. "Dr John Smith") exist | Must flag and quarantine common-name ambiguity |
| OpenAlex search quota is limited (~1,000 searches/day on paid plan) | Must minimise search calls; use targeted strategies |

---

## Pipeline Architecture: 4 Passes

The resolver runs in **4 sequential passes**. Each pass only processes members not yet
resolved by earlier passes. This is strictly sequential — no member is processed twice.

---

### Pass 1 — High-Confidence Direct Match (Zero LLM, Minimal API calls)

**Goal:** Resolve the easy cases instantly using deterministic signals.

**Method:**
1. For each member, construct a **targeted OpenAlex search** using:
   - Full name (exact) + country filter `AU` or `NZ`
   - This is a **single API call per member** (not 3 separate calls)
2. For each returned candidate, compute a **deterministic score** (no LLM):

| Signal | Points | Logic |
|--------|--------|-------|
| Name exact match (normalised) | 40 | Full name matches exactly after lowercasing, stripping titles |
| Name fuzzy match (≥ 92 token_sort_ratio) | 30 | Near-exact spelling |
| Country = AU or NZ (current or ever) | 20 | `last_known_institutions.country_code` or `affiliations[].country_code` |
| Dermatology topic in top-5 OpenAlex topics | 15 | `topics[].display_name` contains derm keywords |
| Institution name fuzzy-matches hospital/practice from HealthShare | 15 | rapidfuzz ≥ 80 against `Hospitals_Names_HS` or `Practices_Names_HS` |
| State match (OpenAlex institution city/state matches ACD state) | 10 | e.g. "Sydney" → NSW |
| Works count in plausible range for a clinician (1–150) | 5 | Penalise 0 and >500 |
| AHPRA number pattern found in OpenAlex display_name or affiliations | 25 | Regex match on `MED\d{10}` |

**Acceptance threshold:** Score ≥ 110 → **HIGH confidence** → accepted, no further processing.

**Rejection:** Score < 50 with no candidates → **NOT_FOUND** → accepted as-is.

**API calls per member:** 1 (AU+NZ combined search with `|` OR filter)

**Expected yield:** ~40–50% of members resolved in this pass.

---

### Pass 2 — Relaxed Search + Calibrated Scoring

**Goal:** Catch members missed by Pass 1 due to name variations, institution mismatches,
or country filter gaps (e.g. NZ-trained but now in AU).

**Method:**
1. For unresolved members only, run a **global search** (no country filter) using:
   - Full name only
   - Retrieve top 10 candidates
2. Apply the same scoring rubric as Pass 1 **plus**:

| Additional Signal | Points | Logic |
|------------------|--------|-------|
| AU/NZ affiliation ever (historical) | 15 | Check `affiliations[].country_code` across all historical affiliations |
| Dermatology concept in works (top concepts) | 10 | `x_concepts[].display_name` |
| Works count 1–50 (clinician-realistic) | 8 | Most ACD members who publish have modest track records |
| Works count 51–150 (active researcher) | 5 | Still plausible |
| Works count > 300 | -20 | Penalty — likely a different person (prolific researcher, not a clinician) |
| h-index < 30 | 5 | Clinician-realistic; penalise h > 50 by -10 |

**Acceptance threshold:** Score ≥ 100 → **HIGH confidence**.
Score 70–99 → **REVIEW** (flagged for manual check).
Score < 70 → **LOW** or **NOT_FOUND**.

**API calls per member:** 1 (global search, no filter)

**Expected yield:** ~20–25% additional members resolved.

---

### Pass 3 — LLM Adjudication of REVIEW Queue

**Goal:** Use Claude to make a final determination on all REVIEW-flagged members from
Passes 1 and 2, using the full richness of available context.

**Method:**
For each REVIEW member, send Claude a structured prompt containing:
- ACD member: name, state, AHPRA number, hospital affiliations, bio text, qualifications
- OpenAlex candidate: display name, institution, country, works count, h-index, top topics, top 5 publication titles
- Scoring breakdown from Pass 1/2

**Claude's task:** Return a structured JSON verdict:
```json
{
  "match": true/false,
  "confidence": 0.0–1.0,
  "reasoning": "one sentence",
  "flags": ["WEAK_TOPIC", "COUNTRY_MISMATCH", "COMMON_NAME", "PLAUSIBLE_CLINICIAN", ...]
}
```

**Acceptance rules from LLM verdict:**
- `match=true` AND `confidence ≥ 0.85` → upgrade to **HIGH**
- `match=true` AND `confidence 0.65–0.84` → keep as **REVIEW** (manual check required)
- `match=false` → downgrade to **NOT_FOUND**

**API calls per member:** 1 LLM call only (no additional OpenAlex calls)

**Expected yield:** Resolves ~60–70% of REVIEW queue to HIGH or NOT_FOUND.

---

### Pass 4 — Common Name & Ambiguity Audit

**Goal:** Post-processing audit to catch false positives where a common name
(e.g. "Dr James Brown") was matched to the wrong person.

**Method:**
1. Flag any accepted member where:
   - Name has token_sort_ratio ≥ 90 against **2 or more** different OpenAlex profiles
   - OR works_count > 300 (suspicious merge — likely a prolific researcher, not a clinician)
   - OR the matched OpenAlex profile has a primary affiliation outside AU/NZ with no AU/NZ history
2. These members are written to a **`common_name_review.csv`** for manual inspection
3. They remain in the resolved output but with `ambiguity_flags = "COMMON_NAME_RISK"` and `confidence = REVIEW`

**API calls per member:** 0 (purely in-memory post-processing)

---

## API Call Budget Summary

| Pass | Members | Calls per member | Total calls |
|------|---------|-----------------|-------------|
| Pass 1 | 649 remaining | 1 (targeted AU/NZ search) | ~649 |
| Pass 2 | ~350 unresolved | 1 (global search) | ~350 |
| Pass 3 | ~100 REVIEW | 0 OpenAlex + 1 LLM | 0 OA + ~100 LLM |
| Pass 4 | All accepted | 0 | 0 |
| **Total** | | | **~1,000 OpenAlex + ~100 LLM** |

This fits within a single day's OpenAlex quota (1,000 searches/day on paid plan).

---

## Scoring Rubric Summary

| Signal | Max Points | Type |
|--------|-----------|------|
| Name exact match | 40 | Deterministic |
| Name fuzzy (≥ 92) | 30 | Deterministic |
| AHPRA number in profile | 25 | Deterministic |
| Country = AU/NZ (current) | 20 | Deterministic |
| Dermatology topic | 15 | Deterministic |
| Institution name match | 15 | Deterministic |
| AU/NZ ever (historical) | 15 | Deterministic |
| State match | 10 | Deterministic |
| Works count plausible (1–50) | 8 | Deterministic |
| Dermatology concept in works | 10 | Deterministic |
| Works count 51–150 | 5 | Deterministic |
| Works count > 300 | -20 | Penalty |
| h-index > 50 | -10 | Penalty |
| LLM confidence ≥ 0.85 | +30 | LLM |
| LLM confidence 0.65–0.84 | +15 | LLM |
| LLM match=false | -999 | LLM (hard reject) |

**Thresholds:**
- Score ≥ 110 (Pass 1) or ≥ 100 (Pass 2) + LLM confirm → **HIGH**
- Score 70–99 or LLM confidence 0.65–0.84 → **REVIEW** (manual check)
- Score < 70 or LLM match=false → **NOT_FOUND** or **LOW**

---

## Output Files

| File | Contents |
|------|---------|
| `data/processed/authors_resolved.csv` | All 712 members with resolution result, scores, confidence tier |
| `data/processed/resolution_rejects.csv` | All non-HIGH members with full scoring breakdown |
| `data/processed/review_queue.csv` | REVIEW-tier members only — for manual inspection |
| `data/processed/common_name_review.csv` | Common-name risk members — for manual inspection |
| `data/logs/resolution.log` | Detailed per-member evidence trail |
| `data/logs/resolution_progress.csv` | Checkpoint file for resume-on-crash |

---

## Key Design Decisions

1. **No co-authorship bootstrap** — removed entirely as per your instruction. The LLM adjudication in Pass 3 replaces it with a more principled approach.

2. **Dermatologist-calibrated priors** — works_count > 300 is penalised (not a clinician), h-index > 50 is penalised. Most ACD members who publish will have 1–50 papers.

3. **AU/NZ-first** — Pass 1 uses a country filter to massively reduce false positive candidates. Only Pass 2 goes global.

4. **Single search call per member per pass** — the AU+NZ filter uses OpenAlex's `|` OR syntax in a single request, not two separate calls.

5. **Resume-on-crash** — CheckpointWriter writes every row immediately to disk. If the process dies, restart picks up from the last written row.

6. **LLM only for borderline cases** — Pass 3 only processes the REVIEW queue (~100 members), not all 649. This keeps LLM costs and latency low.

7. **Manual review gates** — REVIEW and common-name-risk members are written to separate CSV files for human inspection before being used in the dashboard.

---

## Questions for Your Review

1. **Scoring weights** — Are the point values above reasonable? E.g. should AHPRA number match (25 pts) be weighted higher (e.g. 40 pts) since it's a near-certain identity proof?

2. **Works count penalty** — Should we penalise > 300 works more aggressively (e.g. -40 pts) to avoid merging a common-named prolific researcher?

3. **REVIEW threshold** — Is 70–99 the right range for REVIEW, or should we be more conservative (e.g. 80–99)?

4. **Pass 1 acceptance threshold** — Is 110 points too high or too low for automatic HIGH acceptance?

5. **LLM model** — Currently using `claude-haiku-4-5` (fast, cheap). Should we use `claude-sonnet-4-5` for higher accuracy on borderline cases?
