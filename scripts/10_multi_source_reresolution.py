"""
Multi-source re-resolution script for ACD dermatologists.
==========================================================
Fixes the core problem: the original resolver only matched 327/712 members.
This script:
1. Takes ALL 712 members from the master list
2. For each member, searches OpenAlex AND Semantic Scholar
3. Cross-verifies matches between sources
4. Writes corrected manual overrides for mismatched members
5. Updates authors_resolved.csv with correct IDs

Strategy:
- For members already correctly matched (high score, high works_count): keep
- For members with suspicious matches (works_count <= 5, wrong profile): re-search
- For NOT_FOUND members: search both OpenAlex and Semantic Scholar
- For missing members (43): add them with best available match or as unresolved

Sources:
- OpenAlex: https://api.openalex.org/authors
- Semantic Scholar: https://api.semanticscholar.org/graph/v1/author/search
"""
from __future__ import annotations
import json
import logging
import sys
import time
from pathlib import Path
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("/home/ubuntu/acd-dashboard/data/logs/reresolution.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("reresolution")

# ── Paths ────────────────────────────────────────────────────────────────────
DATA = Path("/home/ubuntu/acd-dashboard/data")
MASTER_CSV = DATA / "input/260708_Dermatologists_Consolidated.csv"
RESOLVED_CSV = DATA / "processed/authors_resolved.csv"
OVERRIDES_CSV = DATA / "input/manual_resolver_overrides.csv"
OUTPUT_CSV = DATA / "processed/authors_resolved_corrected.csv"
AUDIT_CSV = DATA / "processed/reresolution_audit.csv"

# ── API helpers ───────────────────────────────────────────────────────────────

def _get(url, params=None, retries=3, delay=1.0):
    """GET with retry and rate limiting."""
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=20,
                             headers={"User-Agent": "ACD-Dashboard/1.0 (research)"})
            if r.status_code == 429:
                time.sleep(10)
                continue
            if r.status_code == 200:
                return r.json()
            time.sleep(delay)
        except Exception as e:
            log.warning(f"Request error: {e}")
            time.sleep(delay * 2)
    return None


def search_openalex(name: str, state: str = None) -> list[dict]:
    """Search OpenAlex for an author by name."""
    params = {
        "search": name,
        "select": "id,display_name,works_count,cited_by_count,summary_stats,affiliations,last_known_institutions,topics",
        "per_page": 5,
    }
    data = _get("https://api.openalex.org/authors", params)
    if not data:
        return []
    results = []
    for a in data.get("results", []):
        ss = a.get("summary_stats", {})
        # Get country affiliations
        countries = set()
        for aff in a.get("affiliations", []):
            inst = aff.get("institution", {})
            if inst.get("country_code"):
                countries.add(inst["country_code"].upper())
        for inst in a.get("last_known_institutions", []):
            if inst.get("country_code"):
                countries.add(inst["country_code"].upper())
        # Get topics
        topics = [t.get("display_name", "") for t in a.get("topics", [])[:5]]
        results.append({
            "source": "openalex",
            "id": a.get("id", "").replace("https://openalex.org/", ""),
            "name": a.get("display_name", ""),
            "works": a.get("works_count", 0),
            "citations": a.get("cited_by_count", 0),
            "h_index": ss.get("h_index", 0),
            "countries": countries,
            "topics": topics,
            "au_nz": bool(countries & {"AU", "NZ"}),
        })
    return results


