"""
23_apply_country_code_filter.py
================================
Applies a country-code based institution filter to all accepted members.
Uses the institution_country field from OpenAlex (much more reliable than name matching).

Edge cases handled:
- Prof Deirdre Murrell: Sutherland Hospital shows IN (India) - data error, she is AU
- Members with aunz_ever=1 but current inst is non-AU (trained in AU, now abroad) - keep if works <= 20
- Members with non-AU current inst AND high works AND aunz_ever=0 - almost certainly wrong person
"""
from __future__ import annotations
import pandas as pd
import requests
import time
import logging
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("country_filter")

RESOLVED_CSV = ROOT / "data" / "processed" / "authors_resolved.csv"
STATS_CSV    = ROOT / "data" / "processed" / "author_summary_stats.csv"

# Members confirmed as legitimate AU dermatologists despite non-AU current institution
# (verified manually or via ORCID)
_EXEMPT = {
    "Prof Deirdre Frances Murrell",  # Sutherland Hospital AU - OpenAlex country code error
    "Dr Robert Rosen",               # Boston Children's - has AU history, paediatric derm
    "Dr Sara Lee De Menezes",        # Apple Israel - melanoma researcher with AU history
    "Dr Sara Sabourirad",            # No institution - hair/skin/nail derm with AU history
    "Dr Esther Hong",                # USYD - clear AU derm
    "Dr Aaron James Robinson",       # Bangor UK - ACD member, has AU history
    "Dr Karolina Louisa Suzanna Kerkemeyer",  # UCL - has AU history, derm topics
    "Dr Johanna Merilyn Kuchel",     # Churchill UK - has AU history
    "Dr Tom Kovitwanichkanont",      # Spain - has AU history, derm topics
    "Dr Rebecca Dunn",               # UK - has AU history
    "Dr Hoang Ly",                   # Vietnam - has AU history
    "Dr On Bon Chan",                # US - has AU history
    "Dr Susan Jade Robertson",       # Malaysia - has AU history
}

# Members that are clearly wrong matches based on institution + topic analysis
_CONFIRMED_WRONG = {
    "Dr Bevin Bhoyrul":             "Sinclair Community College US - wrong person",
    "Dr Alexander John Chamberlain":"Barrie Urology Group CA - urology, not derm",
    "Dr Belinda Maymie Welsh":      "Dermatology Specialists US - wrong person",
    "Dr Christina Sander":          "Daewoo Pharma South Korea - wrong person",
    "Dr Ernest Boon Cheng Tan":     "Memorial Sloan Kettering US - wrong person",
    "Dr Laura Dionisio Wheller":    "American Society Clinical Oncology US - wrong person",
    "Dr Margaret Ann Oziemski":     "Tower Semiconductor Israel - wrong person",
    "Dr Kurosh Parsi":              "St Vincent's Birmingham US (not AU St Vincent's) - wrong person",
    "Dr Devita Surjana":            "Advanced Dermatology US - wrong person",
    "Dr Raquel Mery Ruiz Araujo":   "Hospital Peru - wrong person",
    "Dr Rachel Walther":            "Inserm France - wrong person",
    "Dr Philip Bruder":             "Society of Hematologic Oncology US - wrong person",
    "Dr Niluka Dilrukshi Paththinige": "National Hospital Sri Lanka - wrong person",
    "Dr Mohamed Saleem Loghdey":    "Queen's Medical Centre UK - wrong person",
    "Dr Koraisha Hoosen":           "University of KwaZulu-Natal ZA - wrong person",
    "Dr John Francis Shannon":      "Ohio State University US - wrong person",
    "Dr Desmond Chia Chin Gan":     "St Vincent's Birmingham US - wrong person",
    "Dr Alfonso Perez De Velasco":  "Clifton Hospital UK - wrong person",
    "Dr Sudha Anish":               "Vancouver General Hospital CA - wrong person",
    "Dr Sue Yin Ng":                "Churchill Hospital UK - wrong person",
    "Dr Tahereh Taklif":            "Advanced Dermatology US - wrong person",
}

