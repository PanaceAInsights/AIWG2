"""
13_reject_false_positives.py
Reject confirmed false-positive entity resolution matches and rebuild summary stats.

Confirmed false positives (2+ flags, clearly wrong person):
  - Dr Daniel Thomas Hewitt → matched to John K. Hewitt (Colorado, US) — completely different person
  - Dr Young Jin Kim → matched to Young Jin Kim (Severance Hospital, KR) — Korean researcher
  - Dr Matthew Gibson → matched to Matthew I. Gibson (Manchester, polymer chemist) — wrong field
  - Dr Philip James Clarke → matched to P. J. Clark (UCL, GB) — name mismatch + no AU/NZ
  - Dr Ritu Gupta → matched to Ritu Gupta (Chandigarh University, IN) — Indian researcher
  - Dr Sandeep Kumar → matched to Sandeep Kumar (Raman Research Institute, IN) — Indian physicist
  - Dr Pradeep Kumar → matched to Pradeep Kumar (University of Delhi, IN) — Indian researcher
  - Dr Wenyuan Liu → matched to Wenyuan Liu (China Pharmaceutical University, CN) — Chinese researcher

Medium-risk (1 flag, >100 pubs, no AU/NZ affiliation ever):
  - Dr Chen Xie → Nanjing University of Posts and Telecommunications (CN)
  - Dr Yan Pan → Anhui University (CN)
  - Dr Andrew Lee → Broad Institute (US) — "Andrew Lee" is extremely common
  - Dr Amit Kumar Verma → Bhabha Atomic Research Centre (IN) — atomic research, not derm
  - Dr Prateek Sharma → University of Kansas (US)
  - Dr Lauren Anderson → Texas Tech University (US)
  - Dr Pooja Sharma → Chaudhary Charan Singh University (IN)
  - Dr Shiva Baghaei → matched to Parvaneh Baghaei (Iran) — name mismatch
"""
import pandas as pd
import numpy as np
import shutil
from datetime import datetime

# ── Backup originals ──────────────────────────────────────────────────────────
ts = datetime.now().strftime('%Y%m%d_%H%M%S')
for f in ['data/processed/authors_resolved.csv', 
          'data/processed/author_summary_stats.csv']:
    shutil.copy(f, f.replace('.csv', f'_backup_{ts}.csv'))
print(f"Backed up originals with timestamp {ts}")

# ── Load data ─────────────────────────────────────────────────────────────────
authors = pd.read_csv('data/processed/authors_resolved.csv')
stats   = pd.read_csv('data/processed/author_summary_stats.csv')

# ── Define confirmed false positives ─────────────────────────────────────────
# Format: (acd_name, reason)
CONFIRMED_FP = [
    # HIGH CONFIDENCE (2+ flags)
    ("Dr Daniel Thomas Hewitt",
     "Matched to John K. Hewitt (behavioral geneticist, U Colorado Boulder, US) — completely different person, aunz_ever=0"),
    ("Dr Young Jin  Kim",
     "Matched to Young Jin Kim (Severance Hospital, Korea) — Korean researcher, aunz_ever=0, 955 pubs"),
    ("Dr Matthew Gibson",
     "Matched to Matthew I. Gibson (polymer chemist, U Manchester, UK) — wrong field and country, aunz_ever=0, 391 pubs"),
    ("Dr Philip James Clarke",
     "Matched to P. J. Clark (UCL, UK) — name mismatch (Clarke vs Clark), aunz_ever=0"),
    ("Dr Ritu  Gupta",
     "Matched to Ritu Gupta (Chandigarh University, India) — Indian researcher, aunz_ever=0, 447 pubs"),
    ("Dr Sandeep  Kumar",
     "Matched to Sandeep Kumar (Raman Research Institute, India) — Indian physicist, aunz_ever=0, 427 pubs"),
    ("Dr Pradeep  Kumar",
     "Matched to Pradeep Kumar (U Delhi, India) — Indian researcher, aunz_ever=0, 406 pubs"),
    ("Dr Wenyuan  Liu",
     "Matched to Wenyuan Liu (China Pharmaceutical University, China) — Chinese researcher, aunz_ever=0, 396 pubs"),
    # MEDIUM RISK (1 flag, >100 pubs, no AU/NZ affiliation)
    ("Dr Chen  Xie",
     "Matched to Chen Xie (Nanjing U Posts & Telecomms, China) — Chinese researcher, aunz_ever=0, 182 pubs"),
    ("Dr Yan  Pan",
     "Matched to Yan Pan (Anhui University, China) — Chinese researcher, aunz_ever=0, 150 pubs"),
    ("Dr Andrew Lee",
     "Matched to Andrew Lee (Broad Institute, US) — common name, US researcher, aunz_ever=0, 140 pubs"),
    ("Dr Amit Kumar Verma",
     "Matched to Amit Verma (Bhabha Atomic Research Centre, India) — atomic researcher not dermatologist, aunz_ever=0, 120 pubs"),
    ("Dr Prateek  Sharma",
     "Matched to Prateek Sharma (U Kansas, US) — US researcher, aunz_ever=0, 119 pubs"),
    ("Dr Lauren Anderson",
     "Matched to Lauren Anderson (Texas Tech, US) — US researcher, aunz_ever=0, 148 pubs"),
    ("Dr Pooja  Sharma",
     "Matched to Pooja Sharma (Chaudhary Charan Singh U, India) — Indian researcher, aunz_ever=0, 153 pubs"),
    ("Dr Shiva  Baghaei",
     "Matched to Parvaneh Baghaei (Masih Daneshvari Hospital, Iran) — name mismatch (Shiva vs Parvaneh), aunz_ever=0"),
]