def search_semantic_scholar(name: str) -> list[dict]:
    """Search Semantic Scholar for an author by name."""
    params = {
        "query": name,
        "fields": "authorId,name,paperCount,citationCount,hIndex,affiliations",
        "limit": 5,
    }
    data = _get("https://api.semanticscholar.org/graph/v1/author/search", params)
    if not data:
        return []
    results = []
    for a in data.get("data", []):
        affiliations = [aff.get("name", "") for aff in a.get("affiliations", [])]
        au_nz = any(
            kw in " ".join(affiliations).lower()
            for kw in ["australia", "new zealand", "sydney", "melbourne", "brisbane",
                       "perth", "adelaide", "canberra", "auckland", "queensland",
                       "nsw", "victoria", "unsw", "uq ", "monash", "uwa"]
        )
        results.append({
            "source": "semantic_scholar",
            "id": a.get("authorId", ""),
            "name": a.get("name", ""),
            "works": a.get("paperCount", 0),
            "citations": a.get("citationCount", 0),
            "h_index": a.get("hIndex", 0),
            "affiliations": affiliations,
            "au_nz": au_nz,
        })
    return results


def score_candidate(candidate: dict, member_name: str, state: str = None) -> float:
    """Score a candidate match for a member."""
    score = 0.0
    cname = candidate["name"].lower()
    mname = member_name.lower()

    # Strip titles for matching
    for title in ["dr ", "prof ", "a/prof ", "adj ", "assoc "]:
        mname = mname.replace(title, "")
    mparts = mname.strip().split()
    if not mparts:
        return 0.0

    mlast = mparts[-1]
    mfirst = mparts[0] if len(mparts) > 1 else ""

    # Last name match (most important)
    if mlast in cname:
        score += 40
        # First name / initial match
        if mfirst and (mfirst in cname or (mfirst[0] in cname)):
            score += 20

    # AU/NZ affiliation
    if candidate.get("au_nz"):
        score += 25

    # Dermatology topics
    topics_str = " ".join(candidate.get("topics", [])).lower()
    affiliations_str = " ".join(candidate.get("affiliations", [])).lower()
    if any(t in topics_str or t in affiliations_str
           for t in ["dermatol", "skin", "melanoma", "psoriasis", "eczema"]):
        score += 15

    # Works count (reasonable range for a dermatologist)
    works = candidate.get("works", 0)
    if 5 <= works <= 500:
        score += 10
    elif works > 500:
        score += 5  # could be a merge

    # High h-index bonus
    if candidate.get("h_index", 0) >= 10:
        score += 5

    return score


def find_best_match(member_name: str, state: str = None) -> dict | None:
    """Find the best match for a member across OpenAlex and Semantic Scholar."""
    # Search both sources
    oa_results = search_openalex(member_name, state)
    time.sleep(0.3)  # rate limit
    ss_results = search_semantic_scholar(member_name)
    time.sleep(0.3)

    all_candidates = oa_results + ss_results

    if not all_candidates:
        return None

    # Score all candidates
    scored = []
    for c in all_candidates:
        s = score_candidate(c, member_name, state)
        scored.append((s, c))

    scored.sort(key=lambda x: -x[0])
    best_score, best = scored[0]

    if best_score < 30:
        return None  # Not confident enough

    # Cross-verify: if OpenAlex and Semantic Scholar agree on the person, boost confidence
    oa_best = next((c for s, c in scored if c["source"] == "openalex"), None)
    ss_best = next((c for s, c in scored if c["source"] == "semantic_scholar"), None)

    if oa_best and ss_best:
        # Check if they agree (similar name, similar works count)
        oa_name = oa_best["name"].lower().split()
        ss_name = ss_best["name"].lower().split()
        if oa_name and ss_name and oa_name[-1] == ss_name[-1]:
            # Same last name — cross-verified
            best["cross_verified"] = True
            best["ss_h_index"] = ss_best.get("h_index", 0)
            best["ss_citations"] = ss_best.get("citations", 0)
            best["ss_works"] = ss_best.get("works", 0)

    best["match_score"] = best_score
    return best if best["source"] == "openalex" else oa_best  # prefer OpenAlex ID


