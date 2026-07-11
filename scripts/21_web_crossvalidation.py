"""
21_web_crossvalidation.py — Stage 4: Web Search Cross-Validation
=================================================================

For every accepted match, performs a targeted web search to:
1. Verify/enrich academic title (Dr, A/Prof, Prof) from university/hospital pages
2. Confirm or correct current institution
3. Detect false positives that slipped through (e.g., a dentist with same name)
4. Find ORCID for unresolved members to feed back into Stage 1

Uses the Anthropic Claude API to parse web search snippets intelligently.
"""
from __future__ import annotations

import os
import sys
import time
import json
import logging
from datetime import datetime
from pathlib import Path

import anthropic
import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("web_crossvalidation")

RESOLVED_CSV = ROOT / "data" / "processed" / "authors_resolved.csv"
ROSTER_CSV   = ROOT / "data" / "input" / "Dermatologists_Consolidated.csv"

_AU_DERM_INSTITUTIONS = {
    "royal melbourne hospital", "royal prince alfred hospital", "royal north shore hospital",
    "royal brisbane", "royal perth", "royal adelaide", "royal children", "royal women",
    "princess alexandra hospital", "st vincent", "alfred hospital", "westmead hospital",
    "monash health", "austin hospital", "john hunter hospital", "fiona stanley hospital",
    "gold coast hospital", "sunshine coast hospital", "liverpool hospital",
    "skin health institute", "melanoma institute australia", "skin cancer foundation",
    "university of sydney", "university of melbourne", "university of queensland",
    "university of western australia", "monash university", "university of adelaide",
    "unsw sydney", "flinders university", "james cook university", "deakin university",
    "curtin university", "griffith university", "latrobe university",
    "translational research institute", "qimr berghofer", "peter maccallum",
    "australasian college of dermatologists",
}

_DERM_KEYWORDS = {
    "dermatologist", "dermatology", "skin specialist", "skin cancer",
    "melanoma", "eczema", "psoriasis", "contact dermatitis",
    "mohs surgeon", "cosmetic dermatologist",
}

_NON_DERM_KEYWORDS = {
    "dentist", "dental", "cardiologist", "neurologist", "orthopaedic",
    "ophthalmologist", "gastroenterologist", "psychiatrist", "urologist",
    "gynaecologist", "obstetrician", "anaesthetist", "radiologist",
    "spinal surgeon", "spine surgeon", "astrophysicist",
}

_TITLE_MAP = {
    "professor": "Prof",
    "associate professor": "A/Prof",
    "adjunct professor": "Adj Prof",
    "adjunct associate professor": "Adj A/Prof",
    "clinical professor": "Prof",
    "conjoint professor": "Prof",
    "conjoint associate professor": "A/Prof",
}

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def web_search_snippets(query: str, n: int = 5) -> list[dict]:
    """Use DuckDuckGo HTML search to get snippets for a query."""
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
            title_el = result.select_one(".result__title")
            snippet_el = result.select_one(".result__snippet")
            url_el = result.select_one(".result__url")
            if title_el:
                results.append({
                    "title": title_el.get_text(strip=True),
                    "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                    "url": url_el.get_text(strip=True) if url_el else "",
                })
        return results
    except Exception as e:
        log.warning("Web search failed for '%s': %s", query, e)
        return []


def parse_with_llm(name: str, snippets: list[dict]) -> dict:
    """Use Claude to extract structured information from web search snippets."""
    if not snippets:
        return {}
    
    snippets_text = "\n\n".join([
        f"[{i+1}] Title: {s['title']}\nURL: {s['url']}\nSnippet: {s['snippet']}"
        for i, s in enumerate(snippets)
    ])
    
    prompt = f"""You are reviewing web search results for an Australian dermatologist named "{name}".

Search results:
{snippets_text}

Based ONLY on the above search results, extract the following information as JSON:
{{
  "verified_title": "Prof|A/Prof|Adj A/Prof|Dr|null",
  "verified_institution": "current hospital or university name, or null",
  "is_dermatologist": true|false|null,
  "is_wrong_person": true|false,
  "wrong_person_reason": "explain if wrong person detected, else null",
  "orcid": "ORCID if found, else null",
  "confidence": "high|medium|low",
  "notes": "brief notes about what was found"
}}

Rules:
- Set is_wrong_person=true ONLY if results clearly show a different specialty (e.g., dentist, cardiologist, astrophysicist)
- Set is_dermatologist=null if results are ambiguous or no clear specialty info found
- Extract ORCID only if explicitly shown in results (format: 0000-XXXX-XXXX-XXXX)
- For verified_title, look for "Professor", "Associate Professor", "A/Prof", etc.
- Return ONLY the JSON object, no other text."""

    try:
        msg = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}]
        )
        text = msg.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        log.warning("LLM parse failed for %s: %s", name, e)
        return {}


