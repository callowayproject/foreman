# Implementation Plan: Foreman — AI OSS Co-Maintainer Harness

## Overview

Foreman is a minimal Python harness that acts as an always-on AI co-maintainer for OSS repositories. It manages process lifecycle, credential injection, message routing, and GitHub event polling. All intelligence lives in containerized agents. The MVP delivers automated issue triage: a maintainer installs Foreman, configures one repo, and has issues triaged without writing code — in under 30 minutes.

## Architecture Decisions

- **Vertical ownership:** The harness owns all GitHub API calls. Agents only produce decision + action lists over HTTP. Credentials never enter agent containers.
- **SQLite for memory:** Single-maintainer scale doesn't require a database server. Use stdlib `sqlite3` with a real DB in tests (not mocked).
- **LiteLLM for LLM abstraction:** One interface covers Anthropic and Ollama. Validate with the triage prompt before finalizing.
- **Polling-only in v1:** No public URL assumed. GitHub API polling on a configurable interval.
- **FastAPI for harness server:** Lightweight, async-native, Pydantic-integrated. Better fit than Flask for this workload.
- **Partial scaffolding already exists:** `server.py`, `settings.py`, `logging_info.py`, `middleware.py`, `otel.py`, and `routers/health.py` are scaffolded. Task 1 fixes known issues; Task 11 adds the dispatch loop to `server.py` without removing the existing setup.
- **`settings.py` vs `config.py`:** `settings.py` (scaffolded) handles operational settings from env vars via `pydantic-settings`. `config.py` (to be built in Task 2) handles the YAML runtime config for repos/agents/LLM.

## Dependency Graph

```
pyproject.toml / project scaffold
        │
        ├── Config (YAML + Pydantic)
        │       │
        │       ├── Credentials (env var resolution)
        │       │
        │       ├── LLM backends (LiteLLM adapter)
        │       │
        │       └── Poller (GitHub polling loop)
        │               │
        │               └── Router (event → agent routing)
        │
        ├── Agent Protocol models (Task / Decision Pydantic types)
        │       │
        │       ├── Harness server (dispatch tasks, receive decisions)
        │       │
        │       └── Issue Triage Agent (/task endpoint)
        │
        ├── Memory (SQLite action_log + memory_summary)
        │       └── injected into Task context by Harness
        │
        └── Executor (action list → GitHub API calls)
                └── called by Harness after each decision
```

---

## Phase 1: Foundation

### Task 1: Project scaffold and pyproject.toml

**Description:** The scaffolding for `server.py`, `settings.py`, `logging_info.py`, `middleware.py`, `otel.py`, and `routers/health.py` already exists. This task fixes the three known scaffolding issues from spec §12 and completes the directory skeleton (remaining `__init__.py` stubs, empty test files, Dockerfile placeholder).

Known issues to fix (spec §12):
1. `pyproject.toml` — uncomment `[project.scripts]` and point to `foreman/__main__.py`; add missing runtime deps (`PyYAML`, `PyGithub`, `litellm`, `httpx`, `docker`)
2. `pyproject.toml` — targets Python 3.12+ (not 3.10+)
3. `server.py` — currently a generic FastAPI template; the dispatch loop will be added in Task 11 (retain existing middleware/CORS/logging setup)

**Acceptance criteria:**
- [ ] `pyproject.toml` names the project `foreman`, targets Python 3.12+, uses hatchling as build backend
- [ ] `[project.scripts]` entry points to `foreman.__main__:main` (uncommented)
- [ ] Runtime deps (`PyYAML`, `PyGithub`, `litellm`, `httpx`, `docker`) are listed
- [ ] Remaining directories from spec §4 exist with stub files (`foreman/protocol.py`, `foreman/config.py`, etc.)
- [ ] `uv sync` succeeds
- [ ] `pre-commit run --all-files` on stubs passes (or produces only expected stub-level failures)

**Verification:**
- [ ] `uv sync` exits 0
- [ ] `python -c "import foreman"` succeeds
- [ ] Directory tree matches spec §4

**Dependencies:** None

**Files likely touched:**
- `pyproject.toml`
- `foreman/__init__.py` + remaining submodule stubs
- `agents/issue-triage/` scaffolding

**Estimated scope:** Medium (3–5 files)

---

### Task 2: Config system — YAML loader + Pydantic validation

