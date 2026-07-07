"""Light-weight validators for external identifiers.

Right now this module only validates DOIs. It's intentionally a dumping
ground for similar regex-based validators (ORCID, ROR, etc.) so callers
don't need to learn five module names.
"""
from __future__ import annotations

import re

# ^10\.\d{4,}/ is the canonical DOI shape. The suffix (.+) is deliberately
# loose — the DOI spec permits just about any printable character there.
_DOI_PATTERN = re.compile(r"^10\.\d{4,}/.+$")

# OpenAlex responses wrap DOIs as URLs; strip the resolver prefix before
# matching. Cover the three prefixes we actually see in the wild.
_DOI_URL_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi.org/",
    "dx.doi.org/",
)


def validate_doi(doi: str | None) -> str:
    """Return a normalised DOI string, or ``""`` if the input is not a valid DOI.

    Normalisation steps:

    1. ``None`` / empty / whitespace-only -> ``""``.
    2. Trim leading/trailing whitespace.
    3. Strip any ``https://doi.org/`` (or similar) prefix.
    4. Match against ``^10\\.\\d{4,}/.+`` — return the match if it passes,
       ``""`` otherwise.
    """
    if doi is None:
        return ""

    candidate = doi.strip()
    if not candidate:
        return ""

    # Case-insensitive prefix match so "HTTPS://DOI.ORG/..." also works.
    lower = candidate.lower()
    for prefix in _DOI_URL_PREFIXES:
        if lower.startswith(prefix):
            candidate = candidate[len(prefix):]
            break

    if _DOI_PATTERN.match(candidate):
        return candidate
    return ""
