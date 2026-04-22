---
title: How Foreman Works
summary: Conceptual explanation of Foreman's security model, ownership boundaries, and design decisions.
date: 2026-04-21T00:00:00.000000+00:00
---

# How Foreman Works

## The Core Problem

Running AI agents against live GitHub repositories means giving something autonomous the ability to label issues,
post comments, and close tickets on your behalf.
The obvious risk: an agent that has direct access to your GitHub token can do anything that token permits,
including actions you didn't intend, triggered by a malformed payload or a prompt injection in an issue body.

Foreman is designed around a single constraint that eliminates this risk: **the harness owns all GitHub API calls.**
**Agents never see your credentials.**

## Strict Vertical Ownership

Every component in Foreman has a single responsibility and owns exactly one layer:

```text
GitHub API polling (poller.py)
    ↓
Event router (router.py)        maps repo + event_type → agent URL
    ↓
Harness HTTP server (server.py) fetches memory, builds TaskMessage, POSTs to agent
    ↕
Agent container                 receives TaskMessage, returns DecisionMessage
    ↓
Executor (executor.py)          translates actions → GitHub API calls
    ↓
Memory store (memory.py)        logs every decision before execution
```

The agent container sits in the middle of this chain but has no sideways reach.
It receives a JSON payload over HTTP and returns a JSON response.
It cannot call GitHub, cannot read environment variables from the host, and cannot access the memory database.

## Why Agents Only Produce Action Lists

An agent could be given a GitHub token and told to act directly.
This would be simpler to implement, but it creates several problems:

**Auditability.**
When an agent calls GitHub directly, the harness has no record of what happened unless the agent writes its own log.
With action lists, the harness writes every decision and action to `action_log` *before* executing it,
giving you a complete, tamper-evident record even if a downstream API call fails.

**Safety gates.**
The `allow_close: false` default means the harness can refuse to close issues regardless of what an agent returns.
If the agent always had a token, you'd need to enforce this constraint inside the agent,
and trust that every agent you run respects it.
With the harness as the gatekeeper, the constraint is enforced once, centrally.

**Credential isolation.**
Docker containers are isolated processes, but they're not hardened sandboxes.
If an issue body contained a prompt injection that convinced an agent to exfiltrate environment variables,
a direct-token agent would leak your GitHub token.
A Foreman agent has no token to leak.

## Memory and Context

Foreman maintains a SQLite database (`~/.agent-harness/memory.db`) with three tables:

- **`action_log`** every decision logged before execution, with the rationale and action list.
- **`memory_summary`** a per-(repo, issue) LLM-generated summary injected into the next task for that issue,
    giving the agent continuity across polling cycles.
- **`poll_state`** the last-polled timestamp per repo, used to fetch only new events.

The memory summary means that an agent doesn’t need its own persistent state.
The harness handles storage and automatically injects the relevant history.

## Configuration as the Source of Truth

All behavior is controlled by `config.yaml`, not by agents.
Agents can suggest actions, but cannot override the harness configuration.
Key examples:

- **`allow_close`** — the harness checks this before executing any `close_issue` action.
- **`event_types`** — the router decides which events reach which agents; an agent cannot self-select.
- **`interval_seconds`** — the polling frequency is set by the operator, not by agents.

Secrets (GitHub token, API keys) live only in environment variables and in the harness process.
They are never written to disk in plaintext, never passed in task payloads, and never logged.
