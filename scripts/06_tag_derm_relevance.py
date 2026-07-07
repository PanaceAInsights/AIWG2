"""Phase 6 — Tag publications with dermatology-relevance flag.

Reads publications.csv (from Phase 2) and adds an ``is_derm_relevant``
boolean column. Writes publications_clean.csv.

Uses the three-tier vocabulary from scripts/utils/derm_vocab.py:
  Tier 1 — OpenAlex Topic_Field / SubTopic / Keywords
  Tier 2 — MeSH descriptor tokens
  Tier 3 — Title / Abstract hard-signal stems

CLI::
    python scripts/06_tag_derm_relevance.py [--input-dir PATH] [--output PATH]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.utils.derm_vocab import vectorized_relevance  # noqa: E402

logger = logging.getLogger("acd.phase6")


def run(
    input_dir: Path | None = None,
    output_path: Path | None = None,
) -> dict:
    processed = input_dir or ROOT / "data" / "processed"
    out = output_path or processed / "publications_clean.csv"

    pub_path = processed / "publications.csv"
    if not pub_path.exists():
        logger.error("publications.csv not found at %s", pub_path)
        return {"tagged": 0, "derm_relevant": 0}

    logger.info("Loading publications from %s", pub_path)
    pubs = pd.read_csv(pub_path, low_memory=False)
    logger.info("Loaded %d publications", len(pubs))

    pubs["is_derm_relevant"] = vectorized_relevance(pubs)

    n_derm = int(pubs["is_derm_relevant"].sum())
    pct = n_derm / len(pubs) * 100 if len(pubs) > 0 else 0
    logger.info("Tagged %d / %d (%.1f%%) as dermatology-relevant", n_derm, len(pubs), pct)

    pubs.to_csv(out, index=False, encoding="utf-8")
    logger.info("Wrote %s", out)

    return {"tagged": len(pubs), "derm_relevant": n_derm, "derm_pct": pct}


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Tag publications with dermatology-relevance flag.")
    p.add_argument("--input-dir", type=Path, default=None)
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args(argv)
    result = run(input_dir=args.input_dir, output_path=args.output)
    print(f"Tagged {result['tagged']} publications, {result['derm_relevant']} dermatology-relevant ({result.get('derm_pct', 0):.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
