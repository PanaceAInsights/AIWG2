"""
Smart multi-source re-resolution for ACD dermatologists.
=========================================================
Improved version with:
- Better name parsing (strips titles, handles initials)
- Lower score threshold (many AU dermatologists have few pubs)
- Cross-verification with Semantic Scholar
- Handles members with no academic profile gracefully
- Adds ALL 712 members to resolved CSV (even those with 0 pubs)
"""
from __future__ import annotations
import logging
import sys
import time
from pathlib import Path
import pandas as pd
import requests
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("/home/ubuntu/acd-dashboard/data/logs/smart_reresolution.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("smart_reresolution")

DATA = Path("/home/ubuntu/acd-dashboard/data")
MASTER_CSV = DATA / "input/260708_Dermatologists_Consolidated.csv"
RESOLVED_CSV = DATA / "processed/authors_resolved.csv"
OVERRIDES_CSV = DATA / "input/manual_resolver_overrides.csv"
OUTPUT_CSV = DATA / "processed/authors_resolved_v2.csv"
AUDIT_CSV = DATA / "processed/smart_reresolution_audit.csv"

DERM_TERMS = {
    "dermatol", "skin", "melanoma", "psoriasis", "eczema", "acne",
    "vitiligo", "rosacea", "pemphigus", "bullous", "cutaneous",
    "photodermatol", "mohs", "dermoscopy", "atopic"
}

AU_NZ_TERMS = {
    "australia", "new zealand", "sydney", "melbourne", "brisbane",
    "perth", "adelaide", "canberra", "auckland", "queensland",
    "nsw", "victoria", "unsw", "uq ", "monash", "uwa", "flinders",
    "newcastle", "wollongong", "deakin", "rmit", "griffith", "curtin",
    "hobart", "darwin", "latrobe", "macquarie", "western australia",
    "south australia", "tasmania", "northern territory"
}


def _strip_title(name: str) -> str:
    """Remove academic/medical titles from a name."""
    for t in ["adj a/prof ", "a/prof ", "adj prof ", "assoc prof ", "prof ",
              "dr ", "mr ", "ms ", "mrs "]:
        if name.lower().startswith(t):
            name = name[len(t):]
    return name.strip()


def _name_parts(name: str) -> tuple[str, str, list[str]]:
    """Return (last, first, middles) from a full name."""
    clean = _strip_title(name)
    parts = clean.split()
    if not parts:
        return "", "", []
    last = parts[-1]
    first = parts[0] if len(parts) > 1 else ""
    middles = parts[1:-1] if len(parts) > 2 else []
    return last, first, middles


def _get(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=20,
                             headers={"User-Agent": "ACD-Research-Dashboard/2.0"})
            if r.status_code == 429:
                time.sleep(15)
                continue
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            log.debug(f"Request error ({url}): {e}")
            time.sleep(2)
    return None


def _is_au_nz(candidate: dict) -> bool:
    """Check if a candidate has AU/NZ affiliation."""
    countries = candidate.get("countries", set())
    if countries & {"AU", "NZ"}:
        return True
    affil_str = " ".join(candidate.get("affiliations", [])).lower()
    return any(t in affil_str for t in AU_NZ_TERMS)


def _has_derm(candidate: dict) -> bool:
    """Check if a candidate has dermatology topics."""
    topics_str = " ".join(candidate.get("topics", [])).lower()
    affil_str = " ".join(candidate.get("affiliations", [])).lower()
    combined = topics_str + " " + affil_str
    return any(t in combined for t in DERM_TERMS)


def search_openalex(name: str) -> list[dict]:
    """Search OpenAlex for an author."""
    clean = _strip_title(name)
    data = _get("https://api.openalex.org/authors", {
        "search": clean,
        "select": "id,display_name,works_count,cited_by_count,summary_stats,"
                  "last_known_institutions,affiliations,topics",
        "per_page": 8,
    })
    if not data:
        return []
    results = []
    for a in data.get("results", []):
        ss = a.get("summary_stats", {})
        countries = set()
        affil_names = []
        for inst in (a.get("last_known_institutions") or []):
            if inst and inst.get("country_code"):
                countries.add(inst["country_code"].upper())
            if inst and inst.get("display_name"):
                affil_names.append(inst["display_name"])
        for aff in (a.get("affiliations") or []):
            inst = aff.get("institution") or {}
            if inst.get("country_code"):
                countries.add(inst["country_code"].upper())
            if inst.get("display_name"):
                affil_names.append(inst["display_name"])
        topics = [t.get("display_name", "") for t in (a.get("topics") or [])[:8]]
        results.append({
            "source": "openalex",
            "id": a.get("id", "").replace("https://openalex.org/", ""),
            "name": a.get("display_name", ""),
            "works": a.get("works_count", 0),
            "citations": a.get("cited_by_count", 0),
            "h_index": ss.get("h_index", 0),
            "countries": countries,
            "affiliations": affil_names,
            "topics": topics,
        })
    return results


def search_semantic_scholar(name: str) -> list[dict]:
    """Search Semantic Scholar for an author."""
    clean = _strip_title(name)
    data = _get("https://api.semanticscholar.org/graph/v1/author/search", {
        "query": clean,
        "fields": "authorId,name,paperCount,citationCount,hIndex,affiliations",
        "limit": 5,
    })
    if not data:
        return []
    results = []
    for a in data.get("data", []):
        affil_names = [aff.get("name", "") for aff in (a.get("affiliations") or [])]
        results.append({
            "source": "semantic_scholar",
            "id": a.get("authorId", ""),
            "name": a.get("name", ""),
            "works": a.get("paperCount", 0),
            "citations": a.get("citationCount", 0),
            "h_index": a.get("hIndex", 0),
            "countries": set(),
            "affiliations": affil_names,
            "topics": [],
        })
    return results


def score_match(candidate: dict, member_name: str) -> float:
    """Score a candidate against a member name (0-100)."""
    mlast, mfirst, mmids = _name_parts(member_name)
    clast, cfirst, _ = _name_parts(candidate["name"])

    if not mlast or not clast:
        return 0.0

    score = 0.0

    # Last name similarity (most important — 50 pts)
    last_sim = fuzz.ratio(mlast.lower(), clast.lower()) / 100.0
    if last_sim >= 0.95:
        score += 50
    elif last_sim >= 0.85:
        score += 35
    elif last_sim >= 0.70:
        score += 15
    else:
        return 0.0  # Last name too different — skip

    # First name / initial match (20 pts)
    if mfirst and cfirst:
        first_sim = fuzz.ratio(mfirst.lower(), cfirst.lower()) / 100.0
        if first_sim >= 0.90:
            score += 20
        elif mfirst[0].lower() == cfirst[0].lower():
            score += 12
        else:
            score -= 10  # First name mismatch is a bad sign

    # AU/NZ affiliation (15 pts)
    if _is_au_nz(candidate):
        score += 15

    # Dermatology topics/affiliation (10 pts)
    if _has_derm(candidate):
        score += 10

    # Works count — reasonable range (5 pts)
    works = candidate.get("works", 0)
    if 1 <= works <= 600:
        score += 5

    return score


def find_best_openalex_match(member_name: str) -> dict | None:
    """Find the best OpenAlex match for a member."""
    oa_results = search_openalex(member_name)
    time.sleep(0.25)

    if not oa_results:
        return None

    scored = [(score_match(c, member_name), c) for c in oa_results]
    scored.sort(key=lambda x: -x[0])

    best_score, best = scored[0]

    # Minimum threshold: last name must match (score >= 35)
    if best_score < 35:
        return None

    # Cross-verify with Semantic Scholar for high-value matches
    if best_score >= 50:
        ss_results = search_semantic_scholar(member_name)
        time.sleep(0.25)
        if ss_results:
            ss_scored = [(score_match(c, member_name), c) for c in ss_results]
            ss_scored.sort(key=lambda x: -x[0])
            if ss_scored and ss_scored[0][0] >= 35:
                ss_best = ss_scored[0][1]
                # Check if SS and OA agree on name
                oa_last = _name_parts(best["name"])[0].lower()
                ss_last = _name_parts(ss_best["name"])[0].lower()
                if oa_last == ss_last:
                    best["cross_verified"] = True
                    best["ss_h_index"] = ss_best.get("h_index", 0)
                    best["ss_works"] = ss_best.get("works", 0)

    best["match_score"] = best_score
    return best


def fetch_openalex_stats(openalex_id: str) -> dict:
    """Fetch current stats for an OpenAlex author ID."""
    data = _get(
        f"https://api.openalex.org/authors/{openalex_id}",
        {"select": "id,display_name,works_count,cited_by_count,summary_stats,last_known_institutions"}
    )
    if not data or "id" not in data:
        return {}
    ss = data.get("summary_stats", {})
    countries = set()
    affil_names = []
    for inst in (data.get("last_known_institutions") or []):
        if inst and inst.get("country_code"):
            countries.add(inst["country_code"].upper())
        if inst and inst.get("display_name"):
            affil_names.append(inst["display_name"])
    return {
        "openalex_id": openalex_id,
        "openalex_display_name": data.get("display_name", ""),
        "works_count": data.get("works_count", 0),
        "h_index": ss.get("h_index", 0),
        "cited_by_count": data.get("cited_by_count", 0),
        "last_known_institution": affil_names[0] if affil_names else "",
        "institution_country": next(iter(countries), ""),
        "aunz_ever": 1 if countries & {"AU", "NZ"} else 0,
    }


def main():
    log.info("=== Smart Multi-Source Re-Resolution ===")

    master = pd.read_csv(MASTER_CSV)
    resolved = pd.read_csv(RESOLVED_CSV)
    overrides = pd.read_csv(OVERRIDES_CSV)

    log.info(f"Master: {len(master)} | Resolved: {len(resolved)} | Overrides: {len(overrides)}")

    # Build override map
    override_map = dict(zip(overrides["acd_name"].str.strip(), overrides["correct_openalex_id"].str.strip()))

    # Build master lookup
    master["Name"] = master["Name"].str.strip()
    state_lookup = dict(zip(master["Name"], master.get("State", pd.Series()).fillna("")))
    prac_lookup = dict(zip(master["Name"], master.get("Practitioner_No_AHPRA", pd.Series()).fillna("")))
    loc_lookup = dict(zip(master["Name"], master.get("Location_AHPRA", pd.Series()).fillna("")))

    # Identify all 712 members
    all_master_names = master["Name"].dropna().str.strip().tolist()
    resolved_names = set(resolved["acd_name"].str.strip())

    # Build working resolved dict
    resolved_dict = {row["acd_name"].strip(): row.to_dict() for _, row in resolved.iterrows()}

    # Targets: NOT_FOUND, suspicious matches, and missing members
    not_found_names = resolved[resolved["accepted"] == 0]["acd_name"].str.strip().tolist()
    suspicious_names = resolved[
        (resolved["accepted"] == 1) &
        (resolved["works_count"] <= 3) &
        (~resolved["acd_name"].isin(override_map))
    ]["acd_name"].str.strip().tolist()
    missing_names = [n for n in all_master_names if n not in resolved_names]

    targets = list(set(not_found_names + suspicious_names + missing_names))
    # Remove those already in override_map (will be applied later)
    targets_to_search = [n for n in targets if n not in override_map]

    log.info(f"Targets: {len(targets)} total")
    log.info(f"  NOT_FOUND: {len(not_found_names)}")
    log.info(f"  Suspicious (works<=3): {len(suspicious_names)}")
    log.info(f"  Missing from resolved: {len(missing_names)}")
    log.info(f"  Already have overrides: {len(targets) - len(targets_to_search)}")
    log.info(f"  Need searching: {len(targets_to_search)}")

    new_overrides = []
    audit_rows = []

    for i, name in enumerate(targets_to_search):
        if i % 25 == 0:
            log.info(f"Progress: {i}/{len(targets_to_search)}")

        match = find_best_openalex_match(name)

        if match and match["id"].startswith("A"):
            new_overrides.append({
                "acd_name": name,
                "correct_openalex_id": match["id"],
                "note": (
                    f"Smart re-resolution. works={match.get('works',0)}, "
                    f"h={match.get('h_index',0)}, "
                    f"au_nz={_is_au_nz(match)}, "
                    f"derm={_has_derm(match)}, "
                    f"cross_verified={match.get('cross_verified',False)}, "
                    f"score={match.get('match_score',0):.0f}"
                ),
            })
            log.info(f"  MATCHED {name} -> {match['id']} "
                     f"(works={match.get('works',0)}, h={match.get('h_index',0)}, "
                     f"score={match.get('match_score',0):.0f}, "
                     f"au_nz={_is_au_nz(match)}, derm={_has_derm(match)})")
            audit_rows.append({
                "acd_name": name, "status": "matched",
                "openalex_id": match["id"], "works": match.get("works", 0),
                "h_index": match.get("h_index", 0),
                "au_nz": _is_au_nz(match), "derm": _has_derm(match),
                "cross_verified": match.get("cross_verified", False),
                "match_score": match.get("match_score", 0),
            })
        else:
            log.info(f"  NO MATCH for {name}")
            audit_rows.append({
                "acd_name": name, "status": "no_match",
                "openalex_id": "", "works": 0, "h_index": 0,
                "au_nz": False, "derm": False,
                "cross_verified": False, "match_score": 0,
            })

    # Save new overrides
    log.info(f"\nNew overrides found: {len(new_overrides)}")
    if new_overrides:
        combined = pd.concat([overrides, pd.DataFrame(new_overrides)], ignore_index=True)
        combined.drop_duplicates(subset=["acd_name"], keep="last").to_csv(OVERRIDES_CSV, index=False)
        log.info(f"Saved {len(combined)} total overrides")

    # Reload all overrides
    all_overrides = pd.read_csv(OVERRIDES_CSV)
    override_map_final = dict(zip(
        all_overrides["acd_name"].str.strip(),
        all_overrides["correct_openalex_id"].str.strip()
    ))

    # Apply overrides to resolved dict — fetch fresh stats for corrected IDs
    log.info("Applying overrides and fetching fresh stats...")
    for name, correct_id in override_map_final.items():
        if not correct_id or not correct_id.startswith("A"):
            continue
        current = resolved_dict.get(name, {})
        if current.get("openalex_id") == correct_id:
            continue  # Already correct
        log.info(f"  Applying override: {name} -> {correct_id}")
        stats = fetch_openalex_stats(correct_id)
        time.sleep(0.2)
        if stats:
            if name in resolved_dict:
                resolved_dict[name].update({
                    "openalex_id": correct_id,
                    "openalex_display_name": stats.get("openalex_display_name", ""),
                    "works_count": stats.get("works_count", 0),
                    "h_index": stats.get("h_index", 0),
                    "last_known_institution": stats.get("last_known_institution", ""),
                    "institution_country": stats.get("institution_country", "AU"),
                    "aunz_ever": stats.get("aunz_ever", 1),
                    "accepted": 1,
                    "confidence": "HIGH",
                    "resolution_method": "manual_override_corrected",
                    "reject_reason": "",
                })
            else:
                # New member not yet in resolved
                resolved_dict[name] = {
                    "acd_name": name,
                    "source": "master_list",
                    "priority": "must",
                    "practitioner_no": prac_lookup.get(name, ""),
                    "state": state_lookup.get(name, ""),
                    "speciality_ahpra": "Dermatology",
                    "location_ahpra": loc_lookup.get(name, ""),
                    "ahpra_proven": 1,
                    "openalex_id": correct_id,
                    "openalex_display_name": stats.get("openalex_display_name", ""),
                    "last_known_institution": stats.get("last_known_institution", ""),
                    "institution_country": stats.get("institution_country", "AU"),
                    "aunz_ever": stats.get("aunz_ever", 1),
                    "works_count": stats.get("works_count", 0),
                    "h_index": stats.get("h_index", 0),
                    "profile_url": "",
                    "score_name": 0, "score_country": 0, "score_inst": 0,
                    "score_topic": 0, "score_state": 0, "score_history": 0,
                    "score_hospital": 0, "score_semantic": 0, "score_llm": 0,
                    "total_score": 100,
                    "confidence": "HIGH",
                    "accepted": 1,
                    "reject_reason": "",
                    "resolution_method": "manual_override_corrected",
                    "ambiguity_flags": "",
                    "llm_reasoning": "",
                    "search_pass": "reresolution_v2",
                }

    # Add ALL missing master members (even those with no match)
    log.info("Adding all missing master members...")
    for name in all_master_names:
        if name not in resolved_dict:
            resolved_dict[name] = {
                "acd_name": name,
                "source": "master_list",
                "priority": "must",
                "practitioner_no": prac_lookup.get(name, ""),
                "state": state_lookup.get(name, ""),
                "speciality_ahpra": "Dermatology",
                "location_ahpra": loc_lookup.get(name, ""),
                "ahpra_proven": 1,
                "openalex_id": "",
                "openalex_display_name": "",
                "last_known_institution": "",
                "institution_country": "AU",
                "aunz_ever": 1,
                "works_count": 0,
                "h_index": 0,
                "profile_url": "",
                "score_name": 0, "score_country": 0, "score_inst": 0,
                "score_topic": 0, "score_state": 0, "score_history": 0,
                "score_hospital": 0, "score_semantic": 0, "score_llm": 0,
                "total_score": 0,
                "confidence": "NOT_FOUND",
                "accepted": 0,
                "reject_reason": "no_viable_candidate",
                "resolution_method": "not_found",
                "ambiguity_flags": "",
                "llm_reasoning": "",
                "search_pass": "reresolution_v2",
            }
            log.info(f"  Added missing member: {name}")

    # Write output
    out_df = pd.DataFrame(list(resolved_dict.values()))
    # Ensure consistent column order
    cols = list(resolved.columns)
    for c in out_df.columns:
        if c not in cols:
            cols.append(c)
    out_df = out_df.reindex(columns=cols, fill_value="")
    out_df.sort_values("acd_name").to_csv(OUTPUT_CSV, index=False)
    log.info(f"\nOutput saved: {OUTPUT_CSV} ({len(out_df)} rows)")

    # Save audit
    pd.DataFrame(audit_rows).to_csv(AUDIT_CSV, index=False)

    # Summary
    accepted = out_df[out_df["accepted"] == 1]
    log.info(f"\n=== FINAL SUMMARY ===")
    log.info(f"Total members: {len(out_df)}")
    log.info(f"With OpenAlex match: {len(accepted)}")
    log.info(f"Without match (0 pubs): {len(out_df) - len(accepted)}")
    log.info(f"New matches found: {len(new_overrides)}")

    # Check key researchers
    for name in ["Soyer", "Murrell", "Rodney.*Sinclair"]:
        rows = out_df[out_df["acd_name"].str.contains(name, case=False, na=False, regex=True)]
        if not rows.empty:
            log.info(f"\n{name}: {rows[['acd_name','openalex_id','h_index','works_count','accepted']].to_string()}")


if __name__ == "__main__":
    main()
