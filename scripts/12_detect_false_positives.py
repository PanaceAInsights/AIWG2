"""
12_detect_false_positives.py
Detect and report likely false-positive entity resolution matches.

A false positive is an ACD member that has been matched to a researcher who is
clearly NOT the same person — typically because:
  1. The matched OpenAlex author has NO AU/NZ affiliation history (aunz_ever=0)
  2. Their current institution is outside AU/NZ
  3. Their publication count or h-index is implausibly high for a clinical dermatologist
  4. The OpenAlex display name doesn't match the ACD member name
"""
import pandas as pd
import numpy as np
import re

authors = pd.read_csv('data/processed/authors_resolved.csv')
stats   = pd.read_csv('data/processed/author_summary_stats.csv')

accepted = authors[authors['accepted'] == True].copy()
print(f"Total accepted matches: {len(accepted)}")

# Merge summary stats (pub_count, h_index from publications)
# Drop overlapping cols first to avoid _x/_y
overlap = [c for c in stats.columns if c in accepted.columns and c != 'acd_name']
accepted_clean = accepted.drop(columns=overlap, errors='ignore')
merged = accepted_clean.merge(stats[['acd_name','pub_count','h_index','citation_count']], 
                               on='acd_name', how='left')

# ── Flag 1: No AU/NZ affiliation history + non-AU/NZ institution ─────────────
au_nz = ['AU', 'NZ']
flag1 = (
    (merged['aunz_ever'] == 0) &
    (merged['institution_country'].notna()) &
    (~merged['institution_country'].isin(au_nz)) &
    (merged['institution_country'] != '')
)

# ── Flag 2: Name mismatch — OpenAlex name shares <1 token with ACD name ──────
def name_overlap(acd_name, openalex_name):
    if pd.isna(openalex_name):
        return True  # can't check
    acd_tokens = set(re.sub(r'[^a-z\s]', '', str(acd_name).lower()).split())
    oa_tokens  = set(re.sub(r'[^a-z\s]', '', str(openalex_name).lower()).split())
    # Remove common titles
    stop = {'dr','prof','a/prof','adj','mr','ms','mrs','associate','professor'}
    acd_tokens -= stop
    oa_tokens  -= stop
    if not acd_tokens or not oa_tokens:
        return True
    return len(acd_tokens & oa_tokens) >= 1

merged['name_ok'] = merged.apply(
    lambda r: name_overlap(r['acd_name'], r.get('openalex_display_name')), axis=1
)
flag2 = ~merged['name_ok']

# ── Flag 3: Implausibly high pub count for a clinical dermatologist ───────────
# Genuine high-volume derm researchers rarely exceed ~600 pubs
# Flag anyone with >300 pubs AND aunz_ever=0 AND non-AU/NZ institution
flag3 = (
    (merged['pub_count'].fillna(0) > 300) &
    (merged['aunz_ever'] == 0) &
    (merged['institution_country'].notna()) &
    (~merged['institution_country'].isin(au_nz))
)

# ── Flag 4: h-index > 50 AND aunz_ever=0 AND non-AU/NZ ──────────────────────
flag4 = (
    (merged['h_index'].fillna(0) > 50) &
    (merged['aunz_ever'] == 0) &
    (merged['institution_country'].notna()) &
    (~merged['institution_country'].isin(au_nz))
)

# ── Combine flags ─────────────────────────────────────────────────────────────
merged['flag_no_aunz_foreign'] = flag1.astype(int)
merged['flag_name_mismatch']   = flag2.astype(int)
merged['flag_high_pubs']       = flag3.astype(int)
merged['flag_high_h']          = flag4.astype(int)
merged['flag_count']           = (flag1.astype(int) + flag2.astype(int) + 
                                   flag3.astype(int) + flag4.astype(int))

# Any flag at all
any_flag = merged['flag_count'] > 0
flagged  = merged[any_flag].copy()

print(f"\nFlagged as potentially false positive: {len(flagged)}")
print(f"  - No AU/NZ affiliation + foreign institution: {flag1.sum()}")
print(f"  - Name mismatch: {flag2.sum()}")
print(f"  - High pubs (>300) + no AU/NZ: {flag3.sum()}")
print(f"  - High h-index (>50) + no AU/NZ: {flag4.sum()}")

# ── Print high-confidence false positives (2+ flags) ─────────────────────────
high_conf = flagged[flagged['flag_count'] >= 2].sort_values('pub_count', ascending=False)
print(f"\n=== HIGH CONFIDENCE FALSE POSITIVES (2+ flags): {len(high_conf)} ===")
cols = ['acd_name','openalex_display_name','last_known_institution',
        'institution_country','h_index','pub_count','aunz_ever','flag_count']
print(high_conf[cols].to_string())

# ── Print all flagged ─────────────────────────────────────────────────────────
print(f"\n=== ALL FLAGGED (1+ flag): {len(flagged)} ===")
print(flagged[cols].sort_values(['flag_count','pub_count'], ascending=[False,False]).to_string())

# Save report
flagged[cols + ['flag_no_aunz_foreign','flag_name_mismatch','flag_high_pubs','flag_high_h',
                'openalex_id','total_score','confidence','resolution_method']].sort_values(
    ['flag_count','pub_count'], ascending=[False,False]
).to_csv('data/processed/false_positive_candidates.csv', index=False)
print("\nSaved to data/processed/false_positive_candidates.csv")
