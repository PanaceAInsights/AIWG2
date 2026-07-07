"""Pure helper functions used by Phase 5 — no I/O, no state.

Each function takes a small, well-typed input (a list of ints, a pandas
Series, or a DataFrame) and returns a scalar. Keeping them pure means:

- **Trivial to unit-test** — no temp dirs, no fixtures, no mocks.
- **Cheap to compose** — Phase 5's orchestrator wires them together in
  a single ``groupby(rams_name).apply(...)`` without worrying about
  hidden state.
- **Reusable** — the dashboard (R Shiny) computes the same metrics on
  the fly for filtered subsets; keeping the reference implementation
  here in Python makes cross-stack audits easy (same name, same math).

All functions are NaN-tolerant: empty inputs return a defensible zero
(``0``, ``0.0``, or ``(0, 0)``) rather than raising. Phase 5 assumes
this so an author with zero publications still produces a valid row.
"""
from __future__ import annotations

from typing import Sequence

import pandas as pd


__all__ = [
    "calc_h_index",
    "calc_i10_index",
    "calc_oa_rate",
    "calc_intl_collab_rate",
    "calc_author_position_pct",
    "calc_career_span",
]


# --------------------------------------------------------------------------- #
# h-index and i10
# --------------------------------------------------------------------------- #


def calc_h_index(citations: Sequence[int]) -> int:
    """Compute the h-index.

    The h-index is the largest integer ``h`` such that the author has
    ``h`` papers, each cited at least ``h`` times. Equivalent formulation
    used here: sort citations descending, walk through, and return the
    largest ``i`` (1-indexed) for which ``sorted_citations[i-1] >= i``.

    Parameters
    ----------
    citations:
        Per-work citation counts. Order does not matter.

    Returns
    -------
    int
        The h-index, or ``0`` for empty input.
    """
    if not citations:
        return 0
    # Sort descending; enumerate from 1 for the h-index rank.
    sorted_desc = sorted((int(c) for c in citations), reverse=True)
    h = 0
    for i, c in enumerate(sorted_desc, start=1):
        if c >= i:
            h = i
        else:
            break
    return h


def calc_i10_index(citations: Sequence[int], threshold: int = 10) -> int:
    """Count the papers with at least ``threshold`` citations.

    Google Scholar's original i10 uses ``threshold=10``, but the function
    is parameterised so callers can compute i5 / i20 variants cheaply.
    """
    if not citations:
        return 0
    return sum(1 for c in citations if int(c) >= threshold)


# --------------------------------------------------------------------------- #
# Open-access rate
# --------------------------------------------------------------------------- #


def _coerce_bool(value: object) -> bool | None:
    """Coerce a CSV-loaded value to a tri-state bool (``True``/``False``/``None``).

    pandas reads the ``Open_Access`` column as either a native bool
    (if ``dtype`` was preserved) or as strings ``"True"`` / ``"False"``
    / ``""`` depending on how the CSV was written. We normalise both.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # NaN -> None; any finite numeric -> truthiness.
        if isinstance(value, float) and value != value:  # NaN check
            return None
        return bool(value)
    s = str(value).strip().lower()
    if s in {"true", "1", "yes", "t"}:
        return True
    if s in {"false", "0", "no", "f"}:
        return False
    return None  # empty string, "nan", unknown -> missing


def calc_oa_rate(df: pd.DataFrame, col: str = "Open_Access") -> float:
    """Fraction of rows where ``col`` is truthy. Empty / all-NaN -> 0.0."""
    if col not in df.columns or len(df) == 0:
        return 0.0
    coerced = df[col].map(_coerce_bool)
    total = coerced.notna().sum()
    if total == 0:
        return 0.0
    # Count True values explicitly against the sum of known entries.
    true_count = (coerced == True).sum()  # noqa: E712 - explicit compare for clarity
    return float(true_count) / float(total)


# --------------------------------------------------------------------------- #
# International collaboration
# --------------------------------------------------------------------------- #


def calc_intl_collab_rate(
    countries_series: pd.Series,
    local_codes: set[str] | None = None,
) -> float:
    """Fraction of rows whose country list contains ≥1 non-local country.

    ``countries_series`` holds pipe-joined ISO-3166 alpha-2 codes (e.g.
    ``"AU|NZ|US"``). An entry is "international" if, after stripping
    ``local_codes`` from its set, anything remains. NaN / empty strings
    count as "not international" (no signal = no collab).
    """
    if local_codes is None:
        local_codes = {"AU", "NZ"}
    if len(countries_series) == 0:
        return 0.0

    def _is_intl(raw: object) -> bool:
        if raw is None:
            return False
        if isinstance(raw, float) and raw != raw:  # NaN
            return False
        s = str(raw).strip()
        if not s:
            return False
        codes = {c.strip().upper() for c in s.split("|") if c.strip()}
        return bool(codes - {c.upper() for c in local_codes})

    intl_count = int(countries_series.map(_is_intl).sum())
    return intl_count / len(countries_series)


# --------------------------------------------------------------------------- #
# Author position
# --------------------------------------------------------------------------- #


def calc_author_position_pct(positions: pd.Series, target: str) -> float:
    """Fraction of ``positions`` equal to ``target`` (case-sensitive)."""
    if len(positions) == 0:
        return 0.0
    return float((positions == target).sum()) / float(len(positions))


# --------------------------------------------------------------------------- #
# Career span
# --------------------------------------------------------------------------- #


def calc_career_span(years: pd.Series) -> tuple[int, int]:
    """Return ``(first_year, last_year)``, ignoring NaNs.

    Empty or all-NaN input returns ``(0, 0)`` — a sentinel that the
    dashboard renders as "unknown" rather than propagating NaN through
    ``max(last_year) - min(first_year)``.
    """
    if len(years) == 0:
        return (0, 0)
    numeric = pd.to_numeric(years, errors="coerce").dropna()
    if len(numeric) == 0:
        return (0, 0)
    return (int(numeric.min()), int(numeric.max()))
