"""Map a single OpenAlex ``/works`` record into the 61-column CSV row.

The row's column order matches ``FAFRM_beta_v6/data/RAMS_Rehab_Physicians_Draft.csv``
exactly — that reference header is the contract, and
``tests/test_works_mapper.py::test_column_contract_matches_reference`` is the
test that locks it down.

Design principles:

- **Pure function.** No I/O, no network, no global state. Feed it a dict
  and parameters; get a dict back. Trivially testable and fork-safe.
- **One dict with ordered keys.** Python 3.7+ preserves insertion order on
  dicts, so we write every column in the same order as the reference and
  the ``DictWriter`` at the call site honours that ordering without any
  column list being passed around.
- **Empty-string null policy.** Missing scalar values render as ``""`` —
  NEVER ``None`` and NEVER the literal string ``"None"``. Downstream
  consumers (Pandas, R ``fread``) treat ``""`` as NA, which is what we
  want.
- **Pipe-delimited parallel arrays for year columns.** ``Counts_By_Year``
  and ``Citations_By_Year`` encode as pipe-joined scalars that are parallel
  by index, matching the reference CSV
  (``FAFRM_beta_v6/data/RAMS_Rehab_Physicians_Draft.csv``):
  ``Counts_By_Year="2025|2024|2023"``, ``Citations_By_Year="7|3|7"`` — zip
  them to reconstruct ``(year, cited_by_count)`` pairs. The downstream R
  Shiny dashboard splits on ``|`` and lines them up by position.
"""
from __future__ import annotations

from typing import Any, Iterable, NamedTuple

from scripts.utils.abstract import reconstruct_abstract
from scripts.utils.validation import validate_doi


# --------------------------------------------------------------------- #
# Side-channel container — the flat row PLUS the raw awards list.
# --------------------------------------------------------------------- #


class MappedWork(NamedTuple):
    """Output of :func:`map_work_with_awards`.

    ``row`` is the 61-column publications.csv row (same shape as the
    legacy :func:`map_work_to_row` return value). ``awards`` is the raw
    ``work.awards`` list from OpenAlex, preserved verbatim so Phase 3
    can break it out per-funder and per-award without re-querying the
    API — the flat ``Grants`` column in ``row`` is lossy (funder ROR and
    internal award ids are dropped during pipe-joining).

    Attributes
    ----------
    row:
        The publications.csv row keyed by ``PUBLICATIONS_COLUMNS``.
    awards:
        The raw ``work.awards`` list. Empty list when the work had no
        awards (or no ``awards`` key).
    """

    row: dict[str, Any]
    awards: list[dict[str, Any]]


# --------------------------------------------------------------------- #
# Column contract — matches the reference CSV header byte-for-byte.
# --------------------------------------------------------------------- #

PUBLICATIONS_COLUMNS: tuple[str, ...] = (
    "Unique ID",
    "RAMS_Author",
    "DOI",
    "Title",
    "Publication_Year",
    "Publication_Date",
    "Language",
    "Type",
    "Indexed",
    "Countries",
    "Organisations",
    "FWCI",
    "FullText",
    "Citations",
    "Retracted",
    "Locations",
    "References",
    "PMID",
    "Location_ID",
    "Location_Open_Access",
    "Landing_Page",
    "PDF",
    "ISSN",
    "Publisher",
    "Publication_Type",
    "Journal",
    "Open_Access",
    "OA_Type",
    "APC_Value",
    "APC_Currency",
    "APC_in_USD",
    "Citations_Normalised",
    "Top_1%",
    "Top_10%",
    "Cited_By_Percentile_Year_Min",
    "Cited_By_Percentile_Year_Max",
    "Topic",
    "SubTopic",
    "Topic_Field",
    "Topic_Domain",
    "Abstract",
    "Author_Position",
    "Authors_Countries",
    "Corresponding_Authors",
    "Author_Affiliations",
    "Author_Names",
    "ORCIDs",
    "Topic_Display",
    "Topic_SubField_Display",
    "Keywords",
    "Keyword_Score",
    "Concepts",
    "Concept_Level",
    "Concept_Score",
    "MESH_ID",
    "MESH_Terms",
    "SDG",
    "SDG_Score",
    "Grants",
    "Counts_By_Year",
    "Citations_By_Year",
)


# --------------------------------------------------------------------- #
# Tiny helpers — intentionally small and un-clever.
# --------------------------------------------------------------------- #


