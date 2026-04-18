"""Tests for foreman/protocol.py — TaskMessage, DecisionMessage, ActionItem."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from foreman.protocol import ActionItem, DecisionMessage, DecisionType, LLMBackendRef, TaskContext, TaskMessage


class TestActionItem:
    """Tests for ActionItem model."""

    def test_add_label_action(self) -> None:
        """ActionItem with add_label type and label field."""
        action = ActionItem(type="add_label", label="bug")
        assert action.type == "add_label"
        assert action.label == "bug"

    def test_comment_action(self) -> None:
        """ActionItem with comment type and body field."""
        action = ActionItem(type="comment", body="Thanks for the report.")
        assert action.type == "comment"
        assert action.body == "Thanks for the report."

    def test_extra_fields_allowed(self) -> None:
        """ActionItem accepts arbitrary extra fields for extensibility."""
        action = ActionItem(type="custom_action", custom_field="value")
        assert action.type == "custom_action"
        assert action.custom_field == "value"

    def test_type_required(self) -> None:
        """ActionItem requires the type field."""
        with pytest.raises(ValidationError):
            ActionItem()  # type: ignore[call-arg]


class TestLLMBackendRef:
    """Tests for LLMBackendRef model."""

    def test_valid_ref(self) -> None:
        """LLMBackendRef stores provider and model."""
        ref = LLMBackendRef(provider="anthropic", model="claude-sonnet-4-6")
        assert ref.provider == "anthropic"
        assert ref.model == "claude-sonnet-4-6"

    def test_provider_required(self) -> None:
        """LLMBackendRef requires provider."""
        with pytest.raises(ValidationError):
            LLMBackendRef(model="claude-sonnet-4-6")  # type: ignore[call-arg]

    def test_model_required(self) -> None:
        """LLMBackendRef requires model."""
        with pytest.raises(ValidationError):
            LLMBackendRef(provider="anthropic")  # type: ignore[call-arg]


class TestTaskContext:
    """Tests for TaskContext model."""

    def test_full_context(self) -> None:
        """TaskContext stores memory_summary and llm_backend."""
        backend = LLMBackendRef(provider="anthropic", model="claude-sonnet-4-6")
        ctx = TaskContext(memory_summary="Prior actions: labeled as bug.", llm_backend=backend)
        assert ctx.memory_summary == "Prior actions: labeled as bug."
        assert ctx.llm_backend.provider == "anthropic"

    def test_memory_summary_optional(self) -> None:
        """memory_summary defaults to None."""
        backend = LLMBackendRef(provider="ollama", model="llama3")
        ctx = TaskContext(llm_backend=backend)
        assert ctx.memory_summary is None

    def test_llm_backend_required(self) -> None:
        """llm_backend is required."""
        with pytest.raises(ValidationError):
            TaskContext()  # type: ignore[call-arg]


class TestTaskMessage:
    """Tests for TaskMessage model."""

    def _make_task(self, **overrides: object) -> TaskMessage:
        defaults: dict[str, object] = {
            "type": "issue.triage",
            "repo": "owner/repo",
            "payload": {"issue": {"number": 42}},
            "context": TaskContext(llm_backend=LLMBackendRef(provider="anthropic", model="claude-sonnet-4-6")),
        }
        defaults.update(overrides)
        return TaskMessage(**defaults)  # type: ignore[arg-type]

    def test_task_id_auto_generated(self) -> None:
        """task_id is auto-generated as a UUID4 string when not provided."""
        task = self._make_task()
        # Must be a valid UUID
        parsed = uuid.UUID(task.task_id)
        assert parsed.version == 4

    def test_task_id_explicit(self) -> None:
        """Explicit task_id is preserved."""
        tid = str(uuid.uuid4())
        task = self._make_task(task_id=tid)
        assert task.task_id == tid

    def test_required_fields(self) -> None:
        """type, repo, payload, and context are required."""
        with pytest.raises(ValidationError):
            TaskMessage()  # type: ignore[call-arg]

    def test_field_values(self) -> None:
        """TaskMessage stores all fields correctly."""
        task = self._make_task()
        assert task.type == "issue.triage"
        assert task.repo == "owner/repo"
        assert task.payload == {"issue": {"number": 42}}
        assert task.context.llm_backend.provider == "anthropic"

    def test_roundtrip_json(self) -> None:
        """TaskMessage serialises to JSON and back without loss."""
        task = self._make_task()
        roundtripped = TaskMessage.model_validate_json(task.model_dump_json())
        assert roundtripped.task_id == task.task_id
        assert roundtripped.type == task.type


class TestDecisionMessage:
    """Tests for DecisionMessage model."""

    def _make_decision(self, **overrides: object) -> DecisionMessage:
        defaults: dict[str, object] = {
            "task_id": str(uuid.uuid4()),
            "decision": DecisionType.label_and_respond,
            "rationale": "Issue matches bug pattern.",
            "actions": [ActionItem(type="add_label", label="bug")],
        }
        defaults.update(overrides)
        return DecisionMessage(**defaults)

    def test_valid_decision(self) -> None:
        """DecisionMessage stores all fields correctly."""
        d = self._make_decision()
        assert d.decision == DecisionType.label_and_respond
        assert d.rationale == "Issue matches bug pattern."
        assert len(d.actions) == 1

    def test_decision_type_close(self) -> None:
        """DecisionType.close is a valid decision."""
        d = self._make_decision(decision=DecisionType.close, actions=[])
        assert d.decision == DecisionType.close

    def test_decision_type_escalate(self) -> None:
        """DecisionType.escalate is a valid decision."""
        d = self._make_decision(decision=DecisionType.escalate, actions=[])
        assert d.decision == DecisionType.escalate

    def test_decision_type_skip(self) -> None:
        """DecisionType.skip is a valid decision."""
        d = self._make_decision(decision=DecisionType.skip, actions=[])
        assert d.decision == DecisionType.skip

    def test_invalid_decision_raises(self) -> None:
        """Unknown decision value raises ValidationError."""
        with pytest.raises(ValidationError):
            self._make_decision(decision="do_something_weird")

    def test_actions_default_empty(self) -> None:
        """actions defaults to an empty list."""
        d = DecisionMessage(
            task_id=str(uuid.uuid4()),
            decision=DecisionType.skip,
            rationale="No action needed.",
        )
        assert d.actions == []

    def test_roundtrip_json(self) -> None:
        """DecisionMessage serialises to JSON and back without loss."""
        d = self._make_decision()
        roundtripped = DecisionMessage.model_validate_json(d.model_dump_json())
        assert roundtripped.task_id == d.task_id
        assert roundtripped.decision == d.decision
