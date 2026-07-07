"""Reconstruct plain-text abstracts from OpenAlex's inverted-index format.

OpenAlex stores abstracts as ``{word: [positions...]}`` rather than as a
plain string. This module is a pure decoder — no I/O, no fancy tokenisation.

Gaps in the position space (e.g. positions ``[0, 2]`` with no word at 1)
are silently collapsed; we do not invent padding tokens.
"""
from __future__ import annotations


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """Turn an OpenAlex inverted index into a space-joined string.

    Parameters
    ----------
    inverted_index:
        Either ``None`` / empty dict (returns ``""``) or a mapping of word
        to the integer positions at which that word appears.

    Returns
    -------
    str
        Space-separated words in positional order. Repeated positions per
        word produce repeated occurrences in the output.
    """
    if not inverted_index:
        return ""

    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))

    # Numeric sort on the integer index, not a lexical sort on a stringy key.
    positions.sort(key=lambda t: t[0])
    return " ".join(word for _, word in positions)
