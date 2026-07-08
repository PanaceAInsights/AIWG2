"""Thin HTTP client for the OpenAlex REST API.

All pipeline scripts (``scripts/01_``…``05_``) share this client so that
auth, retry policy, and cursor pagination live in exactly one place.

The client accepts an injected ``requests.Session`` for testability — tests
pass a ``MagicMock`` and never touch the network.
"""
from __future__ import annotations

import http.client
import json as _json
import ssl
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional

import requests

# Status codes that indicate a transient failure worth retrying.
# 429 = rate-limited; 5xx = server-side hiccups.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Upper bound (seconds) on any single backoff — protects against a
# pathological Retry-After value pinning the pipeline for hours.
_MAX_BACKOFF = 30.0

# Initial backoff delay for retryable errors (seconds)
_INITIAL_BACKOFF = 2.0

# Polite-pool inter-request sleep for raw_query (filter=) calls.
# OpenAlex free tier allows ~10 req/s; 0.6s keeps us at ~1.6 req/s.
_POLITE_SLEEP = 0.6


@dataclass
class OpenAlexClient:
    """HTTP client for api.openalex.org with auth, retries, and pagination.

    Parameters
    ----------
    email, api_key:
        OpenAlex polite-pool credentials. Email goes into ``User-Agent``,
        api_key rides on the query string (paid search= endpoint only).
    session:
        Injected for testability. Defaults to a fresh ``requests.Session``
        per instance via ``field(default_factory=...)``.
    max_retries:
        Extra attempts after the initial request, i.e. ``max_retries=3`` ->
        up to 4 total calls.
    sleep_fn:
        Indirection over ``time.sleep`` so tests can assert on backoff
        without actually pausing.
    on_success:
        Optional callback invoked after each 2xx response — reserved for
        the budget tracker in Task 4. Kept here so we don't have to
        retrofit the client later. Receives the parsed JSON dict.
    """

    email: str
    api_key: str
    base_url: str = "https://api.openalex.org"
    session: requests.Session = field(default_factory=requests.Session)
    max_retries: int = 3
    sleep_fn: Callable[[float], None] = time.sleep
    on_success: Optional[Callable[[dict[str, Any]], None]] = None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": f"mailto:{self.email}"}

    def _params(self, extra: Optional[dict[str, Any]]) -> dict[str, Any]:
        p = dict(extra or {})
        # Only inject api_key for paid search= endpoint.
        # filter=display_name.search: is free and rejects api_key param (400 error).
        # We detect paid-search usage by checking for a bare 'search' key (not inside 'filter').
        uses_paid_search = "search" in p and "filter" not in p
        if self.api_key and uses_paid_search:
            p["api_key"] = self.api_key
        # Always add mailto for polite pool (rate-limit leniency)
        if self.email and "mailto" not in p:
            p["mailto"] = self.email
        return p

    @staticmethod
    def _retry_after(resp: Any, fallback: float) -> float:
        """Honour Retry-After on 429 when present; fall back to exponential.

        Note: RFC 7231 also permits Retry-After as an HTTP-date string, but
        OpenAlex sends integer seconds in practice, so we do not parse the
        HTTP-date form — non-numeric values fall through to exponential
        backoff via the ``ValueError`` path.
        """
        headers = getattr(resp, "headers", None) or {}
        raw = headers.get("Retry-After") if hasattr(headers, "get") else None
        if raw is None:
            return fallback
        try:
            # Clamp negative values to 0 so a bogus "Retry-After: -1" does
            # not crash ``time.sleep`` (which rejects negative arguments).
            seconds = max(0.0, min(float(raw), _MAX_BACKOFF))
            return seconds
        except (TypeError, ValueError):
            return fallback

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
        allow_404: bool = False,
        raw_query: Optional[str] = None,
    ) -> dict[str, Any]:
        """GET ``{base_url}{path}`` with auth and retries.

        Parameters
        ----------
        raw_query:
            If provided, appended verbatim to the URL as a query string
            (e.g. ``"filter=display_name.search:peter+soyer&per-page=10"``)
            without any URL-encoding. Use this for OpenAlex filter= params
            that contain colons, which requests would otherwise percent-encode
            causing 400 errors. ``params`` is ignored when ``raw_query`` is set.
            NOTE: api_key is NOT included in raw_query calls — filter-based
            searches are free and rate-limit-free without the key. Including
            the key routes through the paid quota and triggers 429 errors.

        Returns the parsed JSON dict on 2xx. On 404 the default behaviour
        is to raise (via ``resp.raise_for_status()``) — callers fetching a
        single entity by id should treat a 404 as a hard error rather than
        silently dropping the record. Passing ``allow_404=True`` opts into
        the soft-skip behaviour (returns ``{"results": [], "meta": {}}``)
        which is used internally by :meth:`paginate` for zero-result queries.

        Raises on any other non-retryable status or exhausted retries.
        """
        base_url = f"{self.base_url}{path}"
        delay = _INITIAL_BACKOFF
        last_resp: Any = None

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                # Small inter-retry sleep to avoid hammering the API
                self.sleep_fn(0.5)

            if raw_query is not None:
                # Use http.client directly — it sends the URL path verbatim
                # without any percent-encoding (unlike requests/urllib3).
                # Small polite-pool sleep on first attempt to stay under IP rate limit.
                if attempt == 0:
                    self.sleep_fn(_POLITE_SLEEP)

                mailto_suffix = f"&mailto={self.email}" if self.email else ""
                # Include api_key — OpenAlex now charges for all search endpoints.
                api_key_suffix = f"&api_key={self.api_key}" if self.api_key else ""
                url_path = f"/authors?{raw_query}{mailto_suffix}{api_key_suffix}"

                ctx = ssl.create_default_context()
                conn = http.client.HTTPSConnection(
                    "api.openalex.org", timeout=15, context=ctx
                )
                conn.request("GET", url_path, headers=self._headers())
                raw = conn.getresponse()
                body = raw.read()
                conn.close()

                # Wrap in a requests-compatible response object
                resp = requests.Response()
                resp.status_code = raw.status
                resp._content = body
                resp.headers = dict(raw.getheaders())
                resp.encoding = "utf-8"
            else:
                url = base_url
                resp = self.session.get(
                    url,
                    params=self._params(params),
                    headers=self._headers(),
                    timeout=(8, 15),  # (connect_timeout, read_timeout)
                )

            last_resp = resp
            status = resp.status_code

            if status == 200:
                data = resp.json()
                if self.on_success is not None:
                    self.on_success(data)
                return data

            if status == 404 and allow_404:
                return {"results": [], "meta": {}}

            if status in _RETRYABLE_STATUS and attempt < self.max_retries:
                if status == 429:
                    # Honour Retry-After if present, else use short fixed wait
                    retry_after = self._retry_after(resp, 5.0)
                    # Cap at 30s — if OpenAlex says wait longer, we'll just retry
                    wait = min(retry_after, 30.0)
                else:
                    wait = delay
                    delay = min(delay * 2, _MAX_BACKOFF)
                self.sleep_fn(wait)
                continue

            # Non-retryable (including 404 when allow_404=False) or
            # retries exhausted: let requests raise.
            resp.raise_for_status()

        # Retries exhausted on a retryable status that didn't raise above
        if last_resp is not None:
            last_resp.raise_for_status()
        raise RuntimeError(f"Exhausted retries for {base_url}")

    def paginate(
        self,
        path: str,
        params: dict[str, Any],
        per_page: int = 200,
    ) -> Iterator[dict[str, Any]]:
        """Yield every result across cursor-paginated pages.

        Seeds the cursor with ``*`` (OpenAlex convention) and follows
        ``meta.next_cursor`` until the server returns ``None``. Uses
        ``allow_404=True`` internally so that a filter matching zero
        records (e.g. an author with no works) yields nothing instead of
        crashing the pipeline.
        """
        cursor: Optional[str] = "*"
        while cursor is not None:
            page_params = dict(params)
            page_params["per-page"] = per_page
            page_params["cursor"] = cursor
            data = self.get(path, params=page_params, allow_404=True)
            for result in data.get("results", []):
                yield result
            cursor = (data.get("meta") or {}).get("next_cursor")