**Description:** Implement `foreman/config.py`. Load `config.yaml`, resolve environment variable references (`${VAR}` syntax), validate with a Pydantic model that covers all fields in spec §5. Fail fast on startup with a clear error if validation fails. No secret values should appear in repr/str output.

**Acceptance criteria:**
- [ ] Valid config YAML loads without error
- [ ] Missing required field raises `ConfigError` with the field name
- [ ] `${VAR}` references resolve from environment; missing env var raises `ConfigError`
- [ ] `repr()` of the config object does not contain token or API key values
- [ ] `config.example.yaml` matches the schema (loads without error)

**Verification:**
- [ ] `pytest tests/test_config.py` passes with ≥85% coverage on `config.py`

**Dependencies:** Task 1

**Files likely touched:**
- `foreman/config.py`
- `foreman/credentials.py` (env var resolution helper)
- `tests/test_config.py`
- `config.example.yaml`

**Estimated scope:** Medium (3–5 files)

---

### Task 3: Credential injection

**Description:** Implement `foreman/credentials.py` — a thin module that resolves `${VAR}` references in config values and provides a `get_github_token() -> str` function. Ensure no credential value is written to logs. Credential resolution is already partially needed in Task 2; this task finalises the module and adds tests.

**Acceptance criteria:**
- [ ] `resolve_env_refs(value: str) -> str` correctly substitutes all `${VAR}` patterns
- [ ] Missing env var raises `CredentialError` with the variable name (not the attempted value)
- [ ] `get_github_token()` returns the resolved token from config

**Verification:**
- [ ] `pytest tests/test_credentials.py` passes
- [ ] `detect-secrets scan` finds no hardcoded secrets in the module

**Dependencies:** Task 2

**Files likely touched:**
- `foreman/credentials.py`
- `tests/test_credentials.py`

**Estimated scope:** Small (1–2 files)

---

### Checkpoint: Phase 1 — Foundation

- [ ] `uv sync` and `pre-commit run --all-files` pass
- [ ] `pytest tests/test_config.py tests/test_credentials.py` passes
- [ ] Project structure matches spec §4
- [ ] Review with human before proceeding

---

## Phase 2: Data and Memory Layer

### Task 4: Agent protocol models

**Description:** Implement Pydantic models for the Task and Decision message contracts defined in spec §3. These are the shared data types used by the harness server, router, executor, and agents.

**Acceptance criteria:**
- [ ] `TaskMessage` model validates the harness→agent JSON shape (task_id, type, repo, payload, context)
- [ ] `DecisionMessage` model validates the agent→harness JSON shape (task_id, decision enum, rationale, actions list)
- [ ] `ActionItem` model covers all action types (`add_label`, `comment`, `close_issue`)
- [ ] Invalid JSON raises a clear Pydantic `ValidationError`

**Verification:**
- [ ] Unit tests for valid and invalid message shapes pass
- [ ] Models serialise round-trip without data loss

**Dependencies:** Task 1

**Files likely touched:**
- `foreman/protocol.py` (new — not in spec structure, add to `foreman/`)
- `tests/test_protocol.py`

**Estimated scope:** Small (1–2 files)

---

### Task 5: Persistent memory (SQLite)

**Description:** Implement `foreman/memory.py`. Create the `action_log` and `memory_summary` tables on first run. Provide: `log_action(...)`, `get_summary(repo, issue_id) -> str | None`, `update_summary(repo, issue_id, summary)`. Use stdlib `sqlite3`. No mocking in tests — use a real temp-file DB via pytest `tmp_path`.

**Acceptance criteria:**
- [ ] DB file is created at the configured path if it doesn't exist
- [ ] `log_action` writes a row to `action_log` with all required fields
- [ ] `get_summary` returns `None` for an unknown repo/issue
- [ ] `update_summary` inserts or replaces the summary for a repo/issue pair
- [ ] Concurrent calls from the same process don't corrupt the DB (WAL mode enabled)

**Verification:**
- [ ] `pytest tests/test_memory.py` passes with ≥85% branch coverage on `memory.py`
- [ ] No use of `unittest.mock` or `pytest-mock` for SQLite calls

**Dependencies:** Task 1

**Files likely touched:**
- `foreman/memory.py`
- `tests/test_memory.py`

**Estimated scope:** Small (1–2 files)

---

### Checkpoint: Phase 2 — Data Layer

- [ ] `pytest tests/test_protocol.py tests/test_memory.py` passes
- [ ] Memory DB schema matches spec §6 exactly
- [ ] Review with human before proceeding

---

