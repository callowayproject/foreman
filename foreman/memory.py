"""SQLite-backed memory: action_log and memory_summary.

All reads and writes use the stdlib ``sqlite3`` module directly — no ORM,
no mocks.  Tests must use a real temp-file or in-memory database.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pathlib import Path

    from foreman.protocol import ActionItem, DecisionType

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS action_log (
    id          INTEGER PRIMARY KEY,
    repo        TEXT NOT NULL,
    issue_id    INTEGER NOT NULL,
    task_type   TEXT NOT NULL,
    decision    TEXT NOT NULL,
    rationale   TEXT,
    actions     TEXT,
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memory_summary (
    repo        TEXT NOT NULL,
    issue_id    INTEGER NOT NULL,
    summary     TEXT NOT NULL,
    updated_at  DATETIME,
    PRIMARY KEY (repo, issue_id)
);

CREATE TABLE IF NOT EXISTS poll_state (
    repo        TEXT PRIMARY KEY,
    last_polled TEXT NOT NULL
);
"""


class MemoryStore:
    """Persistent action memory backed by a SQLite database.

    Creates the database file and schema on first use. The connection is kept
    open for the lifetime of the instance; call :meth:`close` (or use as a
    context manager) when done.

    Args:
        db_path: Filesystem path to the SQLite database file.
                 Intermediate directories are created automatically.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Action log
    # ------------------------------------------------------------------

    def log_action(
        self,
        repo: str,
        issue_id: int,
        task_type: str,
        decision: DecisionType,
        rationale: Optional[str],
        actions: list[ActionItem],
    ) -> None:
        """Append a decision record to ``action_log``.

        Args:
            repo: Repository in ``owner/repo`` format.
            issue_id: GitHub issue number.
            task_type: Task type string (e.g. ``issue.triage``).
            decision: The agent's decision.
            rationale: Human-readable explanation, or ``None``.
            actions: Ordered list of actions the harness will execute.
        """
        actions_json = json.dumps([a.model_dump() for a in actions])
        self._conn.execute(
            """
            INSERT INTO action_log (repo, issue_id, task_type, decision, rationale, actions)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (repo, issue_id, task_type, decision.value, rationale, actions_json),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Memory summary
    # ------------------------------------------------------------------

    def get_memory_summary(self, repo: str, issue_id: int) -> str | None:
        """Return the stored summary for a (repo, issue_id) pair, or ``None``.

        Args:
            repo: Repository in ``owner/repo`` format.
            issue_id: GitHub issue number.

        Returns:
            The LLM-generated summary string, or ``None`` if absent.
        """
        row = self._conn.execute(
            "SELECT summary FROM memory_summary WHERE repo = ? AND issue_id = ?",
            (repo, issue_id),
        ).fetchone()
        return row[0] if row else None

    def upsert_memory_summary(self, repo: str, issue_id: int, summary: str) -> None:
        """Insert or replace the memory summary for a (repo, issue_id) pair.

        Args:
            repo: Repository in ``owner/repo`` format.
            issue_id: GitHub issue number.
            summary: LLM-generated summary of prior actions on this issue.
        """
        self._conn.execute(
            """
            INSERT INTO memory_summary (repo, issue_id, summary, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (repo, issue_id) DO UPDATE SET
                summary    = excluded.summary,
                updated_at = excluded.updated_at
            """,
            (repo, issue_id, summary),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Poll state
    # ------------------------------------------------------------------

    def get_last_polled(self, repo: str) -> datetime | None:
        """Return the last-polled timestamp for *repo*, or ``None`` if never polled.

        Args:
            repo: Repository in ``owner/repo`` format.

        Returns:
            The stored :class:`~datetime.datetime` (timezone-aware UTC), or
            ``None`` if no poll has been recorded for this repo.
        """
        row = self._conn.execute("SELECT last_polled FROM poll_state WHERE repo = ?", (repo,)).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row[0])

    def set_last_polled(self, repo: str, timestamp: datetime) -> None:
        """Persist the last-polled *timestamp* for *repo*.

        Args:
            repo: Repository in ``owner/repo`` format.
            timestamp: The datetime at which the poll completed.
        """
        self._conn.execute(
            """
            INSERT INTO poll_state (repo, last_polled)
            VALUES (?, ?)
            ON CONFLICT (repo) DO UPDATE SET last_polled = excluded.last_polled
            """,
            (repo, timestamp.isoformat()),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> MemoryStore:
        """Return self for use as a context manager."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close the connection on context exit."""
        self.close()
