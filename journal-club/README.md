# Dermatology Journal Club — article scan toolkit

Automated literature scan for the **Prince of Wales Hospital (POWH) Department of
Dermatology** journal club. Queries PubMed/NCBI by journal + volume + issue,
classifies the papers, and builds three ready-to-use outputs.

## Outputs (generated at the repo root)

| File | What it is | Use it for |
|---|---|---|
| [`journal-club-dashboard.html`](../journal-club-dashboard.html) | Interactive dashboard — search + filter by journal/type, per-paper cards with abstracts | Exploring / presenting live |
| [`journal-club-derm-2025.html`](../journal-club-derm-2025.html) | Printable reading list with every abstract inline | Pre-club reading / PDF handout |
| [`journal-club-derm-2025.csv`](../journal-club-derm-2025.csv) | One row per paper (split journal/year/vol/issue/pages, DOI, PubMed URL, abstract); UTF-8 BOM | Excel, EndNote/Zotero import |

Open any HTML file in a browser — no server or dependencies required.

## How it fits together

```
scope.json ──▶ fetch_pubmed.py ──▶ articles.json ──▶ generate_report.py ──▶ 3 output files
(what to       (queries PubMed/    (article data:     (renders; no network)
 fetch)         NCBI E-utilities)   metadata+abstract)
```

| File | Role |
|---|---|
| `scope.json` | The queries to run (journal + volume/issue, classification mode, section labels) |
| `fetch_pubmed.py` | Standalone NCBI E-utilities client (stdlib only) → writes `articles.json` |
| `articles.json` | Single source of truth: one record per paper incl. abstract |
| `generate_report.py` | Turns `articles.json` into the dashboard, reading list and CSV |

## Current scope (58 papers)

| Journal | Scope | In scope |
|---|---|---|
| **JAAD** (*J Am Acad Dermatol*) | Vol 92, Iss **4 (Apr)** + **5 (May)** 2025 — CME/original/review | 9 CME/review + 10 original |
| **AJD** (*Australas J Dermatol*) | Vol 66, Iss **3** = **May 2025** — whole issue | 31 (9 review, 9 original, 11 case report, 2 letter) |
| **BJD** (*Br J Dermatol*) | Vol 192, Iss **2 (Feb)** + **3 (Mar)** 2025 reviews + adjacent | 8 (Mar 2 + Feb HS suppl 3 + Apr 3) |

## ⚠️ The key method point: scope by issue, not by date

PubMed's publication-date filter **mixes "online-first" dates with print-issue
dates**. A naïve "April–May 2025" search over-returns articles destined for
*later* issues and *misses* issue content posted online earlier (a raw date
sweep returned 353 JAAD / 45 AJD hits and almost entirely **missed** the real
AJD May issue). Always scope by **journal + volume + issue**.

Issue → cover-month mapping (verified against PubMed citation strings):

```
JAAD  Vol 92  Iss 4 = Apr 2025 ; Iss 5 = May 2025      (2 volumes/yr: 92 = H1 2025)
AJD   Vol 66  Iss 3 = May 2025                          (cover date May, e-pub earlier)
BJD   Vol 192 Iss 2 = Feb 2025 ; Iss 3 = Mar 2025       (2 volumes/yr: 192 = H1 2025)
```

## Regenerate

```bash
# 1. fetch from PubMed (writes articles.json)        — needs network (see below)
python3 journal-club/fetch_pubmed.py

# 2. build the dashboard / reading list / CSV        — no network needed
python3 journal-club/generate_report.py
```

If you only tweaked `articles.json` by hand or changed presentation, just run
step 2. Validate the fetcher offline (no network) with:

```bash
python3 journal-club/fetch_pubmed.py --selftest      # parser + classifier check
python3 journal-club/fetch_pubmed.py --dry-run       # query + classify, print, don't write
```

## Run it again for next month's journal club

1. **Edit `scope.json`** — change the volume/issue numbers (and section labels)
   for the issues you want. Use the issue→month mapping above.
2. `python3 journal-club/fetch_pubmed.py` — set `NCBI_API_KEY` (and `NCBI_EMAIL`)
   in your environment to lift the rate limit from 3→10 req/sec.
3. `python3 journal-club/generate_report.py`
4. If the scope changed, update the `GENERATED` date and the `JOURNAL_META`
   scope labels at the top of `generate_report.py`; add any **new section label**
   to the relevant journal's `sections` list there.

**Network note.** `fetch_pubmed.py` needs outbound HTTPS to
`eutils.ncbi.nlm.nih.gov`. In *Claude Code on the web* the egress allowlist
blocks it by default (you'll get a clear `403` with instructions) — either add
that host to the environment's network allowlist, run the script on a normal
machine, **or** just ask Claude in this repo: *"Refresh the journal-club scan
for JAAD vol 93 iss 1–2, AJD vol 66 iss 4, BJD vol 192 iss 4 reviews"* — Claude
will run the PubMed queries, update `scope.json`/`articles.json` and regenerate.

## Classification notes

- JAAD tags many **research letters** as plain `Journal Article` (not `Letter[pt]`).
  The `original` mode therefore keeps only items with a real structured abstract
  (`min_abstract` chars), dropping research letters from "Original articles".
- **CME** has no PubMed publication type; CME articles surface as `Review` —
  confirm against the issue contents page (JAAD's multi-part series are the tell).
- The publication-type → badge mapping lives in `fetch_pubmed.py`
  (`badge_from_pubtypes`); `Published Erratum` / retractions are dropped.

## Attribution

Bibliographic data © the respective publishers, indexed by the U.S. National
Library of Medicine (**PubMed/NCBI**, MEDLINE). Every entry links to its DOI and
PubMed record — always cite the primary source.
