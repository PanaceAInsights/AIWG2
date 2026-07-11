"""
22_run_web_crossvalidation.py
==============================
Runs web cross-validation for all accepted members with works > 5.
Uses DuckDuckGo search + Claude Haiku to verify specialty and title.
Also catches institution mismatches (e.g., French CS institute for an AU dermatologist).
"""
from __future__ import annotations
import os, sys, time, json, logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import anthropic
from openai import OpenAI
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("web_cv")

RESOLVED_CSV = ROOT / "data" / "processed" / "authors_resolved.csv"
ROSTER_CSV   = ROOT / "data" / "input" / "Dermatologists_Consolidated.csv"

# Use OpenAI-compatible proxy with claude-haiku-4-5 (fast, cheap, good enough for parsing)
client = OpenAI()

# Known non-AU institutions that slipped through resolution (institution name → reason)
_KNOWN_NON_AU_INSTS = {
    "bangor university": "UK university",
    "institut national de recherche en sciences et technologies du numérique": "French CS institute",
    "daewoo pharma": "South Korean pharma",
    "university of kwazulu-natal": "South African university",
    "university college london": "UK university",
    "boston children's hospital": "US hospital",
    "michigan state university": "US university",
    "apple (israel)": "Israeli tech company",
    "barrie urology group": "Urology practice (wrong specialty)",
    "clifton hospital": "UK hospital",
    "hollywood orthopaedic group": "Orthopaedic practice (wrong specialty)",
}

def is_suspicious_institution(inst_name: str, country_code: str) -> tuple[bool, str]:
    """Returns (is_suspicious, reason). Uses country code from OpenAlex as primary signal."""
    if not inst_name or inst_name == 'nan': return False, ""
    inst_lower = inst_name.lower()
    
    # Check known bad institutions
    for bad_inst, reason in _KNOWN_NON_AU_INSTS.items():
        if bad_inst in inst_lower:
            return True, f"Known non-AU/wrong institution: {reason}"
    
    # Use OpenAlex country code as primary signal (much more reliable than name matching)
    if country_code and country_code not in ('AU', 'NZ', 'nan', '', 'None'):
        return True, f"Non-AU/NZ country code: {country_code}"
    
    return False, ""

def web_search(query: str, n: int = 5) -> list[dict]:
    try:
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
        r = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for result in soup.select(".result")[:n]:
            title_el   = result.select_one(".result__title")
            snippet_el = result.select_one(".result__snippet")
            url_el     = result.select_one(".result__url")
            if title_el:
                results.append({
                    "title":   title_el.get_text(strip=True),
                    "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                    "url":     url_el.get_text(strip=True) if url_el else "",
                })
        return results
    except Exception as e:
        log.warning("Search failed: %s", e)
        return []

