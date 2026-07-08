"""Phase 2 orchestrator: download every RMSANZ author's works from OpenAlex.

Reads ``authors_resolved.csv`` (output of Phase 1), filters to authors
with confidence ∈ {high, medium}, sorts must-tier first, and for each
author issues a cursor-paginated ``/works`` query. Every returned work
is mapped into the 61-column schema via
:func:`scripts.utils.works_mapper.map_work_with_awards` and appended to
``publications.csv`` (deduped on ``Unique ID``). One row per
(author, work) pair is written to ``author_works_link.csv``. When the
work has non-empty ``awards``, the raw list is persisted to
``works_awards_raw.csv`` — a side-table consumed by Phase 3 so we do
not have to re-query OpenAlex for funder detail that the flat
``Grants`` column would otherwise drop (funder ROR + internal award id).

Design notes:

- **Four checkpoints**, each backed by :class:`CheckpointWriter`:
    1. ``publications.csv`` keyed on ``Unique ID`` — dedup across authors.
    2. ``author_works_link.csv`` keyed on a derived ``_link_key`` column
       (``"{acd_name}|{work_id}"``). Keeps ``CheckpointWriter`` unchanged
       while still giving us per-pair idempotency on restart.
    3. ``works_awards_raw.csv`` keyed on ``openalex_work_id`` — the raw
       ``work.awards`` list serialised to JSON. Written only for works
       whose awards list is non-empty; consumed by Phase 3.
    4. ``_completed_authors.csv`` keyed on ``openalex_author_id`` —
       tracks which authors finished cleanly so a mid-author crash
       re-processes the author from scratch (dedup on ``Unique ID`` in
       ``publications.csv`` absorbs the overlap).
- **Budget-aware.** Every /works call is counted by ``CreditBudget``; a
  :class:`BudgetExhausted` raised mid-run bails out cleanly, leaving
  partial CSVs that a next-day re-run resumes.
- Thin orchestrator (~200 lines); the heavy lifting lives in
  ``scripts.utils.works_mapper``.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import requests
from dotenv import load_dotenv
from tqdm import tqdm

# Allow "python scripts/02_download_publications.py" to import utils.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.utils.budget import BudgetExhausted, CreditBudget  # noqa: E402
from scripts.utils.checkpoint import CheckpointWriter  # noqa: E402
from scripts.utils.openalex_client import OpenAlexClient  # noqa: E402
from scripts.utils.works_mapper import (  # noqa: E402
    PUBLICATIONS_COLUMNS,
    map_work_with_awards,
)

logger = logging.getLogger("acd.phase2")


# --------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------- #

# Select string from plan Appendix A — narrows the /works payload by ~60%.
_WORKS_SELECT = (
    "id,doi,title,publication_year,cited_by_count,authorships,topics,"
    "open_access,awards,funders,fwci,cited_by_percentile_year,"
    "primary_location,type,language,is_retracted,keywords,mesh,"
    "sustainable_development_goals,counts_by_year,abstract_inverted_index,"
    "publication_date,referenced_works_count,locations_count,indexed_in,"
    "ids,apc_list,has_fulltext"
)

# Confidences we download works for. Low / not_found are skipped —
# the operator triages them separately via resolution_log.csv.
_ELIGIBLE_CONFIDENCES = {"HIGH", "REVIEW"}

# Polite delay between authors (spec §5.5) — OpenAlex polite-pool guidance.
_PER_AUTHOR_SLEEP_S = 0.1

# Default daily budget (matches CreditBudget's fallback).
_DEFAULT_DAILY_LIMIT = 100_000

# Link CSV columns — the ``_link_key`` column is derived by the orchestrator
# so CheckpointWriter can dedup on a single column without needing composite
# key support.
_LINK_COLUMNS = [
    "acd_name",
    "openalex_author_id",
    "openalex_work_id",
    "author_position",
    "is_corresponding",
    "_link_key",
]

# Per-author completion log — a one-column CSV that records which author
# ids have finished without crashing. Separate from publications.csv so
# that partial writes during a crash don't mark the author as done.
_COMPLETED_COLUMNS = ["openalex_author_id"]

# Raw awards side-channel — Phase 3 consumes this to emit funding.csv
# without re-querying /works. Keyed on openalex_work_id so a work is
# written at most once across all authors who share it.
_AWARDS_RAW_COLUMNS = ["openalex_work_id", "awards_json"]


# --------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------- #


@dataclass
class RunResult:
    """Summary returned to the caller and the test suite."""

    authors_processed: int
    authors_skipped: int
    works_written: int
    remaining_authors: int
    exhausted: bool


# --------------------------------------------------------------------- #
# Input loading
# --------------------------------------------------------------------- #


def _load_eligible_authors(
    input_path: Path, must_only: bool
) -> pd.DataFrame:
    """Read authors_resolved.csv, filter + sort for Phase 2.

    Filtering rules:
      * ``confidence`` in {high, medium}
      * non-empty ``openalex_id`` (defensive — medium rows may have it blank)
      * ``--must-only`` drops the nice tier entirely.

    Sorting: must-first, then stable by ``acd_name`` for deterministic
    resume behaviour.
    """
    df = pd.read_csv(input_path, dtype=str).fillna("")

    df = df[df["confidence"].isin(_ELIGIBLE_CONFIDENCES)]
    df = df[df["openalex_id"].str.strip() != ""]
    if must_only:
        df = df[df["priority"] == "must"]

    df["_rank"] = df["priority"].map({"must": 0, "nice": 1}).fillna(2)
    df = df.sort_values(by=["_rank", "acd_name"], kind="stable").reset_index(drop=True)
    df = df.drop(columns=["_rank"])
    return df


# --------------------------------------------------------------------- #
# Per-author processing
# --------------------------------------------------------------------- #


def _strip_author_id(raw: str) -> str:
    """Strip the OpenAlex URL prefix if present. ``A1234`` pass-through."""
    for prefix in ("https://openalex.org/", "http://openalex.org/"):
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw


def _process_author(
    *,
    acd_name: str,
    author_id: str,
    client: OpenAlexClient,
    pubs_writer: CheckpointWriter,
    links_writer: CheckpointWriter,
    awards_writer: CheckpointWriter,
) -> int:
    """Download every work for ``author_id`` and append rows to all sinks.

    Returns the number of works processed for this author (including any
    that were dedup-skipped in ``publications.csv`` — they still produce a
    link row).
    """
    bare_id = _strip_author_id(author_id)
    filter_str = f"authorships.author.id:{bare_id}"
    works_seen = 0

    for work in client.paginate(
        "/works",
        params={"filter": filter_str, "select": _WORKS_SELECT},
    ):
        works_seen += 1
        mapped = map_work_with_awards(
            work, rams_name=acd_name, rams_author_id=bare_id
        )
        row = mapped.row
        work_id = row["Unique ID"]

        # publications.csv: dedupe on Unique ID.
        pubs_writer.write_row(row)

        # works_awards_raw.csv: write only when awards is non-empty —
        # we don't want rows like (Wxxx, "[]") polluting the side-table.
        # Checkpoint dedup on openalex_work_id means co-authored works
        # serialise the awards list exactly once.
        if mapped.awards:
            awards_writer.write_row(
                {
                    "openalex_work_id": work_id,
                    "awards_json": json.dumps(mapped.awards, ensure_ascii=False),
                }
            )

        # author_works_link.csv: ALWAYS append per (author, work) pair.
        is_corresponding = False
        for authorship in work.get("authorships") or []:
            author_obj = authorship.get("author") or {}
            if _strip_author_id(author_obj.get("id") or "") == bare_id:
                is_corresponding = bool(authorship.get("is_corresponding"))
                break

        link_row = {
            "acd_name": acd_name,
            "openalex_author_id": bare_id,
            "openalex_work_id": work_id,
            "author_position": row["Author_Position"],
            "is_corresponding": is_corresponding,
            "_link_key": f"{acd_name}|{work_id}",
        }
        links_writer.write_row(link_row)

    return works_seen


# --------------------------------------------------------------------- #
# Main orchestration
# --------------------------------------------------------------------- #


def run(
    *,
    input_path: Path,
    out_dir: Path,
    session: Optional[requests.Session] = None,
    must_only: bool = False,
    limit_authors: Optional[int] = None,
    budget_limit: int = _DEFAULT_DAILY_LIMIT,
    sleep_fn: Callable[[float], None] = time.sleep,
    email: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> RunResult:
    """Run the Phase 2 pipeline. Returns a :class:`RunResult` summary.

    All outputs live under ``out_dir`` —
    ``processed/{publications.csv, author_works_link.csv, _completed_authors.csv}``
    and ``logs/{download_progress.csv, credit_usage.json}``.

    Tests pass a ``MagicMock`` session so no HTTP traffic leaks.
    """
    input_path = Path(input_path)
    out_dir = Path(out_dir)

    processed_dir = out_dir / "processed"
    logs_dir = out_dir / "logs"
    processed_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    pubs_csv = processed_dir / "publications.csv"
    links_csv = processed_dir / "author_works_link.csv"
    awards_csv = processed_dir / "works_awards_raw.csv"
    completed_csv = processed_dir / "_completed_authors.csv"
    progress_log = logs_dir / "download_progress.csv"
    credit_state = logs_dir / "credit_usage.json"

    df = _load_eligible_authors(input_path, must_only=must_only)
    if limit_authors is not None:
        df = df.head(limit_authors).reset_index(drop=True)

    total_authors = len(df)

    budget = CreditBudget(daily_limit=budget_limit, state_path=credit_state)

    client = OpenAlexClient(
        email=email or os.environ.get("OPENALEX_EMAIL", ""),
        api_key=api_key or os.environ.get("OPENALEX_API_KEY", ""),
        base_url=(
            base_url
            or os.environ.get("OPENALEX_BASE_URL")
            or "https://api.openalex.org"
        ),
        session=session if session is not None else requests.Session(),
        on_success=lambda _payload: budget.charge(1),
    )

    pubs_writer = CheckpointWriter(
        csv_path=pubs_csv,
        columns=list(PUBLICATIONS_COLUMNS),
        key_column="Unique ID",
        progress_log=progress_log,
    )
    links_writer = CheckpointWriter(
        csv_path=links_csv,
        columns=_LINK_COLUMNS,
        key_column="_link_key",
        progress_log=progress_log,
    )
    awards_writer = CheckpointWriter(
        csv_path=awards_csv,
        columns=_AWARDS_RAW_COLUMNS,
        key_column="openalex_work_id",
        progress_log=progress_log,
    )
    completed_writer = CheckpointWriter(
        csv_path=completed_csv,
        columns=_COMPLETED_COLUMNS,
        key_column="openalex_author_id",
        progress_log=progress_log,
    )

    authors_processed = 0
    authors_skipped = 0
    works_written = 0
    exhausted = False

    pbar = tqdm(df.to_dict("records"), desc="phase2", disable=None)
    try:
        for rec in pbar:
            acd_name = str(rec.get("acd_name") or "").strip()
            author_id = _strip_author_id(str(rec.get("openalex_id") or "").strip())
            if not acd_name or not author_id:
                continue

            # Skip authors already completed in a prior successful run.
            if completed_writer.has_key(author_id):
                authors_skipped += 1
                continue

            try:
                n_works = _process_author(
                    acd_name=acd_name,
                    author_id=author_id,
                    client=client,
                    pubs_writer=pubs_writer,
                    links_writer=links_writer,
                    awards_writer=awards_writer,
                )
            except BudgetExhausted:
                logger.warning(
                    "Budget exhausted while processing %r; resume next day.",
                    acd_name,
                )
                exhausted = True
                break

            completed_writer.write_row({"openalex_author_id": author_id})
            authors_processed += 1
            works_written += n_works

            pbar.set_description(
                f"authors: {authors_processed + authors_skipped}/"
                f"{total_authors} · works: {pubs_writer.count}"
            )
            sleep_fn(_PER_AUTHOR_SLEEP_S)
    finally:
        pbar.close()

    remaining = max(
        0,
        total_authors - (authors_processed + authors_skipped),
    )

    if exhausted:
        logger.warning(
            "Phase 2 halted on budget: processed=%d skipped=%d remaining=%d works=%d",
            authors_processed, authors_skipped, remaining, works_written,
        )
    else:
        logger.info(
            "Phase 2 complete: processed=%d skipped=%d works=%d",
            authors_processed, authors_skipped, works_written,
        )

    return RunResult(
        authors_processed=authors_processed,
        authors_skipped=authors_skipped,
        works_written=works_written,
        remaining_authors=remaining,
        exhausted=exhausted,
    )


# --------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Download all RMSANZ authors' works from OpenAlex.",
    )
    p.add_argument(
        "--input",
        type=Path,
        default=Path("data/processed/authors_resolved.csv"),
        help="Path to authors_resolved.csv (Phase 1 output).",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data"),
        help="Root output directory (creates processed/ and logs/).",
    )
    p.add_argument(
        "--must-only",
        action="store_true",
        help="Skip nice-tier authors (faster first pass).",
    )
    p.add_argument(
        "--limit-authors",
        type=int,
        default=None,
        help="Process only the first N eligible authors.",
    )
    p.add_argument(
        "--budget-limit",
        type=int,
        default=_DEFAULT_DAILY_LIMIT,
        help="Daily OpenAlex request budget (default: 100000).",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()
    args = _build_parser().parse_args(argv)

    result = run(
        input_path=args.input,
        out_dir=args.out_dir,
        must_only=args.must_only,
        limit_authors=args.limit_authors,
        budget_limit=args.budget_limit,
    )
    if result.exhausted:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
