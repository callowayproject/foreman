"""Triage prompt construction and LLM response parsing."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import litellm

if TYPE_CHECKING:
    from agent import DecisionMessage, TaskMessage

_VALID_DECISIONS = {"label_and_respond", "close", "escalate", "skip"}

# Keywords in memory_summary that indicate a comment was recently posted.
_RECENT_COMMENT_KEYWORDS = [
    "comment was posted",
    "commented",
    "a comment",
    "responded",
]


def build_prompt(task: TaskMessage) -> str:
    """Build the triage prompt from a task message.

    Args:
        task: The incoming :class:`~agent.TaskMessage` from the harness.

    Returns:
        A formatted prompt string ready to send to the LLM.
    """
    payload = task.payload
    title = payload.get("title", "")
    body = payload.get("body", "")
    author = payload.get("author", "unknown")
    labels = payload.get("labels", [])

    memory_section = ""
    if task.context.memory_summary:
        memory_section = f"\n\nPrevious context on this issue:\n{task.context.memory_summary}"

    return (
        f"You are an issue triage assistant for the GitHub repository {task.repo}.\n"
        f"A new or updated issue has been submitted. Analyse it and return a JSON decision.\n"
        f"{memory_section}\n"
        f"Issue #{payload.get('issue_number', '?')} by @{author}\n"
        f"Title: {title}\n"
        f"Body:\n{body}\n"
        f"Current labels: {labels}\n\n"
        f"Return ONLY a JSON object with this exact shape (no markdown fences):\n"
        f'{{"decision": "<label_and_respond|close|escalate|skip>", '
        f'"rationale": "<one sentence>", '
        f'"actions": [<action objects>]}}\n\n'
        f"Action object shapes:\n"
        f'  add_label:   {{"type": "add_label", "label": "<name>"}}\n'
        f'  comment:     {{"type": "comment", "body": "<markdown>"}}\n'
        f'  close_issue: {{"type": "close_issue"}}\n'
    )


def parse_llm_response(
    raw: str,
    *,
    task_id: str,
    allow_close: bool = False,
) -> DecisionMessage:
    """Extract and validate a :class:`~agent.DecisionMessage` from raw LLM text.

    Searches for the first JSON object in *raw*, validates it, and applies the
    ``allow_close`` guard.  Returns a ``skip`` decision on any parse failure.

    Args:
        raw: Raw text returned by the LLM.
        task_id: Task identifier to set on the returned message.
        allow_close: Whether ``close_issue`` actions are permitted.

    Returns:
        A validated :class:`~agent.DecisionMessage`.
    """
    from agent import ActionItem, DecisionMessage

    def _skip(rationale: str = "Could not parse LLM response") -> DecisionMessage:
        return DecisionMessage(task_id=task_id, decision="skip", rationale=rationale, actions=[])

    # Find the first '{' and attempt to parse the JSON from that position.
    start = raw.find("{")
    if start == -1:
        return _skip()

    try:
        data: dict[str, Any] = json.loads(raw[start:])
    except json.JSONDecodeError:
        return _skip()

    decision_value = data.get("decision", "")
    if decision_value not in _VALID_DECISIONS:
        return _skip(f"Unknown decision value: '{decision_value}'")

    actions = [ActionItem(**a) for a in data.get("actions", []) if isinstance(a, dict)]

    # apply allow_close guard
    if not allow_close:
        actions = [a for a in actions if a.type != "close_issue"]

    return DecisionMessage(
        task_id=task_id,
        decision=decision_value,
        rationale=data.get("rationale", ""),
        actions=actions,
    )


def _recent_comment_in_memory(memory_summary: str | None) -> bool:
    """Return True if *memory_summary* indicates a recent comment was posted.

    Args:
        memory_summary: LLM-generated summary of prior actions, or ``None``.

    Returns:
        ``True`` when any recent-comment keyword is found in the summary.
    """
    if not memory_summary:
        return False
    lower = memory_summary.lower()
    return any(kw in lower for kw in _RECENT_COMMENT_KEYWORDS)


def _call_llm(prompt: str, provider: str, model: str, api_key: str | None = None) -> str:
    """Call the LLM via LiteLLM and return the response text.

    Args:
        prompt: The user prompt to send.
        provider: LLM provider identifier (e.g. ``"anthropic"``).
        model: Model name (e.g. ``"claude-haiku-4-5-20251001"``).
        api_key: Optional API key (required for Anthropic; omit for Ollama).

    Returns:
        The model's response text.
    """
    full_model = model if "/" in model else f"{provider}/{model}"
    kwargs: dict[str, Any] = {"model": full_model, "messages": [{"role": "user", "content": prompt}]}
    if api_key:
        kwargs["api_key"] = api_key
    response = litellm.completion(**kwargs)
    return response.choices[0].message.content or ""


def run_triage(task: TaskMessage) -> DecisionMessage:
    """Run LLM-based triage on *task* and return a decision.

    Applies a duplicate-comment guard before calling the LLM: if
    ``memory_summary`` indicates a comment was posted within the last 24 hours,
    the task is immediately skipped without an LLM call.

    Args:
        task: The incoming :class:`~agent.TaskMessage` from the harness.

    Returns:
        A :class:`~agent.DecisionMessage` with decision, rationale, and actions.
    """
    if _recent_comment_in_memory(task.context.memory_summary):
        from agent import DecisionMessage

        return DecisionMessage(
            task_id=task.task_id,
            decision="skip",
            rationale="A comment was posted recently — skipping to avoid duplicate response.",
            actions=[],
        )

    prompt = build_prompt(task)
    backend = task.context.llm_backend
    raw = _call_llm(prompt, provider=backend.provider, model=backend.model)

    allow_close = bool(task.payload.get("allow_close", False))
    return parse_llm_response(raw, task_id=task.task_id, allow_close=allow_close)
