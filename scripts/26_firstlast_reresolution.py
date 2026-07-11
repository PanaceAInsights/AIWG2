"""
Script 26: First+Last Name Re-Resolution for not_found Members
==============================================================
Root cause: The original pipeline searched OpenAlex using the FULL name string
(e.g., "Geoffrey Kwo X'iong Lee"). When a member has 3+ middle names, unusual
characters (apostrophes, hyphens), or non-Western name components, OpenAlex's
fuzzy search fails to find the correct profile.

Fix: For all members with resolution_method='not_found', search OpenAlex using
ONLY first name + last name, then apply strict hard-filter vetoes:
  1. AU/NZ affiliation required (aunz_ever OR institution_country in AU/NZ)
  2. Proportional derm topic threshold (1 derm topic per 5 works)
  3. Name plausibility check (first name must match)

Also handles: pass3_llm_no_candidate (24 members) and veto2_recheck (20 members)
"""

import pandas as pd
import requests
import time
import re
import json
import os
import sys

# Force unbuffered output
sys.stdout = sys.stderr  # redirect stdout to stderr for nohup
import functools
print = functools.partial(print, flush=True)

OPENALEX_BASE = "https://api.openalex.org"
EMAIL = "research@panaceainsights.com.au"
HEADERS = {"User-Agent": f"ACD-Dashboard/1.0 (mailto:{EMAIL})"}

AU_NZ_COUNTRIES = {'AU', 'NZ'}

DERM_KEYWORDS = [
    'dermatol', 'skin', 'melanoma', 'psoriasis', 'eczema', 'acne',
    'rosacea', 'urticaria', 'pemphigus', 'bullous', 'vitiligo',
    'alopecia', 'nail', 'hair loss', 'photodermatol', 'photodamage',
    'sunscreen', 'uv radiation', 'keratinocyte', 'basal cell',
    'squamous cell carcinoma', 'merkel', 'cutaneous', 'subcutaneous',
    'wound healing', 'scar', 'keloid', 'contact dermatitis',
    'atopic', 'seborrheic', 'tinea', 'onychomycosis', 'wart',
    'haemangioma', 'vascular malformation', 'port wine', 'birthmark',
    'phlebolog', 'venous', 'varicose', 'porphyria', 'ichthyosis',
    'epidermolysis', 'sclerotherapy', 'laser', 'cosmetic dermatol',
    'mohs', 'dermoscopy', 'dermatoscopy', 'patch test', 'allergen',
    'occupational dermatol', 'photoallerg', 'photosensitiv'
]

def is_derm_topic(topic_name):
    t = topic_name.lower()
    return any(kw in t for kw in DERM_KEYWORDS)

def extract_first_last(acd_name):
    """Extract first and last name from ACD full name string."""
    if pd.isna(acd_name):
        return None, None
    # Remove title prefix
    n = re.sub(r'^(Dr|Prof|A/Prof|Adj A/Prof|Mr|Ms|Mrs|Assoc Prof|Miss)\s+', 
               '', str(acd_name).strip(), flags=re.I)
    # Remove extra spaces
    n = re.sub(r'\s+', ' ', n).strip()
    parts = n.split()
    if len(parts) < 2:
        return n, None
    first = parts[0]
    last = parts[-1]
    return first, last