def main():
    log.info("Loading data files...")
    master = pd.read_csv(MASTER_CSV)
    resolved = pd.read_csv(RESOLVED_CSV)
    overrides = pd.read_csv(OVERRIDES_CSV)

    log.info(f"Master: {len(master)} members")
    log.info(f"Resolved: {len(resolved)} members")
    log.info(f"Existing overrides: {len(overrides)}")

    # Build lookup of existing overrides
    override_map = dict(zip(overrides["acd_name"], overrides["correct_openalex_id"]))

    # Identify members needing re-resolution:
    # 1. NOT_FOUND members
    # 2. Members with suspicious matches (works_count <= 3 and no override)
    # 3. Members missing from resolved entirely
    master_names = set(master["Name"].dropna().str.strip())
    resolved_names = set(resolved["acd_name"].dropna().str.strip())
    missing_from_resolved = master_names - resolved_names

    not_found = resolved[resolved["accepted"] == 0]["acd_name"].tolist()
    suspicious = resolved[
        (resolved["accepted"] == 1) &
        (resolved["works_count"] <= 3) &
        (~resolved["acd_name"].isin(override_map))
    ]["acd_name"].tolist()

    # Build state lookup from master
    state_lookup = dict(zip(master["Name"].str.strip(), master["State"].str.strip()))

    targets = list(set(not_found + suspicious + list(missing_from_resolved)))
    log.info(f"Targets for re-resolution: {len(targets)}")
    log.info(f"  NOT_FOUND: {len(not_found)}")
    log.info(f"  Suspicious (works<=3): {len(suspicious)}")
    log.info(f"  Missing from resolved: {len(missing_from_resolved)}")

    # Run re-resolution
    new_overrides = []
    audit_rows = []
    new_members = []

    for i, name in enumerate(targets):
        if i % 20 == 0:
            log.info(f"Progress: {i}/{len(targets)}")

        state = state_lookup.get(name, "")

        # Skip if already in overrides
        if name in override_map:
            log.debug(f"Skipping {name} — already has override")
            continue

        match = find_best_match(name, state)

        if match:
            openalex_id = match.get("id", "")
            if openalex_id and openalex_id.startswith("A"):
                new_overrides.append({
                    "acd_name": name,
                    "correct_openalex_id": openalex_id,
                    "note": (
                        f"Multi-source re-resolution. "
                        f"OA works={match.get('works',0)}, "
                        f"h={match.get('h_index',0)}, "
                        f"cross_verified={match.get('cross_verified', False)}, "
                        f"score={match.get('match_score',0):.0f}"
                    ),
                })
                log.info(f"  MATCHED {name} -> {openalex_id} "
                         f"(works={match.get('works',0)}, h={match.get('h_index',0)}, "
                         f"score={match.get('match_score',0):.0f})")
            audit_rows.append({
                "acd_name": name,
                "status": "matched",
                "openalex_id": openalex_id,
                "works": match.get("works", 0),
                "h_index": match.get("h_index", 0),
                "cross_verified": match.get("cross_verified", False),
                "match_score": match.get("match_score", 0),
            })
        else:
            log.info(f"  NO MATCH for {name}")
            audit_rows.append({
                "acd_name": name,
                "status": "no_match",
                "openalex_id": "",
                "works": 0,
                "h_index": 0,
                "cross_verified": False,
                "match_score": 0,
            })

        # Add missing members to resolved
        if name in missing_from_resolved:
            row_in_master = master[master["Name"].str.strip() == name]
            if not row_in_master.empty:
                m = row_in_master.iloc[0]
                new_members.append({
                    "acd_name": name,
                    "source": "master_list",
                    "priority": "must",
                    "practitioner_no": m.get("Practitioner_No_AHPRA", ""),
                    "state": m.get("State", ""),
                    "speciality_ahpra": "Dermatology",
                    "location_ahpra": m.get("Location_AHPRA", ""),
                    "ahpra_proven": 1,
                    "openalex_id": match.get("id", "") if match else "",
                    "openalex_display_name": match.get("name", "") if match else "",
                    "last_known_institution": "",
                    "institution_country": "AU",
                    "aunz_ever": 1,
                    "works_count": match.get("works", 0) if match else 0,
                    "h_index": match.get("h_index", 0) if match else 0,
                    "profile_url": "",
                    "score_name": 0, "score_country": 0, "score_inst": 0,
                    "score_topic": 0, "score_state": 0, "score_history": 0,
                    "score_hospital": 0, "score_semantic": 0, "score_llm": 0,
                    "total_score": match.get("match_score", 0) if match else 0,
                    "confidence": "HIGH" if (match and match.get("match_score", 0) >= 50) else "NOT_FOUND",
                    "accepted": 1 if (match and match.get("match_score", 0) >= 50) else 0,
                    "reject_reason": "" if match else "no_viable_candidate",
                    "resolution_method": "multi_source_reresolution",
                    "ambiguity_flags": "",
                    "llm_reasoning": "",
                    "search_pass": "reresolution",
                })

    # Save new overrides
    log.info(f"\nNew overrides found: {len(new_overrides)}")
    if new_overrides:
        new_ov_df = pd.DataFrame(new_overrides)
        combined_overrides = pd.concat([overrides, new_ov_df], ignore_index=True)
        combined_overrides.drop_duplicates(subset=["acd_name"], keep="last").to_csv(
            OVERRIDES_CSV, index=False
        )
        log.info(f"Updated overrides saved to {OVERRIDES_CSV}")

    # Apply overrides to resolved CSV
    log.info("Applying all overrides to resolved CSV...")
    all_overrides = pd.read_csv(OVERRIDES_CSV)
    override_map_updated = dict(zip(all_overrides["acd_name"], all_overrides["correct_openalex_id"]))

    # Update resolved with correct IDs
    def apply_override(row):
        if row["acd_name"] in override_map_updated:
            correct_id = override_map_updated[row["acd_name"]]
            if correct_id and correct_id != row.get("openalex_id", ""):
                # Fetch updated stats from OpenAlex
                data = _get(
                    f"https://api.openalex.org/authors/{correct_id}",
                    {"select": "id,display_name,works_count,cited_by_count,summary_stats,last_known_institutions"}
                )
                if data and "id" in data:
                    ss = data.get("summary_stats", {})
                    row["openalex_id"] = correct_id
                    row["openalex_display_name"] = data.get("display_name", row.get("openalex_display_name", ""))
                    row["works_count"] = data.get("works_count", 0)
                    row["h_index"] = ss.get("h_index", 0)
                    row["accepted"] = 1
                    row["confidence"] = "HIGH"
                    row["resolution_method"] = "manual_override_corrected"
                    time.sleep(0.2)
        return row

    resolved_updated = resolved.apply(apply_override, axis=1)

    # Add missing members
    if new_members:
        new_members_df = pd.DataFrame(new_members)
        # Ensure same columns
        for col in resolved_updated.columns:
            if col not in new_members_df.columns:
                new_members_df[col] = ""
        new_members_df = new_members_df[resolved_updated.columns]
        resolved_updated = pd.concat([resolved_updated, new_members_df], ignore_index=True)
        log.info(f"Added {len(new_members)} missing members")

    resolved_updated.to_csv(OUTPUT_CSV, index=False)
    log.info(f"Corrected resolved CSV saved to {OUTPUT_CSV} ({len(resolved_updated)} rows)")

    # Save audit
    pd.DataFrame(audit_rows).to_csv(AUDIT_CSV, index=False)
    log.info(f"Audit saved to {AUDIT_CSV}")

    # Summary
    accepted_final = resolved_updated[resolved_updated["accepted"] == 1]
    log.info(f"\n=== FINAL SUMMARY ===")
    log.info(f"Total members: {len(resolved_updated)}")
    log.info(f"Accepted (with OpenAlex ID): {len(accepted_final)}")
    log.info(f"Not found: {len(resolved_updated) - len(accepted_final)}")


if __name__ == "__main__":
    main()
