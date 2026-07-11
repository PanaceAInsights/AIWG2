"""
Script 24: Split-Profile Detection and Aggregation

Problem: OpenAlex sometimes splits a single researcher's publications across
multiple author IDs. This is common when:
  - The researcher published under different name variants (e.g., "D.L. Damian" vs "Diona Damian")
  - Institution changes caused OpenAlex's disambiguation to create separate profiles
  - ORCID was added to one profile but not the other

Solution:
  1. For each accepted match, search OpenAlex for all author IDs with the same name
     and overlapping AU/NZ institutions
  2. If multiple candidate IDs are found with the same name + AU institutions,
     fetch all their works and compute a deduplicated h-index and works count
  3. Store the aggregated stats and the list of all contributing IDs

This produces more accurate metrics that match Scopus's merged view.
"""

import requests
import pandas as pd
import json
import time
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

BASE = Path(__file__).parent.parent
RESOLVED = BASE / 'data/processed/authors_resolved.csv'
STATS = BASE / 'data/processed/author_summary_stats.csv'

HEADERS = {"User-Agent": "ACD-Dashboard/2.0 (panaceainsights.com.au)"}
DERM_KEYWORDS = {
    'dermatol', 'skin', 'melanoma', 'psoriasis', 'eczema', 'acne', 'rosacea',
    'cutaneous', 'keratinocyte', 'basal cell', 'squamous cell', 'nail', 'hair',
    'alopecia', 'vitiligo', 'pemphigus', 'bullous', 'urticaria', 'photodermat',
    'phototherapy', 'nicotinamide', 'sunscreen', 'UV', 'ultraviolet'
}


