# ACD Research Intelligence Platform

> **Australasian College of Dermatologists — Research Intelligence Dashboard**
>
> Developed by [Dr Yagiz Aksoy MD PhD](https://www.linkedin.com/in/yagizalpaksoy/) · [PanaceaAI](https://www.panaceainsights.com.au)

A full-stack research intelligence platform for **712 Australian and New Zealand dermatologists**, comprising:

- A **Python ETL pipeline** that resolves each dermatologist to their OpenAlex author profile, downloads their publications, funding grants, and clinical trials
- A **Plotly Dash dashboard** with 12 interactive pages, ACD brand palette, and a Claude-powered AI research assistant

---

## Repository Structure

```
acd-dashboard/
├── data/
│   ├── input/                    # Input files (not committed — see .gitignore)
│   │   ├── 260708_Dermatologists_Consolidated.csv   # Source registry
│   │   ├── anzctr_export.xlsx                        # ANZCTR bulk export
│   │   ├── derm_institutions_au_nz.csv               # Institution catalog
│   │   ├── manual_resolver_overrides.csv             # Force-accept overrides
│   │   ├── manual_fp_overrides.csv                   # Force-reject overrides
│   │   └── manual_resolver_blacklist.csv             # Permanent exclusions
│   └── processed/                # Pipeline outputs (generated, not committed)
│
├── scripts/
│   ├── utils/
│   │   ├── openalex_client.py    # OpenAlex API client
│   │   ├── name_matching.py      # Name normalisation + fuzzy matching
│   │   ├── checkpoint.py         # Pipeline checkpoint/resume
│   │   ├── budget.py             # API rate limiting
│   │   ├── works_mapper.py       # OpenAlex work → publication row
│   │   ├── derm_vocab.py         # Dermatology relevance vocabulary
│   │   └── derm_taxonomy.py      # Topic taxonomy for classification
│   │
│   ├── 01c_resolve_authors.py    # ★ ML-assisted entity resolver (5-stage)
│   ├── 02_download_publications.py
│   ├── 03_extract_funding.py
│   ├── 04b_match_anzctr_export.py
│   ├── 05_compute_stats.py
│   ├── 06_tag_derm_relevance.py
│   ├── 08_emit_publications_clean.py
│   ├── 09_classify_missing_topics.py
│   └── 21_build_search_index.py
│
├── dashboard/
│   ├── app.py                    # Dash app entry point
│   ├── layout.py                 # Shell (sidebar + topbar)
│   ├── theme.py                  # ACD colour palette + design tokens
│   ├── data.py                   # Centralised data loader
│   ├── ai_tools.py               # Claude chatbot backend
│   ├── assets/styles.css         # Global CSS
│   └── pages/
│       ├── overview.py           # KPIs + charts
│       ├── profiles.py           # Member directory + detail pane
│       ├── publications.py       # Publication browser
│       ├── impact.py             # Citations + h-index
│       ├── funding.py            # Funding grants
│       ├── trials.py             # Clinical trials
│       ├── heatmap.py            # Topic × State heatmap
│       ├── collaboration.py      # Co-authorship network
│       ├── benchmarking.py       # State benchmarking
│       ├── experts.py            # Expert finder
│       ├── chatbot.py            # AI assistant
│       └── methodology.py        # Data methodology
│
├── requirements.txt              # Pipeline dependencies
├── dashboard/requirements.txt    # Dashboard dependencies
├── render.yaml                   # Render.com deployment config
└── .env.example                  # Environment variable template
```

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/PanaceAInsights/acd-dashboard.git
cd acd-dashboard
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r dashboard/requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY and OPENALEX_EMAIL
```

### 3. Place input files

```
data/input/260708_Dermatologists_Consolidated.csv   ← provided
data/input/anzctr_export.xlsx                        ← provided
```

### 4. Run the ETL pipeline

Run each script in order. Each script is independently resumable via checkpoints.

```bash
# Stage 1 — Entity resolution (ML-assisted, ~2–4 hours for 712 members)
python scripts/01c_resolve_authors.py

# Stage 2 — Download publications
python scripts/02_download_publications.py

# Stage 3 — Extract funding
python scripts/03_extract_funding.py

# Stage 4 — Match clinical trials
python scripts/04b_match_anzctr_export.py

# Stage 5 — Compute statistics
python scripts/05_compute_stats.py

# Stage 6 — Tag dermatology relevance
python scripts/06_tag_derm_relevance.py

# Stage 7 — Classify missing topics
python scripts/09_classify_missing_topics.py

# Stage 8 — Build search index
python scripts/21_build_search_index.py
```

### 5. Launch the dashboard

```bash
cd dashboard
python app.py
# Open http://localhost:8050
```

---

## Entity Resolution — Key Design Decisions

### What was changed from RMSANZ

The RMSANZ pipeline used a **co-authorship bootstrap** (Pass 2) to boost borderline members
by checking overlap with high-confidence seed authors. This caused false positives when
common-named dermatologists were incorrectly linked to co-author clusters.

The ACD pipeline **replaces this with**:

1. **LLM-assisted disambiguation** — Claude Haiku is invoked for borderline candidates
   (score 70–89) to assess whether the OpenAlex profile matches the input dermatologist
   based on institution, specialty, career timeline, and publication topics.

2. **Ambiguity flag system** — Six flags are assigned to accepted profiles:
   - `COMMON_NAME` — surname appears in > 3 AU/NZ OpenAlex profiles
   - `HIGH_VOLUME` — > 500 works (possible merged profile)
   - `WEAK_TOPIC` — < 20% dermatology-relevant works
   - `COUNTRY_MISMATCH` — no AU/NZ affiliation in last 3 years
   - `LLM_UNCERTAIN` — LLM returned < 80% confidence
   - `NAME_ONLY` — accepted on name similarity alone

3. **Review queue** — All flagged profiles are written to `data/processed/review_queue.csv`
   for human verification before inclusion in final analyses.

### Manual overrides

Place corrections in the input files before re-running Stage 1:

| File | Purpose |
|------|---------|
| `manual_resolver_overrides.csv` | Force-accept a specific OpenAlex ID for a member |
| `manual_fp_overrides.csv` | Force-reject a false positive |
| `manual_resolver_blacklist.csv` | Permanently exclude an OpenAlex ID from all matches |

---

## Deployment (Render.com)

1. Push to GitHub
2. Create a new **Web Service** on Render, connect the `PanaceAInsights/acd-dashboard` repo
3. Render will auto-detect `render.yaml`
4. Set the `ANTHROPIC_API_KEY` environment variable in the Render dashboard
5. Upload `data/processed/` files to the service (or mount a persistent disk)

---

## Colour Palette

| Name | Hex | Usage |
|------|-----|-------|
| Deep Aubergine | `#1B1424` | Main background |
| Dark Plum | `#3D3149` | Sidebar / topbar |
| Mauve Purple | `#814C7E` | Nav active / wave |
| Muted Violet | `#553E51` | Borders / transitions |
| Copper | `#C27D4E` | Primary accent |
| Burnt Copper | `#AD6A3C` | Hover states |
| Light Copper | `#D99561` | Highlights |
| Warm Cream | `#ECE7DF` | Body text |
| White | `#FFFFFE` | Headings |
| Blue-Violet | `#575571` | Subtle accents |

---

## Attribution

Data sourced from [OpenAlex](https://openalex.org) (CC0) and [ANZCTR](https://www.anzctr.org.au).
Developed by [Dr Yagiz Aksoy MD PhD](https://www.linkedin.com/in/yagizalpaksoy/) · [PanaceaAI](https://www.panaceainsights.com.au)