## Phase 3: LLM Abstraction

### Task 6: LLM backend base interface

**Description:** Implement `foreman/llm/base.py` — an abstract base class `LLMBackend` with a single method `complete(prompt: str, system: str | None) -> str`. Include a `from_config(config: LLMConfig) -> LLMBackend` factory.

**Acceptance criteria:**
- [ ] `LLMBackend` is an ABC with `complete` as the abstract method
- [ ] `from_config` returns the correct concrete class based on `provider`
- [ ] Unsupported provider raises `ValueError` with the provider name

**Verification:**
- [ ] Unit tests for factory logic pass (no real LLM calls)

**Dependencies:** Task 2

**Files likely touched:**
- `foreman/llm/__init__.py`
- `foreman/llm/base.py`
- `tests/test_llm_base.py`

**Estimated scope:** Small (1–2 files)

---

### Task 7: Anthropic + Ollama backends via LiteLLM

**Description:** Implement `foreman/llm/anthropic.py` and `foreman/llm/ollama.py`, both wrapping LiteLLM. Both classes implement `LLMBackend.complete`. Tests use recorded fixtures (real LLM responses captured once, stored in `tests/fixtures/`, replayed in CI).

**Acceptance criteria:**
- [ ] `AnthropicBackend.complete` returns the model's text response
- [ ] `OllamaBackend.complete` returns the model's text response
- [ ] Fixtures exist for at least one triage prompt per backend
- [ ] Tests replay fixtures without live LLM calls

**Verification:**
- [ ] `pytest tests/test_llm_backends.py` passes with no live LLM calls
- [ ] Same triage prompt sent to both backends produces structurally equivalent decisions (manual validation step, not automated)

**Dependencies:** Task 6

**Files likely touched:**
- `foreman/llm/anthropic.py`
- `foreman/llm/ollama.py`
- `tests/test_llm_backends.py`
- `tests/fixtures/anthropic_triage_response.json`
- `tests/fixtures/ollama_triage_response.json`

**Estimated scope:** Medium (3–5 files)

---

### Checkpoint: Phase 3 — LLM Abstraction

- [ ] `pytest tests/test_llm_*.py` passes, no live LLM calls
- [ ] Both backends reachable locally (manual smoke test: capture fixtures)
- [ ] Review with human before proceeding

---

## Phase 4: GitHub Integration

### Task 8: GitHub executor

**Description:** Implement `foreman/executor.py`. Given a `DecisionMessage`, translate each action into a GitHub API call (add label, post comment, close issue). All calls use the bot identity from config. Mock PyGithub/httpx at the boundary in tests.

**Acceptance criteria:**
- [ ] `execute(decision: DecisionMessage, repo: str)` processes all actions in order
- [ ] `add_label` calls the correct PyGithub method with the label name
- [ ] `comment` posts the body string to the issue
- [ ] `close_issue` only runs if `allow_close: true` is set in agent config; skipped otherwise
- [ ] Actions are logged to `action_log` before execution (not after)
- [ ] Unknown action types raise `UnknownActionError` (not silently skipped)

**Verification:**
- [ ] `pytest tests/test_executor.py` passes with mocked GitHub calls
- [ ] `close_issue` guard test: confirm close is skipped when `allow_close` is false

**Dependencies:** Tasks 2, 4, 5

**Files likely touched:**
- `foreman/executor.py`
- `tests/test_executor.py`

**Estimated scope:** Small–Medium (2–3 files)

---

### Task 9: GitHub poller

**Description:** Implement `foreman/poller.py`. Poll all configured repos concurrently on `interval_seconds`. There is no maximum repo count, so use `asyncio` with a semaphore to bound concurrent GitHub API calls and avoid rate limits. For each repo, fetch new or updated issues since the last poll timestamp (persisted in the memory DB between restarts). Emit events to the router. Skip issues created by repo owners/maintainers unless overridden.

**Acceptance criteria:**
- [ ] Poller polls all repos concurrently (asyncio + semaphore, default max 5 concurrent)
- [ ] Only issues updated since `last_polled` are emitted per repo
- [ ] `last_polled` timestamp is persisted to memory DB and survives restarts
- [ ] Issues by repo owners/maintainers are skipped by default
- [ ] Single poll cycle is independently testable (not entangled with the loop)
- [ ] GitHub 403/429 responses trigger exponential backoff, not a crash