def _s(value: Any) -> Any:
    """Null-policy coerce: ``None`` -> ``""``, everything else untouched.

    We keep native types for numeric columns (``int``, ``float``, ``bool``)
    because ``csv.DictWriter`` will ``str()`` them on write and the Shiny
    dashboard parses them back via ``readr``'s type inference. Forcing
    ``str(...)`` here would serialise ``True`` as ``"True"`` and bleed
    Python-isms into the CSV.
    """
    return "" if value is None else value


def _pipe(values: Iterable[Any]) -> str:
    """Pipe-join a sequence, rendering each element as a string.

    Empty input -> ``""``, single -> bare token, many -> ``"a|b|c"``.
    ``None`` elements pass through as the literal string ``"None"`` because
    a caller who puts a ``None`` in a list has opted into that — the null
    policy applies only to scalar columns. In practice callers pre-filter.
    """
    out = [("" if v is None else str(v)) for v in values]
    return "|".join(out)


def _strip_openalex_url(raw: str | None) -> str:
    """Strip ``https://openalex.org/`` / ``https://orcid.org/`` if present."""
    if not raw:
        return ""
    for prefix in (
        "https://openalex.org/",
        "http://openalex.org/",
        "https://orcid.org/",
        "http://orcid.org/",
    ):
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw


def _author_index(
    authorships: list[dict[str, Any]], target_id: str
) -> int | None:
    """Index of the authorship whose author.id matches ``target_id``.

    Matches on the bare OpenAlex id (``A12345``), stripping any URL prefix
    on the input side so callers can pass either form.
    """
    target = _strip_openalex_url(target_id)
    for i, a in enumerate(authorships):
        author_id = _strip_openalex_url(((a.get("author") or {}).get("id")) or "")
        if author_id == target:
            return i
    return None


def _author_position(
    authorships: list[dict[str, Any]], target_id: str
) -> str:
    """Return ``first`` / ``middle`` / ``last`` / ``""`` for the RAMS author."""
    idx = _author_index(authorships, target_id)
    if idx is None or not authorships:
        return ""
    if idx == 0:
        return "first"
    if idx == len(authorships) - 1:
        return "last"
    return "middle"


def _safe_get(d: Any, *path: str) -> Any:
    """Walk ``d[path[0]][path[1]]...`` returning ``None`` at the first miss."""
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _counts_by_year_years(counts_by_year: list[dict[str, Any]] | None) -> str:
    """Pipe-joined years from ``counts_by_year``, ordered as OpenAlex returns.

    Parallel (by index) to :func:`_citations_by_year_values` — downstream
    reconstructs ``(year, cited_by_count)`` pairs by zipping the two
    pipe-split lists. Empty / missing input renders as ``""``.
    """
    if not counts_by_year:
        return ""
    parts: list[str] = []
    for entry in counts_by_year:
        if not isinstance(entry, dict):
            continue
        year = entry.get("year")
        parts.append("" if year is None else str(year))
    return "|".join(parts)


def _citations_by_year_values(counts_by_year: list[dict[str, Any]] | None) -> str:
    """Pipe-joined citation counts, parallel to :func:`_counts_by_year_years`.

    Each position holds the ``cited_by_count`` for the corresponding year
    in :func:`_counts_by_year_years`; a missing field renders as ``0``
    (OpenAlex's documented semantics for absent-year entries). Empty /
    missing input renders as ``""``.
    """
    if not counts_by_year:
        return ""
    parts: list[str] = []
    for entry in counts_by_year:
        if not isinstance(entry, dict):
            continue
        parts.append(str(entry.get("cited_by_count", 0)))
    return "|".join(parts)


# --------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------- #