def crossvalidate_member(name: str, current_inst: str = "", state: str = "") -> dict:
    """Run web search cross-validation for a single member."""
    # Build targeted query
    location = f"Australia {state}" if state else "Australia"
    query = f'"{name}" dermatologist {location}'
    
    log.info("  Searching: %s", query)
    snippets = web_search_snippets(query, n=5)
    time.sleep(1.5)  # Be polite to search engines
    
    if not snippets:
        return {"status": "no_results"}
    
    result = parse_with_llm(name, snippets)
    result["query"] = query
    result["num_snippets"] = len(snippets)
    return result


def main():
    import shutil
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    resolved = pd.read_csv(RESOLVED_CSV)
    roster   = pd.read_csv(ROSTER_CSV)
    
    # Build state map from roster
    state_map = {}
    for _, row in roster.iterrows():
        name = str(row.get('Name') or '').strip()
        state = str(row.get('State') or '').strip()
        if name and state:
            state_map[name] = state
    
    # Target: all currently accepted members with works > 5
    accepted = resolved[
        (resolved['accepted'] == 1) &
        (pd.to_numeric(resolved['works_count'], errors='coerce').fillna(0) > 5)
    ].copy()
    
    log.info("Cross-validating %d accepted members...", len(accepted))
    
    results = []
    flagged_for_review = []
    title_updates = []
    
    for i, (idx, row) in enumerate(accepted.iterrows()):
        name = row['acd_name']
        state = state_map.get(name, "")
        inst = str(row.get('last_known_institution') or '')
        
        log.info("[%d/%d] %s", i+1, len(accepted), name)
        
        cv = crossvalidate_member(name, inst, state)
        cv['acd_name'] = name
        cv['current_inst'] = inst
        results.append(cv)
        
        # Flag potential false positives
        if cv.get('is_wrong_person'):
            log.warning("  *** POTENTIAL FALSE POSITIVE: %s — %s", name, cv.get('wrong_person_reason'))
            flagged_for_review.append({
                'acd_name': name,
                'reason': cv.get('wrong_person_reason'),
                'confidence': cv.get('confidence'),
            })
        
        # Collect title updates
        new_title = cv.get('verified_title')
        if new_title and new_title != 'null' and new_title is not None:
            # Check if roster title differs
            current_name = name
            for prefix in ['Dr ', 'Prof ', 'A/Prof ', 'Adj A/Prof ']:
                if current_name.startswith(prefix):
                    current_prefix = prefix.strip()
                    break
            else:
                current_prefix = None
            
            if current_prefix and new_title != current_prefix:
                title_updates.append({
                    'acd_name': name,
                    'current_title': current_prefix,
                    'suggested_title': new_title,
                    'confidence': cv.get('confidence'),
                })
                log.info("  Title update: %s → %s", current_prefix, new_title)
        
        # ORCID enrichment
        orcid = cv.get('orcid')
        if orcid and str(orcid) != 'null' and orcid:
            log.info("  Found ORCID: %s", orcid)
            # Could trigger re-resolution with this ORCID
    
    # Save results
    audit_path = ROOT / "data" / "processed" / f"web_crossvalidation_audit_{ts}.csv"
    pd.DataFrame(results).to_csv(audit_path, index=False)
    log.info("Saved audit to %s", audit_path)
    
    if flagged_for_review:
        flag_path = ROOT / "data" / "processed" / f"flagged_for_manual_review_{ts}.csv"
        pd.DataFrame(flagged_for_review).to_csv(flag_path, index=False)
        log.warning("Flagged %d members for manual review: %s", len(flagged_for_review), flag_path)
    
    if title_updates:
        title_path = ROOT / "data" / "processed" / f"title_updates_{ts}.csv"
        pd.DataFrame(title_updates).to_csv(title_path, index=False)
        log.info("Suggested %d title updates: %s", len(title_updates), title_path)
    
    log.info("\n=== WEB CROSS-VALIDATION SUMMARY ===")
    log.info("Members checked: %d", len(accepted))
    log.info("Potential false positives flagged: %d", len(flagged_for_review))
    log.info("Title updates suggested: %d", len(title_updates))
    
    return results, flagged_for_review, title_updates


if __name__ == "__main__":
    main()
