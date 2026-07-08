#!/usr/bin/env python3
"""
Merge Pass 3 LLM adjudication results from review_queue.csv back into authors_resolved.csv.

The CheckpointWriter skips already-written keys, so the final rewrite in the resolver
doesn't update rows that were already in the CSV. This script applies the LLM results
from review_queue.csv to the main authors_resolved.csv.
"""
import pandas as pd
from pathlib import Path
import shutil
from datetime import datetime

ROOT = Path(__file__).parent.parent
PROCESSED = ROOT / "data" / "processed"

authors_csv = PROCESSED / "authors_resolved.csv"
review_csv = PROCESSED / "review_queue.csv"
common_name_csv = PROCESSED / "common_name_review.csv"

# Backup the original
backup_path = PROCESSED / f"authors_resolved_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
shutil.copy2(authors_csv, backup_path)
print(f"Backed up to: {backup_path}")

# Load both files
df = pd.read_csv(authors_csv)
rq = pd.read_csv(review_csv)

print(f"\nBefore merge:")
print(f"  authors_resolved.csv: {len(df)} rows")
print(f"  Confidence: {df['confidence'].value_counts().to_dict()}")
print(f"\nreview_queue.csv: {len(rq)} rows")
print(f"  LLM results: {rq['confidence'].value_counts().to_dict()}")

# Merge: for each member in review_queue, update the corresponding row in authors_resolved
# The review_queue has the LLM-adjudicated confidence, accepted, llm_reasoning, etc.
update_cols = [
    'confidence', 'accepted', 'score_llm', 'total_score', 'resolution_method',
    'ambiguity_flags', 'llm_reasoning', 'reject_reason', 'openalex_id',
    'openalex_display_name', 'profile_url'
]

# Merge using pandas update approach - convert to string-typed columns first
# to avoid dtype conflicts
for col in update_cols:
    if col in df.columns:
        df[col] = df[col].astype(object)

# Build index on acd_name
df = df.set_index('acd_name')
rq = rq.set_index('acd_name')

updated_count = 0
for name, rq_row in rq.iterrows():
    if name in df.index:
        for col in update_cols:
            if col in rq.columns and col in df.columns:
                val = rq_row.get(col)
                df.at[name, col] = val
        updated_count += 1

df = df.reset_index()
print(f"\nUpdated {updated_count} rows with LLM results")

# Run Pass 4 audit (common-name & suspicious-merge)
# Flag common names and suspicious merges
_WORKS_PENALTY_THRESHOLD = 300
_NAME_EXACT = 50  # score_name value for exact match
HV_EXCEPTIONS = {'soyer', 'murrell', 'sinclair', 'damian'}

def normalise_name(name: str) -> str:
    import re
    name = re.sub(r'\b(Dr|Prof|Assoc|Mr|Ms|Mrs|A/Prof)\b', '', name, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', name).strip().lower()

# Build id → [names] map (skip NaN/empty/nan string)
id_to_names = {}
for _, row in df.iterrows():
    oid = str(row.get('openalex_id') or '').strip()
    if oid and oid.lower() not in ('nan', 'none', ''):
        id_to_names.setdefault(oid, []).append(row['acd_name'])

common_name_rows = []
for idx, row in df.iterrows():
    flags = [f for f in str(row.get('ambiguity_flags') or '').split('|') if f and f.lower() != 'nan']
    flag_reasons = []
    
    # Duplicate OpenAlex ID
    oid = str(row.get('openalex_id') or '').strip()
    if oid and oid.lower() not in ('nan', 'none', '') and len(id_to_names.get(oid, [])) > 1:
        if 'COMMON_NAME_RISK' not in flags:
            flags.append('COMMON_NAME_RISK')
        flag_reasons.append(f"OpenAlex ID {oid} matched to {len(id_to_names[oid])} members")
    
    # Suspicious volume
    works = int(row.get('works_count') or 0)
    is_exact = int(row.get('score_name') or 0) >= _NAME_EXACT
    norm = normalise_name(str(row.get('acd_name') or ''))
    last_name = norm.split()[-1] if norm.split() else ''
    if works > _WORKS_PENALTY_THRESHOLD and not is_exact and last_name not in HV_EXCEPTIONS:
        if 'SUSPICIOUS_VOLUME' not in flags:
            flags.append('SUSPICIOUS_VOLUME')
        flag_reasons.append(f"works_count={works} but name not exact match")
    
    # No AU/NZ history
    if str(row.get('accepted')) == '1' and str(row.get('aunz_ever')) == '0':
        if 'NO_AUNZ_HISTORY' not in flags:
            flags.append('NO_AUNZ_HISTORY')
        flag_reasons.append("accepted profile has no AU/NZ affiliation history")
    
    if flag_reasons:
        # Downgrade HIGH → REVIEW
        if row.get('confidence') == 'HIGH':
            df.at[idx, 'confidence'] = 'REVIEW'
            df.at[idx, 'accepted'] = '0'
            df.at[idx, 'reject_reason'] = 'pass4_audit:' + ';'.join(flag_reasons)
        df.at[idx, 'ambiguity_flags'] = '|'.join(dict.fromkeys(flags))
        common_name_rows.append({
            'acd_name': row['acd_name'],
            'state': row.get('state', ''),
            'openalex_id': row.get('openalex_id', ''),
            'openalex_display_name': row.get('openalex_display_name', ''),
            'last_known_institution': row.get('last_known_institution', ''),
            'works_count': works,
            'ambiguity_flags': df.at[idx, 'ambiguity_flags'],
            'total_score': row.get('total_score', 0),
            'confidence': df.at[idx, 'confidence'],
            'flag_reason': '; '.join(flag_reasons),
        })

print(f"\nPass 4 audit: {len(common_name_rows)} members flagged")

# Write common_name_review.csv
if common_name_rows:
    pd.DataFrame(common_name_rows).to_csv(common_name_csv, index=False)
    print(f"Written: {common_name_csv}")

# Write final authors_resolved.csv
df.to_csv(authors_csv, index=False)
print(f"\nWritten: {authors_csv}")

print(f"\nAfter merge + Pass 4:")
print(f"  Total rows: {len(df)}")
print(f"  Confidence: {df['confidence'].value_counts().to_dict()}")
print(f"  Accepted: {df['accepted'].value_counts().to_dict()}")

# Write resolution_complete.flag
flag_path = PROCESSED / "resolution_complete.flag"
flag_path.write_text(f"Resolution complete at {datetime.now().isoformat()}\n")
print(f"\nFlag written: {flag_path}")
