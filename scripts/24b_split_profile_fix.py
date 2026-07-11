"""
Script 24b: Split-Profile Fix

Approach:
1. Immediately aggregate Diona Damian (confirmed split: A5109680281 + A5040089794)
2. Identify other high-risk split candidates using heuristics (no ORCID, works < 30,
   but Scopus-style name variants likely) — check only those via OpenAlex
3. For each confirmed split, aggregate works, deduplicate by DOI, recompute h-index

The key insight: rather than scanning all 381 members, we use the resolved CSV's
own data to identify candidates where the works_count seems low relative to the
member's seniority (Prof/A/Prof with < 20 works is suspicious).
"""

import requests, pandas as pd, json, time, logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

BASE = Path(__file__).parent.parent
RESOLVED = BASE / 'data/processed/authors_resolved.csv'
STATS    = BASE / 'data/processed/author_summary_stats.csv'
HEADERS  = {"User-Agent": "ACD-Dashboard/2.0 (panaceainsights.com.au)"}


def oa_get(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                time.sleep(5 * (attempt + 1))
        except Exception as e:
            log.warning(f"Request error: {e}")
            time.sleep(2)
    return None


def get_works(author_id):
    """Fetch all works for an author, return list of {doi, title, cited_by_count}."""
    works = {}
    cursor = '*'
    while True:
        data = oa_get("https://api.openalex.org/works", params={
            "filter": f"authorships.author.id:{author_id}",
            "select": "id,doi,title,publication_year,cited_by_count",
            "per-page": 200, "cursor": cursor
        })
        if not data:
            break
        batch = data.get('results', [])
        for w in batch:
            key = (w.get('doi') or '').strip() or w.get('title', '').lower()[:100]
            if key:
                works[key] = w.get('cited_by_count', 0)
        meta = data.get('meta', {})
        cursor = meta.get('next_cursor')
        if not cursor or not batch:
            break
        time.sleep(0.15)
    return works


def compute_h(cited_counts):
    s = sorted(cited_counts, reverse=True)
    h = 0
    for i, c in enumerate(s):
        if c >= i + 1:
            h = i + 1
        else:
            break
    return h


def find_same_person_profiles(acd_name, primary_id):
    """
    Search OpenAlex for other profiles with the same name and AU/NZ affiliation.
    Uses the author search endpoint with name query.
    """
    parts = acd_name.strip().split()
    titles = {'Dr','Prof','A/Prof','Adj','Mr','Mrs','Ms','Miss','Sir','Emeritus'}
    parts = [p for p in parts if p not in titles]
    if len(parts) < 2:
        return []
    
    # Try "Firstname Lastname" search
    first, last = parts[0], parts[-1]
    query = f"{first} {last}"
    
    data = oa_get("https://api.openalex.org/authors", params={
        "search": query, "per-page": 10,
        "select": "id,display_name,last_known_institutions,works_count,h_index,orcid,affiliations"
    })
    if not data:
        return []
    
    matches = []
    for a in data.get('results', []):
        aid = a['id'].replace('https://openalex.org/', '')
        if aid == primary_id:
            continue
        
        # Must share last name
        if last.lower() not in a.get('display_name', '').lower():
            continue
        
        # Must have AU/NZ affiliation somewhere
        affs = a.get('affiliations') or []
        lk   = a.get('last_known_institutions') or []
        au = (any((af.get('institution') or {}).get('country_code') in ('AU','NZ') for af in affs)
              or any(i.get('country_code') in ('AU','NZ') for i in lk))
        if not au:
            continue
        
        matches.append({
            'id': aid,
            'display_name': a.get('display_name'),
            'works_count': a.get('works_count', 0),
            'orcid': a.get('orcid', '')
        })
    return matches


def aggregate_and_update(resolved, acd_name, primary_id, split_ids):
    """Aggregate works from primary + split IDs and update the resolved dataframe."""
    log.info(f"  Aggregating {acd_name}: {primary_id} + {split_ids}")
    
    all_works = {}
    for aid in [primary_id] + split_ids:
        w = get_works(aid)
        log.info(f"    {aid}: {len(w)} unique works")
        all_works.update(w)  # DOI/title deduplication via dict merge
        time.sleep(0.5)
    
    citations = list(all_works.values())
    h = compute_h(citations)
    total_cites = sum(citations)
    n_works = len(citations)
    
    log.info(f"  Aggregated: works={n_works}, h={h}, citations={total_cites}")
    
    mask = (resolved['acd_name'] == acd_name) & (resolved['accepted'] == 1)
    if mask.sum() > 0:
        resolved.loc[mask, 'works_count']     = n_works
        resolved.loc[mask, 'h_index']         = h
        resolved.loc[mask, 'total_citations']  = total_cites
        resolved.loc[mask, 'split_ids']        = json.dumps(split_ids)
        resolved.loc[mask, 'notes']            = (
            f"Aggregated from {primary_id} + {','.join(split_ids)}"
        )
        log.info(f"  Updated resolved CSV for {acd_name}")
    else:
        log.warning(f"  Could not find {acd_name} in resolved CSV")
    
    return resolved


def main():
    resolved = pd.read_csv(RESOLVED)
    
    # Ensure split_ids column exists
    if 'split_ids' not in resolved.columns:
        resolved['split_ids'] = ''
    if 'total_citations' not in resolved.columns:
        resolved['total_citations'] = pd.NA

    # ── Step 1: Fix Diona Damian (confirmed split) ──────────────────────────
    log.info("=== Step 1: Aggregating Diona Damian (confirmed split) ===")
    resolved = aggregate_and_update(
        resolved,
        acd_name   = 'Dr Diona Lee Damian',
        primary_id = 'A5109680281',   # 59 works, no ORCID
        split_ids  = ['A5040089794']  # 47 works, ORCID 0000-0002-2857-1775
    )

    # ── Step 2: Scan high-risk members for additional splits ─────────────────
    # High-risk = Prof/A/Prof with works_count < 25 (likely under-counted)
    #           + members with no ORCID and works_count < 15
    accepted = resolved[resolved['accepted'] == 1].copy()
    
    # Flag candidates: senior title but low works
    def is_high_risk(row):
        name = str(row.get('acd_name', ''))
        works = row.get('works_count', 0)
        if pd.isna(works):
            works = 0
        is_senior = any(t in name for t in ['Prof ', 'A/Prof '])
        has_orcid = pd.notna(row.get('orcid')) and str(row.get('orcid', '')).startswith('0000')
        already_split = pd.notna(row.get('split_ids')) and str(row.get('split_ids', '')) not in ('', '[]', 'nan')
        if already_split:
            return False
        if is_senior and works < 25:
            return True
        if not has_orcid and works < 10:
            return True
        return False
    
    high_risk = accepted[accepted.apply(is_high_risk, axis=1)]
    log.info(f"\n=== Step 2: Scanning {len(high_risk)} high-risk members for split profiles ===")
    
    split_candidates = []
    for _, row in high_risk.iterrows():
        acd_name   = row['acd_name']
        primary_id = str(row.get('openalex_id', '')).replace('https://openalex.org/', '')
        if not primary_id or primary_id == 'nan':
            continue
        
        candidates = find_same_person_profiles(acd_name, primary_id)
        if candidates:
            log.info(f"  SPLIT CANDIDATE: {acd_name} ({primary_id}, works={row['works_count']})")
            for c in candidates:
                log.info(f"    + {c['id']} | {c['display_name']} | works={c['works_count']} orcid={c['orcid']}")
            split_candidates.append({
                'acd_name': acd_name,
                'primary_id': primary_id,
                'primary_works': row['works_count'],
                'candidates': json.dumps(candidates)
            })
        time.sleep(0.2)
    
    if split_candidates:
        df = pd.DataFrame(split_candidates)
        out = BASE / 'data/processed/split_profile_candidates.csv'
        df.to_csv(out, index=False)
        log.info(f"\nSaved {len(split_candidates)} split candidates to {out}")
        
        # Auto-aggregate cases where there is exactly one candidate
        # and the combined works would be < 200 (safe to auto-merge)
        for sc in split_candidates:
            cands = json.loads(sc['candidates'])
            if len(cands) == 1:
                c = cands[0]
                combined = (sc['primary_works'] or 0) + (c['works_count'] or 0)
                if combined < 200:
                    log.info(f"\n  Auto-aggregating {sc['acd_name']} (combined works ~{combined})")
                    resolved = aggregate_and_update(
                        resolved,
                        acd_name   = sc['acd_name'],
                        primary_id = sc['primary_id'],
                        split_ids  = [c['id']]
                    )
    else:
        log.info("  No additional split profiles found in high-risk set.")
    
    # ── Step 3: Save updated resolved CSV and rebuild stats ──────────────────
    resolved.to_csv(RESOLVED, index=False)
    log.info(f"\nSaved updated resolved CSV: {len(resolved)} rows")
    
    # Rebuild stats from accepted rows
    accepted2 = resolved[resolved['accepted'] == 1].copy()
    stats_cols = [c for c in [
        'acd_name', 'openalex_id', 'openalex_display_name',
        'last_known_institution', 'institution_country',
        'works_count', 'h_index', 'total_citations',
        'aunz_ever', 'confidence', 'resolution_method', 'split_ids'
    ] if c in resolved.columns]
    accepted2[stats_cols].to_csv(STATS, index=False)
    log.info(f"Stats rebuilt: {len(accepted2)} accepted rows")
    
    # Final verification
    dd = accepted2[accepted2['acd_name'] == 'Dr Diona Lee Damian']
    if len(dd) > 0:
        log.info(f"\n✓ Diona Damian: works={dd['works_count'].values[0]}, "
                 f"h={dd['h_index'].values[0]}, "
                 f"citations={dd['total_citations'].values[0] if 'total_citations' in dd.columns else 'N/A'}")
    
    log.info("\nDone.")


if __name__ == '__main__':
    main()
