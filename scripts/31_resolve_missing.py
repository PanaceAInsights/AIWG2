"""
Script 31: Comprehensive resolution of all members missing OpenAlex profiles.

Problem: 228 members (72 HIGH-conf with no OA ID + 156 NOT_FOUND) have no OpenAlex data.
The user correctly identified that researchers like Anes Yang (h=13, 33 works) and 
Amanda Saracino (h=12, 26 works) DO exist in OpenAlex but were missed.

Strategy:
1. Search OpenAlex by name for each unresolved member
2. Filter candidates by Australian affiliation
3. Check if any candidate has dermatology-related topics
4. Accept matches that pass both filters
5. For accepted matches, pull full stats (h-index, works, citations, FWCI)
6. Update both resolved CSV and stats CSV
"""
import pandas as pd
import requests
import time
import re
import sys
import json

EMAIL = "research@panaceainsights.com.au"
STATS_PATH = "data/processed/author_summary_stats.csv"
RESOLVED_PATH = "data/processed/authors_resolved.csv"

# Australian institutions keywords
AU_KEYWORDS = [
    'australia', 'sydney', 'melbourne', 'queensland', 'brisbane', 'perth',
    'adelaide', 'hobart', 'darwin', 'canberra', 'monash', 'unsw', 'uq',
    'usyd', 'unimelb', 'anu', 'uwa', 'flinders', 'deakin', 'griffith',
    'macquarie', 'newcastle', 'wollongong', 'curtin', 'rmit', 'latrobe',
    'james cook', 'tasmania', 'western australia', 'south australia',
    'new south wales', 'victoria', 'royal', 'st vincent', "children's",
    'princess alexandra', 'westmead', 'liverpool hospital', 'concord',
    'alfred', 'austin', 'box hill', 'epworth', 'cabrini', 'peter mac',
    'skin health institute', 'translational research institute',
    'qimr', 'berghofer', 'garvan', 'baker', 'murdoch', 'telethon',
    'new zealand', 'auckland', 'otago', 'wellington', 'christchurch'
]

# Dermatology topic keywords
DERM_KEYWORDS = [
    'dermat', 'skin', 'melanom', 'psoriasis', 'eczema', 'acne',
    'wound', 'hair', 'nail', 'pemphig', 'lupus', 'lichen',
    'kerato', 'basal cell', 'squamous cell', 'mohs', 'phototherapy',
    'atopic', 'urticaria', 'alopecia', 'vitiligo', 'scleroderma',
    'cutaneous', 'epidermal', 'keratinocyte', 'fibroblast',
    'collagen', 'cosmetic', 'laser', 'botox', 'filler',
    'hidradenitis', 'rosacea', 'bullous', 'blister'
]


def normalize_name(name: str) -> str:
    """Strip title prefix from name."""
    return re.sub(r'^(Prof|A/Prof|Adj A/Prof|Clin A/Prof|Clin Prof|Emeritus Prof|Assoc Prof|Dr)\s+', '', name).strip()


def has_au_affiliation(author_data: dict) -> bool:
    """Check if author has Australian/NZ affiliation."""
    # Check affiliations
    affiliations = author_data.get('affiliations') or []
    for aff in affiliations:
        inst = aff.get('institution', {})
        name = (inst.get('display_name', '') or '').lower()
        country = (inst.get('country_code', '') or '').lower()
        if country in ('au', 'nz'):
            return True
        for kw in AU_KEYWORDS:
            if kw in name:
                return True
    
    # Check last_known_institutions
    last_insts = author_data.get('last_known_institutions') or []
    for inst in last_insts:
        name = (inst.get('display_name', '') or '').lower()
        country = (inst.get('country_code', '') or '').lower()
        if country in ('au', 'nz'):
            return True
        for kw in AU_KEYWORDS:
            if kw in name:
                return True
    
    return False


