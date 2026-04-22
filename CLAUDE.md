# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Foreman** is a minimal Python harness acting as an always-on AI co-maintainer for OSS repositories.
It manages process lifecycle, credential injection, message routing, and GitHub event polling.
All intelligence lives in containerized agents.
The harness owns all GitHub API calls — agents only produce decision + action lists over HTTP,
so credentials never enter agent containers.

The MVP target: a maintainer installs Foreman, configures one repo, and has issues triaged
(labeled, responded to, or closed) without writing code — in under 30 minutes.

## Spec-driven Development

New features are developed by hashing out an idea.
This idea is then turned into a spec.
The spec is turned into a plan.
The plan is iteratively implemented.

All files for a feature are written in Markdown and live in the `docs/specs/<feature-name>/` directory.

## Commands

### Setup

```bash
uv sync                        # install all dependency groups (dev, test, docs)
pre-commit install             # install git hooks
```

### Development

Always add `--agent-digest=term` when running pytest to see token-optimized test results.

Use the python-tester skill when writing Python tests.

```bash
uv run pytest --agent-digest=term                  # run all tests with coverage
uv run pytest --agent-digest=term tests/test_config.py # run a single test file
uv run pytest --agent-digest=term tests/test_config.py::test_name # run a single test
uv run pytest --agent-digest=term --no-cov         # run tests without coverage
pre-commit run --all-files                         # run all linters/formatters
```

### Entry point (once implemented)

```bash
uv run foreman start --config config.yaml
```

## Architecture

The system follows a strict vertical ownership model:

```text
GitHub API polling (poller.py)
    → Event router (router.py) — maps repo+event_type → agent URL
        → Harness HTTP server (server.py) — fetches memory, builds TaskMessage, POSTs to agent
            ↔ Agent container (agents/issue-triage/) — returns DecisionMessage
        → Executor (executor.py) — translates actions into GitHub API calls
        → Memory (memory.py) — logs every action, updates per-issue summaries
```

**Key constraint:** The harness executes all GitHub API calls.
Agents produce `DecisionMessage` (decision + action list) — they never call GitHub directly.

### Agent Protocol (JSON over HTTP)

**Task (harness → agent):**

```json
{ "task_id": "uuid4", "type": "issue.triage", "repo": "owner/repo",
  "payload": {}, "context": { "memory_summary": "...", "llm_backend": {...} } }
```

**Decision (agent → harness):**

```json
{ "task_id": "uuid4", "decision": "label_and_respond|close|escalate|skip",
  "rationale": "...", "actions": [{"type": "add_label", "label": "bug"}, ...] }
```

### Planned Module Structure

```text
foreman/
├── config.py           # YAML config loader + Pydantic validation; ${VAR} env resolution
├── credentials.py      # Env var resolution; get_github_token()
├── server.py           # FastAPI — dispatch loop: fetch memory → build task → POST to agent → execute
├── poller.py           # asyncio polling loop; concurrent per-repo with semaphore (default max 5)
├── router.py           # event_type + repo → RouteTarget (agent URL + merged config)
├── executor.py         # DecisionMessage actions → GitHub API calls (via PyGithub/httpx)
├── memory.py           # SQLite: action_log + memory_summary tables; WAL mode
├── protocol.py         # Pydantic models: TaskMessage, DecisionMessage, ActionItem
└── llm/
    ├── base.py         # Abstract LLMBackend ABC + from_config() factory
    ├── anthropic.py    # Wraps LiteLLM for Anthropic
    └── ollama.py       # Wraps LiteLLM for Ollama
agents/
└── issue-triage/
    ├── agent.py        # FastAPI: POST /task, GET /health
    └── prompts/triage.py
```

### Memory (SQLite)

Two tables in `~/.agent-harness/memory.db` (path overridable in config):

- `action_log` — every decision logged before execution
- `memory_summary` — per-repo+issue LLM-generated summary injected into task context on next dispatch

SQLite is used directly via stdlib `sqlite3` — **never mock it in tests**;
use a real temp-file DB via `pytest tmp_path`.

### Configuration (YAML)

All secrets are `${VAR}` environment variable references — the config file itself never contains raw secrets.
See `config.example.yaml` for the full schema.

## Code Style

- **Formatter/linter:** ruff (line length 119, Google docstring convention)
- **Type checking:** mypy (`--no-strict-optional --ignore-missing-imports`)
- **Docstrings:** interrogate (≥90% coverage), pydoclint (Google style)
- **Type hints:** required on all public functions and methods; `--keep-runtime-typing`
- **Python minimum:** 3.12

Pre-commit hooks enforce: ruff-format, ruff-check, mypy, pydoclint, interrogate, detect-secrets, pyupgrade, check-yaml,
check-toml.

## Testing Strategy

- **Framework:** pytest + pytest-cov; target ≥85% line / ≥80% branch coverage
- **LLM calls:** Recorded fixtures in `tests/fixtures/` — real responses captured once, replayed in CI.
    No live LLM calls.
- **GitHub API calls:** Mock PyGithub/httpx at the boundary with pytest-mock.
- **SQLite:** Use a real in-memory or temp-file DB — never mock it.
- **Agent protocol:** Integration tests spin up the agent container locally and send real HTTP task messages.

## Behavioral Constraints

**Always automatic:**

- Poll configured repos on the set interval
- Inject credentials from environment; never log or expose them
- Write every decision and action to `action_log` before executing

**Require explicit `allow_close: true` in agent config:**

- Closing an issue (default: label + comment only)

**Never:**

- Call GitHub API as anything other than the configured bot identity
- Store raw secrets in config, logs, or the memory DB
- Execute shell commands or arbitrary code from agent decision payloads
