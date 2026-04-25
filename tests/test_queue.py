"""Tests for foreman/queue.py — TaskQueue."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Generator

import pytest

from foreman.protocol import ActionItem, DecisionMessage, DecisionType, LLMBackendRef, TaskContext, TaskMessage
from foreman.queue import TaskQueue

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TASK_CONTEXT = TaskContext(llm_backend=LLMBackendRef(provider="anthropic", model="claude-sonnet-4-6"))


def _make_task(task_id: str = "task-1") -> TaskMessage:
    return TaskMessage(
        task_id=task_id,
        type="issue.triage",
        repo="owner/repo",
        payload={"issue": {"number": 1, "title": "Bug"}},
        context=_TASK_CONTEXT,
    )


def _make_decision(task_id: str = "task-1") -> DecisionMessage:
    return DecisionMessage(
        task_id=task_id,
        decision=DecisionType.label_and_respond,
        rationale="Looks like a bug",
        actions=[ActionItem(type="add_label", label="bug")],
    )


@pytest.fixture()
def queue(tmp_path: Path) -> Generator[TaskQueue, Any, None]:
    """Return a TaskQueue backed by a temp-file SQLite DB."""
    q = TaskQueue(db_path=tmp_path / "queue.db")
    yield q
    q.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    """Verify the task_queue table and index are created on init."""

    def test_table_exists(self, queue: TaskQueue) -> None:
        """task_queue table is present after init."""
        row = queue._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_queue'").fetchone()
        assert row is not None

    def test_index_exists(self, queue: TaskQueue) -> None:
        """idx_task_queue_status index is present after init."""
        row = queue._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_task_queue_status'"
        ).fetchone()
        assert row is not None

    def test_db_file_created(self, tmp_path: Path) -> None:
        """DB file and parent directories are auto-created."""
        db_path = tmp_path / "nested" / "dir" / "queue.db"
        TaskQueue(db_path=db_path)
        assert db_path.exists()


# ---------------------------------------------------------------------------
# enqueue + claim_next (happy path)
# ---------------------------------------------------------------------------


class TestEnqueueAndClaimNext:
    """enqueue → claim_next round-trip."""

    def test_enqueue_inserts_pending_task(self, queue: TaskQueue) -> None:
        """enqueue inserts a row with status=pending."""
        task = _make_task("t1")
        queue.enqueue(task, agent_url="http://agent:9001")
        row = queue._conn.execute("SELECT status FROM task_queue WHERE task_id = 't1'").fetchone()
        assert row is not None
        assert row[0] == "pending"

    def test_claim_next_returns_task_message(self, queue: TaskQueue) -> None:
        """claim_next returns the TaskMessage for the claimed task."""
        task = _make_task("t1")
        queue.enqueue(task, agent_url="http://agent:9001")
        claimed = queue.claim_next(agent_url="http://agent:9001")
        assert claimed is not None
        assert claimed.task_id == "t1"
        assert claimed.type == "issue.triage"

    def test_claim_next_sets_status_claimed(self, queue: TaskQueue) -> None:
        """After claim_next the row status is claimed."""
        task = _make_task("t1")
        queue.enqueue(task, agent_url="http://agent:9001")
        queue.claim_next(agent_url="http://agent:9001")
        row = queue._conn.execute("SELECT status FROM task_queue WHERE task_id = 't1'").fetchone()
        assert row[0] == "claimed"

    def test_claim_next_empty_queue_returns_none(self, queue: TaskQueue) -> None:
        """claim_next returns None when no pending tasks exist."""
        result = queue.claim_next(agent_url="http://agent:9001")
        assert result is None

    def test_claim_next_only_returns_matching_agent_url(self, queue: TaskQueue) -> None:
        """claim_next only returns tasks enqueued for the given agent_url."""
        task = _make_task("t1")
        queue.enqueue(task, agent_url="http://other-agent:9002")
        result = queue.claim_next(agent_url="http://agent:9001")
        assert result is None

    def test_claim_next_claims_oldest_task_first(self, queue: TaskQueue) -> None:
        """claim_next returns tasks in FIFO order (oldest created_at first)."""
        for i in range(3):
            queue.enqueue(_make_task(f"t{i}"), agent_url="http://agent:9001")
            time.sleep(0.01)  # ensure distinct created_at values
        first = queue.claim_next(agent_url="http://agent:9001")
        assert first is not None
        assert first.task_id == "t0"


# ---------------------------------------------------------------------------
# complete + drain_completed
# ---------------------------------------------------------------------------


class TestCompleteAndDrain:
    """complete + drain_completed round-trip."""

    def test_complete_sets_status_completed(self, queue: TaskQueue) -> None:
        """complete() sets status=completed and stores the result."""
        task = _make_task("t1")
        queue.enqueue(task, agent_url="http://agent:9001")
        queue.claim_next(agent_url="http://agent:9001")
        queue.complete("t1", _make_decision("t1"))
        row = queue._conn.execute("SELECT status FROM task_queue WHERE task_id = 't1'").fetchone()
        assert row[0] == "completed"

    def test_drain_completed_returns_task_and_decision(self, queue: TaskQueue) -> None:
        """drain_completed returns (TaskMessage, DecisionMessage) tuples."""
        task = _make_task("t1")
        decision = _make_decision("t1")
        queue.enqueue(task, agent_url="http://agent:9001")
        queue.claim_next(agent_url="http://agent:9001")
        queue.complete("t1", decision)
        results = queue.drain_completed()
        assert len(results) == 1
        returned_task, returned_decision = results[0]
        assert returned_task.task_id == "t1"
        assert returned_decision.task_id == "t1"
        assert returned_decision.decision == DecisionType.label_and_respond

    def test_drain_completed_marks_rows_done(self, queue: TaskQueue) -> None:
        """drain_completed transitions completed rows to done."""
        task = _make_task("t1")
        queue.enqueue(task, agent_url="http://agent:9001")
        queue.claim_next(agent_url="http://agent:9001")
        queue.complete("t1", _make_decision("t1"))
        queue.drain_completed()
        row = queue._conn.execute("SELECT status FROM task_queue WHERE task_id = 't1'").fetchone()
        assert row[0] == "done"

    def test_drain_completed_empty_returns_empty_list(self, queue: TaskQueue) -> None:
        """drain_completed returns [] when no completed tasks exist."""
        assert queue.drain_completed() == []

    def test_drain_completed_does_not_return_same_task_twice(self, queue: TaskQueue) -> None:
        """Calling drain_completed twice returns each task only once."""
        task = _make_task("t1")
        queue.enqueue(task, agent_url="http://agent:9001")
        queue.claim_next(agent_url="http://agent:9001")
        queue.complete("t1", _make_decision("t1"))
        first = queue.drain_completed()
        second = queue.drain_completed()
        assert len(first) == 1
        assert len(second) == 0


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------


class TestHeartbeat:
    """heartbeat updates last_heartbeat."""

    def test_heartbeat_updates_last_heartbeat(self, queue: TaskQueue) -> None:
        """heartbeat() updates the last_heartbeat column."""
        task = _make_task("t1")
        queue.enqueue(task, agent_url="http://agent:9001")
        queue.claim_next(agent_url="http://agent:9001")
        before = queue._conn.execute("SELECT last_heartbeat FROM task_queue WHERE task_id = 't1'").fetchone()[0]
        time.sleep(0.01)
        queue.heartbeat("t1")
        after = queue._conn.execute("SELECT last_heartbeat FROM task_queue WHERE task_id = 't1'").fetchone()[0]
        assert after is not None
        assert after > (before or 0)


# ---------------------------------------------------------------------------
# requeue_stale
# ---------------------------------------------------------------------------


class TestRequeueStale:
    """requeue_stale re-enqueues timed-out claimed tasks."""

    def test_requeue_stale_re_enqueues_timed_out_task(self, tmp_path: Path) -> None:
        """A claimed task past the timeout is re-enqueued and retry_count incremented."""
        q = TaskQueue(db_path=tmp_path / "queue.db", claim_timeout_seconds=1)
        task = _make_task("t1")
        q.enqueue(task, agent_url="http://agent:9001")
        q.claim_next(agent_url="http://agent:9001")

        # Force both claimed_at and last_heartbeat into the past to simulate timeout
        past = time.time() - 10
        q._conn.execute(
            "UPDATE task_queue SET claimed_at = ?, last_heartbeat = ? WHERE task_id = 't1'",
            (past, past),
        )

        count = q.requeue_stale()
        assert count == 1

        row = q._conn.execute("SELECT status, retry_count FROM task_queue WHERE task_id = 't1'").fetchone()
        assert row[0] == "pending"
        assert row[1] == 1

    def test_requeue_stale_ignores_fresh_claims(self, queue: TaskQueue) -> None:
        """A recently claimed task is not re-enqueued."""
        task = _make_task("t1")
        queue.enqueue(task, agent_url="http://agent:9001")
        queue.claim_next(agent_url="http://agent:9001")
        count = queue.requeue_stale()
        assert count == 0

    def test_requeue_stale_ignores_heartbeated_task(self, tmp_path: Path) -> None:
        """A task with a recent heartbeat is not re-enqueued even if claimed_at is old."""
        q = TaskQueue(db_path=tmp_path / "queue.db", claim_timeout_seconds=1)
        task = _make_task("t1")
        q.enqueue(task, agent_url="http://agent:9001")
        q.claim_next(agent_url="http://agent:9001")

        # Age the claimed_at but keep last_heartbeat fresh
        now = time.time()
        q._conn.execute(
            "UPDATE task_queue SET claimed_at = ?, last_heartbeat = ? WHERE task_id = 't1'",
            (now - 10, now),
        )
        q._conn.commit()

        count = q.requeue_stale()
        assert count == 0


# ---------------------------------------------------------------------------
# fail_exhausted
# ---------------------------------------------------------------------------


class TestFailExhausted:
    """fail_exhausted marks tasks at max_retries as failed."""

    def test_fail_exhausted_marks_task_failed(self, queue: TaskQueue) -> None:
        """A pending task at max_retries is marked failed."""
        task = _make_task("t1")
        queue.enqueue(task, agent_url="http://agent:9001")
        queue._conn.execute("UPDATE task_queue SET retry_count = 3 WHERE task_id = 't1'")
        queue._conn.commit()
        count = queue.fail_exhausted(max_retries=3)
        assert count == 1
        row = queue._conn.execute("SELECT status FROM task_queue WHERE task_id = 't1'").fetchone()
        assert row[0] == "failed"

    def test_fail_exhausted_ignores_tasks_below_max(self, queue: TaskQueue) -> None:
        """Tasks with retry_count < max_retries are not failed."""
        task = _make_task("t1")
        queue.enqueue(task, agent_url="http://agent:9001")
        queue._conn.execute("UPDATE task_queue SET retry_count = 2 WHERE task_id = 't1'")
        queue._conn.commit()
        count = queue.fail_exhausted(max_retries=3)
        assert count == 0


# ---------------------------------------------------------------------------
# Concurrent claim safety
# ---------------------------------------------------------------------------


class TestConcurrentClaim:
    """Two threads calling claim_next simultaneously claim only one task each."""

    def test_concurrent_claim_no_double_claim(self, queue: TaskQueue) -> None:
        """Only one thread claims a task when two race simultaneously."""
        queue.enqueue(_make_task("t1"), agent_url="http://agent:9001")

        results: list[TaskMessage | None] = []
        lock = threading.Lock()

        def claim() -> None:
            result = queue.claim_next(agent_url="http://agent:9001")
            with lock:
                results.append(result)

        t1 = threading.Thread(target=claim)
        t2 = threading.Thread(target=claim)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        claimed = [r for r in results if r is not None]
        assert len(claimed) == 1
