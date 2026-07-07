"""ACD Dashboard — Methodology page."""
from __future__ import annotations

from dash import html, dcc
import dash_bootstrap_components as dbc

from dashboard.theme import (
    COPPER, MAUVE_PURPLE, LIGHT_COPPER, BG_CARD, BORDER_COLOR,
    TEXT_MUTED, WHITE, WARM_CREAM, DARK_PLUM, TIER_HIGH, TIER_REVIEW,
)

PAGE_TITLE = "Methodology"
PAGE_HREF  = "/methodology"

_METHODOLOGY_MD = """
## Data Sources

| Source | Description |
|--------|-------------|
| **Input CSV** | 712 dermatologists sourced from AHPRA, HealthShare, and ACD member lists |
| **OpenAlex** | Open scholarly graph — publications, citations, funding, author disambiguation |
| **ANZCTR** | Australian New Zealand Clinical Trials Registry — bulk export matched by PI name |

---

## Entity Resolution Pipeline

The ACD Research Intelligence Platform uses a **multi-stage, ML-assisted entity resolution pipeline**
to match each dermatologist in the input registry to their correct OpenAlex author profile.

### Stage 1 — Candidate Retrieval
For each dermatologist, the pipeline issues two OpenAlex API queries:
1. **Exact name search** — `display_name.search:"First Last"`
2. **Institution-boosted search** — name + known AU/NZ institution hint

Up to 10 candidates are retrieved per query (20 total), deduplicated by OpenAlex author ID.

### Stage 2 — Multi-Signal Scoring
Each candidate is scored against 8 independent signals:

| Signal | Max Points | Description |
|--------|-----------|-------------|
| Name similarity | 30 | Fuzzy token-set ratio (rapidfuzz) against normalised display name |
| Country evidence | 20 | AU/NZ affiliation in last 5 years |
| Institution match | 15 | Fuzzy match against known AU/NZ dermatology institutions |
| AHPRA proof | 10 | AHPRA number pattern in works/affiliations |
| Topic density | 10 | Fraction of works in dermatology-relevant OpenAlex topics |
| Works volume | 5 | Reasonable publication count (not suspiciously high) |
| h-index plausibility | 5 | h-index consistent with career stage |
| Last active | 5 | Active within last 5 years |

Candidates scoring **≥ 90 points** are accepted as **HIGH confidence**.
Candidates scoring **70–89 points** are flagged as **REVIEW** (manual verification recommended).
Candidates scoring **< 70 points** are rejected.

### Stage 3 — Ambiguity Detection (replaces co-authorship bootstrap)
Instead of using co-authorship clustering (which introduced false positives in RMSANZ),
the ACD pipeline uses **LLM-assisted disambiguation** for borderline cases:

- **COMMON_NAME flag** — surname appears in > 3 distinct OpenAlex profiles with AU/NZ affiliation
- **HIGH_VOLUME flag** — accepted profile has > 500 works (possible merge of multiple authors)
- **WEAK_TOPIC flag** — < 20% of works are dermatology-relevant
- **COUNTRY_MISMATCH flag** — best candidate has no AU/NZ affiliation in last 3 years
- **LLM_UNCERTAIN flag** — Claude Haiku was invoked for disambiguation and returned < 80% confidence
- **NAME_ONLY flag** — match was accepted on name similarity alone (no institution/topic corroboration)

All flagged profiles are written to `data/processed/review_queue.csv` for human review.

### Stage 4 — Strict Acceptance Policy
Final acceptance requires ALL of:
- `total_score ≥ 90` (HIGH) or `total_score ≥ 70` (REVIEW)
- At least one AU/NZ affiliation ever recorded
- Name fuzzy score ≥ 25 (prevents pure-score gaming)

### Stage 5 — Manual Override Support
Operators can place corrections in:
- `data/input/manual_resolver_overrides.csv` — force-accept a specific OpenAlex ID
- `data/input/manual_fp_overrides.csv` — force-reject a false positive
- `data/input/manual_resolver_blacklist.csv` — permanently exclude an OpenAlex ID

---

## Publication Relevance Tagging

Publications are tagged `is_derm_relevant = True` if they match any of:
1. OpenAlex **Topic_Field** contains a dermatology-relevant field (e.g. "Dermatology", "Skin")
2. **MeSH descriptors** include dermatology terms
3. **Title or abstract** contains high-signal dermatology stems (e.g. "melanoma", "psoriasis",
   "atopic dermatitis", "skin cancer", "eczema", "acne", "rosacea", "vitiligo")

---

## Clinical Trials Matching

ANZCTR bulk export is matched to ACD members using:
1. **Exact normalised name match** against Principal Investigator names
2. **Fuzzy match** (rapidfuzz token_set_ratio ≥ 92) with last-name token intersection guard

Only members with HIGH or REVIEW confidence are included in trial matching.

---

## Confidence Tiers

| Tier | Criteria | Dashboard Treatment |
|------|----------|---------------------|
| **HIGH** | Score ≥ 90, AU/NZ-ever, name fuzzy ≥ 25 | Fully included in all analyses |
| **REVIEW** | Score 70–89 | Included but flagged; shown in amber |
| **NOT_FOUND** | No candidate met threshold | Excluded from publication/trial analyses |

---

## Data Lineage

All intermediate files are written to `data/processed/`. The pipeline is fully
reproducible — re-running any script overwrites its output deterministically.
Checkpoints are saved after each stage so the pipeline can be resumed after interruption.

---

## Attribution

Data sourced from [OpenAlex](https://openalex.org) (CC0) and
[ANZCTR](https://www.anzctr.org.au) (public registry).
Platform developed by [Dr Yagiz Aksoy MD PhD](https://www.linkedin.com/in/yagizalpaksoy/)
for [PanaceaAI](https://www.panaceainsights.com.au).
"""


def layout():
    return html.Div([
        html.Div([
            dcc.Markdown(
                _METHODOLOGY_MD,
                style={"color": WARM_CREAM, "fontSize": "14px", "lineHeight": "1.7"},
            ),
        ], className="acd-card"),
    ])
