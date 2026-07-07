"""Phase 5 orchestrator: pre-compute per-author summary stats.

Consumes the CSVs produced by Phases 1-4 and emits a single
``author_summary_stats.csv`` with one row per resolved author and 22
columns (identity + raw aggregates + must-tier percentile ranks).

The downstream R Shiny dashboard has to render radar charts and
leaderboards for 600-939 authors at click-time. Computing h-index,
percentile ranks and open-access rates live (in R) would blow out the
first-paint budget, so we pre-compute them here once per pipeline run
and ship a flat table the dashboard can ``fread`` and filter on.

**Percentile rule** (spec §7.4):

- Percentiles are computed **over the must-tier distribution only**.
  Must-tier authors are the RMSANZ-primary list and represent the
  "real" population; nice-tier authors (other societies, foreign) are
  included for context but would skew the distribution if pooled.
- Must-tier authors get ``rank(pct=True) * 100`` with ``method="average"``
  (ties get the midpoint rank, matching SciPy's ``rankdata`` default).
- Nice-tier authors are interpolated against the sorted must-tier
  distribution using ``(must < v).sum() / len(must) * 100`` — the
  fraction of must-tier authors strictly below their value. A nice-tier
  author tied with the must-tier max scores ~100; tied with the min
  scores ~0.
- Empty must-tier (shouldn't happen, but defensive) -> all rows get
  ``50.0`` as a neutral sentinel so the dashboard doesn't NaN out.

Design choices worth calling out:

- **No checkpointing.** This is a single-shot transformation of on-disk
  CSVs; re-running overwrites the output. Phase 1-4 checkpoints already
  protect the expensive (API-bound) work.
- **Trials CSV is optional** (spec §7.3). Missing or headers-only file
  -> ``trial_count = 0`` for every author.
- **Ordering is alphabetical by acd_name** for deterministic diffs.

CLI::

    python scripts/05_compute_stats.py [--input-dir PATH] [--output PATH]
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.utils.metrics import (  # noqa: E402
    calc_author_position_pct,
    calc_career_span,
    calc_h_index,
    calc_i10_index,
    calc_intl_collab_rate,
    calc_oa_rate,
)

logger = logging.getLogger("acd.phase5")


# --------------------------------------------------------------------------- #
# Output schema — locked order; dashboard code reads by position.
# --------------------------------------------------------------------------- #

OUTPUT_COLUMNS: tuple[str, ...] = (
    "acd_name",
    "priority",
    "pub_count",
    "citation_count",
    "h_index",
    "i10_index",
    "fwci_mean",
    "fwci_median",
    "oa_rate",
    "intl_collab_rate",
    "first_author_pct",
    "last_author_pct",
    "grants_count",
    "first_year",
    "last_year",
    "trial_count",
    "rehab_pub_count",
    "rehab_relevance_pct",
    "pub_count_pctile",
    "citation_count_pctile",
    "h_index_pctile",
    "oa_rate_pctile",
    "intl_collab_rate_pctile",
    "grants_count_pctile",
)

# Metrics that get a must-tier percentile companion column.
_PCTILE_METRICS: tuple[str, ...] = (
    "pub_count",
    "citation_count",
    "h_index",
    "oa_rate",
    "intl_collab_rate",
    "grants_count",
)


@dataclass
class RunResult:
    """Summary returned to the caller and the test suite."""

    authors: int
    must_authors: int
    nice_authors: int
    output_path: Path


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #


def _read_trials(path: Path) -> pd.DataFrame:
    """Load ``clinical_trials.csv`` or return an empty frame.

    Phase 4 is optional — the file may not exist, or may be headers-only.
    Either is a valid "no trials" state; we return a frame with a
    ``acd_name`` column so ``groupby`` downstream still works.
    """
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame({"acd_name": pd.Series(dtype=str)})
    try:
        df = pd.read_csv(path, on_bad_lines="warn", dtype=str)
    except pd.errors.EmptyDataError:
        return pd.DataFrame({"acd_name": pd.Series(dtype=str)})
    if "acd_name" not in df.columns:
        return pd.DataFrame({"acd_name": pd.Series(dtype=str)})
    return df


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def _rehab_count(pub_rows: pd.DataFrame) -> int:
    """Count rehab-relevant publications for an author."""
    if "is_rehab_relevant" not in pub_rows.columns:
        return 0
    col = pub_rows["is_rehab_relevant"]
    return int(col.apply(
        lambda x: 1 if x is True or str(x).strip().lower() == "true" else 0
    ).sum())


def _per_author_stats(
    acd_name: str,
    pub_rows: pd.DataFrame,
    n_grants: int,
    n_trials: int,
) -> dict[str, object]:
    """Compute the raw (pre-pctile) aggregate row for one author."""
    if len(pub_rows) == 0:
        return {
            "acd_name": acd_name,
            "pub_count": 0,
            "citation_count": 0,
            "h_index": 0,
            "i10_index": 0,
            "fwci_mean": float("nan"),
            "fwci_median": float("nan"),
            "oa_rate": 0.0,
            "intl_collab_rate": 0.0,
            "first_author_pct": 0.0,
            "last_author_pct": 0.0,
            "grants_count": n_grants,
            "first_year": 0,
            "last_year": 0,
            "trial_count": n_trials,
            "rehab_pub_count": 0,
            "rehab_relevance_pct": 0.0,
        }

    citations = pd.to_numeric(pub_rows["Citations"], errors="coerce").fillna(0).astype(int).tolist()
    fwci = pd.to_numeric(pub_rows.get("FWCI"), errors="coerce")
    first_year, last_year = calc_career_span(pub_rows["Publication_Year"])

    return {
        "acd_name": acd_name,
        "pub_count": int(len(pub_rows)),
        "citation_count": int(sum(citations)),
        "h_index": calc_h_index(citations),
        "i10_index": calc_i10_index(citations, threshold=10),
        "fwci_mean": float(fwci.mean()) if fwci.notna().any() else float("nan"),
        "fwci_median": float(fwci.median()) if fwci.notna().any() else float("nan"),
        "oa_rate": calc_oa_rate(pub_rows),
        "intl_collab_rate": calc_intl_collab_rate(pub_rows["Authors_Countries"]),
        "first_author_pct": calc_author_position_pct(pub_rows["author_position"], "first"),
        "last_author_pct": calc_author_position_pct(pub_rows["author_position"], "last"),
        "grants_count": n_grants,
        "first_year": first_year,
        "last_year": last_year,
        "trial_count": n_trials,
        "rehab_pub_count": int(_rehab_count(pub_rows)),
        "rehab_relevance_pct": round(
            100.0 * _rehab_count(pub_rows) / len(pub_rows), 1
        ) if len(pub_rows) > 0 else 0.0,
    }


def _apply_must_tier_pctiles(df: pd.DataFrame, metric: str) -> pd.Series:
    """Compute must-tier percentile ranks, interpolating nice-tier against must.

    See module docstring for the rationale.
    """
    pctiles = pd.Series(np.nan, index=df.index, dtype=float)
    must_mask = df["priority"] == "must"
    must_df = df[must_mask]
    nice_df = df[~must_mask]

    if len(must_df) == 0:
        pctiles[:] = 50.0
        return pctiles

    must_ranks = must_df[metric].rank(method="average", pct=True) * 100.0
    pctiles.loc[must_df.index] = must_ranks

    if len(nice_df) > 0:
        must_values = must_df[metric].dropna().to_numpy()
        if len(must_values) == 0:
            pctiles.loc[nice_df.index] = 50.0
        else:
            def _interp(v: object) -> float:
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    return 50.0
                return float((must_values < v).sum()) / float(len(must_values)) * 100.0

            pctiles.loc[nice_df.index] = nice_df[metric].map(_interp)

    return pctiles


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #


def run(*, input_dir: Path, output_path: Path) -> RunResult:
    """Run Phase 5 — writes ``author_summary_stats.csv``."""
    input_dir = Path(input_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    authors = pd.read_csv(input_dir / "authors_resolved.csv", dtype=str).fillna("")
    pubs = pd.read_csv(input_dir / "publications.csv")
    links = pd.read_csv(input_dir / "author_works_link.csv", dtype=str).fillna("")
    funding_path = input_dir / "funding.csv"
    funding = pd.read_csv(funding_path, dtype=str).fillna("") if funding_path.exists() else pd.DataFrame()
    trials = _read_trials(input_dir / "clinical_trials.csv")

    # Join links -> pubs so every per-author row has the publication's
    # metrics plus the (author, work)-specific author_position.
    pubs_indexed = pubs.set_index("Unique ID")
    link_metrics_cols = [c for c in ("Citations", "FWCI", "Open_Access", "Authors_Countries", "Publication_Year", "is_rehab_relevant") if c in pubs_indexed.columns]
    joined = links.merge(
        pubs_indexed[link_metrics_cols],
        left_on="openalex_work_id",
        right_index=True,
        how="left",
    )

    # Distinct-award counts per author. The award key is a composite
    # (funder_id, funder_award_id, award_id) -- this matches the
    # Phase 3 row granularity. An empty funding frame -> empty Series.
    if len(funding) > 0:
        funding_keyed = funding.assign(
            _award_key=funding["funder_id"].astype(str) + "|"
            + funding["funder_award_id"].astype(str) + "|"
            + funding["award_id"].astype(str)
        )
        grants_per_author = funding_keyed.groupby("acd_name")["_award_key"].nunique()
    else:
        grants_per_author = pd.Series(dtype=int)

    trials_per_author = trials.groupby("acd_name").size() if len(trials) > 0 else pd.Series(dtype=int)

    rows: list[dict[str, object]] = []
    for acd_name in authors["acd_name"]:
        author_pubs = joined[joined["acd_name"] == acd_name]
        n_grants = int(grants_per_author.get(acd_name, 0))
        n_trials = int(trials_per_author.get(acd_name, 0))
        rows.append(_per_author_stats(acd_name, author_pubs, n_grants, n_trials))

    stats = pd.DataFrame(rows)
    # Merge priority back in.
    stats = stats.merge(authors[["acd_name", "priority"]], on="acd_name", how="left")

    # Compute percentiles per metric.
    for metric in _PCTILE_METRICS:
        stats[f"{metric}_pctile"] = _apply_must_tier_pctiles(stats, metric)

    # Column order + deterministic sort.
    stats = stats.reindex(columns=list(OUTPUT_COLUMNS))
    stats = stats.sort_values("acd_name", kind="stable").reset_index(drop=True)
    stats.to_csv(output_path, index=False)

    must_count = int((stats["priority"] == "must").sum())
    nice_count = int((stats["priority"] == "nice").sum())
    logger.info(
        "Phase 5 complete: %d authors (%d must, %d nice) -> %s",
        len(stats), must_count, nice_count, output_path,
    )
    return RunResult(
        authors=len(stats),
        must_authors=must_count,
        nice_authors=nice_count,
        output_path=output_path,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Phase 5: compute per-author summary statistics.",
    )
    p.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/processed"),
        help="Directory containing phase 1-4 output CSVs.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/author_summary_stats.csv"),
        help="Where to write author_summary_stats.csv.",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _build_parser().parse_args(argv)
    run(input_dir=args.input_dir, output_path=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
