"""
Script 27b: Reliable comprehensive fix with retry logic and intermediate saves.

Fixes:
1. Pablo Fernandez-Penas (ORCID-based resolution)
2. Ozge Gunduz (ORCID-based resolution)
3. Pascale Guitera (ORCID-based resolution)
4. Cathy Zhao (verify h-index)
5. Title fixes: Deshan (Prof→A/Prof), Diona (Dr→Prof), Simone (Dr→A/Prof, NSW→QLD)
6. Fetch h_index for ALL accepted members with h=0 (with retry + exponential backoff)
7. Update stats CSV to match
"""

import pandas as pd
import requests
import time
import sys
import os

OPENALEX_BASE = "https://api.openalex.org"
HEADERS = {"User-Agent": "mailto:admin@panaceainsights.com.au"}

os.chdir('/home/ubuntu/acd-dashboard')

def fetch_author_data(openalex_id, max_retries=3, base_timeout=30):
    """Fetch h_index, works_count, cited_by_count from OpenAlex with retry logic."""
    url = f"{OPENALEX_BASE}/authors/{openalex_id}"
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=base_timeout)
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
            elif r.status_code == 429:
                # Rate limited - wait longer
                wait_time = 5 * (attempt + 1)
                print(f"  Rate limited, waiting {wait_time}s...", flush=True)
                time.sleep(wait_time)
            else:
                print(f"  HTTP {r.status_code} for {openalex_id}", flush=True)
                return None
        except requests.exceptions.Timeout:
            wait_time = 5 * (attempt + 1)
            print(f"  Timeout (attempt {attempt+1}/{max_retries}) for {openalex_id}, waiting {wait_time}s...", flush=True)
            time.sleep(wait_time)
        except Exception as e:
            print(f"  ERROR fetching {openalex_id}: {e}", flush=True)
            if attempt < max_retries - 1:
                time.sleep(3)
            else:
                return None
    return None


def search_by_orcid(orcid, max_retries=3):
    """Search OpenAlex by ORCID with retry."""
    url = f"{OPENALEX_BASE}/authors?filter=orcid:{orcid}"
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                results = r.json().get('results', [])
                if results:
                    return results[0]
                return None
        except Exception as e:
            print(f"  ERROR searching ORCID {orcid} (attempt {attempt+1}): {e}", flush=True)
            time.sleep(5 * (attempt + 1))
    return None


