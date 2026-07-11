"""
Script 32: Fetch detailed profile data from OpenAlex for all members.

For each member, fetches:
1. counts_by_year (publications and citations per year) - from author endpoint
2. topics with counts - from author endpoint
3. grants/funders/awards - from works endpoint (paginated)

Saves to:
- data/processed/author_counts_by_year.json  (yearly pub/citation data)
- data/processed/author_grants.json  (grants and funders)
- data/processed/author_topics_detail.json  (topics with counts and domains)
"""
import pandas as pd
import requests
import time
import json
import sys

EMAIL = "research@panaceainsights.com.au"
STATS_PATH = "data/processed/author_summary_stats.csv"

# Output paths
COUNTS_PATH = "data/processed/author_counts_by_year.json"
GRANTS_PATH = "data/processed/author_grants.json"
TOPICS_PATH = "data/processed/author_topics_detail.json"


def fetch_author_profile(oa_id: str) -> dict | None:
    """Fetch author profile from OpenAlex."""
    url = f"https://api.openalex.org/authors/{oa_id}"
    try:
        r = requests.get(url, params={'mailto': EMAIL}, timeout=20)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def fetch_grants_for_author(oa_id: str) -> list:
    """Fetch all unique grants/awards for an author from their works."""
    all_awards = {}
    all_funders = {}
    page = 1
    per_page = 50
    
    while True:
        url = (f"https://api.openalex.org/works?"
               f"filter=authorships.author.id:{oa_id}"
               f"&select=id,funders,awards,publication_year"
               f"&per_page={per_page}&page={page}&mailto={EMAIL}")
        try:
            r = requests.get(url, timeout=30)
            if r.status_code != 200:
                break
            data = r.json()
            results = data.get('results', [])
            if not results:
                break
            
            for w in results:
                # Collect funders
                for f in (w.get('funders') or []):
                    fid = f.get('id', '')
                    if fid and fid not in all_funders:
                        all_funders[fid] = {
                            'id': fid,
                            'name': f.get('display_name', ''),
                            'ror': f.get('ror', ''),
                        }
                
                # Collect awards
                for a in (w.get('awards') or []):
                    aid = a.get('id', '')
                    if aid and aid not in all_awards:
                        all_awards[aid] = {
                            'id': aid,
                            'name': a.get('display_name', ''),
                            'award_id': a.get('funder_award_id', ''),
                            'funder': a.get('funder_display_name', ''),
                            'funder_id': a.get('funder_id', ''),
                        }
            
            # Check if more pages
            total = data.get('meta', {}).get('count', 0)
            if page * per_page >= total:
                break
            
            # Limit to first 200 works for grants (to avoid excessive API calls)
            if page >= 4:
                break
            
            page += 1
            time.sleep(0.2)
            
        except Exception:
            break
    
    return {
        'funders': list(all_funders.values()),
        'awards': list(all_awards.values()),
    }


def main():
    stats = pd.read_csv(STATS_PATH)
    members = stats[stats['openalex_id'].notna()]
    print(f"Total members to process: {len(members)}")
    sys.stdout.flush()
    
    counts_data = {}
    topics_data = {}
    grants_data = {}
    
    # Part 1: Fetch author profiles (counts_by_year + topics)
    print("\n=== Part 1: Fetching author profiles (counts_by_year + topics) ===")
    sys.stdout.flush()
    
    for i, (idx, row) in enumerate(members.iterrows()):
        oa_id = str(row['openalex_id']).strip()
        name = row['acd_name']
        
        profile = fetch_author_profile(oa_id)
        if profile:
            # Extract counts_by_year
            counts = profile.get('counts_by_year', [])
            counts_data[oa_id] = {
                'name': name,
                'counts_by_year': sorted(counts, key=lambda x: x.get('year', 0))
            }
            
            # Extract topics
            topics = profile.get('topics') or []
            topics_data[oa_id] = {
                'name': name,
                'topics': [{
                    'name': t.get('display_name', ''),
                    'count': t.get('count', 0),
                    'domain': t.get('domain', {}).get('display_name', '') if t.get('domain') else '',
                    'field': t.get('field', {}).get('display_name', '') if t.get('field') else '',
                    'subfield': t.get('subfield', {}).get('display_name', '') if t.get('subfield') else '',
                } for t in topics[:10]]
            }
        
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(members)}] profiles fetched")
            sys.stdout.flush()
            # Save intermediate
            with open(COUNTS_PATH, 'w') as f:
                json.dump(counts_data, f)
            with open(TOPICS_PATH, 'w') as f:
                json.dump(topics_data, f)
            time.sleep(1)
        else:
            time.sleep(0.3)
    
    # Save final counts and topics
    with open(COUNTS_PATH, 'w') as f:
        json.dump(counts_data, f)
    with open(TOPICS_PATH, 'w') as f:
        json.dump(topics_data, f)
    
    print(f"\nPart 1 complete: {len(counts_data)} profiles with counts_by_year")
    print(f"Topics saved for {len(topics_data)} members")
    sys.stdout.flush()
    
    # Part 2: Fetch grants (from works endpoint - slower)
    print("\n=== Part 2: Fetching grants from works ===")
    sys.stdout.flush()
    
    for i, (idx, row) in enumerate(members.iterrows()):
        oa_id = str(row['openalex_id']).strip()
        name = row['acd_name']
        
        grants = fetch_grants_for_author(oa_id)
        grants_data[oa_id] = {
            'name': name,
            'funders': grants['funders'],
            'awards': grants['awards'],
        }
        
        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{len(members)}] grants fetched "
                  f"(last: {name[:30]} - {len(grants['funders'])} funders, {len(grants['awards'])} awards)")
            sys.stdout.flush()
            # Save intermediate
            with open(GRANTS_PATH, 'w') as f:
                json.dump(grants_data, f)
            time.sleep(1)
        else:
            time.sleep(0.3)
    
    # Save final grants
    with open(GRANTS_PATH, 'w') as f:
        json.dump(grants_data, f)
    
    # Summary
    members_with_grants = sum(1 for v in grants_data.values() if v['funders'] or v['awards'])
    total_awards = sum(len(v['awards']) for v in grants_data.values())
    total_funders = sum(len(v['funders']) for v in grants_data.values())
    
    print(f"\n=== COMPLETE ===")
    print(f"Members with grants/funders: {members_with_grants}/{len(members)}")
    print(f"Total unique awards: {total_awards}")
    print(f"Total unique funders: {total_funders}")
    print(f"\nFiles saved:")
    print(f"  {COUNTS_PATH}")
    print(f"  {TOPICS_PATH}")
    print(f"  {GRANTS_PATH}")


if __name__ == "__main__":
    main()