fp_names = [name for name, _ in CONFIRMED_FP]
fp_reasons = {name: reason for name, reason in CONFIRMED_FP}

print(f"\nRejecting {len(fp_names)} confirmed false positives...")

# ── Update authors_resolved.csv ───────────────────────────────────────────────
# For each false positive: clear the OpenAlex match, set accepted=False
mask = authors['acd_name'].isin(fp_names)
print(f"Found {mask.sum()} matching rows in authors_resolved.csv")

authors.loc[mask, 'accepted']           = 0
authors.loc[mask, 'reject_reason']      = authors.loc[mask, 'acd_name'].map(
    lambda n: fp_reasons.get(n, 'false_positive_detected')
)
authors.loc[mask, 'openalex_id']        = None
authors.loc[mask, 'openalex_display_name'] = None
authors.loc[mask, 'last_known_institution'] = None
authors.loc[mask, 'institution_country']   = None
authors.loc[mask, 'h_index']              = None
authors.loc[mask, 'works_count']          = None
authors.loc[mask, 'aunz_ever']            = None
authors.loc[mask, 'profile_url']          = None
authors.loc[mask, 'resolution_method']    = 'rejected_false_positive'

authors.to_csv('data/processed/authors_resolved.csv', index=False)
print("Saved updated authors_resolved.csv")

# ── Update author_summary_stats.csv ──────────────────────────────────────────
# Zero out publication stats for false positives
stat_mask = stats['acd_name'].isin(fp_names)
print(f"Found {stat_mask.sum()} matching rows in author_summary_stats.csv")

zero_cols = ['pub_count', 'citation_count', 'h_index', 'i10_index',
             'fwci_mean', 'fwci_median', 'oa_rate', 'intl_collab_rate',
             'first_author_pct', 'last_author_pct', 'grants_count',
             'first_year', 'last_year', 'trial_count', 'derm_pub_count',
             'derm_relevance_rate', 'pub_count_pctile', 'citation_count_pctile',
             'h_index_pctile', 'oa_rate_pctile', 'intl_collab_rate_pctile',
             'grants_count_pctile', 'total_citations', 'total_works']
for col in zero_cols:
    if col in stats.columns:
        stats.loc[stat_mask, col] = None

stats.to_csv('data/processed/author_summary_stats.csv', index=False)
print("Saved updated author_summary_stats.csv")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n=== REJECTION SUMMARY ===")
for name, reason in CONFIRMED_FP:
    print(f"\n  REJECTED: {name}")
    print(f"  Reason: {reason}")

remaining_accepted = (authors['accepted'] == True).sum()
print(f"\nRemaining accepted matches: {remaining_accepted}")
print(f"Rejected false positives: {len(fp_names)}")