def parse_with_llm(name: str, snippets: list[dict]) -> dict:
    if not snippets:
        return {"status": "no_results"}
    
    text = "\n\n".join([
        f"[{i+1}] Title: {s['title']}\nURL: {s['url']}\nSnippet: {s['snippet']}"
        for i, s in enumerate(snippets)
    ])
    
    prompt = f"""You are reviewing web search results for an Australian dermatologist named "{name}".

Search results:
{text}

Extract the following as JSON (return ONLY the JSON object):
{{
  "verified_title": "Prof|A/Prof|Adj A/Prof|Dr|null",
  "verified_institution": "current hospital or university name, or null",
  "is_dermatologist": true|false|null,
  "is_wrong_person": true|false,
  "wrong_person_reason": "explain if wrong person, else null",
  "orcid": "ORCID if found (format 0000-XXXX-XXXX-XXXX), else null",
  "confidence": "high|medium|low",
  "notes": "brief notes"
}}

Rules:
- Set is_wrong_person=true ONLY if results clearly show a DIFFERENT specialty (dentist, cardiologist, etc.)
- Set is_dermatologist=null if ambiguous or no clear specialty info
- Extract ORCID only if explicitly shown
- For verified_title: look for Professor, Associate Professor, A/Prof in academic pages"""

    try:
        resp = client.chat.completions.create(
            model="claude-haiku-4-5",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        log.warning("LLM parse failed for %s: %s", name, e)
        return {"status": "parse_error"}

def main():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    resolved = pd.read_csv(RESOLVED_CSV)
    roster   = pd.read_csv(ROSTER_CSV)
    
    # Build state map
    state_map = {}
    for _, row in roster.iterrows():
        n = str(row.get('Name') or '').strip()
        s = str(row.get('State') or '').strip()
        if n and s: state_map[n] = s
    
    # Target: accepted members
    accepted = resolved[resolved['accepted'] == 1].copy()
    log.info("Cross-validating %d accepted members", len(accepted))
    
    all_results = []
    flagged     = []
    title_updates = []
    inst_mismatches = []
    
    for i, (idx, row) in enumerate(accepted.iterrows()):
        name         = str(row['acd_name'])
        state        = state_map.get(name, "")
        inst         = str(row.get('last_known_institution') or '')
        country_code = str(row.get('institution_country') or '')
        works        = float(row.get('works_count') or 0)
        
        log.info("[%d/%d] %s (inst=%s, cc=%s)", i+1, len(accepted), name, inst[:50], country_code)
        
        # First: quick institution check using country code (no web search needed)
        suspicious, reason = is_suspicious_institution(inst, country_code)
        if suspicious:
            log.warning("  *** SUSPICIOUS INSTITUTION: %s → %s (%s)", name, inst, reason)
            inst_mismatches.append({'acd_name': name, 'institution': inst, 'country_code': country_code, 'reason': reason, 'works': works})
        
        # Web search for members with works > 5 (others have too little data to validate)
        if works > 5:
            location = f"Australia {state}" if state else "Australia"
            query = f'"{name}" dermatologist {location}'
            snippets = web_search(query, n=5)
            time.sleep(1.5)
            
            cv = parse_with_llm(name, snippets)
            cv['acd_name'] = name
            cv['current_inst'] = inst
            cv['state'] = state
            all_results.append(cv)
            
            if cv.get('is_wrong_person'):
                log.warning("  *** FALSE POSITIVE: %s — %s", name, cv.get('wrong_person_reason'))
                flagged.append({
                    'acd_name': name, 'inst': inst,
                    'reason': cv.get('wrong_person_reason'),
                    'confidence': cv.get('confidence'),
                    'notes': cv.get('notes'),
                })
            
            # Title updates
            new_title = cv.get('verified_title')
            if new_title and new_title not in ('null', None, ''):
                for prefix in ['Prof ', 'A/Prof ', 'Adj A/Prof ', 'Dr ']:
                    if name.startswith(prefix):
                        cur = prefix.strip()
                        break
                else:
                    cur = None
                if cur and new_title != cur:
                    title_updates.append({
                        'acd_name': name, 'current': cur,
                        'suggested': new_title,
                        'confidence': cv.get('confidence'),
                    })
                    log.info("  Title: %s → %s", cur, new_title)
            
            # ORCID enrichment
            orcid = cv.get('orcid')
            if orcid and orcid not in ('null', None, ''):
                log.info("  ORCID found: %s", orcid)
                resolved.loc[idx, 'orcid'] = orcid
        else:
            all_results.append({'acd_name': name, 'status': 'skipped_low_works', 'works': works})
    
    # Save outputs
    pd.DataFrame(all_results).to_csv(
        ROOT / "data" / "processed" / f"web_cv_audit_{ts}.csv", index=False)
    
    if flagged:
        fp_path = ROOT / "data" / "processed" / f"web_cv_flagged_{ts}.csv"
        pd.DataFrame(flagged).to_csv(fp_path, index=False)
        log.warning("Flagged %d potential false positives → %s", len(flagged), fp_path)
    
    if title_updates:
        t_path = ROOT / "data" / "processed" / f"web_cv_title_updates_{ts}.csv"
        pd.DataFrame(title_updates).to_csv(t_path, index=False)
        log.info("Suggested %d title updates → %s", len(title_updates), t_path)
    
    if inst_mismatches:
        im_path = ROOT / "data" / "processed" / f"web_cv_inst_mismatches_{ts}.csv"
        pd.DataFrame(inst_mismatches).to_csv(im_path, index=False)
        log.warning("Found %d institution mismatches → %s", len(inst_mismatches), im_path)
    
    # Save updated resolved with any ORCID enrichments
    resolved.to_csv(RESOLVED_CSV, index=False)
    
    log.info("\n=== SUMMARY ===")
    log.info("Members checked: %d", len(accepted))
    log.info("Potential false positives: %d", len(flagged))
    log.info("Title updates suggested: %d", len(title_updates))
    log.info("Institution mismatches: %d", len(inst_mismatches))

if __name__ == "__main__":
    main()
