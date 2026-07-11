# ACD Entity Resolution Pipeline Design

## 1. Background & Problem Statement

The previous entity resolution system suffered from multiple failure modes that resulted in false positives (wrong person accepted) and false negatives (correct person rejected). Through iterative debugging, we identified the following core issues:

1.  **Geography Bypass:** The system accepted researchers with common names (e.g., "Daniel Hewitt", "Matthew Gibson") who had no Australian/New Zealand affiliation, simply because their names matched and they had high publication counts.
2.  **Specialty Bypass:** The system accepted researchers with AU/NZ affiliations who were not dermatologists (e.g., "Kevin Phan" - spinal surgeon, "William Archer Berry" - prostate cancer).
3.  **Wrong ID Conflation:** When multiple OpenAlex profiles existed for a name, the system sometimes picked the wrong one, leading to rejection of a legitimate member because the *wrong profile* lacked dermatology topics (e.g., Rebecca Saunderson).
4.  **Rigid Topic Thresholds:** A strict "3 out of 10 topics must be dermatology" rule penalised legitimate dermatologists who had fewer than 10 total topics in OpenAlex (e.g., 1 derm topic out of 5 total).
5.  **Missing Web Cross-Validation:** The system relied entirely on OpenAlex data, ignoring the wealth of information available on hospital and university websites (e.g., confirming "Prof" or "A/Prof" titles, specific hospital affiliations).

To solve this, we are designing a systematic, multi-stage entity resolution and verification pipeline.

## 2. Pipeline Architecture

The new pipeline consists of 5 distinct stages, moving from broad candidate retrieval to strict filtering, scoring, and finally external cross-validation.

### Stage 1: Multi-Source Candidate Retrieval
Instead of a single OpenAlex name search, the system casts a wide net to ensure the *correct* profile is at least in the candidate pool.
*   **ORCID Lookup:** If an ORCID is known, fetch the exact OpenAlex profile.
*   **Name + AU/NZ Filter:** Search OpenAlex for the name, restricted to AU/NZ affiliations.
*   **Name + Hospital/University:** If the roster lists a specific hospital, search OpenAlex using the name and the institution string.
*   **Web Search (Google Scholar / PubMed):** Use web search to find the researcher's Google Scholar or PubMed profile, then extract the correct institutional affiliation or ORCID to feed back into OpenAlex.

### Stage 2: Hard-Filter Veto Layer (The "Kill Switch")
Every candidate retrieved in Stage 1 must pass strict vetoes. If a candidate fails any veto, they are immediately discarded, regardless of their name match score.
*   **Geography Veto:** Must have at least one current or historical affiliation in Australia or New Zealand (`aunz_ever == True`).
*   **Proportional Specialty Veto:** Must meet a proportional dermatology topic threshold based on their total publication count and total available OpenAlex topics.
    *   Works 1–50: $\ge 1$ derm topic (out of however many exist).
    *   Works 51–100: $\ge 2$ derm topics.
    *   Works 101+: $\ge 3$ derm topics.
*   **Explicit Wrong-Specialty Veto:** If the top 3 topics are exclusively from unrelated fields (e.g., astrophysics, orthopaedics, veterinary, cardiovascular) with zero dermatology overlap, veto the candidate.

### Stage 3: Scoring, Ranking, and Confidence Assignment
Candidates that survive Stage 2 are scored based on multiple dimensions.
*   **Name Similarity (0-40 pts):** Exact match, fuzzy match, or initial match.
*   **Geographic Recency (0-25 pts):** Current AU/NZ affiliation scores higher than historical.
*   **Specialty Density (0-20 pts):** Higher proportion of derm topics yields more points.
*   **Institution Match (0-15 pts):** Does the OpenAlex institution match the roster hospital/clinic?

The highest-scoring candidate is selected. If the score is $\ge 85$, confidence is `HIGH`. If $70-84$, confidence is `MEDIUM`. Below 70 is rejected.

### Stage 4: Web Search Cross-Validation (Enrichment)
For the selected candidate, perform a targeted web search (e.g., `"Dr Hans Peter Soyer" AND ("Translational Research Institute" OR "Dermatology")`) to cross-validate and enrich the profile.
*   **Title Verification:** Extract actual academic titles ("Prof", "A/Prof", "Dr") from university pages to correct the roster.
*   **Institution Verification:** Confirm current hospital or clinic affiliations.
*   **False Positive Check:** If the web search reveals the person is definitively a different specialty (e.g., a dentist with the same name), flag for manual review.

### Stage 5: Auto-Correction and State Management
The pipeline updates the `authors_resolved.csv` state file.
*   It maintains an `exempt_list` for known, manually verified exceptions (e.g., paediatric dermatologists whose topics skew heavily towards vascular anomalies rather than general dermatology).
*   It logs a detailed `reject_reason` for every discarded candidate to enable easy auditing.

## 3. Implementation Plan

This architecture will be implemented as a unified Python module (`scripts/20_comprehensive_entity_resolution.py`) that replaces the fragmented, iterative scripts (`01c`, `11`, `14`, `15`, `16`, `18`).

It will be run as a full re-resolution pass over the entire ACD roster, producing a pristine, highly-confident dataset.