def oa_get(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                time.sleep(5 * (attempt + 1))
            else:
                return None
        except Exception as e:
            log.warning(f"Request error: {e}")
            time.sleep(2)
    return None


def get_all_works_for_author(author_id):
    """Fetch all work DOIs/titles for an author to enable deduplication."""
    works = []
    cursor = '*'
    while True:
        data = oa_get("https://api.openalex.org/works",
            params={
                "filter": f"authorships.author.id:{author_id}",
                "select": "id,doi,title,publication_year,cited_by_count",
                "per-page": 200,
                "cursor": cursor
            })
        if not data:
            break
        batch = data.get('results', [])
        works.extend(batch)
        meta = data.get('meta', {})
        cursor = meta.get('next_cursor')
        if not cursor or len(batch) == 0:
            break
        time.sleep(0.15)
    return works


def compute_h_index(cited_by_counts):
    """Compute h-index from a list of citation counts."""
    counts = sorted(cited_by_counts, reverse=True)
    h = 0
    for i, c in enumerate(counts):
        if c >= i + 1:
            h = i + 1
        else:
            break
    return h


def find_split_profiles(acd_name, primary_id, primary_orcid=None):
    """
    Search for additional OpenAlex profiles that may belong to the same person.
    Returns list of (id, works_count, orcid) tuples for all matching profiles.
    """
    # Extract last name for search
    parts = acd_name.strip().split()
    # Remove titles
    titles = {'Dr', 'Prof', 'A/Prof', 'Adj', 'Mr', 'Mrs', 'Ms', 'Miss', 'Sir'}
    parts = [p for p in parts if p not in titles]
    if not parts:
        return []
    
    last_name = parts[-1]
    first_name = parts[0] if len(parts) > 1 else ''
    
    # Search by name
    query = f"{first_name} {last_name}".strip()
    data = oa_get("https://api.openalex.org/authors",
        params={
            "search": query,
            "per-page": 10,
            "select": "id,display_name,last_known_institutions,works_count,h_index,orcid,affiliations"
        })
    
    if not data:
        return []
    
    candidates = []
    for a in data.get('results', []):
        aid = a['id'].replace('https://openalex.org/', '')
        if aid == primary_id:
            continue  # Skip the primary (already matched)
        
        # Check if this candidate has AU/NZ affiliation
        all_affs = a.get('affiliations') or []
        au_nz = any(
            (aff.get('institution') or {}).get('country_code') in ('AU', 'NZ')
            for aff in all_affs
        )
        if not au_nz:
            # Also check last_known_institutions
            lk = a.get('last_known_institutions') or []
            au_nz = any(i.get('country_code') in ('AU', 'NZ') for i in lk)
        
        if not au_nz:
            continue
        
        # Check name similarity - last name must match
        display = a.get('display_name', '').lower()
        if last_name.lower() not in display:
            continue
        
        # Check first name initial match
        if first_name:
            first_initial = first_name[0].lower()
            display_parts = display.split()
            if display_parts and not any(p.startswith(first_initial) for p in display_parts):
                continue
        
        candidates.append({
            'id': aid,
            'display_name': a.get('display_name'),
            'works_count': a.get('works_count', 0),
            'h_index': a.get('h_index'),
            'orcid': a.get('orcid'),
            'au_nz': au_nz
        })
    
    return candidates


def aggregate_profiles(primary_id, split_ids):
    """
    Fetch all works from primary + split IDs, deduplicate by DOI/title,
    and compute aggregated metrics.
    """
    log.info(f"  Aggregating {primary_id} + {split_ids}")
    all_works = {}
    
    for aid in [primary_id] + split_ids:
        works = get_all_works_for_author(aid)
        log.info(f"    {aid}: {len(works)} works fetched")
        for w in works:
            # Deduplicate by DOI first, then by title
            key = w.get('doi') or w.get('title', '').lower()[:80]
            if key and key not in all_works:
                all_works[key] = w
        time.sleep(0.5)
    
    deduplicated = list(all_works.values())
    citations = [w.get('cited_by_count', 0) for w in deduplicated]
    h = compute_h_index(citations)
    total_citations = sum(citations)
    
    return {
        'works_count': len(deduplicated),
        'h_index': h,
        'total_citations': total_citations,
        'split_ids': split_ids,
        'all_ids': [primary_id] + split_ids
    }


def main():
    resolved = pd.read_csv(RESOLVED)
    accepted = resolved[resolved['accepted'] == 1].copy()
    
    log.info(f"Checking {len(accepted)} accepted members for split profiles...")
    
    split_results = []
    
    for idx, row in accepted.iterrows():
        acd_name = row['acd_name']
        primary_id = str(row['openalex_id']) if pd.notna(row['openalex_id']) else None
        
        if not primary_id or primary_id == 'nan':
            continue
        
        # Strip the URL prefix if present
        primary_id = primary_id.replace('https://openalex.org/', '')
        
        # Search for split profiles
        candidates = find_split_profiles(acd_name, primary_id)
        
        if candidates:
            log.info(f"  SPLIT CANDIDATES for {acd_name}: {[c['id'] for c in candidates]}")
            split_results.append({
                'acd_name': acd_name,
                'primary_id': primary_id,
                'primary_works': row['works_count'],
                'candidates': json.dumps(candidates)
            })
        
        time.sleep(0.2)
    
    log.info(f"\nFound {len(split_results)} members with potential split profiles")
    
    if split_results:
        df = pd.DataFrame(split_results)
        out = BASE / 'data/processed/split_profile_candidates.csv'
        df.to_csv(out, index=False)
        log.info(f"Saved to {out}")
        
        for r in split_results:
            log.info(f"\n  {r['acd_name']} (primary={r['primary_id']}, works={r['primary_works']})")
            for c in json.loads(r['candidates']):
                log.info(f"    Candidate: {c['id']} | {c['display_name']} | works={c['works_count']} h={c['h_index']} orcid={c.get('orcid')}")
    
    # Now handle Diona Damian specifically as the confirmed case
    log.info("\n=== Aggregating Diona Damian (confirmed split) ===")
    primary = 'A5109680281'   # 59 works, no ORCID
    split   = ['A5040089794'] # 47 works, ORCID 0000-0002-2857-1775
    
    agg = aggregate_profiles(primary, split)
    log.info(f"Aggregated: works={agg['works_count']}, h={agg['h_index']}, citations={agg['total_citations']}")
    
    # Update resolved CSV with aggregated stats
    mask = (resolved['acd_name'] == 'Dr Diona Lee Damian') & (resolved['accepted'] == 1)
    if mask.sum() > 0:
        resolved.loc[mask, 'works_count'] = agg['works_count']
        resolved.loc[mask, 'h_index'] = agg['h_index']
        resolved.loc[mask, 'total_citations'] = agg['total_citations']
        resolved.loc[mask, 'split_ids'] = json.dumps(split)
        resolved.loc[mask, 'notes'] = f"Aggregated from {primary} + {split[0]}"
        resolved.to_csv(RESOLVED, index=False)
        log.info("Updated resolved CSV")
    
    # Rebuild stats
    accepted2 = resolved[resolved['accepted'] == 1].copy()
    stats_cols = [c for c in [
        'acd_name','openalex_id','openalex_display_name',
        'last_known_institution','institution_country',
        'works_count','h_index','total_citations','aunz_ever',
        'confidence','resolution_method','split_ids'
    ] if c in resolved.columns]
    accepted2[stats_cols].to_csv(STATS, index=False)
    log.info(f"Stats rebuilt: {len(accepted2)} rows")
    
    # Verify Diona Damian
    dd = accepted2[accepted2['acd_name'] == 'Dr Diona Lee Damian']
    log.info(f"\nDiona Damian final: works={dd['works_count'].values[0]}, h={dd['h_index'].values[0]}, citations={dd.get('total_citations', pd.Series([None])).values[0] if 'total_citations' in dd.columns else 'N/A'}")


if __name__ == '__main__':
    main()