**Verification:**
- [ ] `pytest tests/test_poller.py` passes with mocked GitHub API calls
- [ ] Manual: start the poller against a test repo, confirm it emits exactly the expected events

**Dependencies:** Tasks 2, 3, 5

**Files likely touched:**
- `foreman/poller.py`
- `tests/test_poller.py`

**Estimated scope:** Medium (2–3 files)

---

### Checkpoint: Phase 4 — GitHub Integration

- [ ] `pytest tests/test_executor.py tests/test_poller.py` passes
- [ ] No live GitHub calls in tests
- [ ] Review with human before proceeding

---

## Phase 5: Harness Core

### Task 10: Router

**Description:** Implement `foreman/routers/agent.py`. Map incoming GitHub events (by repo + event type) to the agent URL configured for that repo. Return a `RouteTarget` with the agent URL and merged agent config. Note: `foreman/routers/` already exists with `health.py` scaffolded — add `agent.py` to the same package.

**Acceptance criteria:**
- [ ] `route(event_type: str, repo: str) -> RouteTarget` returns the correct agent URL
- [ ] Unmapped event type returns `None` (skip, no error)
- [ ] Unmapped repo raises `RoutingError`
- [ ] Multiple agents per repo are supported (each handles its own event types)

**Verification:**
- [ ] `pytest tests/test_router.py` passes
- [ ] Edge cases covered: unknown event type, unknown repo, multiple agents

**Dependencies:** Tasks 2, 4

**Files likely touched:**
- `foreman/routers/agent.py` (new — in the existing `routers/` package)
- `foreman/routers/__init__.py` (update exports)
- `tests/test_router.py`

**Estimated scope:** Small (1–2 files)

---

### Task 11: Harness HTTP server and dispatch loop

**Description:** Extend `foreman/server.py` with the Foreman dispatch loop. The file is already scaffolded as a generic FastAPI app with CORS, GZip, middleware, and structlog — retain all of that and add: (1) receive routed events from the poller, (2) fetch the memory summary for context, (3) build a `TaskMessage`, (4) POST it to the agent container's `/task` endpoint, (5) receive the `DecisionMessage`, (6) call the executor. This is the orchestration core.

**Acceptance criteria:**
- [ ] `dispatch(event, route_target)` builds and sends the task, receives the decision, executes actions
- [ ] Memory summary is injected into task context before dispatch
- [ ] Memory summary is updated after the decision is logged
- [ ] Agent HTTP errors (non-200) are logged and the task is skipped, not crashed
- [ ] A task is never dispatched more than once concurrently to the same agent

**Verification:**
- [ ] `pytest tests/test_server.py` passes with mocked agent HTTP calls and mocked executor
- [ ] Sequence verified: log → dispatch → receive → execute → update summary

**Dependencies:** Tasks 4, 5, 8, 10

**Files likely touched:**
- `foreman/server.py`
- `tests/test_server.py`

**Estimated scope:** Medium (2–3 files)

---

### Task 12: Main entrypoint and startup validation

**Description:** Implement `foreman/__main__.py` (or a `foreman.main` module). On startup: load and validate config (fail fast), initialize the memory DB, start the poller loop, start the FastAPI server. Provide a CLI entry point (`foreman start --config config.yaml`).

**Acceptance criteria:**
- [ ] `foreman start --config missing.yaml` exits with a clear error message (non-zero)
- [ ] Invalid config exits with the specific field that failed validation
- [ ] Startup sequence: validate → init DB → start poller → start server
- [ ] `SIGINT` / `SIGTERM` shuts down cleanly (no orphaned threads)

**Verification:**
- [ ] `foreman start --config config.example.yaml` starts without error (requires example config with valid env vars set)
- [ ] `pytest tests/test_main.py` covers startup error paths

**Dependencies:** Tasks 2, 5, 9, 11

**Files likely touched:**
- `foreman/__main__.py`
- `tests/test_main.py`

**Estimated scope:** Small–Medium (2–3 files)

---

### Checkpoint: Phase 5 — Harness Core

- [ ] `pytest tests/` passes (all harness tests)
- [ ] `foreman start --config config.example.yaml` starts cleanly with valid env vars
- [ ] Poller → Router → Server → Executor sequence is exercised end-to-end in a test
- [ ] Review with human before proceeding

---

## Phase 6: Issue Triage Agent

### Task 13: Container lifecycle manager

