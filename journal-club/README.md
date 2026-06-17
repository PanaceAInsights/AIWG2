# Dermatology Journal Club — article scan toolkit

Automated literature scan for the **Prince of Wales Hospital (POWH) Department of
Dermatology** journal club. Pulls the requested journals/issues from PubMed/NCBI
and builds three ready-to-use outputs.

## Outputs (generated at the repo root)

| File | What it is | Use it for |
|---|---|---|
| [`journal-club-dashboard.html`](../journal-club-dashboard.html) | Interactive, self-contained dashboard — search + filter by journal/type, per-paper cards with abstracts | Exploring / presenting live |
| [`journal-club-derm-2025.html`](../journal-club-derm-2025.html) | Printable reading list with every abstract inline | Pre-club reading / PDF handout |
| [`journal-club-derm-2025.csv`](../journal-club-derm-2025.csv) | One row per paper (split journal/year/vol/issue/pages, DOI, PubMed URL, abstract); UTF-8 BOM | Excel, EndNote/Zotero import |

Open any HTML file in a browser — no server or dependencies required.

## Current scope (June 2026 build · 58 papers)

| Journal | Scope | In scope |
|---|---|---|
| **JAAD** (*J Am Acad Dermatol*) | Vol 92, Iss **4 (Apr)** + **5 (May)** 2025 — CME/original/review | 9 CME/review + 10 original |
| **AJD** (*Australas J Dermatol*) | Vol 66, Iss **3** = **May 2025** — whole issue | 31 (9 review, 9 original, 11 case report, 2 letter) |
| **BJD** (*Br J Dermatol*) | Vol 192, Iss **2 (Feb)** + **3 (Mar)** 2025 reviews + adjacent | 8 (Mar 2 + Feb HS suppl 3 + Apr 3) |

## ⚠️ The key method point: scope by issue, not by date

PubMed's publication-date filter **mixes "online-first" dates with print-issue
dates**. A naïve "April–May 2025" search therefore over-returns articles destined
for *later* issues and *misses* issue content that was posted online earlier
(e.g. a raw date sweep returned 353 JAAD and 45 AJD hits, and almost entirely
**missed** the real AJD May issue). To match what a reader sees in the printed
issue, always scope by **journal + volume + issue**.

Issue → cover-month mapping (verified against PubMed citation strings):

```
JAAD  Vol 92  Iss 4 = Apr 2025 ; Iss 5 = May 2025      (2 volumes/yr: 92 = H1 2025)
AJD   Vol 66  Iss 3 = May 2025                          (cover date May, e-pub earlier)
BJD   Vol 192 Iss 2 = Feb 2025 ; Iss 3 = Mar 2025       (2 volumes/yr: 192 = H1 2025)
```

PubMed search patterns used (example — JAAD reviews for Apr–May):

```
"J Am Acad Dermatol"[Journal] AND 92[Volume] AND (4[Issue] OR 5[Issue]) AND Review[pt]
```

JAAD tags many research letters as plain `Journal Article` (not `Letter[pt]`),
so "original articles" were separated from research letters by presence of a
structured abstract.

## Regenerate

```bash
python3 journal-club/generate_report.py
```

Reads `journal-club/abstracts.json` (abstracts keyed by PMID) plus the article
tables embedded in `generate_report.py`, and rewrites the three output files.
No network access needed — the data is self-contained and reproducible.

## Run it again for a new journal club

The literature lookup itself needs PubMed access, which is done in a Claude Code
session (NCBI E-utilities are blocked by the egress allowlist for standalone
scripts). The repeatable workflow:

1. **Ask Claude** in this repo, e.g.
   *"Refresh the journal-club scan for JAAD vol 93 iss 1–2, AJD vol 66 iss 4, BJD vol 192 iss 4 reviews."*
   Claude will run the volume/issue PubMed queries, update the article tables in
   `generate_report.py` and `abstracts.json`, and regenerate the outputs.
2. **Or edit by hand:** add entries to the relevant list in `generate_report.py`
   (`art(pmid, doi, authors, title, cite, badge)`), add each PMID's abstract to
   `abstracts.json`, then run the command above.

Update `GENERATED` (date) and the `JOURNALS` scope labels at the top of
`generate_report.py` when the scope changes.

## Attribution

Bibliographic data © the respective publishers, indexed by the U.S. National
Library of Medicine (**PubMed/NCBI**, MEDLINE). Every entry links to its DOI and
PubMed record — always cite the primary source.
