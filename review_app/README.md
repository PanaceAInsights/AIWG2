# ACD Entity Resolution Review Interface

A lightweight Flask web app for manually reviewing and adjudicating
REVIEW-tier and flagged entity resolution results after running
`scripts/01c_resolve_authors.py`.

## Usage

```bash
# From the project root
pip install flask
python review_app/app.py
# → Open http://localhost:5050
```

## Features

- Lists all REVIEW-tier members and common-name flagged members
- Warning badges for:
  - ⚠ **High Volume** — works > 300, name not exact match
  - 🌏 **No AU/NZ History** — accepted profile has no AU/NZ affiliation
  - 🔬 **Weak Specialty** — < 1 dermatology topic in top-10 topics
  - 👥 **Common Name** — same OpenAlex ID matched to 2+ members
  - 🤖 **LLM Disagreement** — standard and adversarial LLM calls disagreed
  - 🗺 **Country Mismatch** — no current or historical AU/NZ country
- Click any row to see full evidence: scores, LLM reasoning, OpenAlex link
- **Accept** — confirms the match as correct
- **Reject** — adds the candidate to `manual_fp_overrides.csv`
- **Override** — enter a correct OpenAlex ID, saved to `manual_resolver_overrides.csv`
- **Skip** — defers for later review
- Progress bar showing how many have been reviewed
- Export decisions as CSV

## Output Files

After reviewing, re-run the resolver to apply your decisions:

```bash
python scripts/01c_resolve_authors.py
```

The resolver will automatically use:
- `data/input/manual_resolver_overrides.csv` — your accepted overrides
- `data/input/manual_fp_overrides.csv` — your rejected candidates
