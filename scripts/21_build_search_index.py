"""Build a lightweight full-text search index for publications.

Reads publications_clean.csv and concatenates the key text fields into a
single lowercased `search_text` column. The output (~5-10 MB) enables
fast keyword/substring search without loading the full 62-column file.

Usage:
    python scripts/21_build_search_index.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"

INPUT = PROCESSED / "publications_clean.csv"
OUTPUT = PROCESSED / "publications_search_index.csv"

# Columns to concatenate into search_text
TEXT_COLS = ["Title", "Abstract", "Keywords", "MESH_Terms", "DOI", "Author_Names"]


def build_search_index() -> None:
    if not INPUT.exists():
        print(f"ERROR: input file not found: {INPUT}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {INPUT.name} ...")
    # Only read what we need
    header = pd.read_csv(INPUT, encoding="utf-8", nrows=0).columns.tolist()
    usecols = ["Unique ID", "RAMS_Author"] + [c for c in TEXT_COLS if c in header]
    df = pd.read_csv(INPUT, encoding="utf-8", low_memory=False, usecols=usecols)

    print(f"  {len(df):,} rows loaded with cols: {usecols}")

    # Build search_text: join non-null text fields, lowercase
    parts = []
    for col in TEXT_COLS:
        if col in df.columns:
            parts.append(df[col].fillna("").astype(str))
    combined = parts[0]
    for p in parts[1:]:
        combined = combined + " " + p
    df["search_text"] = combined.str.lower().str.strip()

    # Keep only the output columns
    out = df[["Unique ID", "RAMS_Author", "search_text"]].copy()

    # Write
    out.to_csv(OUTPUT, index=False, encoding="utf-8")
    size_mb = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"Written {OUTPUT.name} ({len(out):,} rows, {size_mb:.1f} MB)")


if __name__ == "__main__":
    build_search_index()
