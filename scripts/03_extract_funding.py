"""Phase 3: extract per-funder, per-award funding rows from Phase 2 outputs.

Pure transformation — reads the already-downloaded side-table
``works_awards_raw.csv`` together with ``author_works_link.csv``, and
emits one row per (RMSANZ author × award) pair into ``funding.csv``.
No OpenAlex calls; fully offline, idempotent, cheap to re-run.

Schema of ``funding.csv`` (8 columns):

    openalex_work_id  — from author_works_link.csv
    acd_name         — from author_works_link.csv
    funder_id         — bare OpenAlex id, e.g. ``F4320303785``
    funder_name       — funder display name
    funder_ror        — funder ROR id if present, else ``""``
    award_id          — bare OpenAlex award id (when OpenAlex exposes one)
    award_name        — award display name
    funder_award_id   — funder's internal identifier (``awards[].award_id``)

Expected Australian funders to spot-check post-live-run:

    NHMRC (National Health and Medical Research Council)
    MRFF  (Medical Research Future Fund)
    ARC   (Australian Research Council)

# TODO verify post-live-run — sanity-check that these three appear in the
# funder_name column after the first real Phase 2 download.

Design notes:

- Keyed on ``openalex_work_id`` in both sides — an inner-join on
  non-empty awards. Works without awards, or works present only in
  ``author_works_link`` (orphans), are skipped.
- The output key is ``"{acd_name}|{openalex_work_id}|{funder_id}|{award_key}"``
  where ``award_key`` prefers the OpenAlex award id, then falls back to
  ``funder_award_id``, then the award display name. This keeps re-runs
  idempotent: re-processing the same inputs appends nothing.
- Output is overwritten on each run by default — there's no API cost to
  protect against, so a clean re-run is the simplest mental model.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("acd.phase3")


FUNDING_COLUMNS: tuple[str, ...] = (
    "openalex_work_id",
    "acd_name",
    "funder_id",
    "funder_name",
    "funder_ror",
    "award_id",
    "award_name",
    "funder_award_id",
)


def _strip_openalex_url(raw: str | None) -> str:
    """Strip ``https://openalex.org/`` prefix; pass-through for bare ids."""
    if not raw:
        return ""
    for prefix in ("https://openalex.org/", "http://openalex.org/"):
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw


@dataclass
class RunResult:
    """Summary returned to the caller and the test suite."""

    authors_considered: int
    works_with_awards: int
    rows_written: int


def _load_links(path: Path) -> dict[str, list[str]]:
    """Return a mapping ``openalex_work_id -> [acd_name, ...]``.

    One work can be co-authored by multiple RMSANZ members, so the value
    is a list. We preserve input order so the funding.csv rows stay
    deterministic run-to-run (the dashboard's diff view appreciates
    this).
    """
    out: dict[str, list[str]] = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            wid = (row.get("openalex_work_id") or "").strip()
            name = (row.get("acd_name") or "").strip()
            if not wid or not name:
                continue
            out.setdefault(wid, []).append(name)
    return out


def _load_awards(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Return a mapping ``openalex_work_id -> awards list``.

    Rows whose JSON fails to parse are logged and skipped — a single
    corrupt row should not kill the whole pipeline.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            wid = (row.get("openalex_work_id") or "").strip()
            if not wid:
                continue
            raw = row.get("awards_json") or ""
            try:
                parsed = json.loads(raw) if raw else []
            except json.JSONDecodeError as exc:
                logger.warning(
                    "works_awards_raw.csv: invalid JSON for %s (%s); skipping",
                    wid, exc,
                )
                continue
            if isinstance(parsed, list) and parsed:
                out[wid] = parsed
    return out


def _award_key(award: dict[str, Any]) -> str:
    """Stable within-work tie-breaker for dedup and deterministic ordering."""
    for candidate in (
        _strip_openalex_url(award.get("id")),
        award.get("award_id") or "",
        award.get("display_name") or "",
    ):
        if candidate:
            return str(candidate)
    return ""


def _iter_funding_rows(
    links: dict[str, list[str]],
    awards_by_work: dict[str, list[dict[str, Any]]],
) -> Iterable[dict[str, Any]]:
    """Emit one funding row per (acd_name × award) for every shared work id."""
    # Inner join: both sides must know about the work.
    shared_work_ids = [wid for wid in awards_by_work if wid in links]
    for wid in shared_work_ids:
        for acd_name in links[wid]:
            for award in awards_by_work[wid]:
                yield {
                    "openalex_work_id": wid,
                    "acd_name": acd_name,
                    "funder_id": _strip_openalex_url(award.get("funder")),
                    "funder_name": award.get("funder_display_name") or "",
                    "funder_ror": award.get("funder_ror") or "",
                    "award_id": _strip_openalex_url(award.get("id")),
                    "award_name": award.get("display_name") or "",
                    "funder_award_id": award.get("award_id") or "",
                }


def run(
    *,
    input_dir: Path,
    output_path: Path,
) -> RunResult:
    """Run Phase 3 — writes ``funding.csv`` and returns a :class:`RunResult`."""
    input_dir = Path(input_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    links = _load_links(input_dir / "author_works_link.csv")
    awards_by_work = _load_awards(input_dir / "works_awards_raw.csv")

    # Overwrite-on-every-run — pure transformation, no credit cost, so the
    # simplest possible semantics. Header written unconditionally.
    rows_written = 0
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(FUNDING_COLUMNS))
        writer.writeheader()
        for row in _iter_funding_rows(links, awards_by_work):
            writer.writerow(row)
            rows_written += 1

    logger.info(
        "Phase 3 complete: acd_name×work_id pairs=%d, funded works=%d, rows=%d",
        sum(len(v) for v in links.values()),
        len(awards_by_work),
        rows_written,
    )
    return RunResult(
        authors_considered=sum(len(v) for v in links.values()),
        works_with_awards=len(awards_by_work),
        rows_written=rows_written,
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Phase 3: break out publications.csv grants into funding.csv."
    )
    p.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/processed"),
        help="Directory containing author_works_link.csv and works_awards_raw.csv.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/funding.csv"),
        help="Where to write funding.csv.",
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
