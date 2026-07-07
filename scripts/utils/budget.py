"""Daily credit budget tracker for OpenAlex API usage.

OpenAlex grants polite-pool callers a soft daily limit (defaults to
100,000 requests here — see plan §4D). This module persists the day's
usage to a small JSON file so that:

- Resuming a crashed pipeline doesn't reset the counter to zero.
- An operator can ``cat`` the state file and see at a glance how much
  budget is left.
- A fresh calendar day automatically rolls the counter over.

The intended wiring is ``OpenAlexClient(on_success=lambda _: budget.charge(1))``
so the client only pays for actually-successful responses.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable

# Default state file path. Callers typically override this in tests.
_DEFAULT_STATE_PATH = Path("data") / "logs" / "credit_usage.json"

# Default polite-pool cap. Kept as a module constant so a stray edit to the
# constructor signature doesn't silently change production behaviour.
_DEFAULT_DAILY_LIMIT = 100_000


class BudgetExhausted(RuntimeError):
    """Raised when a charge would push us past the daily limit.

    Subclasses ``RuntimeError`` so callers can catch it specifically
    without catching every ``Exception``.
    """


class CreditBudget:
    """Counter that charges per API call and persists to JSON.

    State file shape (human inspectable on purpose)::

        {
          "date": "2026-04-18",   // local date, ISO format
          "used": 12345
        }

    Parameters
    ----------
    daily_limit:
        Maximum charges permitted per calendar day.
    state_path:
        JSON file path. Created on first charge if missing.
    now_fn:
        Injected clock for deterministic date-rollover tests.
    """

    def __init__(
        self,
        daily_limit: int = _DEFAULT_DAILY_LIMIT,
        state_path: str | Path | None = None,
        now_fn: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.daily_limit: int = daily_limit
        self.state_path: Path = (
            Path(state_path) if state_path is not None else _DEFAULT_STATE_PATH
        )
        self._now_fn: Callable[[], datetime] = now_fn
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        self._used: int
        self._date: str
        self._used, self._date = self._load_or_initialise()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _today(self) -> str:
        return self._now_fn().date().isoformat()

    def _load_or_initialise(self) -> tuple[int, str]:
        """Return ``(used, date)`` from disk, applying daily-rollover logic.

        - File missing or corrupt -> fresh counter at today's date.
        - File dated today         -> load its ``used``.
        - File from a prior date   -> reset to zero and rewrite.
        """
        today = self._today()
        if not self.state_path.exists():
            return (0, today)

        try:
            raw = self.state_path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            stored_date = str(payload.get("date", ""))
            stored_used = int(payload.get("used", 0))
        except (OSError, ValueError):
            # Corrupt / unparseable: don't crash the pipeline, start fresh.
            return (0, today)

        if stored_date == today:
            return (stored_used, today)

        # Different date -> rollover. Persist the reset so a later reader
        # sees a consistent, today-dated file.
        self._persist(0, today)
        return (0, today)

    def _persist(self, used: int, date: str) -> None:
        """Atomically write state to disk.

        A crash mid-write must never leave a truncated / empty JSON file —
        otherwise ``_load_or_initialise`` would treat it as "start fresh"
        and silently reset the counter to zero, letting the pipeline spend
        another full day's budget. We write to a sibling ``.tmp`` file,
        fsync, and then use ``os.replace`` — which is atomic on both POSIX
        and Windows when source and destination are on the same filesystem.
        """
        payload = {"date": date, "used": used}
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.state_path)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def charge(self, cost: int = 1) -> None:
        """Increment ``used`` by ``cost``. Raises :class:`BudgetExhausted` if over limit.

        ``cost == 0`` is a documented no-op. Negative ``cost`` raises
        ``ValueError`` — we treat it as a caller bug, not a silent refund.
        """
        if cost < 0:
            raise ValueError(f"cost must be >= 0, got {cost}")
        if cost == 0:
            return

        # Roll over silently if the clock has crossed midnight since init.
        today = self._today()
        if today != self._date:
            self._used = 0
            self._date = today

        if self._used + cost > self.daily_limit:
            raise BudgetExhausted(
                f"would exceed daily limit: used={self._used} "
                f"cost={cost} limit={self.daily_limit}"
            )

        self._used += cost
        self._persist(self._used, self._date)

    def remaining(self) -> int:
        """Credits left today. Never negative."""
        return max(0, self.daily_limit - self._used)

    @property
    def used_today(self) -> int:
        """Charges applied so far today."""
        return self._used
