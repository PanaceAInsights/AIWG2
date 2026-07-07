"""ANZCTR search-page scraper (best-effort).

ANZCTR exposes no API; we hit ``TrialSearch.aspx`` with a query string and
parse the HTML results table. The scraper is deliberately defensive:

- Every parse step is wrapped so that a missing cell or a layout change
  produces ``[]`` rather than crashing the batch.
- ``sleep_fn(1.0)`` is called on every request regardless of outcome so
  we do not violate the 1-req-per-sec courtesy rate (spec §3.1).
- The ``User-Agent`` carries the project maintainer's email so ANZCTR
  admins can contact us if we're causing trouble.

The scraper returns rows in the 12-column schema
(:data:`scripts.utils.ctgov_client.TRIAL_COLUMNS`) so the orchestrator
can ``extend()`` its CT.gov rows with these without column mapping.

Note: ANZCTR's HTML has changed under our feet before. The orchestrator
auto-disables this source after 20 consecutive physicians with zero
successful parses (spec §7.3 fallback to CT.gov-only).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


_DEFAULT_BASE_URL = "https://www.anzctr.org.au"
_SEARCH_PATH = "/TrialSearch.aspx"

# ANZCTR trial ids look like "ACTRN12612345678" or "ACTRN0123456789".
_TRIAL_ID_PATTERN = re.compile(r"ACTRN\d{11,14}", re.IGNORECASE)


def _text(node: Any) -> str:
    """Safely pull collapsed text from a BeautifulSoup node (or blank)."""
    if node is None:
        return ""
    try:
        return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
    except Exception:  # pragma: no cover - defensive
        return ""


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    m = pattern.search(text or "")
    return m.group(0) if m else ""


@dataclass
class AnzctrScraper:
    """HTML scraper for the ANZCTR public search page.

    Parameters
    ----------
    user_agent:
        Goes into ``User-Agent``; spec requires a contactable identifier.
    session:
        Injected for testability.
    base_url:
        Override for tests (fixtures can point at localhost).
    sleep_fn:
        Called with ``1.0`` after each HTTP request — always, even on
        failure. Tests pass a recording lambda.
    """

    user_agent: str
    session: requests.Session = field(default_factory=requests.Session)
    base_url: str = _DEFAULT_BASE_URL
    sleep_fn: Callable[[float], None] = time.sleep

    def search(self, name: str) -> list[dict[str, str]]:
        """Return 12-column rows for every ANZCTR trial matching ``name``.

        Wraps HTTP and parsing in a broad try/except — on any error
        returns ``[]``. The orchestrator relies on this "never raise"
        contract to keep the batch going.
        """
        name = (name or "").strip()
        if not name:
            return []

        url = urljoin(self.base_url, _SEARCH_PATH)
        params = {"searchTxt": name, "isBasic": "True"}
        headers = {"User-Agent": self.user_agent}

        try:
            try:
                resp = self.session.get(
                    url, params=params, headers=headers, timeout=30
                )
            finally:
                self.sleep_fn(1.0)

            if resp.status_code != 200:
                return []
            return self._parse(name, resp.text)
        except Exception:
            # Best-effort: one malformed response must not kill the batch.
            return []

    def _parse(self, name: str, html: str) -> list[dict[str, str]]:
        """Parse the search-results HTML into 12-column rows.

        Any parse failure at the row level is caught locally so a single
        bad row doesn't torch the rest of the page.
        """
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            return []

        rows: list[dict[str, str]] = []
        # ANZCTR's results page has historically used a table with
        # ``id="ctl00_body_GridView1"`` or similar. We fall back to any
        # table that contains ACTRN-style trial ids in its cells.
        tables = soup.find_all("table")
        for table in tables:
            body_text = _text(table)
            if "ACTRN" not in body_text.upper():
                continue
            for tr in table.find_all("tr"):
                try:
                    row = self._parse_row(name, tr)
                except Exception:
                    row = None
                if row is not None:
                    rows.append(row)
        return rows

    def _parse_row(
        self, name: str, tr: Any
    ) -> Optional[dict[str, str]]:
        """Parse one result-table row. Returns None if the row is a header
        or has no recognisable trial id."""
        cells = tr.find_all(["td", "th"])
        if not cells:
            return None
        # The id column may carry the trial number as plain text, a link's
        # text, or an href. Scan all options.
        trial_id = ""
        title = ""
        link_href = ""
        for cell in cells:
            text = _text(cell)
            if not trial_id:
                trial_id = _first_match(_TRIAL_ID_PATTERN, text)
            # Capture the link text if it's the trial row's primary anchor.
            anchor = cell.find("a") if hasattr(cell, "find") else None
            if anchor is not None:
                href = anchor.get("href") if hasattr(anchor, "get") else None
                if isinstance(href, str) and not link_href:
                    link_href = href
                anchor_text = _text(anchor)
                if anchor_text and not title and trial_id not in anchor_text:
                    title = anchor_text
        if not trial_id:
            return None
        if not title:
            # Fall back to the longest non-id cell.
            texts = [
                _text(c) for c in cells if trial_id not in _text(c)
            ]
            texts = [t for t in texts if t]
            title = max(texts, key=len, default="")

        url = urljoin(self.base_url, link_href) if link_href else (
            f"{self.base_url}/Trial/Registration/TrialReview.aspx?id={trial_id}"
        )

        # ANZCTR's search results do not carry the full 12-column detail
        # — we only reliably get id, title, and (sometimes) status. The
        # dashboard tolerates empty fields; we prefer ''-over-None so the
        # CSV round-trips cleanly.
        return {
            "rams_name": name,
            "trial_id": trial_id.upper(),
            "registry": "ANZCTR",
            "title": title,
            "status": "",
            "condition": "",
            "intervention": "",
            "phase": "",
            "start_date": "",
            "completion_date": "",
            "role": "",
            "sponsor": "",
            "url": url,
        }
