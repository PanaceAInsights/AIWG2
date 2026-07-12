"""
Script 33: Fill missing oa_rate and derm_relevance_rate for 135 newly resolved members.
Also fix the profile card to show 'N/A' instead of 'nan%'.
"""
import pandas as pd
import requests
import time
import json

DERM_CONCEPTS = {
    'dermatology', 'skin', 'melanoma', 'psoriasis', 'eczema', 'dermatitis',
    'cutaneous', 'epidermis', 'keratinocyte', 'wound healing', 'hair loss',
    'alopecia', 'acne', 'vitiligo', 'pemphigus', 'bullous', 'urticaria',
    'pruritus', 'atopic', 'squamous cell', 'basal cell', 'mohs',
    'dermoscopy', 'phototherapy', 'skin cancer', 'skin neoplasm'
}

def is_derm_topic(topic_name):
    """Check if a topic name is dermatology-related."""
    name_lower = topic_name.lower()
    return any(kw in name_lower for kw in DERM_CONCEPTS)

def fetch_author_metrics(openalex_id):
    """Fetch oa_rate and derm_relevance from OpenAlex."""
    url = f"https://api.openalex.org/authors/{openalex_id}"
    try:
        r = requests.get(url, params={'mailto': 'research@panaceainsights.com'}, timeout=30)
        if r.status_code != 200:
            return None, None
        data = r.json()
        
        # OA rate from summary_stats
        summary = data.get('summary_stats', {})
        oa_pct = summary.get('oa_percent', None)
        if oa_pct is not None:
            oa_rate = oa_pct / 100.0  # Store as 0-1
        else:
            oa_rate = None
        
        # Derm relevance from topics
        topics = data.get('topics', [])
        total_works = sum(t.get('count', 0) for t in topics)
        derm_works = sum(t.get('count', 0) for t in topics if is_derm_topic(t.get('display_name', '')))
        
        if total_works > 0:
            derm_rate = (derm_works / total_works) * 100  # Store as percentage
        else:
            derm_rate = None
            
        derm_pub_count = derm_works
        
        return oa_rate, derm_rate, derm_pub_count
    except Exception as e:
        print(f"  Error fetching {openalex_id}: {e}")
        return None, None, None

def main():
    stats = pd.read_csv('data/processed/author_summary_stats.csv')
    missing = stats[stats['oa_rate'].isna() & stats['openalex_id'].notna()].copy()
    print(f"Filling metrics for {len(missing)} members...")
    
    updated = 0
    for idx, row in missing.iterrows():
        oa_id = row['openalex_id']
        result = fetch_author_metrics(oa_id)
        if result[0] is not None:
            stats.at[idx, 'oa_rate'] = result[0]
        if result[1] is not None:
            stats.at[idx, 'derm_relevance_rate'] = result[1]
        if len(result) > 2 and result[2] is not None:
            stats.at[idx, 'derm_pub_count'] = result[2]
        updated += 1
        if updated % 20 == 0:
            print(f"  Processed {updated}/{len(missing)}...")
        time.sleep(0.15)  # Rate limit
    
    # Also compute oa_rate_pctile for all
    valid_oa = stats['oa_rate'].dropna()
    if len(valid_oa) > 0:
        stats['oa_rate_pctile'] = stats['oa_rate'].rank(pct=True) * 100
    
    stats.to_csv('data/processed/author_summary_stats.csv', index=False)
    print(f"\nDone. Updated {updated} members.")
    print(f"Remaining NaN oa_rate: {stats['oa_rate'].isna().sum()}")
    print(f"Remaining NaN derm_relevance_rate: {stats['derm_relevance_rate'].isna().sum()}")

if __name__ == '__main__':
    main()
