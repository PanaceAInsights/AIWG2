"""Pure scoring utilities for resolving RMSANZ physicians to OpenAlex authors.

The OpenAlex ``/authors?search=...`` endpoint returns a ranked list of
candidates for any name. For common Anglophone names ("Michael Smith")
that list may contain a dozen plausible matches in multiple countries.
This module picks the right one — or flags the match as ``not_found`` so
the orchestrator can surface it for manual triage.

The three public functions are pure: no HTTP, no file I/O. The
orchestrator (``scripts/02_resolve_authors.py``) fetches candidates via
``OpenAlexClient`` and calls :func:`resolve_author`.

Scoring weights live in the plan (spec §4.2). Brief summary:

- Exact normalised name match:                 +40
- Fuzzy token_set_ratio >= 85 (non-exact):     +25
- AU/NZ country on any institution:            +30
- works_count > 0:                             +10
- Log bonus for prolific authors, capped:      +log2(works_count+1), max 20
- State keyword present in institution name:   +10

Confidence thresholds: >=70 high, 50-69 medium, 30-49 low, <30 not_found.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, NamedTuple

from rapidfuzz import fuzz

# --------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------- #

# Case-insensitive title prefixes. Ordered so longer phrases match before
# their shorter substrings (e.g. "Associate Professor" before "Prof").
_TITLE_PATTERN = re.compile(
    r"""
    ^\s*(?:
        associate\s+professor|
        assoc\.?\s*prof\.?|
        a/prof\.?|
        professor|
        prof\.?|
        dr\.?|
        mr\.?|
        mrs\.?|
        ms\.?|
        miss
    )\s+
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Case-insensitive post-nominal tokens. Matched at word boundaries, with
# optional preceding punctuation (comma, period, whitespace). We iterate
# the sub so that "Ian Cameron MBBS, FRACP, PhD" strips all three.
_POSTNOMINAL_PATTERN = re.compile(
    r"""
    \b(?:
        AM|OAM|FAFRM|FRACP|FRCP|FRCPE|FRACGP|
        PhD|MD|MBBS|MRCP|
        BSc\.?|MSc\.?|BMed
    )\b\.?
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Punctuation to drop outright during normalisation. Commas are handled
# separately (used as the "Last, First" delimiter before being dropped).
_PUNCT_PATTERN = re.compile(r"[.()\[\]\"']+")

# Collapse any run of whitespace to a single space.
_WHITESPACE_PATTERN = re.compile(r"\s+")

# AU state abbreviations mapped to keywords we expect to find in an
# OpenAlex institution display_name. We search for both the abbreviation
# and the standard expansion so "University of Sydney, NSW" and
# "University of Sydney, New South Wales" both count.
_STATE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "NSW": ("new south wales", "nsw"),
    "VIC": ("victoria", "vic"),
    "QLD": ("queensland", "qld"),
    "SA":  ("south australia",),     # "sa" alone is too noisy
    "WA":  ("western australia",),   # "wa" alone is too noisy
    "TAS": ("tasmania", "tas"),
    "ACT": ("australian capital territory", "canberra"),
    "NT":  ("northern territory",),  # "nt" alone is too noisy
}

# NZ-ish state strings we silently ignore for state matching (spec §4.2).
_NZ_STATES = frozenset({"NZ", "NEW ZEALAND"})

# Countries whose authors we treat as "local" for the affiliation bonus.
_LOCAL_COUNTRIES = frozenset({"AU", "NZ"})

# Fuzzy-match threshold — see spec §4.2.
_FUZZY_THRESHOLD = 85

# Confidence band cutoffs.
_THRESHOLD_HIGH = 70
_THRESHOLD_MEDIUM = 50
_THRESHOLD_LOW = 30

# Scoring weights (see module docstring for the full rubric)
_WEIGHT_EXACT_NAME = 40
_WEIGHT_FUZZY_NAME = 25
_WEIGHT_LOCAL_COUNTRY = 30       # AU or NZ institution
_WEIGHT_WORKS_BASE = 10          # any work exists
_WEIGHT_WORKS_BONUS_CAP = 20     # log-scaled prolific-author bonus cap
_WEIGHT_STATE_MATCH = 10

# Alternatives window — candidates within this many points of the winner
# are returned as alternative_ids for manual triage.
_ALTERNATIVE_SCORE_GAP = 10


class NameMatchResult(NamedTuple):
    """Captured name-match signals for one candidate.

    Recorded once during scoring so :func:`_determine_method` can classify
    the winning match without re-running normalisation or rapidfuzz.
    """

    is_exact: bool
    best_fuzzy: float


# --------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------- #


def normalise_name(name: str) -> str:
    """Return a lowercased, diacritic-folded, title-stripped form of ``name``.

    Handles the grab-bag of formats we see in the RMSANZ register:

    - Honorific prefixes: ``Dr``, ``Prof``, ``A/Prof``, ``Associate Professor``, …
    - Post-nominal chains: ``AM``, ``OAM``, ``FAFRM``, ``FRACP``, ``PhD``, …
    - Comma-inverted form: ``Cameron, Ian D.`` → ``ian d cameron``.
    - Diacritics via NFKD fold: ``Müller`` → ``muller``.
    - Free punctuation and whitespace.

    Non-string or empty inputs return an empty string rather than raising —
    the orchestrator will pass this through to ``resolve_author`` which
    treats it as an unmatchable record.
    """
    if not name or not isinstance(name, str):
        return ""

    # 1. Unicode fold: "Müller" -> "Muller".
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()

    # 2. If the name is comma-inverted ("Smith, John"), swap before any
    # further cleaning so post-nominal stripping doesn't chew on the
    # comma-delimited segment as if it were the surname.
    if "," in text:
        # Split on the FIRST comma only — honours "Smith, John, AM" by
        # swapping "Smith" with "John, AM" so the post-nominal stripper
        # still has a clean pass.
        head, _, tail = text.partition(",")
        text = f"{tail.strip()} {head.strip()}"

    # 3. Strip titles from the front. Loop to catch chained titles like
    # "Dr Prof Ian Cameron" (rare, but cheap to handle).
    while True:
        new_text = _TITLE_PATTERN.sub("", text)
        if new_text == text:
            break
        text = new_text

    # 4. Strip post-nominals anywhere in the string. Multiple passes
    # until stable — covers "Ian Cameron MBBS, FRACP, PhD".
    while True:
        new_text = _POSTNOMINAL_PATTERN.sub("", text)
        if new_text == text:
            break
        text = new_text

    # 5. Drop remaining punctuation (periods, parens, etc.) and commas.
    text = _PUNCT_PATTERN.sub(" ", text)
    text = text.replace(",", " ")

    # 6. Collapse whitespace, lowercase, trim.
    text = _WHITESPACE_PATTERN.sub(" ", text).strip().lower()

    return text


# --------------------------------------------------------------------- #
# Candidate scoring
# --------------------------------------------------------------------- #


def _candidate_names(candidate: dict[str, Any]) -> list[str]:
    """Return the canonical name form(s) we'll score against for this candidate.

    Intentionally narrow: returns ONLY ``display_name``.
    ``display_name_alternatives`` is deliberately excluded.

    **Why alternatives are untrusted:** OpenAlex aggregates works
    authored by different real people under a single author record
    whenever their names collide on a common surname. The resulting
    ``display_name_alternatives`` list mixes spelling variants of the
    canonical author with wholly unrelated names attached via the
    aggregation. A live Phase 1 resolution run produced an 8.8% false-
    positive rate (e.g. physician "Yan Zhang" → OpenAlex "Yi Zhang"
    with 2216 works, "Ibrahim Ali" → "Imran Ali", "Samantha Kennedy"
    → "Sidney H. Kennedy") because the physician's exact name appeared
    as an alternative on an otherwise-unrelated author record. The
    dual last-name + first-name token gate can't catch this class
    because the alternative IS a legitimate full match string.

    Dropping alternatives from scoring eliminates the surname-collision
    false-positive class entirely. Genuine variant spellings ("J. Smith"
    vs "Jane Smith") still match because the initial-letter expansion in
    :func:`_first_name_tokens` lets the two forms intersect, and
    ``token_set_ratio`` above threshold carries the fuzzy bonus.
    """
    display = candidate.get("display_name")
    return [display] if isinstance(display, str) else []


def _country_codes(candidate: dict[str, Any]) -> list[str]:
    """Every country code attached to this candidate, uppercased.

    Pulls from both ``last_known_institutions[*].country_code`` and
    ``affiliations[*].institution.country_code``. A missing or non-string
    code is skipped silently — OpenAlex sometimes returns ``null``.
    """
    codes: list[str] = []
    for inst in candidate.get("last_known_institutions") or []:
        code = (inst or {}).get("country_code")
        if isinstance(code, str):
            codes.append(code.upper())
    for aff in candidate.get("affiliations") or []:
        inst = (aff or {}).get("institution") or {}
        code = inst.get("country_code")
        if isinstance(code, str):
            codes.append(code.upper())
    return codes


def _institution_names(candidate: dict[str, Any]) -> list[str]:
    """Every institution display_name attached to the candidate."""
    names: list[str] = []
    for inst in candidate.get("last_known_institutions") or []:
        display = (inst or {}).get("display_name")
        if isinstance(display, str):
            names.append(display)
    for aff in candidate.get("affiliations") or []:
        inst = (aff or {}).get("institution") or {}
        display = inst.get("display_name")
        if isinstance(display, str):
            names.append(display)
    return names


def _last_name_tokens(name: str) -> set[str]:
    """Return the set of last-name tokens derived from ``name``.

    OpenAlex aggregates common names (notably Chinese surnames — Zhang,
    Li, Wang — and high-frequency Anglophone surnames). A single author
    profile's ``display_name_alternatives`` often contains wholly
    different people's names ("Yan Zhang" and "Yi Zhang" can both show
    up on the same record). Exact/fuzzy name matching alone therefore
    over-awards the name bonus to false positives.

    This helper produces the set used to gate name-match scoring:

    - Normalise via :func:`normalise_name` (title/post-nominal stripping,
      NFKD diacritic fold, comma-inversion, lowercasing).
    - Tokenise on whitespace.
    - If multiple tokens remain, return ``{final_token}``.
    - If exactly one token remains (mononym or surname-only), return
      ``{that_token}``.
    - Empty input yields the empty set.

    Examples::

        _last_name_tokens("ian cameron")        -> {"cameron"}
        _last_name_tokens("ian david cameron")  -> {"cameron"}
        _last_name_tokens("yi zhang")           -> {"zhang"}
        _last_name_tokens("cameron")            -> {"cameron"}
        _last_name_tokens("")                   -> set()
    """
    normalised = normalise_name(name)
    if not normalised:
        return set()
    tokens = normalised.split()
    if not tokens:
        return set()
    return {tokens[-1]}


def _first_name_tokens(name: str) -> set[str]:
    """Return the set of first-name tokens (with initial variants) from ``name``.

    Companion gate to :func:`_last_name_tokens`. Surname collisions are
    the dominant failure mode of the OpenAlex resolver: the last-name
    guard alone still allowed a live Phase 1 run to produce 35/297
    (11.8%) high-confidence matches that shared ONLY the surname
    ("Yan Zhang" → "Yi Zhang" with 2216 works). This helper enables a
    companion first-name gate in :func:`_best_name_match`.

    Behaviour:

    - Normalise via :func:`normalise_name` (title/post-nominal stripping,
      NFKD diacritic fold, comma-inversion, lowercasing).
    - Tokenise on whitespace.
    - Return a set containing:
        * the FIRST token (always, if any tokens exist),
        * the SECOND token if there are ≥3 tokens — middle-name
          tolerance, because OpenAlex commonly indexes a person
          "Ian David Cameron" as just "David Cameron" or "I. D. Cameron",
        * plus the single-letter initial of every included token.

    - For a single-token name (mononym or surname-only input) the helper
      returns ``{token, first_letter}`` — mirroring :func:`_last_name_tokens`'s
      mononym behaviour so the dual-gate collapses to one token on
      mononym inputs.
    - Empty or whitespace-only input yields the empty set.

    The initial-letter expansion is what lets "Ian Cameron" match
    "I. Cameron": the physician's set becomes ``{"ian", "i"}`` and the
    candidate's ``{"i"}``; they intersect on ``"i"``. Without this
    expansion an initialised first-name form would be locked out of
    scoring.

    Examples::

        _first_name_tokens("ian cameron")              -> {"ian", "i"}
        _first_name_tokens("ian david cameron")        -> {"ian", "i", "david", "d"}
        _first_name_tokens("i cameron")                -> {"i"}
        _first_name_tokens("i d cameron")              -> {"i", "d"}
        _first_name_tokens("maria fernanda silva")     -> {"maria", "m", "fernanda", "f"}
        _first_name_tokens("cameron")                  -> {"cameron", "c"}
        _first_name_tokens("")                         -> set()
    """
    normalised = normalise_name(name)
    if not normalised:
        return set()
    tokens = normalised.split()
    if not tokens:
        return set()

    # Always include the first token.
    picked: list[str] = [tokens[0]]
    # Include the second token as a middle-name tolerance hook, but ONLY
    # when ≥3 tokens remain (so "Ian Cameron" doesn't list "cameron" as
    # a first-name variant — a two-token name is strictly first-then-last).
    if len(tokens) >= 3:
        picked.append(tokens[1])

    # Expand with single-letter initials so "Ian" matches "I." and vice
    # versa. A token that's already one character is its own initial.
    result: set[str] = set()
    for tok in picked:
        if not tok:
            continue
        result.add(tok)
        result.add(tok[0])
    return result


def _best_name_match(physician_norm: str, candidate: dict[str, Any]) -> NameMatchResult:
    """Return ``NameMatchResult(is_exact, best_fuzzy_score)`` for the physician vs candidate.

    Compares ONLY against ``display_name``. ``display_name_alternatives``
    is untrusted because OpenAlex aggregates common surnames across
    different people — a physician's exact name can appear as an alt
    on a wholly unrelated author's record, breaking exact-name scoring.
    See :func:`_candidate_names` for the full rationale and the live
    Phase 1 FP evidence (8.8% rate before this fix).

    The fuzzy score is computed with :func:`rapidfuzz.fuzz.token_set_ratio`
    over the single ``display_name`` form. An empty ``physician_norm``
    returns ``NameMatchResult(False, 0.0)`` — no name to match against.

    **Dual name-token gate:** the ``display_name`` is scored only when
    BOTH the last-name token set AND the first-name token set intersect
    the physician's. A live Phase 1 run surfaced 35/297 (11.8%) false
    positives where the surname matched but the first name differed
    ("Yan Zhang" → "Yi Zhang" with 2216 works, "Ibrahim Ali" → "Imran
    Ali", "Samantha Kennedy" → "Sidney H. Kennedy"). The first-name
    gate rejects those. See :func:`_first_name_tokens` for the exact
    tokens considered (including single-letter initials so "Ian" vs
    "I." still matches). A display_name failing either gate scores 0
    on the name component — it cannot flip ``is_exact`` nor raise
    ``best_fuzzy``.
    """
    if not physician_norm:
        return NameMatchResult(False, 0.0)

    physician_last = _last_name_tokens(physician_norm)
    physician_first = _first_name_tokens(physician_norm)

    is_exact = False
    best_fuzzy = 0.0
    for raw_name in _candidate_names(candidate):
        cand_norm = normalise_name(raw_name)
        if not cand_norm:
            continue
        # Dual gate: skip forms that don't share a surname token AND a
        # first-name token with the physician. If either side has no
        # tokens at all, skip — we have no basis to assert a match.
        candidate_last = _last_name_tokens(cand_norm)
        candidate_first = _first_name_tokens(cand_norm)
        if not physician_last or not candidate_last:
            continue
        if not physician_first or not candidate_first:
            continue
        if physician_last.isdisjoint(candidate_last):
            continue
        if physician_first.isdisjoint(candidate_first):
            continue

        if cand_norm == physician_norm:
            is_exact = True
        score = fuzz.token_set_ratio(physician_norm, cand_norm)
        if score > best_fuzzy:
            best_fuzzy = score
    return NameMatchResult(is_exact, best_fuzzy)


def _works_bonus(works_count: Any) -> int:
    """Return the works-count score contribution.

    +10 flat for works_count > 0, plus a log2 bonus clamped at 20 so that
    a single-paper author doesn't look identical to a 500-paper one, but
    very prolific authors also don't swamp the scoring.

    Defensively coerces strings and floats to int — OpenAlex returns int
    today, but upstream changes or cached payloads might not. Malformed
    inputs return 0 silently.
    """
    try:
        wc = int(works_count)  # handles int, float, numeric str
    except (TypeError, ValueError):
        return 0
    if wc <= 0:
        return 0
    return _WEIGHT_WORKS_BASE + min(
        _WEIGHT_WORKS_BONUS_CAP, int(math.log2(wc + 1))
    )


def _state_match(physician_state: str | None, institution_names: list[str]) -> bool:
    """Return True if any institution name contains the physician's state keyword."""
    if not physician_state:
        return False
    state_upper = physician_state.strip().upper()
    if state_upper in _NZ_STATES:
        # Spec §4.2: skip silently for NZ-ish physician state.
        return False
    keywords = _STATE_KEYWORDS.get(state_upper)
    if not keywords:
        return False
    for inst_name in institution_names:
        lower = inst_name.lower()
        for kw in keywords:
            if kw in lower:
                return True
    return False


def _score_candidate_preprocessed(
    physician_norm: str,
    physician_state: str | None,
    candidate: dict[str, Any],
) -> tuple[int, NameMatchResult]:
    """Score one candidate given a pre-normalised physician name.

    Returns ``(score, name_match_info)`` so the caller can reuse the
    name-match signals for method classification without re-running
    normalisation or rapidfuzz.
    """
    name_match = _best_name_match(physician_norm, candidate)

    score = 0

    # Name component — exact OR fuzzy, never both.
    if name_match.is_exact:
        score += _WEIGHT_EXACT_NAME
    elif name_match.best_fuzzy >= _FUZZY_THRESHOLD:
        score += _WEIGHT_FUZZY_NAME

    # Country component — single +30, not per-institution cumulative.
    codes = _country_codes(candidate)
    if any(c in _LOCAL_COUNTRIES for c in codes):
        score += _WEIGHT_LOCAL_COUNTRY

    # Works component.
    score += _works_bonus(candidate.get("works_count", 0))

    # State component.
    if _state_match(physician_state, _institution_names(candidate)):
        score += _WEIGHT_STATE_MATCH

    return score, name_match


def score_candidate(physician: dict[str, Any], candidate: dict[str, Any]) -> int:
    """Return the integer score for one OpenAlex candidate vs one physician.

    See module docstring for the weight breakdown. This function is pure;
    it does not mutate either input. Thin wrapper around
    :func:`_score_candidate_preprocessed` that normalises the physician
    name once — prefer calling the preprocessed form directly when
    scoring many candidates against the same physician.
    """
    physician_norm = normalise_name(physician.get("name") or "")
    score, _ = _score_candidate_preprocessed(
        physician_norm, physician.get("state"), candidate
    )
    return score


# --------------------------------------------------------------------- #
# Top-level resolution
# --------------------------------------------------------------------- #


def _strip_openalex_id(raw: Any) -> str | None:
    """Return just the bare 'A…' identifier from a URL or id."""
    if not isinstance(raw, str) or not raw:
        return None
    # URLs look like "https://openalex.org/A5023888391".
    return raw.rsplit("/", 1)[-1]


def _determine_method(name_match: NameMatchResult) -> str:
    """Classify what decided the winning match.

    Preference order when multiple signals contribute:
    - exact_name if the winner's name exactly matches the physician's.
    - fuzzy_name if a fuzzy match (>= threshold) contributed.
    - affiliation_match if only country/works/state carried the score.

    Reads directly from the name-match result recorded during scoring —
    no re-normalisation, no re-running rapidfuzz.
    """
    if name_match.is_exact:
        return "exact_name"
    if name_match.best_fuzzy >= _FUZZY_THRESHOLD:
        return "fuzzy_name"
    # Name contributed nothing but score is above threshold.
    return "affiliation_match"


def resolve_author(
    physician: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pick the best OpenAlex candidate for ``physician`` and describe it.

    See the plan's Public API section for the full return shape. Empty
    ``candidates`` or a winning score below the ``low`` threshold both
    collapse to ``confidence="not_found"`` with ``openalex_id=None`` so
    the orchestrator has a consistent sentinel to branch on.
    """
    not_found: dict[str, Any] = {
        "openalex_id": None,
        "openalex_display_name": None,
        "confidence": "not_found",
        "score": 0,
        "alternative_ids": [],
        "method": "not_found",
    }

    if not candidates:
        return not_found

    # Normalise the physician's name ONCE for the whole batch. Each
    # candidate then gets scored with the pre-computed form, and the
    # name-match signals are recorded so _determine_method can reuse
    # them without re-running rapidfuzz on the winner.
    physician_norm = normalise_name(physician.get("name") or "")
    physician_state = physician.get("state")

    scored: list[tuple[int, dict[str, Any], NameMatchResult]] = []
    for c in candidates:
        score, name_match = _score_candidate_preprocessed(
            physician_norm, physician_state, c
        )
        scored.append((score, c, name_match))

    # Sort descending by score. Ties are stable — the input order wins,
    # which matches OpenAlex's own relevance ranking.
    scored.sort(key=lambda triple: triple[0], reverse=True)

    top_score, winner, winner_match = scored[0]

    if top_score < _THRESHOLD_LOW:
        return not_found

    # Confidence band.
    if top_score >= _THRESHOLD_HIGH:
        confidence = "high"
    elif top_score >= _THRESHOLD_MEDIUM:
        confidence = "medium"
    else:
        confidence = "low"

    # Alternatives: other candidates within _ALTERNATIVE_SCORE_GAP of the winner.
    alternative_ids: list[str] = []
    for other_score, other_candidate, _ in scored[1:]:
        if top_score - other_score <= _ALTERNATIVE_SCORE_GAP:
            alt_id = _strip_openalex_id(other_candidate.get("id"))
            if alt_id is not None:
                alternative_ids.append(alt_id)

    method = _determine_method(winner_match)

    display = winner.get("display_name")
    return {
        "openalex_id": _strip_openalex_id(winner.get("id")),
        "openalex_display_name": display if isinstance(display, str) else None,
        "confidence": confidence,
        "score": top_score,
        "alternative_ids": alternative_ids,
        "method": method,
    }
