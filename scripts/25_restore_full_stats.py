"""
Script 25: Restore the full rich author_summary_stats.csv.

The stats rebuilds in scripts 13-24 only kept columns from authors_resolved.csv
(works_count, h_index, total_citations) and lost all publications-derived columns
(pub_count, citation_count, fwci_mean, fwci_median, oa_rate, derm_relevance_rate,
percentiles, etc.).

Fix: merge the backup's rich columns with the current accepted member list,
then apply Diona Damian's aggregated override.
"""
import pandas as pd
import json
from pathlib import Path

BASE    = Path(__file__).parent.parent
PROC    = BASE / 'data/processed'
BACKUP  = PROC / 'author_summary_stats_backup_20260711_054628.csv'
RESOLVED = PROC / 'authors_resolved.csv'
OUT     = PROC / 'author_summary_stats.csv'

# 1. Load current accepted members from resolved CSV
resolved = pd.read_csv(RESOLVED)
accepted = resolved[resolved['accepted'] == 1].copy()
print(f"Accepted members: {len(accepted)}")

# 2. Load the rich backup stats
backup = pd.read_csv(BACKUP)
print(f"Backup stats rows: {len(backup)}, columns: {list(backup.columns)}")

# 3. Start from the resolved data for identity columns
identity_cols = ['acd_name', 'openalex_id', 'openalex_display_name',
                 'last_known_institution', 'institution_country',
                 'works_count', 'h_index', 'aunz_ever', 'confidence',
                 'resolution_method']
identity_cols = [c for c in identity_cols if c in resolved.columns]
base = accepted[identity_cols].copy()

# 4. Merge in the rich publications-derived stats from backup
# Drop columns from backup that already exist in base (to avoid _x/_y collisions)
overlap = [c for c in backup.columns if c != 'acd_name' and c in base.columns]
print(f"Dropping overlapping backup cols: {overlap}")
backup_clean = backup.drop(columns=overlap)
rich_cols = [c for c in backup_clean.columns if c != 'acd_name']
merged = base.merge(backup_clean[['acd_name'] + rich_cols], on='acd_name', how='left')
print(f"After merge: {len(merged)} rows")

# Check coverage
has_pubs = merged['pub_count'].notna().sum()
print(f"Members with pub_count from backup: {has_pubs}/{len(merged)}")

# 5. For members in accepted but NOT in backup (new additions since backup),
#    fall back to works_count as pub_count
mask_no_pubs = merged['pub_count'].isna()
print(f"Members missing pub_count (not in backup): {mask_no_pubs.sum()}")
merged.loc[mask_no_pubs, 'pub_count'] = merged.loc[mask_no_pubs, 'works_count']

# 6. Apply Diona Damian aggregated override
dd_mask = merged['acd_name'] == 'Dr Diona Lee Damian'
if dd_mask.sum() > 0:
    merged.loc[dd_mask, 'pub_count']      = 106
    merged.loc[dd_mask, 'works_count']    = 106
    merged.loc[dd_mask, 'h_index']        = 37
    merged.loc[dd_mask, 'citation_count'] = 4766
    print(f"Applied Diona Damian override: pub_count=106, h_index=37, citation_count=4766")
else:
    print("WARNING: Diona Damian not found in merged data")

# 7. Ensure citation_count alias exists
if 'citation_count' not in merged.columns and 'total_citations' in merged.columns:
    merged['citation_count'] = merged['total_citations']
elif 'citation_count' in merged.columns and 'total_citations' not in merged.columns:
    merged['total_citations'] = merged['citation_count']

# 8. Recompute percentiles for the current accepted set
pctile_map = {
    'pub_count': 'pub_count_pctile',
    'citation_count': 'citation_count_pctile',
    'h_index': 'h_index_pctile',
    'oa_rate': 'oa_rate_pctile',
    'intl_collab_rate': 'intl_collab_rate_pctile',
    'grants_count': 'grants_count_pctile',
}
for src, dst in pctile_map.items():
    if src in merged.columns:
        vals = pd.to_numeric(merged[src], errors='coerce')
        merged[dst] = vals.rank(pct=True) * 100

# 9. Save
merged.to_csv(OUT, index=False)
print(f"\nSaved {OUT} with {len(merged)} rows and {len(merged.columns)} columns")
print("Columns:", list(merged.columns))

# 10. Verify top 5
top5 = merged.nlargest(5, 'h_index')[['acd_name','pub_count','citation_count','h_index','fwci_mean']]
print("\nTop 5 by h-index:")
print(top5.to_string())

# Spot check Soyer and Damian
for name in ['Dr Hans Peter Soyer', 'Dr Diona Lee Damian']:
    row = merged[merged['acd_name'] == name]
    if not row.empty:
        r = row.iloc[0]
        print(f"\n{name}: pub={r.get('pub_count')}, cit={r.get('citation_count')}, h={r.get('h_index')}, fwci={r.get('fwci_mean')}")
