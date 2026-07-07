"""Resumable CSV append writer for long-running pipeline steps.

The pipeline fetches thousands of records from OpenAlex. If a run is
interrupted (Ctrl-C, laptop sleep, OS update) we need to pick up where we
left off rather than redownload everything. :class:`CheckpointWriter`
gives us that resume behaviour in a few lines:

1. On ``__init__``, if the target CSV exists, read the ``key_column`` into
   a set of seen keys.
2. On ``write_row``, if the row's key is already seen, skip silently.
   Otherwise append the row and remember the key.
3. On ``log_error``, append a timestamped row to a separate progress log
   CSV so the operator has a running failure report.

One-writer-per-file is the contract — we do not guard against concurrent
appends from multiple processes. That is out of scope for this project.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Any

# Default location for the progress log — relative to the current working
# directory, which the pipeline scripts assume is the project root.
_DEFAULT_PROGRESS_LOG = Path("data") / "logs" / "download_progress.csv"

# The progress log has a fixed schema across all pipeline steps so a single
# dashboard can read it.
_PROGRESS_COLUMNS = ["timestamp", "key", "message"]


class CheckpointWriter:
    """Append-only CSV writer with resume-from-crash semantics.

    Parameters
    ----------
    csv_path:
        Output CSV. Created with a header row on first write; reused
        verbatim on subsequent runs.
    columns:
        Ordered column list. The writer writes this header on a new file
        and uses this ordering on every append — it does **not** infer
        columns from an existing CSV.
    key_column:
        The column whose value acts as the dedupe key. Must be a member of
        ``columns``.
    progress_log:
        Path to the error-log CSV. Defaults to
        ``data/logs/download_progress.csv`` under the current working dir.
    """

    def __init__(
        self,
        csv_path: str | Path,
        columns: list[str],
        key_column: str,
        progress_log: str | Path | None = None,
    ) -> None:
        if key_column not in columns:
            raise ValueError(
                f"key_column {key_column!r} not in columns {columns!r}"
            )
        self.csv_path: Path = Path(csv_path)
        self.columns: list[str] = list(columns)
        self.key_column: str = key_column
        self.progress_log: Path = (
            Path(progress_log) if progress_log is not None else _DEFAULT_PROGRESS_LOG
        )

        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.progress_log.parent.mkdir(parents=True, exist_ok=True)

        self._validate_existing_header()
        self._seen: set[str] = self._load_seen_keys()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _validate_existing_header(self) -> None:
        """Raise if the on-disk header doesn't match the constructor columns.

        Without this check, reopening a CSV with a different ``columns``
        list would write rows under a stale header (e.g. a 3-column row
        under a 2-column header), producing a malformed CSV that later
        readers would mis-parse. Fail loud instead.
        """
        if not self.csv_path.exists() or self.csv_path.stat().st_size == 0:
            return
        with self.csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                existing_header = next(reader)
            except StopIteration:
                # File exists but has no lines at all — treat as empty.
                return
        if existing_header != self.columns:
            raise ValueError(
                f"CheckpointWriter columns mismatch: file has {existing_header!r}, "
                f"got {self.columns!r}. Delete or migrate the file to proceed."
            )

    def _load_seen_keys(self) -> set[str]:
        """Stream the existing CSV and collect keys into a set.

        We use stdlib ``csv`` rather than pandas: one dependency fewer, and
        streaming means we never read the whole file into memory at once.
        Note that the returned set *does* scale with row count — each seen
        key is held in RAM until the process exits. Typical OpenAlex
        workloads are <100k keys × ~30 bytes ≈ 3 MB, which is fine.
        """
        if not self.csv_path.exists():
            return set()
        seen: set[str] = set()
        with self.csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = row.get(self.key_column)
                if key is not None and key != "":
                    seen.add(key)
        return seen

    def _append_row(self, path: Path, columns: list[str], row: dict[str, Any]) -> None:
        """Append a single row, writing the header if the file is new/empty.

        ``flush`` + ``os.fsync`` after every append is deliberate: the whole
        point of the checkpoint file is that a crash-then-restart can pick
        up where the previous run stopped, which only works if the row has
        actually hit the disk and not just the OS page cache.
        """
        write_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(row)
            f.flush()
            os.fsync(f.fileno())

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def has_key(self, key: str) -> bool:
        """True iff ``key`` has already been written to the output CSV."""
        return key in self._seen

    def write_row(self, row: dict[str, Any]) -> bool:
        """Append ``row`` if its key is new; otherwise no-op.

        Returns
        -------
        bool
            ``True`` if the row was appended, ``False`` if the key was
            already present (no write occurred).

        Raises
        ------
        ValueError
            If the row does not contain the ``key_column`` (we refuse to
            silently write rows with no dedupe key).
        """
        if self.key_column not in row:
            raise ValueError(
                f"row is missing key_column {self.key_column!r}: {row!r}"
            )
        key = row[self.key_column]
        if key in self._seen:
            return False

        self._append_row(self.csv_path, self.columns, row)
        self._seen.add(key)
        return True

    def log_error(self, key: str, message: str) -> None:
        """Append a timestamped error row to the progress log."""
        self._append_row(
            self.progress_log,
            _PROGRESS_COLUMNS,
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "key": key,
                "message": message,
            },
        )

    @property
    def count(self) -> int:
        """Number of unique rows written to the output CSV (including pre-existing)."""
        return len(self._seen)
