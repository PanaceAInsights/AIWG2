"""
Script 29: Apply academic title corrections from HealthShare data and manual overrides.

Sources:
1. HealthShare Name_HealthShare column (48 members with Prof/A-Prof)
2. User-specified corrections (Peter Soyer=Prof, Pascale Guitera=Prof, 
   Kiarash Khosrotehrani=Prof, Gayle Fischer=Prof, John Frew=A/Prof, etc.)
3. Web search verification for additional high-profile members
"""
import pandas as pd
import re

STATS_PATH = "data/processed/author_summary_stats.csv"
RESOLVED_PATH = "data/processed/authors_resolved.csv"
CONSOLIDATED_PATH = "data/input/260708_Dermatologists_Consolidated.csv"

def extract_title(name: str) -> tuple[str, str]:
    """Extract title prefix and bare name from a name string."""
    patterns = [
        (r'^Prof\s+', 'Prof'),
        (r'^A/Prof\s+', 'A/Prof'),
        (r'^Adj A/Prof\s+', 'Adj A/Prof'),
        (r'^Assoc Prof\s+', 'A/Prof'),  # Normalize to A/Prof
        (r'^Clin A/Prof\s+', 'Clin A/Prof'),
        (r'^Clin Prof\s+', 'Clin Prof'),
        (r'^Emeritus Prof\s+', 'Emeritus Prof'),
        (r'^Dr\s+', 'Dr'),
    ]
    for pattern, title in patterns:
        if re.match(pattern, name, re.IGNORECASE):
            bare = re.sub(pattern, '', name, flags=re.IGNORECASE).strip()
            return title, bare
    return '', name


def match_name_fuzzy(hs_bare: str, acd_names: list[str]) -> str | None:
    """Match a HealthShare bare name to an ACD name."""
    # HealthShare names are typically short (first + last)
    # ACD names are full (first + middle + last)
    hs_parts = hs_bare.lower().split()
    if len(hs_parts) < 2:
        return None
    
    hs_first = hs_parts[0]
    hs_last = hs_parts[-1]
    
    candidates = []
    for acd_name in acd_names:
        _, acd_bare = extract_title(acd_name)
        acd_parts = acd_bare.lower().split()
        if len(acd_parts) < 2:
            continue
        acd_first = acd_parts[0]
        acd_last = acd_parts[-1]
        
        if acd_first == hs_first and acd_last == hs_last:
            candidates.append(acd_name)
    
    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        # Multiple matches - return None to avoid ambiguity
        return None
    return None


def main():
    stats = pd.read_csv(STATS_PATH)
    res = pd.read_csv(RESOLVED_PATH)
    consolidated = pd.read_csv(CONSOLIDATED_PATH)
    
    # Step 1: Extract titles from HealthShare
    hs_titles = {}
    for _, row in consolidated.iterrows():
        hs_name = row.get('Name_HealthShare')
        if pd.isna(hs_name):
            continue
        title, bare = extract_title(str(hs_name))
        if title and title != 'Dr':
            hs_titles[bare] = title
    
    print(f"HealthShare titles found: {len(hs_titles)}")
    for bare, title in sorted(hs_titles.items()):
        print(f"  {title} {bare}")
    print()
    
    # Step 2: Manual overrides from user + known corrections
    # These take precedence over HealthShare
    manual_overrides = {
        # User specified:
        'Hans Peter Soyer': 'Prof',
        'Pascale Rovel Guitera': 'Prof',
        'Paul Kiarash Khosrotehrani': 'Prof',
        'Gayle Fischer': 'Prof',
        'John Walter Frew': 'A/Prof',
        'Deshan Sebaratnam': 'A/Prof',  # Already done
        'Diona Lee Damian': 'Prof',      # Already done
        'Simone Goldinger': 'A/Prof',    # Already done (Simone not Simon)
        # Additional from HealthShare that are Prof (not A/Prof):
        'Rodney Daniel Sinclair': 'Prof',
        'Deirdre Frances Murrell': 'Prof',
        'Ingrid Margaret Winship': 'Prof',
    }
    
    # Step 3: Match HealthShare titles to ACD names
    acd_names = res['acd_name'].tolist()
    
    title_updates = {}  # acd_name -> new_title
    
    # First apply HealthShare matches
    for hs_bare, title in hs_titles.items():
        matched = match_name_fuzzy(hs_bare, acd_names)
        if matched:
            current_title, _ = extract_title(matched)
            if current_title != title:
                title_updates[matched] = title
    
    # Then apply manual overrides (these take precedence)
    for bare_name, title in manual_overrides.items():
        # Find the ACD name containing this bare name
        for acd_name in acd_names:
            _, acd_bare = extract_title(acd_name)
            if acd_bare == bare_name:
                current_title, _ = extract_title(acd_name)
                if current_title != title:
                    title_updates[acd_name] = title
                break
    
    print(f"\nTitle updates to apply: {len(title_updates)}")
    for old_name, new_title in sorted(title_updates.items()):
        old_title, bare = extract_title(old_name)
        new_name = f"{new_title} {bare}"
        print(f"  {old_name} → {new_name}")
    print()
    
    # Step 4: Apply updates to both CSVs
    for old_name, new_title in title_updates.items():
        _, bare = extract_title(old_name)
        new_name = f"{new_title} {bare}"
        
        # Update resolved CSV
        mask_r = res['acd_name'] == old_name
        if mask_r.any():
            res.loc[mask_r, 'acd_name'] = new_name
        
        # Update stats CSV
        mask_s = stats['acd_name'] == old_name
        if mask_s.any():
            stats.loc[mask_s, 'acd_name'] = new_name
    
    # Step 5: Save
    res.to_csv(RESOLVED_PATH, index=False)
    stats.to_csv(STATS_PATH, index=False)
    print("Saved both CSVs")
    
    # Step 6: Summary
    titles_after = res['acd_name'].str.extract(r'^(Prof|A/Prof|Adj A/Prof|Assoc Prof|Dr|Clin A/Prof|Clin Prof|Emeritus Prof)\s', expand=False)
    print("\nTitle distribution after update:")
    print(titles_after.value_counts().to_string())


if __name__ == "__main__":
    main()
