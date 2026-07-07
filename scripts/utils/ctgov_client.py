"""ClinicalTrials.gov v2 API adapter.

Thin wrapper around the public ``/api/v2/studies`` endpoint. Given a
physician name, the adapter returns a list of 12-column rows (spec §7.1)
filtered to trials where one of the ``overallOfficials`` matches the
physician by the same dual last-name + first-name token gate used to
resolve OpenAlex authors.

The endpoint requires no auth. There is no formal rate limit; we still
self-pace one request per second via the injected ``sleep_fn`` so the
orchestrator can decide whether to actually block. Tests pass
``sleep_fn=lambda _: None`` and a mocked ``requests.Session``.

Design notes:

- **Dual-gate name matching.** A CT.gov search for "Smith" returns every
  study with a "Smith" anywhere in its metadata. The
  ``contactsLocationsModule.overallOfficials`` array is where the
  investigator of record is named; we only emit rows for the subset
  whose official name intersects both the physician's last-name token
  set and their first-name token set (reusing
  :func:`scripts.utils.name_matching._last_name_tokens` /
  ``_first_name_tokens``). This mirrors the OpenAlex author guard.
- **429 policy.** We do NOT retry. A single transient failure skips this
  physician for this run; Phase 4 is best-effort so the cost of a lost
  physician is low, and the caller catches exceptions per-physician
  anyway. Documented rather than silent — a caller wanting retry can
  wrap the call.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import requests

from scripts.utils.name_matching import (
    _first_name_tokens,
    _last_name_tokens,
    normalise_name,
)


# The 12-column schema (spec §7.1). Exposed so the orchestrator and tests
# can import one canonical list instead of duplicating the tuple.
TRIAL_COLUMNS: tuple[str, ...] = (
    "rams_name",
    "trial_id",
    "registry",
    "title",
    "status",
    "condition",
    "intervention",
    "phase",
    "start_date",
    "completion_date",
    "role",
    "sponsor",
    "url",
)


_DEFAULT_BASE_URL = "https://clinicaltrials.gov/api/v2"
_DEFAULT_PAGE_SIZE = 50


def _pipe_join(values: Any) -> str:
    """Pipe-join a list of strings, dropping blanks. Defensively tolerate non-lists."""
    if not isinstance(values, list):
        return ""
    parts = [str(v).strip() for v in values if isinstance(v, str) and v.strip()]
    return "|".join(parts)


def _first_nonempty(*vals: Any) -> str:
    """Return the first non-empty string from the arguments."""
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _investigator_matches(physician_name: str, official_name: str) -> bool:
    """True iff ``official_name`` shares both a last-name and first-name token
    with ``physician_name`` (normalised). Mirrors the OpenAlex dual gate."""
    if not physician_name or not official_name:
        return False
    p_norm = normalise_name(physician_name)
    o_norm = normalise_name(official_name)
    if not p_norm or not o_norm:
        return False
    p_last = _last_name_tokens(p_norm)
    o_last = _last_name_tokens(o_norm)
    p_first = _first_name_tokens(p_norm)
    o_first = _first_name_tokens(o_norm)
    if not (p_last and o_last and p_first and o_first):
        return False
    if p_last.isdisjoint(o_last):
        return False
    if p_first.isdisjoint(o_first):
        return False
    return True


def _extract_phase(design_module: dict[str, Any]) -> str:
    """Pull the first phase string from ``designModule.phases[]``.

    CT.gov returns a list like ``["PHASE2"]`` or ``["PHASE1", "PHASE2"]``.
    We pipe-join to preserve the combined-phase case.
    """
    phases = design_module.get("phases") if isinstance(design_module, dict) else None
    return _pipe_join(phases)


def _extract_conditions(conditions_module: dict[str, Any]) -> str:
    if not isinstance(conditions_module, dict):
        return ""
    return _pipe_join(conditions_module.get("conditions"))


def _extract_interventions(arms_module: dict[str, Any]) -> str:
    """Pull intervention names from ``armsInterventionsModule.interventions[].name``."""
    if not isinstance(arms_module, dict):
        return ""
    items = arms_module.get("interventions")
    if not isinstance(items, list):
        return ""
    names = [
        str(i.get("name")).strip()
        for i in items
        if isinstance(i, dict) and isinstance(i.get("name"), str) and i.get("name").strip()
    ]
    return "|".join(names)


def _extract_completion_date(status_module: dict[str, Any]) -> str:
    """Prefer primary completion, fall back to study completion."""
    if not isinstance(status_module, dict):
        return ""
    primary = (status_module.get("primaryCompletionDateStruct") or {}).get("date")
    study = (status_module.get("completionDateStruct") or {}).get("date")
    return _first_nonempty(primary, study)


def _extract_start_date(status_module: dict[str, Any]) -> str:
    if not isinstance(status_module, dict):
        return ""
    return _first_nonempty((status_module.get("startDateStruct") or {}).get("date"))


def _extract_sponsor(sponsor_module: dict[str, Any]) -> str:
    if not isinstance(sponsor_module, dict):
        return ""
    lead = sponsor_module.get("leadSponsor") or {}
    return _first_nonempty(lead.get("name"))


def _build_url(nct_id: str) -> str:
    """CT.gov human-facing trial URL."""
    return f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else ""


@dataclass
class CtGovClient:
    """HTTP client for the ClinicalTrials.gov v2 studies endpoint.

    Parameters
    ----------
    session:
        Injected for testability. Defaults to a fresh ``requests.Session``.
    base_url:
        Override for tests / staging URLs.
    page_size:
        ``pageSize`` query param cap (CT.gov caps at 1000 but 50 is
        plenty for a narrowed investigator query).
    sleep_fn:
        Called with ``1.0`` after every request so the caller can
        throttle without us touching ``time.sleep`` in tests.
    user_agent:
        Sent on every request for polite-pool identification (spec §3.1).
    """

    user_agent: str
    session: requests.Session = field(default_factory=requests.Session)
    base_url: str = _DEFAULT_BASE_URL
    page_size: int = _DEFAULT_PAGE_SIZE
    sleep_fn: Callable[[float], None] = time.sleep

    def search(self, name: str) -> list[dict[str, str]]:
        """Return 12-column rows for every trial whose investigator matches ``name``.

        Network failures raise — the orchestrator decides per-physician
        whether to swallow (typical) or propagate (not in Phase 4).
        An HTTP 429 is NOT retried: we document and move on.
        """
        name = (name or "").strip()
        if not name:
            return []

        params = {
            "query.term": name,
            "filter.geo": "Australia",
            "format": "json",
            "pageSize": self.page_size,
        }
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        url = f"{self.base_url}/studies"

        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=30)
        finally:
            # Self-pace even on exception so a retrying caller doesn't hammer.
            self.sleep_fn(1.0)

        if resp.status_code == 429:
            # Documented choice: no retry. Let the orchestrator skip this
            # physician for this run. We raise a typed error so callers
            # can distinguish from parse failures.
            raise CtGovRateLimited(
                f"CT.gov returned 429 for {name!r}; skipping (no retry)."
            )

        resp.raise_for_status()
        payload = resp.json() or {}
        studies = payload.get("studies") or []
        rows: list[dict[str, str]] = []
        for study in studies:
            row = self._row_from_study(name, study)
            if row is not None:
                rows.append(row)
        return rows

    def _row_from_study(
        self, physician_name: str, study: dict[str, Any]
    ) -> Optional[dict[str, str]]:
        """Flatten one ``study`` object into a 12-column row, or return None
        if no overall official matches the physician."""
        if not isinstance(study, dict):
            return None
        proto = study.get("protocolSection") or {}
        if not isinstance(proto, dict):
            return None

        contacts = proto.get("contactsLocationsModule")
        if not isinstance(contacts, dict):
            # Missing module -> cannot confirm the physician is the
            # investigator, drop the study.
            return None
        officials = contacts.get("overallOfficials")
        if not isinstance(officials, list) or not officials:
            return None

        matched_role = ""
        matched = False
        for off in officials:
            if not isinstance(off, dict):
                continue
            off_name = off.get("name")
            if not isinstance(off_name, str):
                continue
            if _investigator_matches(physician_name, off_name):
                matched = True
                role = off.get("role") or off.get("officialRole")
                if isinstance(role, str):
                    matched_role = role
                break
        if not matched:
            return None

        ident = proto.get("identificationModule") or {}
        status = proto.get("statusModule") or {}
        design = proto.get("designModule") or {}
        conditions = proto.get("conditionsModule") or {}
        arms = proto.get("armsInterventionsModule") or {}
        sponsor = proto.get("sponsorCollaboratorsModule") or {}

        nct_id = _first_nonempty(ident.get("nctId"))
        title = _first_nonempty(
            ident.get("briefTitle"), ident.get("officialTitle")
        )

        return {
            "rams_name": physician_name,
            "trial_id": nct_id,
            "registry": "ClinicalTrials.gov",
            "title": title,
            "status": _first_nonempty(status.get("overallStatus")),
            "condition": _extract_conditions(conditions),
            "intervention": _extract_interventions(arms),
            "phase": _extract_phase(design),
            "start_date": _extract_start_date(status),
            "completion_date": _extract_completion_date(status),
            "role": matched_role,
            "sponsor": _extract_sponsor(sponsor),
            "url": _build_url(nct_id),
        }


class CtGovRateLimited(RuntimeError):
    """Raised when CT.gov returns HTTP 429. Orchestrator treats as skip."""
