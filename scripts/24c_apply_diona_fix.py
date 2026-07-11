"""
Script 24c: Apply Diona Damian split-profile aggregation directly.
Aggregated values already computed: works=106, h=37, citations=4766
"""
import pandas as pd, json
from pathlib import Path

BASE = Path(__file__).parent.parent
RESOLVED = BASE / 'data/processed/authors_resolved.csv'
STATS    = BASE / 'data/processed/author_summary_stats.csv'

resolved = pd.read_csv(RESOLVED)

# Add new columns if missing
for col, default in [('split_ids', ''), ('total_citations', None), ('notes', '')]:
    if col not in resolved.columns:
        resolved[col] = default

# Apply aggregated values for Diona Damian
mask = (resolved['acd_name'] == 'Dr Diona Lee Damian') & (resolved['accepted'] == 1)
print(f"Rows matching Diona Damian: {mask.sum()}")
print("Before:", resolved.loc[mask, ['works_count','h_index']].to_string())

resolved.loc[mask, 'works_count']    = 106
resolved.loc[mask, 'h_index']        = 37
resolved.loc[mask, 'total_citations'] = 4766
resolved.loc[mask, 'split_ids']      = json.dumps(['A5040089794'])
resolved.loc[mask, 'notes']          = 'Aggregated from A5109680281 + A5040089794 (split profile)'

print("After:", resolved.loc[mask, ['works_count','h_index','total_citations','split_ids']].to_string())

resolved.to_csv(RESOLVED, index=False)
print(f"Saved resolved CSV ({len(resolved)} rows)")

# Rebuild stats
accepted = resolved[resolved['accepted'] == 1].copy()
stats_cols = [c for c in [
    'acd_name', 'openalex_id', 'openalex_display_name',
    'last_known_institution', 'institution_country',
    'works_count', 'h_index', 'total_citations',
    'aunz_ever', 'confidence', 'resolution_method', 'split_ids'
] if c in resolved.columns]
accepted[stats_cols].to_csv(STATS, index=False)
print(f"Stats rebuilt: {len(accepted)} accepted rows")

# Verify top 5 by h-index
top = accepted.nlargest(5, 'h_index')[['acd_name','h_index','works_count','last_known_institution']]
print("\nTop 5 by h-index:")
print(top.to_string())
