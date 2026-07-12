"""
Script 33b: Fill missing oa_rate for 135 members using works endpoint counts.
"""
import pandas as pd
import requests
import time

def fetch_oa_rate(openalex_id):
    """Fetch OA rate from works endpoint."""
    try:
        # Total works
        r1 = requests.get('https://api.openalex.org/works', params={
            'filter': f'authorships.author.id:{openalex_id}',
            'per_page': 1,
            'mailto': 'research@panaceainsights.com'
        }, timeout=20)
        if r1.status_code != 200:
            return None
        total = r1.json()['meta']['count']
        if total == 0:
            return 0.0
        
        # OA works
        r2 = requests.get('https://api.openalex.org/works', params={
            'filter': f'authorships.author.id:{openalex_id},is_oa:true',
            'per_page': 1,
            'mailto': 'research@panaceainsights.com'
        }, timeout=20)
        if r2.status_code != 200:
            return None
        oa_count = r2.json()['meta']['count']
        
        return oa_count / total  # 0-1 range
    except Exception as e:
        print(f"  Error: {e}")
        return None

def main():
    stats = pd.read_csv('data/processed/author_summary_stats.csv')
    missing = stats[stats['oa_rate'].isna() & stats['openalex_id'].notna()]
    print(f"Fetching OA rates for {len(missing)} members...")
    
    updated = 0
    for idx, row in missing.iterrows():
        oa_id = row['openalex_id']
        rate = fetch_oa_rate(oa_id)
        if rate is not None:
            stats.at[idx, 'oa_rate'] = rate
            updated += 1
        if (updated) % 20 == 0 and updated > 0:
            print(f"  Processed {updated}/{len(missing)}...")
        time.sleep(0.2)  # Rate limit (2 requests per member)
    
    # Recompute percentile
    valid_oa = stats['oa_rate'].dropna()
    stats['oa_rate_pctile'] = stats['oa_rate'].rank(pct=True) * 100
    
    stats.to_csv('data/processed/author_summary_stats.csv', index=False)
    print(f"\nDone. Updated {updated}/{len(missing)} OA rates.")
    print(f"Remaining NaN oa_rate: {stats['oa_rate'].isna().sum()}")

if __name__ == '__main__':
    main()
