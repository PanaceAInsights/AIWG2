"""
Script 28: Bulk update citations, FWCI, and other details from OpenAlex author endpoint.

For all members with OpenAlex IDs that have missing citation_count or fwci_mean,
fetch from the author endpoint and update both CSVs.
"""
import pandas as pd
import requests
import time
import sys

STATS_PATH = "data/processed/author_summary_stats.csv"
RESOLVED_PATH = "data/processed/authors_resolved.csv"
EMAIL = "research@panaceainsights.com.au"

def fetch_author(openalex_id: str, retries: int = 3) -> dict | None:
    """Fetch author data from OpenAlex."""
    # Normalize ID
    oid = openalex_id.strip()
    if not oid.startswith("http"):
        url = f"https://api.openalex.org/authors/{oid}"
    else:
        url = oid
    
    for attempt in range(retries):
        try:
            r = requests.get(url, params={"mailto": EMAIL}, timeout=30)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            else:
                print(f"  HTTP {r.status_code} for {oid}")
                return None
        except Exception as e:
            print(f"  Error for {oid}: {e}")
            time.sleep(2)
    return None


def main():
    stats = pd.read_csv(STATS_PATH)
    res = pd.read_csv(RESOLVED_PATH)
    
    # Find members needing update: have openalex_id but missing citations or fwci
    need_update = stats[
        (stats['openalex_id'].notna()) & 
        (stats['openalex_id'] != '') &
        (
            (stats['citation_count'].isna()) | (stats['citation_count'] == 0) |
            (stats['fwci_mean'].isna()) | (stats['fwci_mean'] == 0)
        )
    ].copy()
    
    print(f"Members needing citation/FWCI update: {len(need_update)}")
    print(f"Starting bulk fetch from OpenAlex...")
    print()
    
    updated = 0
    failed = 0
    
    for i, (idx, row) in enumerate(need_update.iterrows()):
        name = row['acd_name']
        oid = row['openalex_id']
        
        # Rate limit: 10 requests per second max
        if i > 0 and i % 10 == 0:
            time.sleep(1.1)
        
        author = fetch_author(oid)
        if not author:
            failed += 1
            print(f"  [{i+1}/{len(need_update)}] FAILED: {name}")
            continue
        
        # Extract data
        summary_stats = author.get('summary_stats', {})
        h_index = summary_stats.get('h_index', 0)
        cited_by = author.get('cited_by_count', 0)
        works_count = author.get('works_count', 0)
        
        # FWCI: OpenAlex doesn't provide FWCI directly at author level
        # We need to compute it from the 2yr_mean_citedness vs expected
        # Actually OpenAlex summary_stats has '2yr_mean_citedness' and 
        # '2yr_cited_by_count' but not FWCI
        # The FWCI we have in the stats was computed from works - keep existing if > 0
        # For missing FWCI, we'll need to fetch from works (done separately)
        
        # i10_index
        i10_index = summary_stats.get('i10_index', 0)
        
        # Update stats CSV
        stats.loc[idx, 'citation_count'] = cited_by
        stats.loc[idx, 'total_citations'] = cited_by
        stats.loc[idx, 'i10_index'] = i10_index
        
        # Update h_index if it was 0
        if pd.isna(stats.loc[idx, 'h_index']) or stats.loc[idx, 'h_index'] == 0:
            stats.loc[idx, 'h_index'] = h_index
        
        # Update works_count
        stats.loc[idx, 'works_count'] = works_count
        if pd.isna(stats.loc[idx, 'pub_count']) or stats.loc[idx, 'pub_count'] == 0:
            stats.loc[idx, 'pub_count'] = works_count
        
        # Update resolved CSV too
        res_idx = res[res['acd_name'] == name].index
        if len(res_idx) > 0:
            ridx = res_idx[0]
            if pd.isna(res.loc[ridx, 'h_index']) or res.loc[ridx, 'h_index'] == 0:
                res.loc[ridx, 'h_index'] = h_index
            res.loc[ridx, 'works_count'] = works_count
            if 'total_citations' in res.columns:
                res.loc[ridx, 'total_citations'] = cited_by
        
        updated += 1
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(need_update)}] Progress: {updated} updated, {failed} failed")
            sys.stdout.flush()
    
    print(f"\nDone! Updated: {updated}, Failed: {failed}")
    print()
    
    # Now handle FWCI for those still missing
    # FWCI needs to be computed from works - let's fetch a sample of works for each
    # member with missing FWCI and compute mean FWCI
    missing_fwci = stats[
        (stats['openalex_id'].notna()) & 
        (stats['openalex_id'] != '') &
        ((stats['fwci_mean'].isna()) | (stats['fwci_mean'] == 0))
    ]
    
    print(f"Members still missing FWCI: {len(missing_fwci)}")
    print("Fetching FWCI from works...")
    
    fwci_updated = 0
    for i, (idx, row) in enumerate(missing_fwci.iterrows()):
        name = row['acd_name']
        oid = row['openalex_id']
        
        if i > 0 and i % 5 == 0:
            time.sleep(1.1)
        
        # Fetch recent works with FWCI
        try:
            url = f"https://api.openalex.org/works"
            params = {
                'filter': f'authorships.author.id:{oid}',
                'select': 'id,fwci',
                'per_page': 100,
                'mailto': EMAIL
            }
            r = requests.get(url, params=params, timeout=30)
            if r.status_code != 200:
                continue
            works = r.json().get('results', [])
            fwci_values = [w['fwci'] for w in works if w.get('fwci') is not None and w['fwci'] > 0]
            if fwci_values:
                mean_fwci = sum(fwci_values) / len(fwci_values)
                median_fwci = sorted(fwci_values)[len(fwci_values)//2]
                stats.loc[idx, 'fwci_mean'] = round(mean_fwci, 2)
                stats.loc[idx, 'fwci_median'] = round(median_fwci, 2)
                fwci_updated += 1
        except Exception as e:
            print(f"  FWCI error for {name}: {e}")
        
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(missing_fwci)}] FWCI progress: {fwci_updated} updated")
            sys.stdout.flush()
    
    print(f"FWCI updated: {fwci_updated}")
    print()
    
    # Save
    stats.to_csv(STATS_PATH, index=False)
    res.to_csv(RESOLVED_PATH, index=False)
    print("Saved both CSVs")
    
    # Final stats
    still_missing_cit = ((stats['citation_count'].isna()) | (stats['citation_count'] == 0)).sum()
    still_missing_fwci = ((stats['fwci_mean'].isna()) | (stats['fwci_mean'] == 0)).sum()
    print(f"Remaining missing citations: {still_missing_cit}")
    print(f"Remaining missing FWCI: {still_missing_fwci}")


if __name__ == "__main__":
    main()