def has_derm_topics(author_data: dict) -> bool:
    """Check if author has dermatology-related topics."""
    topics = author_data.get('topics') or []
    for t in topics[:15]:
        name = (t.get('display_name', '') or '').lower()
        for kw in DERM_KEYWORDS:
            if kw in name:
                return True
    
    # Also check x_concepts (older field)
    concepts = author_data.get('x_concepts') or []
    for c in concepts[:15]:
        name = (c.get('display_name', '') or '').lower()
        for kw in DERM_KEYWORDS:
            if kw in name:
                return True
    
    return False


def search_openalex_author(name: str) -> list:
    """Search OpenAlex for author by name, return list of candidates."""
    url = "https://api.openalex.org/authors"
    params = {
        'search': name,
        'mailto': EMAIL,
        'per_page': 10,
        'select': 'id,display_name,works_count,cited_by_count,summary_stats,affiliations,last_known_institutions,topics,x_concepts,orcid'
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code != 200:
            return []
        data = r.json()
        return data.get('results', [])
    except Exception:
        return []


def get_author_details(oa_id: str) -> dict:
    """Get full author details from OpenAlex."""
    url = f"https://api.openalex.org/authors/{oa_id}"
    try:
        r = requests.get(url, params={'mailto': EMAIL}, timeout=20)
        if r.status_code != 200:
            return {}
        return r.json()
    except Exception:
        return {}


def resolve_member(acd_name: str) -> dict | None:
    """Try to find the correct OpenAlex profile for a member.
    
    Returns dict with profile info or None if not found.
    """
    bare_name = normalize_name(acd_name)
    
    # Try different name variants
    name_parts = bare_name.split()
    search_variants = [bare_name]
    
    # Try first + last only (skip middle names)
    if len(name_parts) > 2:
        search_variants.append(f"{name_parts[0]} {name_parts[-1]}")
    
    for search_name in search_variants:
        candidates = search_openalex_author(search_name)
        if not candidates:
            time.sleep(0.5)
            continue
        
        # Score each candidate
        best_match = None
        best_score = 0
        
        for cand in candidates:
            score = 0
            
            # Check Australian affiliation
            if has_au_affiliation(cand):
                score += 50
            
            # Check dermatology topics
            if has_derm_topics(cand):
                score += 40
            
            # Check name similarity
            cand_name = (cand.get('display_name', '') or '').lower()
            bare_lower = bare_name.lower()
            first_name = name_parts[0].lower() if name_parts else ''
            last_name = name_parts[-1].lower() if name_parts else ''
            
            if last_name in cand_name and first_name in cand_name:
                score += 30
            elif last_name in cand_name:
                score += 15
            
            # Bonus for having works
            works = cand.get('works_count', 0) or 0
            if works > 0:
                score += min(10, works)
            
            if score > best_score:
                best_score = score
                best_match = cand
        
        # Accept if score is high enough (AU affiliation + name match minimum)
        if best_match and best_score >= 45:
            oa_id = best_match['id'].replace('https://openalex.org/', '')
            h_index = best_match.get('summary_stats', {}).get('h_index', 0) or 0
            works_count = best_match.get('works_count', 0) or 0
            cited_by = best_match.get('cited_by_count', 0) or 0
            
            # Get institution
            last_insts = best_match.get('last_known_institutions', [])
            institution = last_insts[0].get('display_name', '') if last_insts else ''
            
            # Get topics for research expertise
            topics = best_match.get('topics', [])
            topic_names = [t.get('display_name', '') for t in topics[:5] if t.get('display_name')]
            
            # Determine confidence
            confidence = 'HIGH'
            if not has_au_affiliation(best_match):
                confidence = 'MEDIUM'
            elif not has_derm_topics(best_match):
                confidence = 'MEDIUM'
            
            return {
                'openalex_id': oa_id,
                'h_index': h_index,
                'works_count': works_count,
                'cited_by_count': cited_by,
                'institution': institution,
                'confidence': confidence,
                'research_expertise': '; '.join(topic_names),
                'has_au': has_au_affiliation(best_match),
                'has_derm': has_derm_topics(best_match),
            }
        
        time.sleep(0.3)
    
    return None


def main():
    res = pd.read_csv(RESOLVED_PATH)
    stats = pd.read_csv(STATS_PATH)
    
    # Find members needing resolution
    # 1. HIGH confidence but no OpenAlex ID
    high_no_oa = res[(res['confidence'] == 'HIGH') & (res['openalex_id'].isna())]
    # 2. NOT_FOUND members
    not_found = res[res['confidence'] == 'NOT_FOUND']
    # 3. MEDIUM confidence members (might have wrong match)
    
    to_resolve = pd.concat([high_no_oa, not_found]).drop_duplicates(subset=['acd_name'])
    print(f"Total members to search: {len(to_resolve)}")
    sys.stdout.flush()
    
    found_count = 0
    results = []
    
    for i, (idx, row) in enumerate(to_resolve.iterrows()):
        name = row['acd_name']
        
        result = resolve_member(name)
        
        if result:
            found_count += 1
            results.append((idx, name, result))
            if found_count <= 10 or found_count % 20 == 0:
                print(f"  FOUND: {name} → h={result['h_index']}, works={result['works_count']}, "
                      f"AU={result['has_au']}, derm={result['has_derm']}")
        
        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{len(to_resolve)}] Found: {found_count}")
            sys.stdout.flush()
            time.sleep(1)
        else:
            time.sleep(0.5)
    
    print(f"\n=== RESULTS ===")
    print(f"Searched: {len(to_resolve)}")
    print(f"Found: {found_count}")
    print(f"Still not found: {len(to_resolve) - found_count}")
    sys.stdout.flush()
    
    # Apply results to CSVs
    stats_names = set(stats['acd_name'].tolist())
    
    for idx, name, result in results:
        # Update resolved CSV
        res.loc[idx, 'openalex_id'] = result['openalex_id']
        res.loc[idx, 'confidence'] = result['confidence']
        if result['institution']:
            res.loc[idx, 'last_known_institution'] = result['institution']
        
        # Update or add to stats CSV
        if name in stats_names:
            stats_idx = stats[stats['acd_name'] == name].index[0]
            stats.loc[stats_idx, 'openalex_id'] = result['openalex_id']
            stats.loc[stats_idx, 'h_index'] = result['h_index']
            stats.loc[stats_idx, 'pub_count'] = result['works_count']
            stats.loc[stats_idx, 'citation_count'] = result['cited_by_count']
            if result['research_expertise']:
                stats.loc[stats_idx, 'research_expertise'] = result['research_expertise']
        else:
            # Add new row to stats
            new_row = {
                'acd_name': name,
                'openalex_id': result['openalex_id'],
                'h_index': result['h_index'],
                'pub_count': result['works_count'],
                'citation_count': result['cited_by_count'],
                'research_expertise': result['research_expertise'],
                'confidence': result['confidence'],
            }
            # Copy state from resolved
            if 'state' in res.columns:
                new_row['state'] = res.loc[idx, 'state']
            stats = pd.concat([stats, pd.DataFrame([new_row])], ignore_index=True)
    
    # Mark remaining NOT_FOUND as genuinely not indexed
    # (they have no OpenAlex profile at all)
    
    # Save
    res.to_csv(RESOLVED_PATH, index=False)
    stats.to_csv(STATS_PATH, index=False)
    
    print(f"\nSaved. Stats now has {len(stats)} rows.")
    print(f"Resolved CSV updated with {found_count} new OpenAlex IDs.")
    
    # Also save a report of what was found
    report = []
    for _, name, result in results:
        report.append({
            'name': name,
            'openalex_id': result['openalex_id'],
            'h_index': result['h_index'],
            'works': result['works_count'],
            'citations': result['cited_by_count'],
            'institution': result['institution'],
            'au_affiliation': result['has_au'],
            'derm_topics': result['has_derm'],
        })
    
    if report:
        pd.DataFrame(report).to_csv('data/processed/resolution_report_31.csv', index=False)
        print("Report saved to data/processed/resolution_report_31.csv")


if __name__ == "__main__":
    main()
