"""SQLite-backed task queue for the queue-mediated agent protocol.

All reads and writes use the stdlib ``sqlite3`` module directly — no ORM,
no mocks.  Tests must use a real temp-file database via ``pytest tmp_path``.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from foreman.protocol import DecisionMessage, TaskMessage

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS task_queue (
    task_id        TEXT PRIMARY KEY,
    agent_url      TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    payload        TEXT NOT NULL,
    created_at     REAL NOT NULL,
    claimed_at     REAL,
    completed_at   REAL,
    result         TEXT,
    retry_count    INTEGER NOT NULL DEFAULT 0,
    last_heartbeat REAL
);

CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue (status, agent_url);
"""


class TaskQueue:
    """Durable task queue backed by a SQLite database.

    Creates the database file and schema on first use.
    The connection is kept open for the lifetime of the instance.

    Args:
        db_path: Filesystem path to the SQLite database file.
                 Intermediate directories are created automatically.
        claim_timeout_seconds: Seconds before a claimed task without a recent
                               heartbeat is eligible for re-enqueueing.
    """

    def __init__(self, db_path: Path, claim_timeout_seconds: int = 300) -> None:
        self.db_path = db_path
        self.claim_timeout_seconds = claim_timeout_seconds
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None → autocommit; we manage all transactions manually
        # so that BEGIN IMMEDIATE works for atomic claim_next().
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def enqueue(self, task: TaskMessage, agent_url: str) -> None:
        """Insert a new task with status=pending.

        Args:
            task: The task message to enqueue.
            agent_url: Base URL of the agent that should process this task.
        """
        self._conn.execute(
            """
            INSERT INTO task_queue (task_id, agent_url, status, payload, created_at)
            VALUES (?, ?, 'pending', ?, ?)
            """,
            (task.task_id, agent_url, task.model_dump_json(), time.time()),
        )
        self._conn.commit()

    def claim_next(self, agent_url: str) -> TaskMessage | None:
        """Claim the oldest pending task for agent_url.

        Uses a threading lock plus ``BEGIN IMMEDIATE`` so that concurrent
        callers — whether in the same process or different ones — cannot
        double-claim the same task.

        Args:
            agent_url: The agent URL requesting a task.

        Returns:
            The :class:`~foreman.protocol.TaskMessage` for the claimed task,
            or ``None`` if the queue has no pending tasks for this agent.
        """
        from foreman.protocol import TaskMessage as _TaskMessage

        # _lock serialises same-process threads; BEGIN IMMEDIATE handles
        # cross-process / cross-connection contention at the SQLite level.
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    """
                    SELECT task_id, payload FROM task_queue
                    WHERE status = 'pending' AND agent_url = ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (agent_url,),
                ).fetchone()
                if row is None:
                    self._conn.execute("ROLLBACK")
                    return None
                task_id, payload_json = row
                now = time.time()
                self._conn.execute(
                    """
                    UPDATE task_queue
                    SET status = 'claimed', claimed_at = ?, last_heartbeat = ?
                    WHERE task_id = ?
                    """,
                    (now, now, task_id),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            return _TaskMessage.model_validate_json(payload_json)

    def complete(self, task_id: str, decision: DecisionMessage) -> None:
        """Mark a task completed and store the decision result.

        Args:
            task_id: ID of the task to mark completed.
            decision: The agent's :class:`~foreman.protocol.DecisionMessage`.
        """
        self._conn.execute(
            """
            UPDATE task_queue
            SET status = 'completed', completed_at = ?, result = ?
            WHERE task_id = ?
            """,
            (time.time(), decision.model_dump_json(), task_id),
        )
        self._conn.commit()

    def heartbeat(self, task_id: str) -> None:
        """Reset last_heartbeat to now, extending the claim window.

        Args:
            task_id: ID of the claimed task to heartbeat.
        """
        self._conn.execute(
            "UPDATE task_queue SET last_heartbeat = ? WHERE task_id = ?",
            (time.time(), task_id),
        )
        self._conn.commit()

    def drain_completed(self) -> list[tuple[TaskMessage, DecisionMessage]]:
        """Return all completed tasks without transitioning their status.

        Called by the harness drain loop.  The caller must call
        :meth:`mark_done` for each task after it has been successfully
        processed, giving at-least-once delivery semantics.

        Returns:
            A list of ``(TaskMessage, DecisionMessage)`` tuples for each
            completed task.  Rows remain ``status=completed`` after this call.
        """
        from foreman.protocol import DecisionMessage as _DecisionMessage
        from foreman.protocol import TaskMessage as _TaskMessage

        rows = self._conn.execute(
            "SELECT task_id, payload, result FROM task_queue WHERE status = 'completed'"
        ).fetchall()
        if not rows:
            return []
        return [
            (_TaskMessage.model_validate_json(payload), _DecisionMessage.model_validate_json(result))
            for _, payload, result in rows
        ]

    def mark_done(self, task_id: str) -> None:
        """Transition a completed task to done after successful processing.

        Args:
            task_id: ID of the completed task to mark done.
        """
        self._conn.execute(
            "UPDATE task_queue SET status = 'done' WHERE task_id = ? AND status = 'completed'",
            (task_id,),
        )
        self._conn.commit()

    def requeue_stale(self) -> int:
        """Re-enqueue claimed tasks that have exceeded the claim timeout.

        A task is considered stale when both conditions hold:

        - ``status = 'claimed'``
        - ``MAX(claimed_at, last_heartbeat) + claim_timeout_seconds < now``

        Returns:
            The number of tasks re-enqueued.
        """
        cutoff = time.time() - self.claim_timeout_seconds
        cursor = self._conn.execute(
            """
            UPDATE task_queue
            SET status = 'pending', claimed_at = NULL, last_heartbeat = NULL,
                retry_count = retry_count + 1
            WHERE status = 'claimed'
              AND MAX(COALESCE(last_heartbeat, claimed_at), claimed_at) < ?
            """,
            (cutoff,),
        )
        self._conn.commit()
        return cursor.rowcount

    def fail_exhausted(self, max_retries: int = 3) -> int:
        """Mark tasks that have exceeded max_retries as failed.

        Args:
            max_retries: Tasks with ``retry_count >= max_retries`` are marked
                         ``failed``.

        Returns:
            The number of tasks marked failed.
        """
        cursor = self._conn.execute(
            """
            UPDATE task_queue SET status = 'failed'
            WHERE status = 'pending' AND retry_count >= ?
            """,
            (max_retries,),
        )
        self._conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> TaskQueue:
        """Return self for use as a context manager."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close the connection on context exit."""
        self.close()
