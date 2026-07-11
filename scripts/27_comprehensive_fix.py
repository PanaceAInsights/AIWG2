"""
Script 27: Comprehensive fix for all identified issues.

1. Fetch h_index from OpenAlex for ALL 296 accepted members with h=0
2. Fix Pablo Fernandez-Penas (wrong ID → correct ORCID-based ID)
3. Fix Ozge Gunduz (not matched → match via ORCID)
4. Fix title errors: Deshan Sebaratnam (Prof→A/Prof), Diona Damian (Dr→Prof), Simone Goldinger (Dr→A/Prof, NSW→QLD)
5. Verify Adrian Lim's profile is correct

This script does NOT rebuild stats — it only updates the resolved CSV in place.
"""

import pandas as pd
import requests
import time
import sys

OPENALEX_BASE = "https://api.openalex.org"
HEADERS = {"User-Agent": "mailto:admin@panaceainsights.com.au"}

def fetch_author_data(openalex_id):
    """Fetch h_index, works_count, cited_by_count from OpenAlex author endpoint."""
    url = f"{OPENALEX_BASE}/authors/{openalex_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return {
                'h_index': data.get('summary_stats', {}).get('h_index', 0) or 0,
                'works_count': data.get('works_count', 0),
                'cited_by_count': data.get('cited_by_count', 0),
                'display_name': data.get('display_name', ''),
                'last_known_institution': (data.get('last_known_institutions') or [{}])[0].get('display_name', '') if data.get('last_known_institutions') else '',
                'institution_country': (data.get('last_known_institutions') or [{}])[0].get('country_code', '') if data.get('last_known_institutions') else '',
            }
    except Exception as e:
        print(f"  ERROR fetching {openalex_id}: {e}", flush=True)
    return None

def search_by_orcid(orcid):
    """Search OpenAlex by ORCID."""
    url = f"{OPENALEX_BASE}/authors?filter=orcid:{orcid}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            results = r.json().get('results', [])
            if results:
                return results[0]
    except Exception as e:
        print(f"  ERROR searching ORCID {orcid}: {e}", flush=True)
    return None

