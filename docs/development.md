---
title: Developer Guide
summary: Development environment setup, testing, and tooling reference for contributors to Foreman.
date: 2026-04-21T00:00:00.000000+00:00
---

# Developer Guide

## Setup

Install all dependency groups (runtime, dev, test, docs):

```bash
uv sync
```

Install the git pre-commit hooks:

```bash
pre-commit install
```

Pre-commit runs automatically on every `git commit`.
To run all hooks manually against every file:

```bash
pre-commit run --all-files
```

## Running Tests

| Command                                         | Description                           |
| ----------------------------------------------- | ------------------------------------- |
| `uv run pytest`                                 | Run the full test suite with coverage |
| `uv run pytest tests/test_config.py`            | Run a single test file                |
| `uv run pytest tests/test_config.py::test_name` | Run a single test                     |
| `uv run pytest --no-cov`                        | Run tests without coverage reporting  |

Coverage targets: **≥85% line coverage, ≥80% branch coverage.**

Reports are written to the terminal and to `htmlcov/` after each run.

## Pre-Commit Hooks

The following hooks run on every commit:

| Hook               | Tool                       | What it checks                                               |
| ------------------ | -------------------------- | ------------------------------------------------------------ |
| Format             | `ruff-format`              | Code style (line length 119)                                 |
| Lint               | `ruff-check`               | Import order, style rules, common errors                     |
| Type check         | `mypy`                     | Type annotations (`--no-strict-optional --ignore-missing-imports`) |
| Docstring style    | `pydoclint`                | Google-style docstrings                                      |
| Docstring coverage | `interrogate`              | ≥90% public function/method docstring coverage               |
| Secret detection   | `detect-secrets`           | Prevents committing credentials                              |
| Syntax             | `check-yaml`, `check-toml` | Valid YAML and TOML files                                    |
| Upgrade syntax     | `pyupgrade`                | Modernizes Python syntax to 3.12+                            |

## Code Style

| Concern        | Tool / Setting                                                 |
|----------------|----------------------------------------------------------------|
| Formatter      | ruff-format, line length 119                                   |
| Linter         | ruff (see `[tool.ruff]` in `pyproject.toml` for full rule set) |
| Docstrings     | Google convention (`pydoclint`, `interrogate`)                 |
| Type hints     | Required on all public functions and methods                   |
| Python minimum | 3.12                                                           |

## Testing Strategy

### LLM calls

LLM calls use recorded fixtures in `tests/fixtures/`.
Real responses are captured once and replayed in CI.
No live LLM calls are made during tests.

### GitHub API calls

Mock PyGithub and httpx at the boundary using `pytest-mock`.
Do not make real GitHub API calls in tests.

### SQLite

Use a real in-memory or temp-file database via `pytest`'s `tmp_path` fixture.
Do not mock SQLite.

```python
def test_something(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    ...
```

### Agent protocol

Integration tests spin up the agent container locally and send real HTTP task messages.
These are in `tests/integration/`.

## Project Structure

```text
foreman/
├── config.py        # YAML loader and Pydantic config models
├── credentials.py   # Environment variable resolution, get_github_token()
├── server.py        # FastAPI dispatch loop
├── poller.py        # asyncio GitHub polling loop
├── router.py        # event_type + repo → RouteTarget
├── executor.py      # DecisionMessage actions → GitHub API calls
├── memory.py        # SQLite: action_log, memory_summary, poll_state
├── protocol.py      # Pydantic models: TaskMessage, DecisionMessage, ActionItem
├── containers.py    # Docker container lifecycle management
└── llm/
    ├── base.py      # Abstract LLMBackend + from_config() factory
    ├── anthropic.py # Anthropic via LiteLLM
    └── ollama.py    # Ollama via LiteLLM
agents/
└── issue-triage/
    ├── agent.py         # FastAPI: POST /task, GET /health
    └── prompts/triage.py
tests/
├── fixtures/        # Recorded LLM response fixtures
└── integration/     # Agent container integration tests
```