**Description:** Implement `foreman/containers.py`. The harness manages Docker container start/stop for each configured agent type. On startup, pull (if needed) and start agent containers. On shutdown, stop them. Expose `start_agent(agent_type: str) -> str` (returns container URL) and `stop_all()`. Use the Docker SDK for Python (`docker` package).

**Acceptance criteria:**
- [ ] `start_agent` pulls the image if not present locally, starts the container, and waits for the `/health` endpoint to respond before returning
- [ ] `stop_all` stops all managed containers on harness shutdown
- [ ] If a container exits unexpectedly, the harness logs the error and attempts one restart before marking it failed
- [ ] Container URLs are registered with the router after startup
- [ ] Docker socket unavailability raises `ContainerError` with a clear message at startup

**Verification:**
- [ ] `pytest tests/test_containers.py` passes with mocked Docker SDK calls
- [ ] Manual: `foreman start` brings up the triage container and registers its URL

**Dependencies:** Tasks 2, 10

**Files likely touched:**
- `foreman/containers.py`
- `tests/test_containers.py`

**Estimated scope:** Medium (2–3 files)

---

### Task 14: Agent HTTP server scaffold

**Description:** Implement `agents/issue-triage/agent.py` — a FastAPI app that exposes `POST /task` and `GET /health`. Receives a `TaskMessage`, delegates to triage logic, returns a `DecisionMessage`. Write the `Dockerfile` and `agents/issue-triage/pyproject.toml`.

**Acceptance criteria:**
- [ ] `POST /task` with a valid `TaskMessage` body returns a `DecisionMessage` with HTTP 200
- [ ] `POST /task` with invalid JSON returns HTTP 422
- [ ] `GET /health` returns HTTP 200 (required by container lifecycle manager)
- [ ] Container builds with `docker build` without errors
- [ ] Container starts and passes the health check used by Task 13

**Verification:**
- [ ] `docker build -t foreman-issue-triage agents/issue-triage/` succeeds
- [ ] `pytest tests/test_agent_triage.py` integration tests pass (spin up container locally)

**Dependencies:** Tasks 4, 7, 13

**Files likely touched:**
- `agents/issue-triage/agent.py`
- `agents/issue-triage/Dockerfile`
- `agents/issue-triage/pyproject.toml`

**Estimated scope:** Medium (3–4 files)

---

### Task 15: Triage logic and prompt

**Description:** Implement `agents/issue-triage/prompts/triage.py` and the triage decision function. Given a `TaskMessage` (issue payload + memory summary + LLM backend config), call the LLM backend and parse the response into a `DecisionMessage`. Handle the four decisions: `label_and_respond`, `close`, `escalate`, `skip`.

**Acceptance criteria:**
- [ ] LLM response is parsed into a valid `DecisionMessage`
- [ ] Unparseable LLM response defaults to `skip` (not a crash)
- [ ] `close` decision is only included in actions if `allow_close: true` in agent config
- [ ] Duplicate comment guard: if a comment was posted in the last 24 hours (from memory), action is `skip`
- [ ] Prompt includes the memory summary when present

**Verification:**
- [ ] `pytest tests/test_agent_triage.py` passes using recorded LLM fixtures
- [ ] Manual: send a real issue payload to the running container, verify correct decision

**Dependencies:** Tasks 7, 14

**Files likely touched:**
- `agents/issue-triage/prompts/triage.py`
- `tests/test_agent_triage.py`
- `tests/fixtures/` (triage-specific fixtures)

**Estimated scope:** Medium (3–4 files)

---

---

### Task 13b: Wire ContainerManager into startup sequence

**Description:** `ContainerManager` (Task 13) was built as a standalone component but is never instantiated or called from `__main__.py`. The `Router.register_url()` method exists for exactly this purpose but is also never called. This task wires container startup/shutdown into `_run_start` / `_run_loop` and calls `router.register_url()` so that dynamically-assigned container ports are used at dispatch time.

Changes needed in `foreman/__main__.py`:
1. Instantiate `ContainerManager` in `_run_start` (or pass it into `_run_loop`).
2. Collect the unique agent types configured across all repos.
3. For each unique agent type, call `container_manager.start_agent(agent_type)` to pull/start the container and get its URL.
4. Call `router.register_url(agent_type, url)` for each started container before the poll loop begins.
5. On shutdown (the `finally` block in `_run_loop`), call `container_manager.stop_all()`.
6. Catch `ContainerError` at startup and exit with a clear error message (non-zero).

