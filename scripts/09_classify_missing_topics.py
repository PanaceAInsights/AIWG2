"""Phase 9 — Classify publications that have no OpenAlex topic assignment.

For each publication where Topic_Field is blank, applies the dermatology
taxonomy rules from scripts/utils/derm_taxonomy.py to infer SubTopic and
Topic_Field from the Title + Keywords fields.

CLI::
    python scripts/09_classify_missing_topics.py [--input PATH] [--output PATH]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.utils.derm_taxonomy import TOPIC_RULES  # noqa: E402

logger = logging.getLogger("acd.phase9")


def _classify_row(title: str, keywords: str) -> tuple[str, str]:
    """Return (SubTopic, Topic_Field) for a publication."""
    text = f"{title} {keywords}".lower()
    for subtopic, field, tokens in TOPIC_RULES:
        if any(tok in text for tok in tokens):
            return subtopic, field
    return "", ""


def run(
    input_path: Path | None = None,
    output_path: Path | None = None,
) -> dict:
    processed = ROOT / "data" / "processed"
    src = input_path or processed / "publications_clean.csv"
    dst = output_path or src  # overwrite in place

    if not src.exists():
        logger.error("Input file not found: %s", src)
        return {"classified": 0}

    pubs = pd.read_csv(src, low_memory=False)
    logger.info("Loaded %d publications from %s", len(pubs), src)

    missing_mask = (
        pubs.get("Topic_Field", pd.Series(dtype=str)).fillna("").str.strip() == ""
    )
    n_missing = int(missing_mask.sum())
    logger.info("%d publications have no Topic_Field — classifying", n_missing)

    classified = 0
    for idx in pubs[missing_mask].index:
        title = str(pubs.at[idx, "Title"] if "Title" in pubs.columns else "")
        kw    = str(pubs.at[idx, "Keywords"] if "Keywords" in pubs.columns else "")
        subtopic, field = _classify_row(title, kw)
        if field:
            if "SubTopic" in pubs.columns:
                pubs.at[idx, "SubTopic"] = subtopic
            if "Topic_Field" in pubs.columns:
                pubs.at[idx, "Topic_Field"] = field
            classified += 1

    pubs.to_csv(dst, index=False, encoding="utf-8")
    logger.info("Classified %d / %d missing-topic publications → %s", classified, n_missing, dst)

    return {"classified": classified, "n_missing": n_missing}


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Classify publications missing OpenAlex topics.")
    p.add_argument("--input", type=Path, default=None)
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args(argv)
    result = run(input_path=args.input, output_path=args.output)
    print(f"Classified {result['classified']} / {result['n_missing']} missing-topic publications")
    return 0


if __name__ == "__main__":
    sys.exit(main())