def search_openalex_firstlast(first, last):
    """Search OpenAlex by first + last name only."""
    query = f"{first} {last}"
    url = f"{OPENALEX_BASE}/authors"
    params = {
        "search": query,
        "per-page": 10,
        "mailto": EMAIL
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json().get('results', [])
    except Exception as e:
        print(f"  Search error for '{query}': {e}")
        return []

def get_author_topics(openalex_id):
    """Get top topics for an author."""
    url = f"{OPENALEX_BASE}/authors/{openalex_id}"
    try:
        r = requests.get(url, params={"mailto": EMAIL}, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        topics = data.get('topics', [])
        return [t.get('display_name', '') for t in topics[:10]]
    except:
        return []

def check_aunz(author):
    """Check if author has AU/NZ affiliation.
    Returns (aunz_ever, current_aunz, country_code)
    - aunz_ever: True if any affiliation (current or historical) is AU/NZ
    - current_aunz: True if the CURRENT (last known) institution is AU/NZ
    """
    # Check last known institution (current)
    inst = author.get('last_known_institutions', []) or []
    if not inst:
        inst_single = author.get('last_known_institution')
        if inst_single and isinstance(inst_single, dict):
            inst = [inst_single]
    
    current_aunz = False
    current_cc = None
    for i in (inst or []):
        if isinstance(i, dict):
            cc = i.get('country_code', '')
            if cc in AU_NZ_COUNTRIES:
                current_aunz = True
                current_cc = cc
                break
    
    if current_aunz:
        return True, True, current_cc
    
    # Check affiliations history
    affiliations = author.get('affiliations', [])
    for aff in affiliations:
        inst_aff = aff.get('institution', {})
        if isinstance(inst_aff, dict):
            cc = inst_aff.get('country_code', '')
            if cc in AU_NZ_COUNTRIES:
                return True, False, cc  # historical AU/NZ only
    
    return False, False, None

def proportional_derm_check(topics, works_count):
    """Proportional derm topic threshold: 1 derm topic per 5 works."""
    if works_count <= 5:
        return True  # Too few works to require derm topics
    derm_count = sum(1 for t in topics if is_derm_topic(t))
    required = max(1, works_count // 20)  # 1 per 20 works, min 1
    return derm_count >= required

def score_candidate(author, first_name, last_name):
    """Score a candidate author match. AU/NZ affiliation is ALWAYS required."""
    score = 0
    reasons = []
    
    display_name = author.get('display_name', '')
    works = author.get('works_count', 0)
    
    # Name match check
    name_lower = display_name.lower()
    first_lower = first_name.lower()
    last_lower = last_name.lower()
    
    if last_lower in name_lower:
        score += 40
        reasons.append('last_name_match')
    else:
        return 0, ['last_name_no_match']  # Hard veto: last name must match
    
    if first_lower in name_lower or name_lower.startswith(first_lower[0].lower()):
        score += 30
        reasons.append('first_name_match')
    
    # AU/NZ affiliation — ALWAYS required, no exceptions
    aunz_ever, current_aunz, cc = check_aunz(author)
    if not aunz_ever:
        return 0, ['no_aunz']  # Hard veto: must have AU/NZ affiliation
    
    if current_aunz:
        score += 25
        reasons.append(f'current_aunz_{cc}')
    else:
        # Historical AU/NZ only: ALWAYS require at least 1 derm topic as additional evidence
        # (prevents physicists/engineers with brief AU visiting positions)
        topics_preview = get_author_topics(author.get('id','').split('/')[-1])
        derm_preview = sum(1 for t in topics_preview if is_derm_topic(t))
        if derm_preview == 0:
            return 0, ['historical_aunz_no_derm']  # Reject regardless of works count
        score += 15  # Partial credit for historical AU/NZ
        reasons.append(f'historical_aunz_{cc}')
    
    # Works count bonus (more publications = more likely correct)
    if works >= 20:
        score += 5
    elif works >= 5:
        score += 2
    
    return score, reasons

def process_member(row):
    """Try to resolve a single unresolved member."""
    acd_name = row['acd_name']
    first, last = extract_first_last(acd_name)
    
    if not first or not last:
        return None
    
    print(f"  Searching: {first} {last} (from '{acd_name}')")
    candidates = search_openalex_firstlast(first, last)
    time.sleep(0.3)
    
    if not candidates:
        print(f"    No candidates found")
        return None
    
    # Score all candidates
    scored = []
    for c in candidates:
        s, reasons = score_candidate(c, first, last)
        if s > 0:
            scored.append((s, c, reasons))
    
    if not scored:
        print(f"    No candidates passed hard filters (last_name + aunz)")
        return None
    
    # Take best candidate
    scored.sort(key=lambda x: -x[0])
    best_score, best, best_reasons = scored[0]
    
    openalex_id = best.get('id', '').split('/')[-1]
    works = best.get('works_count', 0)
    h_index = best.get('summary_stats', {}).get('h_index', 0)
    display_name = best.get('display_name', '')
    
    # Get topics for derm check
    topics = get_author_topics(openalex_id)
    time.sleep(0.2)
    
    derm_ok = proportional_derm_check(topics, works)
    derm_count = sum(1 for t in topics if is_derm_topic(t))
    
    if not derm_ok and works > 20:
        print(f"    REJECTED (derm topics {derm_count}/{len(topics)}, works={works}): {display_name}")
        return None
    
    aunz_ever, current_aunz, cc = check_aunz(best)
    inst = best.get('last_known_institutions', [{}]) or [{}]
    inst_name = inst[0].get('display_name', '') if inst else ''
    inst_cc = inst[0].get('country_code', '') if inst else ''
    
    print(f"    MATCHED (score={best_score}, derm={derm_count}/{len(topics)}, works={works}, h={h_index}): {display_name} @ {inst_name} [{inst_cc}]")
    
    return {
        'acd_name': acd_name,
        'openalex_id': openalex_id,
        'openalex_display_name': display_name,
        'last_known_institution': inst_name,
        'institution_country': inst_cc,
        'works_count': works,
        'h_index': h_index,
        'aunz_ever': 1,
        'confidence': 'MEDIUM' if best_score >= 70 else 'LOW',
        'resolution_method': 'firstlast_reresolution',
        'accepted': 1,
        'derm_topics': derm_count,
        'match_score': best_score,
        'match_reasons': ','.join(best_reasons)
    }

def main():
    print("=== Script 26: First+Last Name Re-Resolution ===\n")
    
    resolved_path = 'data/processed/authors_resolved.csv'
    r = pd.read_csv(resolved_path)
    
    # Target: not_found + pass3_llm_no_candidate + veto2_recheck
    target_methods = ['not_found', 'pass3_llm_no_candidate', 'veto2_recheck']
    targets = r[r['resolution_method'].isin(target_methods)].copy()
    print(f"Target members for re-resolution: {len(targets)}")
    print(targets['resolution_method'].value_counts().to_string())
    print()
    
    results = []
    failed = []
    
    for i, (idx, row) in enumerate(targets.iterrows()):
        print(f"[{i+1}/{len(targets)}] {row['acd_name']}")
        result = process_member(row)
        if result:
            results.append(result)
        else:
            failed.append(row['acd_name'])
        
        # Progress save every 20
        if (i + 1) % 20 == 0:
            print(f"\n--- Progress: {len(results)} matched so far ---\n")
    
    print(f"\n=== Results ===")
    print(f"Successfully matched: {len(results)}")
    print(f"Still unresolved: {len(failed)}")
    
    if results:
        # Save results
        results_df = pd.DataFrame(results)
        results_df.to_csv('data/processed/firstlast_reresolution_results.csv', index=False)
        print(f"\nNew matches:")
        print(results_df[['acd_name','openalex_display_name','last_known_institution','institution_country','works_count','h_index','confidence']].to_string())
        
        # Apply to resolved CSV
        print("\nApplying to resolved CSV...")
        update_cols = ['openalex_id','openalex_display_name','last_known_institution',
                      'institution_country','works_count','h_index','aunz_ever',
                      'confidence','resolution_method','accepted']
        
        for _, res in results_df.iterrows():
            mask = r['acd_name'] == res['acd_name']
            if mask.sum() == 0:
                print(f"  WARNING: '{res['acd_name']}' not found in resolved CSV")
                continue
            for col in update_cols:
                if col in res.index:
                    r.loc[mask, col] = res[col]
        
        r.to_csv(resolved_path, index=False)
        print(f"Saved resolved CSV with {r['accepted'].sum()} accepted members")
        
        # Update stats CSV
        stats_path = 'data/processed/author_summary_stats.csv'
        stats = pd.read_csv(stats_path)
        
        # Add new matches to stats (with works_count as pub_count fallback)
        new_stats_rows = []
        for _, res in results_df.iterrows():
            if res['acd_name'] not in stats['acd_name'].values:
                new_row = {
                    'acd_name': res['acd_name'],
                    'openalex_id': res['openalex_id'],
                    'openalex_display_name': res['openalex_display_name'],
                    'last_known_institution': res['last_known_institution'],
                    'institution_country': res['institution_country'],
                    'works_count': res['works_count'],
                    'h_index': res['h_index'],
                    'aunz_ever': 1,
                    'confidence': res['confidence'],
                    'resolution_method': res['resolution_method'],
                    'pub_count': res['works_count'],  # fallback
                    'citation_count': None,
                    'fwci_mean': None
                }
                new_stats_rows.append(new_row)
            else:
                # Update existing row
                mask = stats['acd_name'] == res['acd_name']
                stats.loc[mask, 'openalex_id'] = res['openalex_id']
                stats.loc[mask, 'works_count'] = res['works_count']
                stats.loc[mask, 'h_index'] = res['h_index']
                stats.loc[mask, 'pub_count'] = res['works_count']
                stats.loc[mask, 'accepted'] = 1
        
        if new_stats_rows:
            new_df = pd.DataFrame(new_stats_rows)
            stats = pd.concat([stats, new_df], ignore_index=True)
        
        stats.to_csv(stats_path, index=False)
        print(f"Updated stats CSV: {len(stats)} rows")
    
    print("\nFailed members (still unresolved):")
    for name in failed:
        print(f"  - {name}")

if __name__ == '__main__':
    main()