def map_work_with_awards(
    work: dict[str, Any],
    rams_name: str,
    rams_author_id: str,
) -> MappedWork:
    """Turn an OpenAlex work into a 61-column CSV row plus raw awards.

    This is the full-fidelity mapper: it returns both the flat 61-column
    row (as :func:`map_work_to_row` does) and the raw ``work.awards``
    list for the side-channel. Phase 2 uses this; Phase 3 consumes the
    awards list downstream to emit per-funder / per-award rows.

    See :func:`map_work_to_row` for backward-compatible dict-only return.

    Parameters
    ----------
    work:
        The raw JSON dict from ``/works/{id}`` or a page of ``/works`` —
        whatever keys OpenAlex returned, missing keys are tolerated.
    rams_name:
        The RAMS physician's display name; copied verbatim into
        ``RAMS_Author``.
    rams_author_id:
        The resolved OpenAlex author id (``A123…`` or full URL) for the
        physician — used to derive ``Author_Position``.

    Returns
    -------
    MappedWork
        ``row`` is the publications.csv row; ``awards`` is the raw list
        from ``work.awards`` (or ``[]`` if absent / empty).
    """
    authorships: list[dict[str, Any]] = work.get("authorships") or []
    primary = work.get("primary_location") or {}
    primary_source = primary.get("source") or {}
    open_access = work.get("open_access") or {}
    apc_list = work.get("apc_list") or {}
    percentile = work.get("cited_by_percentile_year") or {}
    topics = work.get("topics") or []
    first_topic = topics[0] if topics else {}
    keywords = work.get("keywords") or []
    concepts = work.get("concepts") or []
    mesh_terms = work.get("mesh") or []
    sdgs = work.get("sustainable_development_goals") or []
    first_sdg = sdgs[0] if sdgs else {}
    awards = work.get("awards") or []
    counts_by_year = work.get("counts_by_year") or []
    ids = work.get("ids") or {}

    # ------------------------------------------------------------ #
    # Derived scalars
    # ------------------------------------------------------------ #

    # Max percentile drives Top_1% / Top_10% — per spec §5.3.
    pct_max = percentile.get("max")
    try:
        top_1 = "Yes" if pct_max is not None and float(pct_max) >= 99 else "No"
        top_10 = "Yes" if pct_max is not None and float(pct_max) >= 90 else "No"
    except (TypeError, ValueError):
        top_1 = "No"
        top_10 = "No"

    # Country count = distinct country codes across every authorship.
    country_set = {
        c
        for a in authorships
        for c in (a.get("countries") or [])
        if c
    }
    # Institution count = distinct institution ids across every authorship.
    inst_set = {
        (i.get("id") or "")
        for a in authorships
        for i in (a.get("institutions") or [])
        if i.get("id")
    }

    # Pipe-joined per-authorship fields — one token per authorship preserves
    # row-alignment with Author_Names (downstream expects these to zip).
    author_names = [
        _safe_get(a, "author", "display_name") or "" for a in authorships
    ]
    author_orcids = [
        _strip_openalex_url(_safe_get(a, "author", "orcid") or "")
        or "None"  # Reference CSV renders missing ORCIDs as literal "None"
        for a in authorships
    ]
    corresponding = [
        _safe_get(a, "author", "display_name") or ""
        for a in authorships
        if a.get("is_corresponding")
    ]
    author_countries = [
        ",".join(a.get("countries") or []) for a in authorships
    ]
    author_affiliations = [
        ",".join(
            (i.get("display_name") or "")
            for i in (a.get("institutions") or [])
        )
        for a in authorships
    ]

    # Concepts / keywords / mesh — pipe-joined across the list in order.
    keyword_names = [k.get("display_name") or "" for k in keywords]
    keyword_scores = [k.get("score") for k in keywords]
    concept_names = [c.get("display_name") or "" for c in concepts]
    concept_levels = [c.get("level") for c in concepts]
    concept_scores = [c.get("score") for c in concepts]
    mesh_ids = [m.get("descriptor_ui") or "" for m in mesh_terms]
    mesh_names = [m.get("descriptor_name") or "" for m in mesh_terms]

    # Grants: "{funder_display_name}: {award.display_name}" per award.
    grants = [
        f"{a.get('funder_display_name') or ''}: {a.get('display_name') or ''}"
        for a in awards
    ]

    # Counts_By_Year vs Citations_By_Year — pipe-joined parallel arrays.
    # Matches the reference CSV format; consumers zip on index to recover
    # (year, cited_by_count) pairs.
    counts_pipe = _counts_by_year_years(counts_by_year)
    citations_pipe = _citations_by_year_values(counts_by_year)

    # ------------------------------------------------------------ #
    # Assemble in EXACT column order (dict preserves insertion order).
    # ------------------------------------------------------------ #

    row: dict[str, Any] = {
        "Unique ID": _strip_openalex_url(work.get("id") or ""),
        "RAMS_Author": rams_name,
        "DOI": validate_doi(work.get("doi")),
        "Title": _s(work.get("title")),
        "Publication_Year": _s(work.get("publication_year")),
        "Publication_Date": _s(work.get("publication_date")),
        "Language": _s(work.get("language")),
        "Type": _s(work.get("type")),
        "Indexed": _pipe(work.get("indexed_in") or []),
        "Countries": len(country_set),
        "Organisations": len(inst_set),
        "FWCI": _s(work.get("fwci")),
        # FullText: OpenAlex exposes this under several names depending on
        # endpoint — `has_fulltext` is the authoritative boolean; fall back
        # to a pdf-url presence check.
        "FullText": _s(
            work.get("has_fulltext")
            if work.get("has_fulltext") is not None
            else (
                True
                if primary.get("pdf_url")
                else (False if "primary_location" in work else None)
            )
        ),
        "Citations": _s(work.get("cited_by_count")),
        "Retracted": _s(work.get("is_retracted")),
        "Locations": _s(
            work.get("locations_count")
            if work.get("locations_count") is not None
            else (len(work.get("locations") or []) if "locations" in work else None)
        ),
        "References": _s(work.get("referenced_works_count")),
        "PMID": _s(ids.get("pmid")),
        "Location_ID": _strip_openalex_url(primary_source.get("id") or "") or "",
        "Location_Open_Access": _s(primary.get("is_oa")),
        "Landing_Page": _s(primary.get("landing_page_url")),
        "PDF": _s(primary.get("pdf_url")),
        "ISSN": _s(primary_source.get("issn_l")),
        "Publisher": _s(primary_source.get("host_organization_name")),
        "Publication_Type": _s(primary_source.get("type")),
        "Journal": _s(primary_source.get("display_name")),
        "Open_Access": _s(open_access.get("is_oa")),
        "OA_Type": _s(open_access.get("oa_status")),
        "APC_Value": _s(apc_list.get("value")),
        "APC_Currency": _s(apc_list.get("currency")),
        "APC_in_USD": _s(apc_list.get("value_usd")),
        "Citations_Normalised": _s(percentile.get("min")),
        "Top_1%": top_1,
        "Top_10%": top_10,
        "Cited_By_Percentile_Year_Min": _s(percentile.get("min")),
        "Cited_By_Percentile_Year_Max": _s(percentile.get("max")),
        "Topic": _strip_openalex_url(first_topic.get("id") or "") or "",
        "SubTopic": _s(_safe_get(first_topic, "subfield", "display_name")),
        "Topic_Field": _s(_safe_get(first_topic, "field", "display_name")),
        "Topic_Domain": _s(_safe_get(first_topic, "domain", "display_name")),
        "Abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
        "Author_Position": _author_position(authorships, rams_author_id),
        "Authors_Countries": _pipe(author_countries),
        "Corresponding_Authors": _pipe(corresponding),
        "Author_Affiliations": _pipe(author_affiliations),
        "Author_Names": _pipe(author_names),
        "ORCIDs": _pipe(author_orcids),
        "Topic_Display": _s(first_topic.get("display_name")),
        "Topic_SubField_Display": _s(
            _safe_get(first_topic, "subfield", "display_name")
        ),
        "Keywords": _pipe(keyword_names),
        "Keyword_Score": _pipe(keyword_scores),
        "Concepts": _pipe(concept_names),
        "Concept_Level": _pipe(concept_levels),
        "Concept_Score": _pipe(concept_scores),
        "MESH_ID": _pipe(mesh_ids),
        "MESH_Terms": _pipe(mesh_names),
        "SDG": _s(first_sdg.get("display_name")),
        "SDG_Score": _s(first_sdg.get("score")),
        "Grants": _pipe(grants),
        "Counts_By_Year": counts_pipe,
        "Citations_By_Year": citations_pipe,
    }

    # Defensive: the contract test verifies this at the test layer; this
    # assert adds a last-mile guard if a future edit drops a column.
    assert tuple(row.keys()) == PUBLICATIONS_COLUMNS, (
        "works_mapper: assembled row does not match PUBLICATIONS_COLUMNS. "
        f"Diff: {set(PUBLICATIONS_COLUMNS) ^ set(row.keys())}"
    )
    return MappedWork(row=row, awards=list(awards))


def map_work_to_row(
    work: dict[str, Any],
    rams_name: str,
    rams_author_id: str,
) -> dict[str, Any]:
    """Backward-compatible shim: returns only the flat 61-column row.

    Thin wrapper over :func:`map_work_with_awards` preserved so the
    ~34 existing mapper tests — and any future caller that only needs
    the flat row — continue to work unchanged. New callers that need
    the raw awards side-channel (Phase 2, Phase 3) should use
    :func:`map_work_with_awards` directly.
    """
    return map_work_with_awards(work, rams_name, rams_author_id).row