def rebuild_stats(resolved: pd.DataFrame) -> pd.DataFrame:
    """Rebuild author_summary_stats from resolved CSV."""
    accepted = resolved[resolved['accepted'] == 1].copy()
    stats = accepted[[
        'acd_name','openalex_id','openalex_display_name',
        'last_known_institution','institution_country',
        'works_count','h_index','aunz_ever',
        'confidence','resolution_method'
    ]].copy()
    stats.columns = [
        'acd_name','openalex_id','openalex_display_name',
        'last_known_institution','institution_country',
        'works_count','h_index','aunz_ever',
        'confidence','resolution_method'
    ]
    return stats

def main():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    resolved = pd.read_csv(RESOLVED_CSV)
    
    accepted = resolved[resolved['accepted'] == 1].copy()
    log.info("Total accepted before filter: %d", len(accepted))
    
    cleared = []
    kept_exempt = []
    
    for idx, row in accepted.iterrows():
        name = str(row['acd_name'])
        cc   = str(row.get('institution_country') or '')
        inst = str(row.get('last_known_institution') or '')
        aunz = int(row.get('aunz_ever') or 0)
        works = float(row.get('works_count') or 0)
        
        # Skip AU/NZ institutions - they're fine
        if cc in ('AU', 'NZ', 'nan', '', 'None'):
            continue
        
        # Check exempt list
        if name in _EXEMPT:
            log.info("EXEMPT (kept): %s [%s, %s]", name, inst, cc)
            kept_exempt.append(name)
            continue
        
        # Check confirmed wrong list
        if name in _CONFIRMED_WRONG:
            reason = _CONFIRMED_WRONG[name]
            log.warning("CLEARING (confirmed wrong): %s — %s", name, reason)
            resolved.loc[idx, 'accepted'] = 0
            resolved.loc[idx, 'confidence'] = ''
            resolved.loc[idx, 'reject_reason'] = f"country_code_filter: {reason}"
            resolved.loc[idx, 'resolution_method'] = 'cleared_country_code_filter'
            cleared.append({'acd_name': name, 'inst': inst, 'cc': cc, 'reason': reason})
            continue
        
        # For remaining non-AU: apply heuristic
        # High works + non-AU + non-exempt = likely wrong person
        if works > 20 and aunz == 0:
            reason = f"Non-AU institution ({cc}: {inst}), works={works:.0f}, aunz_ever=0"
            log.warning("CLEARING (non-AU high-works): %s — %s", name, reason)
            resolved.loc[idx, 'accepted'] = 0
            resolved.loc[idx, 'confidence'] = ''
            resolved.loc[idx, 'reject_reason'] = f"country_code_filter: {reason}"
            resolved.loc[idx, 'resolution_method'] = 'cleared_country_code_filter'
            cleared.append({'acd_name': name, 'inst': inst, 'cc': cc, 'reason': reason})
        elif works > 20 and aunz == 1:
            # Has AU history but current inst is non-AU - flag for review but keep
            log.info("FLAGGED (non-AU current, has AU history): %s [%s, %s, works=%.0f]",
                     name, inst, cc, works)
        else:
            # Low works, non-AU - flag but keep (could be AU derm with few pubs)
            log.info("KEPT (low works, non-AU): %s [%s, %s, works=%.0f]",
                     name, inst, cc, works)
    
    # Save
    resolved.to_csv(RESOLVED_CSV, index=False)
    
    # Rebuild stats
    stats = rebuild_stats(resolved)
    stats.to_csv(STATS_CSV, index=False)
    
    final = (resolved['accepted'] == 1).sum()
    log.info("\n=== COUNTRY CODE FILTER SUMMARY ===")
    log.info("Cleared: %d", len(cleared))
    log.info("Exempt (kept): %d", len(kept_exempt))
    log.info("Final accepted: %d", final)
    
    if cleared:
        pd.DataFrame(cleared).to_csv(
            ROOT / "data" / "processed" / f"country_filter_cleared_{ts}.csv", index=False)
    
    return cleared

if __name__ == "__main__":
    main()
