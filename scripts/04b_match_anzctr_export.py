"""Phase 4 — Match ANZCTR bulk export against resolved ACD dermatologists.

Input:  data/input/anzctr_export.xlsx        (ANZCTR bulk export)
Input:  data/processed/authors_resolved.csv  (Phase 1 output)
Output: data/processed/clinical_trials.csv   — 13 cols:
  acd_name, trial_id, registry, title, status, condition, intervention,
  phase, start_date, completion_date, role, sponsor, url

Matching strategy:
  - CONTACTS sheet filtered to Principal Investigator + AU.
  - Name normalisation via scripts.utils.name_matching.normalise_name.
  - Exact normalised match OR rapidfuzz.token_set_ratio >= 92 with
    last-name token intersection guard.
  - One row per (acd_name, trial_id) pair.

CLI::
    python scripts/04b_match_anzctr_export.py [--input PATH] [--authors PATH] [--output PATH]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.utils.name_matching import normalise_name, _last_name_tokens  # noqa: E402

logger = logging.getLogger("acd.phase4b")

_STRICT_FUZZY = 92
_CONFIDENCE_ACCEPTED = {"HIGH", "REVIEW"}


def _load_member_names(authors_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(authors_csv, dtype=str).fillna("")
    df = df[df["confidence"].isin(_CONFIDENCE_ACCEPTED)].copy()
    df["acd_normalised"] = df["acd_name"].apply(normalise_name)
    df = df[df["acd_normalised"].str.len() > 0]
    return df[["acd_name", "acd_normalised", "priority"]].reset_index(drop=True)


def _load_anzctr_pi(xlsx: Path) -> pd.DataFrame:
    """Return AU Principal Investigators keyed by trial_id."""
    try:
        contacts = pd.read_excel(xlsx, sheet_name="CONTACTS", engine="openpyxl")
        au_pi = contacts[
            (contacts["TYPE"].str.strip() == "Principal Investigator")
            & contacts["COUNTRY"].fillna("").str.contains("Australia", case=False)
        ].copy()
        au_pi["pi_normalised"] = au_pi["NAME"].apply(normalise_name)
        au_pi = au_pi[au_pi["pi_normalised"].str.len() > 0]
        return au_pi[["TRIAL ID", "TITLE", "NAME", "pi_normalised"]].rename(
            columns={"TRIAL ID": "trial_id", "TITLE": "pi_title", "NAME": "pi_name"}
        ).reset_index(drop=True)
    except Exception:
        logger.warning("CONTACTS sheet not found — falling back to TRIAL sheet")

    # Fallback: main sheet
    trial = pd.read_excel(xlsx, engine="openpyxl")
    for col in ["PRINCIPAL INVESTIGATOR", "PI NAME", "INVESTIGATOR", "CONTACT NAME"]:
        if col in trial.columns:
            au_pi = trial[trial.get("RECRUITMENT COUNTRY", pd.Series()).fillna("").str.contains("Australia", case=False)].copy()
            au_pi["pi_normalised"] = au_pi[col].apply(normalise_name)
            au_pi = au_pi[au_pi["pi_normalised"].str.len() > 0]
            return au_pi[["TRIAL ID", col, "pi_normalised"]].rename(
                columns={"TRIAL ID": "trial_id", col: "pi_name"}
            ).assign(pi_title="").reset_index(drop=True)

    logger.error("Cannot identify PI column in ANZCTR export")
    return pd.DataFrame(columns=["trial_id", "pi_title", "pi_name", "pi_normalised"])


def _match_members_to_pis(members: pd.DataFrame, pis: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    pis_lastmap = pis.copy()
    pis_lastmap["last_tokens"] = pis_lastmap["pi_normalised"].apply(_last_name_tokens)

    for _, m in members.iterrows():
        m_norm = m["acd_normalised"]
        m_last = _last_name_tokens(m_norm)
        if not m_last:
            continue

        exact = pis_lastmap[pis_lastmap["pi_normalised"] == m_norm]
        for _, p in exact.iterrows():
            rows.append({"acd_name": m["acd_name"], "priority": m["priority"],
                         "trial_id": p["trial_id"], "pi_name": p["pi_name"],
                         "match_type": "exact", "score": 100})
        matched_trials = set(exact["trial_id"])

        candidate = pis_lastmap[
            pis_lastmap["last_tokens"].apply(lambda t: bool(t & m_last))
            & ~pis_lastmap["trial_id"].isin(matched_trials)
        ]
        for _, p in candidate.iterrows():
            score = fuzz.token_set_ratio(m_norm, p["pi_normalised"])
            if score >= _STRICT_FUZZY:
                rows.append({"acd_name": m["acd_name"], "priority": m["priority"],
                             "trial_id": p["trial_id"], "pi_name": p["pi_name"],
                             "match_type": "fuzzy", "score": int(score)})

    if not rows:
        return pd.DataFrame(columns=["acd_name", "priority", "trial_id", "pi_name", "match_type", "score"])
    return pd.DataFrame(rows)


def _build_trial_rows(matches: pd.DataFrame, xlsx: Path) -> pd.DataFrame:
    if matches.empty:
        return pd.DataFrame()

    trial_ids = set(matches["trial_id"].astype(str))

    trial = pd.read_excel(xlsx, engine="openpyxl")
    if "TRIAL ID" in trial.columns:
        trial = trial[trial["TRIAL ID"].astype(str).isin(trial_ids)].copy()
    else:
        trial = pd.DataFrame()

    hc_agg = pd.Series(dtype=str)
    ic_agg = pd.Series(dtype=str)
    try:
        hc = pd.read_excel(xlsx, sheet_name="HEALTH CONDITION", engine="openpyxl")
        hc = hc[hc["TRIAL ID"].astype(str).isin(trial_ids)]
        hc_agg = hc.groupby("TRIAL ID")["HEALTH CONDITION"].apply(
            lambda s: "|".join(sorted(set(str(x) for x in s.dropna())))
        ).rename("condition_joined")
    except Exception:
        pass
    try:
        ic = pd.read_excel(xlsx, sheet_name="INTERVENTION CODE", engine="openpyxl")
        ic = ic[ic["TRIAL ID"].astype(str).isin(trial_ids)]
        ic_agg = ic.groupby("TRIAL ID")["INTERVENTION CODE"].apply(
            lambda s: "|".join(sorted(set(str(x) for x in s.dropna())))
        ).rename("intervention_joined")
    except Exception:
        pass

    if not trial.empty:
        if not hc_agg.empty:
            trial = trial.merge(hc_agg, left_on="TRIAL ID", right_index=True, how="left")
        if not ic_agg.empty:
            trial = trial.merge(ic_agg, left_on="TRIAL ID", right_index=True, how="left")

    out = matches.merge(trial, left_on="trial_id", right_on="TRIAL ID", how="left") if not trial.empty else matches.copy()

    def _best_date(r, *cols):
        for col in cols:
            v = r.get(col)
            if pd.notna(v):
                return str(v)[:10]
        return ""

    rows = []
    for _, r in out.iterrows():
        actrn = r.get("ACTRN")
        tid = actrn if pd.notna(actrn) and actrn else r["trial_id"]
        url = (f"https://www.anzctr.org.au/Trial/Registration/TrialReview.aspx?id={tid}"
               if isinstance(tid, str) and tid else "")
        rows.append({
            "acd_name":        r["acd_name"],
            "trial_id":        tid or "",
            "registry":        "ANZCTR",
            "title":           (r.get("STUDY TITLE") or r.get("SCIENTIFIC TITLE") or ""),
            "status":          r.get("RECRUITMENT STATUS") or "",
            "condition":       r.get("condition_joined") or "",
            "intervention":    r.get("intervention_joined") or "",
            "phase":           r.get("PHASE") or "",
            "start_date":      _best_date(r, "ACTUAL START DATE", "ANTICIPATED START DATE"),
            "completion_date": _best_date(r, "ACTUAL END DATE", "ANTICIPATED END DATE",
                                          "ACTUAL LAST VISIT DATE", "ANTICIPATED LAST VISIT DATE"),
            "role":            "Principal Investigator",
            "sponsor":         r.get("PRIMARY SPONSOR NAME") or "",
            "url":             url,
        })

    df = pd.DataFrame(rows)
    return df.drop_duplicates(subset=["acd_name", "trial_id"]).reset_index(drop=True)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Match ANZCTR export to ACD dermatologists.")
    p.add_argument("--input",   default=str(ROOT / "data" / "input" / "anzctr_export.xlsx"))
    p.add_argument("--authors", default=str(ROOT / "data" / "processed" / "authors_resolved.csv"))
    p.add_argument("--output",  default=str(ROOT / "data" / "processed" / "clinical_trials.csv"))
    args = p.parse_args(argv)

    xlsx = Path(args.input)
    authors_csv = Path(args.authors)
    output = Path(args.output)

    if not xlsx.exists():
        logger.error("ANZCTR export not found: %s", xlsx)
        return 1
    if not authors_csv.exists():
        logger.error("authors_resolved.csv not found: %s", authors_csv)
        return 1

    logger.info("Loading ANZCTR export (%d MB)...", xlsx.stat().st_size // (1024 * 1024))
    members = _load_member_names(authors_csv)
    logger.info("Loaded %d ACD members (HIGH+REVIEW confidence)", len(members))
    pis = _load_anzctr_pi(xlsx)
    logger.info("Loaded %d Australian Principal Investigators", len(pis))
    matches = _match_members_to_pis(members, pis)
    logger.info(
        "Matched %d trial-PI pairs (%d exact, %d fuzzy) across %d distinct members",
        len(matches),
        (matches["match_type"] == "exact").sum() if not matches.empty else 0,
        (matches["match_type"] == "fuzzy").sum() if not matches.empty else 0,
        matches["acd_name"].nunique() if not matches.empty else 0,
    )
    trial_rows = _build_trial_rows(matches, xlsx)
    output.parent.mkdir(parents=True, exist_ok=True)
    trial_rows.to_csv(output, index=False, encoding="utf-8")
    logger.info("Wrote %d clinical trial rows to %s", len(trial_rows), output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
