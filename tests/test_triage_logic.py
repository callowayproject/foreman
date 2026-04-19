"""Tests for agents/issue-triage/prompts/triage.py — triage logic and prompt."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make the agent importable.
_AGENT_DIR = Path(__file__).parent.parent / "agents" / "issue-triage"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from agent import ActionItem, DecisionMessage, TaskContext, TaskMessage, LLMBackendRef  # noqa: E402
from prompts.triage import build_prompt, parse_llm_response, run_triage  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_ANTHROPIC_FIXTURE = Path(__file__).parent / "fixtures" / "anthropic_triage_response.json"


def _make_task(
    *,
    memory_summary: str = "",
    allow_close: bool = False,
    title: str = "Bug: crash on startup",
    body: str = "Steps to reproduce...",
) -> TaskMessage:
    """Return a minimal TaskMessage for triage tests."""
    return TaskMessage(
        task_id="test-001",
        type="issue.triage",
        repo="owner/repo",
        payload={
            "issue_number": 42,
            "title": title,
            "body": body,
            "author": "user123",
            "labels": [],
            "allow_close": allow_close,
        },
        context=TaskContext(
            llm_backend=LLMBackendRef(provider="anthropic", model="claude-haiku-4-5-20251001"),
            memory_summary=memory_summary or None,
        ),
    )


def _raw_fixture_content() -> str:
    """Return the LLM response string from the anthropic fixture."""
    data = json.loads(_ANTHROPIC_FIXTURE.read_text())
    return data["content"]


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    """build_prompt constructs the triage prompt correctly."""

    def test_includes_issue_title(self) -> None:
        """Issue title appears in the rendered prompt."""
        task = _make_task(title="Bug: widget crashes")
        prompt = build_prompt(task)
        assert "Bug: widget crashes" in prompt

    def test_includes_issue_body(self) -> None:
        """Issue body appears in the rendered prompt."""
        task = _make_task(body="Detailed steps to reproduce.")
        prompt = build_prompt(task)
        assert "Detailed steps to reproduce." in prompt

    def test_includes_memory_summary_when_present(self) -> None:
        """Memory summary is included in the prompt when provided."""
        task = _make_task(memory_summary="Previous label: bug was added 2 days ago.")
        prompt = build_prompt(task)
        assert "Previous label: bug was added 2 days ago." in prompt

    def test_omits_memory_section_when_absent(self) -> None:
        """No memory section is emitted when memory_summary is empty/None."""
        task = _make_task(memory_summary="")
        prompt = build_prompt(task)
        # No placeholder text like "None" or "null" should appear for the summary
        assert "Previous context" not in prompt or "None" not in prompt

    def test_instructs_json_output(self) -> None:
        """Prompt instructs the model to return a JSON decision block."""
        task = _make_task()
        prompt = build_prompt(task)
        assert "json" in prompt.lower() or "JSON" in prompt


# ---------------------------------------------------------------------------
# parse_llm_response
# ---------------------------------------------------------------------------


class TestParseLLMResponse:
    """parse_llm_response extracts a DecisionMessage from raw LLM text."""

    def test_parses_valid_json_block(self) -> None:
        """A valid embedded JSON block is parsed into a DecisionMessage."""
        raw = _raw_fixture_content()
        decision = parse_llm_response(raw, task_id="test-001")
        assert isinstance(decision, DecisionMessage)
        assert decision.task_id == "test-001"
        assert decision.decision in ("label_and_respond", "close", "escalate", "skip")

    def test_parses_actions_from_json(self) -> None:
        """Actions list is correctly extracted from the JSON block."""
        raw = _raw_fixture_content()
        decision = parse_llm_response(raw, task_id="test-001")
        assert isinstance(decision.actions, list)

    def test_defaults_to_skip_on_missing_json(self) -> None:
        """Returns a skip decision when no JSON block is found."""
        decision = parse_llm_response("This response has no JSON at all.", task_id="test-001")
        assert decision.decision == "skip"
        assert decision.task_id == "test-001"
        assert decision.actions == []

    def test_defaults_to_skip_on_malformed_json(self) -> None:
        """Returns a skip decision when JSON is present but malformed."""
        decision = parse_llm_response("Some text {bad json here}", task_id="test-001")
        assert decision.decision == "skip"

    def test_defaults_to_skip_on_invalid_decision_value(self) -> None:
        """Returns skip when decision field is not a valid DecisionType."""
        raw = json.dumps({"decision": "unknown_action", "rationale": "x", "actions": []})
        decision = parse_llm_response(raw, task_id="test-001")
        assert decision.decision == "skip"


# ---------------------------------------------------------------------------
# allow_close guard
# ---------------------------------------------------------------------------


class TestAllowCloseGuard:
    """close_issue actions are filtered when allow_close is False."""

    def test_close_action_removed_when_not_allowed(self) -> None:
        """close_issue action is removed from actions when allow_close=False."""
        raw = json.dumps(
            {
                "decision": "close",
                "rationale": "duplicate issue",
                "actions": [{"type": "close_issue"}],
            }
        )
        decision = parse_llm_response(raw, task_id="test-001", allow_close=False)
        action_types = [a.type for a in decision.actions]
        assert "close_issue" not in action_types

    def test_close_action_kept_when_allowed(self) -> None:
        """close_issue action is preserved when allow_close=True."""
        raw = json.dumps(
            {
                "decision": "close",
                "rationale": "duplicate issue",
                "actions": [{"type": "close_issue"}],
            }
        )
        decision = parse_llm_response(raw, task_id="test-001", allow_close=True)
        action_types = [a.type for a in decision.actions]
        assert "close_issue" in action_types

    def test_non_close_actions_always_kept(self) -> None:
        """add_label and comment actions are kept regardless of allow_close."""
        raw = json.dumps(
            {
                "decision": "label_and_respond",
                "rationale": "bug",
                "actions": [{"type": "add_label", "label": "bug"}, {"type": "comment", "body": "hi"}],
            }
        )
        decision = parse_llm_response(raw, task_id="test-001", allow_close=False)
        action_types = [a.type for a in decision.actions]
        assert "add_label" in action_types
        assert "comment" in action_types


# ---------------------------------------------------------------------------
# Duplicate comment guard
# ---------------------------------------------------------------------------


class TestDuplicateCommentGuard:
    """Tasks are skipped when a comment was posted in the last 24 hours."""

    def test_skips_when_recent_comment_in_memory(self, mocker) -> None:
        """run_triage returns skip when memory indicates a recent comment."""
        task = _make_task(memory_summary="A comment was posted 2 hours ago.")
        mock_llm = mocker.patch("prompts.triage._call_llm")
        mock_llm.return_value = json.dumps(
            {
                "decision": "label_and_respond",
                "rationale": "bug",
                "actions": [{"type": "comment", "body": "hi"}],
            }
        )

        decision = run_triage(task)

        assert decision.decision == "skip"
        assert decision.actions == []

    def test_proceeds_when_no_recent_comment_in_memory(self, mocker) -> None:
        """run_triage calls the LLM when there is no recent comment in memory."""
        task = _make_task(memory_summary="Label 'bug' was added 3 days ago.")
        mock_llm = mocker.patch("prompts.triage._call_llm")
        mock_llm.return_value = json.dumps(
            {
                "decision": "label_and_respond",
                "rationale": "bug",
                "actions": [{"type": "add_label", "label": "bug"}],
            }
        )

        decision = run_triage(task)

        mock_llm.assert_called_once()
        assert decision.decision == "label_and_respond"

    def test_proceeds_when_memory_is_empty(self, mocker) -> None:
        """run_triage calls the LLM when memory_summary is empty."""
        task = _make_task(memory_summary="")
        mock_llm = mocker.patch("prompts.triage._call_llm")
        mock_llm.return_value = json.dumps(
            {
                "decision": "skip",
                "rationale": "not actionable",
                "actions": [],
            }
        )

        decision = run_triage(task)

        mock_llm.assert_called_once()


# ---------------------------------------------------------------------------
# run_triage — LLM call (fixture-based)
# ---------------------------------------------------------------------------


class TestRunTriageWithFixture:
    """run_triage produces a valid DecisionMessage from a recorded LLM fixture."""

    def test_run_triage_returns_decision_message(self, mocker) -> None:
        """run_triage returns a DecisionMessage using a recorded fixture response."""
        fixture_content = _raw_fixture_content()
        task = _make_task()
        mocker.patch("prompts.triage._call_llm", return_value=fixture_content)

        decision = run_triage(task)

        assert isinstance(decision, DecisionMessage)
        assert decision.task_id == "test-001"

    def test_run_triage_decision_is_valid_type(self, mocker) -> None:
        """run_triage decision field is one of the four valid decision values."""
        fixture_content = _raw_fixture_content()
        task = _make_task()
        mocker.patch("prompts.triage._call_llm", return_value=fixture_content)

        decision = run_triage(task)

        assert decision.decision in ("label_and_respond", "close", "escalate", "skip")
