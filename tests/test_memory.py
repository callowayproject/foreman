"""Tests for foreman/memory.py — MemoryStore (action_log + memory_summary)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from foreman.memory import MemoryStore
from foreman.protocol import ActionItem, DecisionType


class TestMemoryStoreInit:
    """Tests for MemoryStore initialisation and schema creation."""

    def test_creates_db_file(self, tmp_path: Path) -> None:
        """MemoryStore creates the SQLite DB file at the given path."""
        db_path = tmp_path / "memory.db"
        m = MemoryStore(db_path)
        assert db_path.exists()
        m.close()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """MemoryStore creates intermediate directories if they don't exist."""
        db_path = tmp_path / "nested" / "dir" / "memory.db"
        m = MemoryStore(db_path)
        assert db_path.exists()
        m.close()

    def test_action_log_table_exists(self, tmp_path: Path) -> None:
        """action_log table is created with the correct schema."""
        db_path = tmp_path / "memory.db"
        store = MemoryStore(db_path)
        store.close()
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='action_log'").fetchall()
        conn.close()
        assert rows, "action_log table should exist"

    def test_memory_summary_table_exists(self, tmp_path: Path) -> None:
        """memory_summary table is created with the correct schema."""
        db_path = tmp_path / "memory.db"
        store = MemoryStore(db_path)
        store.close()
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memory_summary'").fetchall()
        conn.close()
        assert rows, "memory_summary table should exist"


class TestLogAction:
    """Tests for MemoryStore.log_action()."""

    @pytest.fixture()
    def store(self, tmp_path: Path) -> Generator[MemoryStore, None, None]:
        """Return a fresh MemoryStore backed by a temp-file DB, closed after the test."""
        with MemoryStore(tmp_path / "memory.db") as s:
            yield s

    def test_log_action_inserts_row(self, store: MemoryStore) -> None:
        """log_action writes a record to action_log."""
        store.log_action(
            repo="owner/repo",
            issue_id=42,
            task_type="issue.triage",
            decision=DecisionType.label_and_respond,
            rationale="Matches bug pattern.",
            actions=[ActionItem(type="add_label", label="bug")],
        )

        conn = sqlite3.connect(store.db_path)
        rows = conn.execute("SELECT * FROM action_log").fetchall()
        conn.close()
        assert len(rows) == 1

    def test_log_action_stores_correct_values(self, store: MemoryStore) -> None:
        """log_action stores repo, issue_id, task_type, decision, rationale, and actions."""
        actions = [ActionItem(type="add_label", label="bug"), ActionItem(type="comment", body="Hi")]
        store.log_action(
            repo="owner/repo",
            issue_id=7,
            task_type="issue.triage",
            decision=DecisionType.label_and_respond,
            rationale="Looks like a bug.",
            actions=actions,
        )

        conn = sqlite3.connect(store.db_path)
        row = conn.execute("SELECT repo, issue_id, task_type, decision, rationale, actions FROM action_log").fetchone()
        conn.close()

        assert row[0] == "owner/repo"
        assert row[1] == 7
        assert row[2] == "issue.triage"
        assert row[3] == "label_and_respond"
        assert row[4] == "Looks like a bug."
        parsed_actions = json.loads(row[5])
        assert len(parsed_actions) == 2
        assert parsed_actions[0]["type"] == "add_label"

    def test_log_action_multiple_entries(self, store: MemoryStore) -> None:
        """Multiple log_action calls produce multiple rows."""
        for issue_id in range(3):
            store.log_action(
                repo="owner/repo",
                issue_id=issue_id,
                task_type="issue.triage",
                decision=DecisionType.skip,
                rationale="No action.",
                actions=[],
            )

        conn = sqlite3.connect(store.db_path)
        count = conn.execute("SELECT COUNT(*) FROM action_log").fetchone()[0]
        conn.close()
        assert count == 3

    def test_log_action_null_rationale(self, store: MemoryStore) -> None:
        """log_action accepts None rationale."""
        store.log_action(
            repo="owner/repo",
            issue_id=1,
            task_type="issue.triage",
            decision=DecisionType.skip,
            rationale=None,
            actions=[],
        )

        conn = sqlite3.connect(store.db_path)
        row = conn.execute("SELECT rationale FROM action_log").fetchone()
        conn.close()
        assert row[0] is None


class TestMemorySummary:
    """Tests for MemoryStore.get_memory_summary() and upsert_memory_summary()."""

    @pytest.fixture()
    def store(self, tmp_path: Path) -> Generator[MemoryStore, None, None]:
        """Return a fresh MemoryStore backed by a temp-file DB, closed after the test."""
        with MemoryStore(tmp_path / "memory.db") as s:
            yield s

    def test_get_summary_returns_none_when_absent(self, store: MemoryStore) -> None:
        """get_memory_summary returns None when no summary exists for the issue."""
        result = store.get_memory_summary("owner/repo", 42)
        assert result is None

    def test_upsert_creates_summary(self, store: MemoryStore) -> None:
        """upsert_memory_summary creates a new summary record."""
        store.upsert_memory_summary("owner/repo", 42, "Issue labeled as bug.")
        result = store.get_memory_summary("owner/repo", 42)
        assert result == "Issue labeled as bug."

    def test_upsert_updates_existing_summary(self, store: MemoryStore) -> None:
        """upsert_memory_summary replaces an existing summary."""
        store.upsert_memory_summary("owner/repo", 42, "First summary.")
        store.upsert_memory_summary("owner/repo", 42, "Updated summary.")
        result = store.get_memory_summary("owner/repo", 42)
        assert result == "Updated summary."

    def test_summaries_are_per_issue(self, store: MemoryStore) -> None:
        """Each (repo, issue_id) pair has its own independent summary."""
        store.upsert_memory_summary("owner/repo", 1, "Summary for issue 1.")
        store.upsert_memory_summary("owner/repo", 2, "Summary for issue 2.")
        assert store.get_memory_summary("owner/repo", 1) == "Summary for issue 1."
        assert store.get_memory_summary("owner/repo", 2) == "Summary for issue 2."

    def test_summaries_are_per_repo(self, store: MemoryStore) -> None:
        """The same issue number in different repos has independent summaries."""
        store.upsert_memory_summary("org1/repo", 5, "Org1 summary.")
        store.upsert_memory_summary("org2/repo", 5, "Org2 summary.")
        assert store.get_memory_summary("org1/repo", 5) == "Org1 summary."
        assert store.get_memory_summary("org2/repo", 5) == "Org2 summary."