def main():
    print("=" * 60, flush=True)
    print("SCRIPT 27: Comprehensive fix", flush=True)
    print("=" * 60, flush=True)
    
    res = pd.read_csv('data/processed/authors_resolved.csv')
    stats = pd.read_csv('data/processed/author_summary_stats.csv')
    
    # ============================================================
    # PART 1: Fix specific people first
    # ============================================================
    
    print("\n--- PART 1: Fix specific people ---", flush=True)
    
    # 1a. Pablo Fernandez-Penas — ORCID: 0000-0003-4882-1564
    print("\n[1a] Pablo Fernandez-Penas...", flush=True)
    pablo_data = search_by_orcid("0000-0003-4882-1564")
    if pablo_data:
        pablo_id = pablo_data['id'].replace('https://openalex.org/', '')
        pablo_h = pablo_data.get('summary_stats', {}).get('h_index', 0)
        pablo_works = pablo_data.get('works_count', 0)
        pablo_inst = (pablo_data.get('last_known_institutions') or [{}])[0].get('display_name', '')
        pablo_cc = (pablo_data.get('last_known_institutions') or [{}])[0].get('country_code', '')
        print(f"  Found: {pablo_id}, h={pablo_h}, works={pablo_works}, inst={pablo_inst} [{pablo_cc}]", flush=True)
        
        idx = res[res['acd_name'].str.contains('Pablo', case=False, na=False)].index
        if len(idx) > 0:
            res.loc[idx[0], 'openalex_id'] = pablo_id
            res.loc[idx[0], 'h_index'] = pablo_h
            res.loc[idx[0], 'works_count'] = pablo_works
            res.loc[idx[0], 'accepted'] = 1
            res.loc[idx[0], 'confidence'] = 'HIGH'
            res.loc[idx[0], 'institution_display_name'] = pablo_inst
            res.loc[idx[0], 'institution_country'] = pablo_cc
            print(f"  ✓ Updated Pablo Fernandez-Penas", flush=True)
    
    # 1b. Ozge Gunduz — ORCID: 0000-0001-8541-9246
    print("\n[1b] Ozge Gunduz...", flush=True)
    ozge_data = search_by_orcid("0000-0001-8541-9246")
    if ozge_data:
        ozge_id = ozge_data['id'].replace('https://openalex.org/', '')
        ozge_h = ozge_data.get('summary_stats', {}).get('h_index', 0)
        ozge_works = ozge_data.get('works_count', 0)
        ozge_inst = (ozge_data.get('last_known_institutions') or [{}])[0].get('display_name', '')
        ozge_cc = (ozge_data.get('last_known_institutions') or [{}])[0].get('country_code', '')
        print(f"  Found: {ozge_id}, h={ozge_h}, works={ozge_works}, inst={ozge_inst} [{ozge_cc}]", flush=True)
        
        # Remove duplicate row if exists
        ozge_idx = res[res['acd_name'].str.contains('Ozge', case=False, na=False)].index
        if len(ozge_idx) > 1:
            res = res.drop(ozge_idx[1:])  # keep first, drop duplicates
            ozge_idx = [ozge_idx[0]]
        
        if len(ozge_idx) > 0:
            res.loc[ozge_idx[0], 'openalex_id'] = ozge_id
            res.loc[ozge_idx[0], 'h_index'] = ozge_h
            res.loc[ozge_idx[0], 'works_count'] = ozge_works
            res.loc[ozge_idx[0], 'accepted'] = 1
            res.loc[ozge_idx[0], 'confidence'] = 'HIGH'
            res.loc[ozge_idx[0], 'institution_display_name'] = ozge_inst
            res.loc[ozge_idx[0], 'institution_country'] = ozge_cc
            print(f"  ✓ Updated Ozge Gunduz", flush=True)
    
    # 1c. Pascale Guitera — ORCID: 0000-0001-9519-110X
    print("\n[1c] Pascale Guitera (verify correct ID)...", flush=True)
    pascale_data = search_by_orcid("0000-0001-9519-110X")
    if pascale_data:
        pascale_id = pascale_data['id'].replace('https://openalex.org/', '')
        pascale_h = pascale_data.get('summary_stats', {}).get('h_index', 0)
        pascale_works = pascale_data.get('works_count', 0)
        print(f"  Found via ORCID: {pascale_id}, h={pascale_h}, works={pascale_works}", flush=True)
        
        idx = res[res['acd_name'].str.contains('Pascale', case=False, na=False)].index
        if len(idx) > 0:
            res.loc[idx[0], 'openalex_id'] = pascale_id
            res.loc[idx[0], 'h_index'] = pascale_h
            res.loc[idx[0], 'works_count'] = pascale_works
            print(f"  ✓ Updated Pascale Guitera", flush=True)
    
    # 1d. Cathy Zhao — ORCID: 0000-0003-4722-9673
    print("\n[1d] Cathy Zhao (verify correct ID)...", flush=True)
    cathy_data = search_by_orcid("0000-0003-4722-9673")
    if cathy_data:
        cathy_id = cathy_data['id'].replace('https://openalex.org/', '')
        cathy_h = cathy_data.get('summary_stats', {}).get('h_index', 0)
        cathy_works = cathy_data.get('works_count', 0)
        print(f"  Found via ORCID: {cathy_id}, h={cathy_h}, works={cathy_works}", flush=True)
        
        idx = res[res['acd_name'].str.contains('Cathy', case=False, na=False)].index
        if len(idx) > 0:
            res.loc[idx[0], 'openalex_id'] = cathy_id
            res.loc[idx[0], 'h_index'] = cathy_h
            res.loc[idx[0], 'works_count'] = cathy_works
            print(f"  ✓ Updated Cathy Zhao", flush=True)
    
    # ============================================================
    # PART 2: Fix titles
    # ============================================================
    
    print("\n--- PART 2: Fix titles ---", flush=True)
    
    # Deshan Sebaratnam: Prof → A/Prof
    idx = res[res['acd_name'].str.contains('Deshan', case=False, na=False)].index
    if len(idx) > 0:
        old_name = res.loc[idx[0], 'acd_name']
        new_name = old_name.replace('Prof ', 'A/Prof ', 1)
        res.loc[idx[0], 'acd_name'] = new_name
        print(f"  ✓ {old_name} → {new_name}", flush=True)
    
    # Diona Damian: Dr → Prof
    idx = res[res['acd_name'].str.contains('Diona', case=False, na=False)].index
    if len(idx) > 0:
        old_name = res.loc[idx[0], 'acd_name']
        new_name = old_name.replace('Dr ', 'Prof ', 1)
        res.loc[idx[0], 'acd_name'] = new_name
        print(f"  ✓ {old_name} → {new_name}", flush=True)
    
    # Simone Goldinger: Dr → A/Prof, and fix state to QLD
    idx = res[res['acd_name'].str.contains('Goldinger', case=False, na=False)].index
    if len(idx) > 0:
        old_name = res.loc[idx[0], 'acd_name']
        new_name = old_name.replace('Dr ', 'A/Prof ', 1)
        res.loc[idx[0], 'acd_name'] = new_name
        # Fix state if there's a state column
        if 'state' in res.columns:
            res.loc[idx[0], 'state'] = 'QLD'
        print(f"  ✓ {old_name} → {new_name} (state → QLD)", flush=True)
    
    # ============================================================
    # PART 3: Fetch h_index for ALL accepted members with h=0
    # ============================================================
    
    print("\n--- PART 3: Fetch h_index for all accepted with h=0 ---", flush=True)
    
    accepted_h0 = res[(res['accepted']==1) & ((res['h_index']==0) | (res['h_index'].isna()))]
    accepted_h0_with_id = accepted_h0[accepted_h0['openalex_id'].notna() & (accepted_h0['openalex_id'] != '')]
    
    print(f"  Total accepted with h=0: {len(accepted_h0)}", flush=True)
    print(f"  Of those with valid OpenAlex ID: {len(accepted_h0_with_id)}", flush=True)
    
    updated_count = 0
    failed_count = 0
    
    for i, (idx, row) in enumerate(accepted_h0_with_id.iterrows()):
        oa_id = row['openalex_id']
        if pd.isna(oa_id) or oa_id == '':
            continue
            
        data = fetch_author_data(oa_id)
        if data and data['h_index'] > 0:
            res.loc[idx, 'h_index'] = data['h_index']
            # Also update works_count if OpenAlex has more
            if data['works_count'] > (row['works_count'] or 0):
                res.loc[idx, 'works_count'] = data['works_count']
            updated_count += 1
            if updated_count <= 20 or updated_count % 50 == 0:
                print(f"  [{i+1}/{len(accepted_h0_with_id)}] {row['acd_name']}: h={data['h_index']}, works={data['works_count']}", flush=True)
        elif data and data['h_index'] == 0:
            # OpenAlex genuinely has h=0 for this person (very few works)
            pass
        else:
            failed_count += 1
            if failed_count <= 5:
                print(f"  FAILED: {row['acd_name']} ({oa_id})", flush=True)
        
        time.sleep(0.1)  # Rate limiting
        
        # Progress every 50
        if (i+1) % 50 == 0:
            print(f"  Progress: {i+1}/{len(accepted_h0_with_id)}, updated={updated_count}, failed={failed_count}", flush=True)
    
    print(f"\n  DONE: Updated {updated_count} h-indexes, {failed_count} failed API calls", flush=True)
    
    # ============================================================
    # PART 4: Also update the stats CSV
    # ============================================================
    
    print("\n--- PART 4: Update stats CSV ---", flush=True)
    
    # Update stats to match resolved
    # Only update h_index in stats for members whose h changed
    for idx, row in res[res['accepted']==1].iterrows():
        name = row['acd_name']
        h = row['h_index']
        works = row['works_count']
        
        stats_idx = stats[stats['acd_name'] == name].index
        if len(stats_idx) > 0:
            if h > 0:
                stats.loc[stats_idx[0], 'h_index'] = h
            if works > 0:
                stats.loc[stats_idx[0], 'works_count'] = works
                if 'pub_count' in stats.columns:
                    # Only update pub_count if it was 0 or NaN
                    if pd.isna(stats.loc[stats_idx[0], 'pub_count']) or stats.loc[stats_idx[0], 'pub_count'] == 0:
                        stats.loc[stats_idx[0], 'pub_count'] = works
        else:
            # Add new row to stats for newly accepted members
            new_row = {'acd_name': name, 'h_index': h, 'works_count': works}
            if 'pub_count' in stats.columns:
                new_row['pub_count'] = works
            stats = pd.concat([stats, pd.DataFrame([new_row])], ignore_index=True)
    
    # Also update stats for title changes
    old_names = {
        'Prof Deshan Sebaratnam': 'A/Prof Deshan Sebaratnam',
        'Dr Diona Lee Damian': 'Prof Diona Lee Damian',
        'Dr Simone Goldinger': 'A/Prof Simone Goldinger',
    }
    for old, new in old_names.items():
        sidx = stats[stats['acd_name'] == old].index
        if len(sidx) > 0:
            stats.loc[sidx[0], 'acd_name'] = new
            print(f"  Stats: {old} → {new}", flush=True)
    
    # ============================================================
    # PART 5: Save
    # ============================================================
    
    print("\n--- PART 5: Save ---", flush=True)
    res.to_csv('data/processed/authors_resolved.csv', index=False)
    stats.to_csv('data/processed/author_summary_stats.csv', index=False)
    
    # Final summary
    accepted = res[res['accepted']==1]
    h_nonzero = accepted[accepted['h_index'] > 0]
    print(f"\n  Total accepted: {len(accepted)}", flush=True)
    print(f"  With h_index > 0: {len(h_nonzero)}", flush=True)
    print(f"  Still h=0: {len(accepted) - len(h_nonzero)}", flush=True)
    print("\n✓ DONE", flush=True)

if __name__ == '__main__':
    main()