def main():
    print("=" * 60, flush=True)
    print("SCRIPT 27b: Reliable comprehensive fix", flush=True)
    print("=" * 60, flush=True)

    res = pd.read_csv('data/processed/authors_resolved.csv')
    stats = pd.read_csv('data/processed/author_summary_stats.csv')

    # ============================================================
    # PART 1: Fix specific people via ORCID
    # ============================================================

    print("\n--- PART 1: Fix specific people via ORCID ---", flush=True)

    # 1a. Pablo Fernandez-Penas — ORCID: 0000-0003-4882-1564
    print("\n[1a] Pablo Fernandez-Penas...", flush=True)
    pablo_data = search_by_orcid("0000-0003-4882-1564")
    if pablo_data:
        pablo_id = pablo_data['id'].replace('https://openalex.org/', '')
        pablo_h = pablo_data.get('summary_stats', {}).get('h_index', 0)
        pablo_works = pablo_data.get('works_count', 0)
        pablo_inst = (pablo_data.get('last_known_institutions') or [{}])[0].get('display_name', '') if pablo_data.get('last_known_institutions') else ''
        pablo_cc = (pablo_data.get('last_known_institutions') or [{}])[0].get('country_code', '') if pablo_data.get('last_known_institutions') else ''
        print(f"  Found: {pablo_id}, h={pablo_h}, works={pablo_works}, inst={pablo_inst} [{pablo_cc}]", flush=True)

        idx = res[res['acd_name'].str.contains('Pablo', case=False, na=False)].index
        if len(idx) > 0:
            res.loc[idx[0], 'openalex_id'] = pablo_id
            res.loc[idx[0], 'h_index'] = pablo_h
            res.loc[idx[0], 'works_count'] = pablo_works
            res.loc[idx[0], 'accepted'] = 1
            res.loc[idx[0], 'confidence'] = 'HIGH'
            res.loc[idx[0], 'institution_display_name'] = pablo_inst if 'institution_display_name' in res.columns else None
            if 'last_known_institution' in res.columns:
                res.loc[idx[0], 'last_known_institution'] = pablo_inst
            res.loc[idx[0], 'institution_country'] = pablo_cc
            print(f"  ✓ Updated Pablo Fernandez-Penas", flush=True)
    else:
        print("  ✗ Could not find Pablo via ORCID", flush=True)

    time.sleep(0.5)

    # 1b. Ozge Gunduz — ORCID: 0000-0001-8541-9246
    print("\n[1b] Ozge Gunduz...", flush=True)
    ozge_data = search_by_orcid("0000-0001-8541-9246")
    if ozge_data:
        ozge_id = ozge_data['id'].replace('https://openalex.org/', '')
        ozge_h = ozge_data.get('summary_stats', {}).get('h_index', 0)
        ozge_works = ozge_data.get('works_count', 0)
        ozge_inst = (ozge_data.get('last_known_institutions') or [{}])[0].get('display_name', '') if ozge_data.get('last_known_institutions') else ''
        ozge_cc = (ozge_data.get('last_known_institutions') or [{}])[0].get('country_code', '') if ozge_data.get('last_known_institutions') else ''
        print(f"  Found: {ozge_id}, h={ozge_h}, works={ozge_works}, inst={ozge_inst} [{ozge_cc}]", flush=True)

        ozge_idx = res[res['acd_name'].str.contains('Ozge', case=False, na=False)].index
        if len(ozge_idx) > 0:
            res.loc[ozge_idx[0], 'openalex_id'] = ozge_id
            res.loc[ozge_idx[0], 'h_index'] = ozge_h
            res.loc[ozge_idx[0], 'works_count'] = ozge_works
            res.loc[ozge_idx[0], 'accepted'] = 1
            res.loc[ozge_idx[0], 'confidence'] = 'HIGH'
            if 'last_known_institution' in res.columns:
                res.loc[ozge_idx[0], 'last_known_institution'] = ozge_inst
            res.loc[ozge_idx[0], 'institution_country'] = ozge_cc
            print(f"  ✓ Updated Ozge Gunduz", flush=True)
    else:
        print("  ✗ Could not find Ozge via ORCID", flush=True)

    time.sleep(0.5)

    # 1c. Pascale Guitera — ORCID: 0000-0001-9519-110X
    print("\n[1c] Pascale Guitera...", flush=True)
    pascale_data = search_by_orcid("0000-0001-9519-110X")
    if pascale_data:
        pascale_id = pascale_data['id'].replace('https://openalex.org/', '')
        pascale_h = pascale_data.get('summary_stats', {}).get('h_index', 0)
        pascale_works = pascale_data.get('works_count', 0)
        pascale_inst = (pascale_data.get('last_known_institutions') or [{}])[0].get('display_name', '') if pascale_data.get('last_known_institutions') else ''
        print(f"  Found via ORCID: {pascale_id}, h={pascale_h}, works={pascale_works}, inst={pascale_inst}", flush=True)

        idx = res[res['acd_name'].str.contains('Pascale', case=False, na=False)].index
        if len(idx) > 0:
            res.loc[idx[0], 'openalex_id'] = pascale_id
            res.loc[idx[0], 'h_index'] = pascale_h
            res.loc[idx[0], 'works_count'] = pascale_works
            res.loc[idx[0], 'accepted'] = 1
            res.loc[idx[0], 'confidence'] = 'HIGH'
            if 'last_known_institution' in res.columns:
                res.loc[idx[0], 'last_known_institution'] = pascale_inst
            print(f"  ✓ Updated Pascale Guitera", flush=True)
    else:
        print("  ✗ Could not find Pascale via ORCID", flush=True)

    time.sleep(0.5)

    # 1d. Cathy Zhao — ORCID: 0000-0003-4722-9673
    print("\n[1d] Cathy Zhao...", flush=True)
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
    else:
        print("  ✗ Could not find Cathy via ORCID", flush=True)

    time.sleep(0.5)

    # ============================================================
    # PART 2: Fix titles
    # ============================================================

    print("\n--- PART 2: Fix titles ---", flush=True)

    # Deshan Sebaratnam: Prof → A/Prof
    idx = res[res['acd_name'].str.contains('Deshan', case=False, na=False)].index
    if len(idx) > 0:
        old_name = res.loc[idx[0], 'acd_name']
        if old_name.startswith('Prof '):
            new_name = 'A/Prof ' + old_name[5:]
            res.loc[idx[0], 'acd_name'] = new_name
            print(f"  ✓ {old_name} → {new_name}", flush=True)
        else:
            print(f"  Deshan already has correct title: {old_name}", flush=True)

    # Diona Damian: Dr → Prof
    idx = res[res['acd_name'].str.contains('Diona', case=False, na=False)].index
    if len(idx) > 0:
        old_name = res.loc[idx[0], 'acd_name']
        if old_name.startswith('Dr '):
            new_name = 'Prof ' + old_name[3:]
            res.loc[idx[0], 'acd_name'] = new_name
            print(f"  ✓ {old_name} → {new_name}", flush=True)
        else:
            print(f"  Diona already has correct title: {old_name}", flush=True)

    # Simone Goldinger: Dr → A/Prof, state → QLD
    idx = res[res['acd_name'].str.contains('Goldinger', case=False, na=False)].index
    if len(idx) > 0:
        old_name = res.loc[idx[0], 'acd_name']
        if old_name.startswith('Dr '):
            new_name = 'A/Prof ' + old_name[3:]
            res.loc[idx[0], 'acd_name'] = new_name
            print(f"  ✓ {old_name} → {new_name}", flush=True)
        else:
            print(f"  Simone already has correct title: {old_name}", flush=True)
        if 'state' in res.columns:
            res.loc[idx[0], 'state'] = 'QLD'
            print(f"  ✓ Simone state → QLD", flush=True)

    # ============================================================
    # PART 2b: Save intermediate (specific fixes done)
    # ============================================================
    print("\n--- Saving intermediate (Parts 1-2 done) ---", flush=True)
    res.to_csv('data/processed/authors_resolved.csv', index=False)
    print("  ✓ Saved authors_resolved.csv (Parts 1-2)", flush=True)

    # ============================================================
    # PART 3: Fetch h_index for ALL accepted members with h=0
    # ============================================================

    print("\n--- PART 3: Fetch h_index for all accepted with h=0 ---", flush=True)

    # Re-read to be safe (we just saved)
    res = pd.read_csv('data/processed/authors_resolved.csv')

    accepted_h0 = res[(res['accepted'] == 1) & ((res['h_index'] == 0) | (res['h_index'].isna()))]
    accepted_h0_with_id = accepted_h0[accepted_h0['openalex_id'].notna() & (accepted_h0['openalex_id'] != '')]

    print(f"  Total accepted with h=0: {len(accepted_h0)}", flush=True)
    print(f"  Of those with valid OpenAlex ID: {len(accepted_h0_with_id)}", flush=True)

    updated_count = 0
    failed_count = 0
    batch_size = 50

    for i, (idx, row) in enumerate(accepted_h0_with_id.iterrows()):
        oa_id = row['openalex_id']
        if pd.isna(oa_id) or oa_id == '':
            continue

        data = fetch_author_data(oa_id)
        if data:
            if data['h_index'] > 0:
                res.loc[idx, 'h_index'] = data['h_index']
                updated_count += 1
            # Always update works_count if OpenAlex has more
            if data['works_count'] > (row['works_count'] or 0):
                res.loc[idx, 'works_count'] = data['works_count']
            if updated_count <= 20 or updated_count % 50 == 0:
                if data['h_index'] > 0:
                    print(f"  [{i+1}/{len(accepted_h0_with_id)}] {row['acd_name']}: h={data['h_index']}, works={data['works_count']}", flush=True)
        else:
            failed_count += 1
            if failed_count <= 10:
                print(f"  FAILED: {row['acd_name']} ({oa_id})", flush=True)

        # Rate limiting - 0.2s between calls
        time.sleep(0.2)

        # Save intermediate every batch_size members
        if (i + 1) % batch_size == 0:
            print(f"  Progress: {i+1}/{len(accepted_h0_with_id)}, updated={updated_count}, failed={failed_count}", flush=True)
            res.to_csv('data/processed/authors_resolved.csv', index=False)
            print(f"  ✓ Intermediate save at {i+1}", flush=True)

    # Final save for Part 3
    res.to_csv('data/processed/authors_resolved.csv', index=False)
    print(f"\n  DONE Part 3: Updated {updated_count} h-indexes, {failed_count} failed API calls", flush=True)

    # ============================================================
    # PART 4: Update stats CSV
    # ============================================================

    print("\n--- PART 4: Update stats CSV ---", flush=True)

    # Re-read resolved (just saved)
    res = pd.read_csv('data/processed/authors_resolved.csv')

    # Update stats to match resolved
    for idx, row in res[res['accepted'] == 1].iterrows():
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
                    current_pub = stats.loc[stats_idx[0], 'pub_count']
                    if pd.isna(current_pub) or current_pub == 0:
                        stats.loc[stats_idx[0], 'pub_count'] = works
        else:
            # Add new row to stats for newly accepted members
            new_row = {'acd_name': name, 'h_index': h, 'works_count': works}
            if 'pub_count' in stats.columns:
                new_row['pub_count'] = works
            stats = pd.concat([stats, pd.DataFrame([new_row])], ignore_index=True)

    # Update stats for title changes (old name → new name)
    title_changes = {
        'Prof Deshan Sebaratnam': 'A/Prof Deshan Sebaratnam',
        'Dr Diona Lee Damian': 'Prof Diona Lee Damian',
        'Dr Simone Goldinger': 'A/Prof Simone Goldinger',
    }
    for old, new in title_changes.items():
        sidx = stats[stats['acd_name'] == old].index
        if len(sidx) > 0:
            stats.loc[sidx[0], 'acd_name'] = new
            print(f"  Stats title: {old} → {new}", flush=True)
        else:
            # Maybe already changed or partial match
            partial = stats[stats['acd_name'].str.contains(old.split()[-1], case=False, na=False)]
            if len(partial) > 0:
                print(f"  Stats: '{old}' not found, but found: {partial['acd_name'].tolist()}", flush=True)

    stats.to_csv('data/processed/author_summary_stats.csv', index=False)
    print("  ✓ Saved author_summary_stats.csv", flush=True)

    # ============================================================
    # PART 5: Final summary
    # ============================================================

    print("\n--- PART 5: Final summary ---", flush=True)
    res = pd.read_csv('data/processed/authors_resolved.csv')
    accepted = res[res['accepted'] == 1]
    h_nonzero = accepted[accepted['h_index'] > 0]
    print(f"  Total accepted: {len(accepted)}", flush=True)
    print(f"  With h_index > 0: {len(h_nonzero)}", flush=True)
    print(f"  Still h=0: {len(accepted) - len(h_nonzero)}", flush=True)

    # Verify key people
    print("\n  Key profiles:", flush=True)
    for name in ['Pablo', 'Pascale', 'Ozge', 'Cathy', 'Diona', 'Adrian.*Lim', 'Deshan', 'Goldinger']:
        match = res[res['acd_name'].str.contains(name, case=False, na=False)]
        if len(match) > 0:
            row = match.iloc[0]
            print(f"    {row['acd_name']}: h={row['h_index']}, works={row['works_count']}, id={row['openalex_id']}", flush=True)

    print("\n✓ ALL DONE", flush=True)


if __name__ == '__main__':
    main()