**Acceptance criteria:**
- [ ] `foreman start` pulls and starts agent containers before the poll loop begins
- [ ] `router.register_url` is called for each successfully started container
- [ ] `stop_all` is called on clean shutdown (SIGINT/SIGTERM)
- [ ] `ContainerError` on Docker unavailability exits with a clear error (non-zero exit code)
- [ ] If no agents are configured with a known image, startup proceeds without Docker (graceful degradation)

**Verification:**
- [ ] `pytest tests/test_main.py` covers container startup, URL registration, and shutdown paths (mocked Docker SDK)
- [ ] Manual: `foreman start --config config.example.yaml` brings up the triage container and registers its URL before the first poll

**Dependencies:** Tasks 10, 12, 13

**Files likely touched:**
- `foreman/__main__.py`
- `tests/test_main.py`

**Estimated scope:** Small (1–2 files)

---

### Checkpoint: Phase 6 — Issue Triage Agent

- [ ] `docker build` succeeds
- [ ] Container lifecycle manager starts and stops the triage container cleanly
- [ ] Integration tests (container + harness) pass
- [ ] Triage decisions verified against the four decision types
- [ ] Review with human before proceeding

---

## Phase 7: Integration and Polish

### Task 16: End-to-end integration test

**Description:** Write an integration test that exercises the full path: poller detects a new issue → router maps it → harness dispatches a task to the agent container → agent returns a decision → executor applies actions (mocked GitHub API). Use recorded LLM fixtures so no live LLM calls are made.

**Acceptance criteria:**
- [ ] One test covers the complete happy path for issue triage
- [ ] Memory is updated after the decision (verified by reading the DB)
- [ ] Mocked GitHub API calls match expected calls (labels + comment posted)
- [ ] Test is repeatable (no order dependencies, no shared state)

**Verification:**
- [ ] `pytest tests/test_integration.py` passes
- [ ] Coverage report shows ≥85% line and ≥80% branch coverage overall

**Dependencies:** Tasks 12, 15

**Files likely touched:**
- `tests/test_integration.py`

**Estimated scope:** Medium (1–2 test files, but touches many modules)

---

### Task 17: config.example.yaml and CHANGELOG bootstrap

**Description:** Finalize `config.example.yaml` to match the full schema. Create `CHANGELOG.md` with an initial `0.1.0` entry. Verify `pre-commit run --all-files` passes clean on the full codebase.

**Acceptance criteria:**
- [ ] `config.example.yaml` loads without error via the config module
- [ ] All schema fields are present and commented
- [ ] `CHANGELOG.md` follows the keep-a-changelog format
- [ ] `pre-commit run --all-files` exits 0

**Verification:**
- [ ] `python -c "from foreman.config import load_config; load_config('config.example.yaml')"` succeeds with required env vars set
- [ ] `pre-commit run --all-files` exits 0

**Dependencies:** Task 2

**Files likely touched:**
- `config.example.yaml`
- `CHANGELOG.md`

**Estimated scope:** Small (1–2 files)

---

### Final Checkpoint

- [ ] `pytest tests/` passes with ≥85% line / ≥80% branch coverage
- [ ] `pre-commit run --all-files` exits 0
- [ ] `foreman start --config config.example.yaml` starts and polls a test repo
- [ ] Issue triage works end-to-end: new issue → labeled + commented by bot
- [ ] Human acceptance test: install on a real repo, triage one issue in <30 minutes
- [ ] All acceptance criteria in spec §2 and §10 are met

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LiteLLM latency or capability gaps between Anthropic and Ollama | High | Validate with the triage prompt against both backends in Task 7 before committing |
| Docker not available in deployment environment | High | Document as a hard prerequisite in README; fail fast with a clear message |
| SQLite WAL mode insufficient under concurrent multi-repo polling | Low | WAL mode enabled; revisit only if locking issues observed; SQLite advisory locks as fallback |
| GitHub rate limits on polling interval | Medium | Implement exponential backoff and cache `ETag` headers for conditional requests |
| Agent container cold-start latency on first dispatch | Low | Warm containers on startup; document expected first-dispatch latency |

## Open Questions — Resolved

| Question | Decision |
|----------|----------|
| Container lifecycle management | Harness manages start/stop of agent containers (not pre-started). Add Task 13a: Container lifecycle manager. |
| Maximum number of repos | No limit. Poller must handle unbounded repo lists; use concurrent polling with a semaphore to avoid GitHub rate limits. |
| Polling timestamps between restarts | Yes — stored in memory DB (already planned). |
