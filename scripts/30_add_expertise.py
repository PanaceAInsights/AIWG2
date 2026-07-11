"""
Script 30: Add clinical expertise from consolidated spreadsheet and research expertise
from OpenAlex topics to the stats CSV.

Clinical expertise sources (from consolidated spreadsheet):
1. Special_Interests_HS - free-text clinical interests from HealthShare
2. Interests_Names_HS - structured pipe-separated interest tags

Research expertise: derived from OpenAlex author topics (top concepts).
"""
import pandas as pd
import requests
import time
import re
import sys

STATS_PATH = "data/processed/author_summary_stats.csv"
RESOLVED_PATH = "data/processed/authors_resolved.csv"
CONSOLIDATED_PATH = "data/input/260708_Dermatologists_Consolidated.csv"
EMAIL = "research@panaceainsights.com.au"


def normalize_name_for_matching(name: str) -> str:
    """Strip title and normalize for fuzzy matching."""
    # Remove title prefix
    name = re.sub(r'^(Prof|A/Prof|Adj A/Prof|Assoc Prof|Dr|Clin A/Prof|Clin Prof|Emeritus Prof)\s+', '', name)
    # Remove extra spaces
    name = re.sub(r'\s+', ' ', name).strip()
    return name.lower()


def get_first_last(name: str) -> tuple[str, str]:
    """Get first and last name parts."""
    parts = name.split()
    if len(parts) < 2:
        return name, ''
    return parts[0], parts[-1]


def match_consolidated_to_acd(consolidated: pd.DataFrame, acd_names: list[str]) -> dict:
    """Match consolidated spreadsheet rows to ACD names.
    Returns dict: acd_name -> consolidated row index
    """
    matches = {}
    
    # Build lookup from ACD names
    acd_lookup = {}
    for acd_name in acd_names:
        bare = normalize_name_for_matching(acd_name)
        first, last = get_first_last(bare)
        if first and last:
            acd_lookup[(first, last)] = acd_name
    
    # Match from consolidated
    for idx, row in consolidated.iterrows():
        name = str(row.get('Name', ''))
        if not name or name == 'nan':
            continue
        bare = normalize_name_for_matching(name)
        first, last = get_first_last(bare)
        
        if (first, last) in acd_lookup:
            matches[acd_lookup[(first, last)]] = idx
    
    return matches


def clean_clinical_expertise(special_interests: str, interests_names: str) -> str:
    """Combine and clean clinical expertise from HealthShare fields."""
    parts = []
    
    # Special_Interests_HS is more detailed (free text)
    if pd.notna(special_interests) and str(special_interests).strip():
        text = str(special_interests).strip()
        # Clean up common patterns
        text = text.rstrip('.')
        parts.append(text)
    
    # Interests_Names_HS has structured tags (pipe-separated)
    if pd.notna(interests_names) and str(interests_names).strip():
        tags = [t.strip() for t in str(interests_names).split('|') if t.strip()]
        # Only add tags not already covered in the free text
        if parts:
            existing_lower = parts[0].lower()
            new_tags = [t for t in tags if t.lower() not in existing_lower]
            if new_tags:
                parts.append('; '.join(new_tags))
        else:
            parts.append('; '.join(tags))
    
    return ' | '.join(parts) if parts else ''


def fetch_research_topics(openalex_id: str) -> str:
    """Fetch top research topics from OpenAlex author profile."""
    if not openalex_id or pd.isna(openalex_id):
        return ''
    
    oid = str(openalex_id).strip()
    if not oid.startswith('http'):
        url = f"https://api.openalex.org/authors/{oid}"
    else:
        url = oid
    
    try:
        r = requests.get(url, params={'mailto': EMAIL, 'select': 'topics'}, timeout=20)
        if r.status_code != 200:
            return ''
        data = r.json()
        topics = data.get('topics', [])
        if not topics:
            return ''
        
        # Get top 5 topics by count, excluding generic ones
        generic_terms = {'medicine', 'biology', 'science', 'research', 'health'}
        topic_names = []
        for t in topics[:10]:
            name = t.get('display_name', '')
            if name.lower() not in generic_terms and len(name) > 3:
                topic_names.append(name)
            if len(topic_names) >= 5:
                break
        
        return '; '.join(topic_names)
    except Exception:
        return ''


def main():
    stats = pd.read_csv(STATS_PATH)
    res = pd.read_csv(RESOLVED_PATH)
    consolidated = pd.read_csv(CONSOLIDATED_PATH)
    
    print(f"Stats rows: {len(stats)}")
    print(f"Consolidated rows: {len(consolidated)}")
    
    # Add new columns if not present
    if 'clinical_expertise' not in stats.columns:
        stats['clinical_expertise'] = ''
    if 'research_expertise' not in stats.columns:
        stats['research_expertise'] = ''
    
    # Step 1: Match consolidated to ACD names
    acd_names = stats['acd_name'].tolist()
    matches = match_consolidated_to_acd(consolidated, acd_names)
    print(f"\nMatched {len(matches)} members to consolidated spreadsheet")
    
    # Step 2: Extract clinical expertise
    clinical_count = 0
    for acd_name, cons_idx in matches.items():
        row = consolidated.iloc[cons_idx]
        expertise = clean_clinical_expertise(
            row.get('Special_Interests_HS'),
            row.get('Interests_Names_HS')
        )
        if expertise:
            stats_idx = stats[stats['acd_name'] == acd_name].index
            if len(stats_idx) > 0:
                stats.loc[stats_idx[0], 'clinical_expertise'] = expertise
                clinical_count += 1
    
    print(f"Clinical expertise added for {clinical_count} members")
    
    # Step 3: Fetch research expertise from OpenAlex topics
    # Only for members with openalex_id and missing research_expertise
    need_research = stats[
        (stats['openalex_id'].notna()) & 
        (stats['openalex_id'] != '') &
        ((stats['research_expertise'].isna()) | (stats['research_expertise'] == ''))
    ]
    
    print(f"\nFetching research topics for {len(need_research)} members...")
    research_count = 0
    
    for i, (idx, row) in enumerate(need_research.iterrows()):
        if i > 0 and i % 10 == 0:
            time.sleep(1.1)
        
        topics = fetch_research_topics(row['openalex_id'])
        if topics:
            stats.loc[idx, 'research_expertise'] = topics
            research_count += 1
        
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(need_research)}] Research topics: {research_count} added")
            sys.stdout.flush()
    
    print(f"Research expertise added for {research_count} members")
    
    # Step 4: Save
    stats.to_csv(STATS_PATH, index=False)
    print(f"\nSaved stats CSV with expertise columns")
    
    # Summary
    has_clinical = (stats['clinical_expertise'].notna() & (stats['clinical_expertise'] != '')).sum()
    has_research = (stats['research_expertise'].notna() & (stats['research_expertise'] != '')).sum()
    print(f"Total with clinical expertise: {has_clinical}")
    print(f"Total with research expertise: {has_research}")


if __name__ == "__main__":
    main()
