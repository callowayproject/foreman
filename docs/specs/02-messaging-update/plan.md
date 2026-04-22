# Implementation Plan: Queue-Mediated Agent Protocol

## Overview

Replace the synchronous `POST /task → DecisionMessage` dispatch in `server.py` with a durable, SQLite-backed task queue.
Events are enqueued before any dispatch attempt; agents claim tasks via HTTP;
the harness drains completed tasks on a background loop.
Zero task loss under an agent restart is the MVP acceptance criterion.

## Architecture Decisions

- **Config-first:** Add `QueueConfig` to `config.py` before writing `TaskQueue` — the timeout
  and retry defaults flow from config into every other component.
- **Harness owns the database:** Agents never touch `queue.db` directly.
  All queue I/O goes through HTTP endpoints on the harness.
  `foreman-client` wraps these calls.
- **Three new harness endpoints:** `POST /queue/next` (claim), `POST /queue/complete`
  (store result), `POST /queue/heartbeat` (extend claim window); plus `POST /harness/result` (drain nudge).
  Only `/harness/result` is specified in the spec;
  the other three are the implicit contract required by `ForemanClient.next_task()` / `complete_task()` / `heartbeat()`.
- **`complete_task()` does two things:** stores the `DecisionMessage` in the queue DB *and*
  sends `POST /harness/result` to nudge the drain loop — so agent authors call only one method.
- **Delete the synchronous path entirely in Phase 4:** no fallback, no feature flag.

## Open Questions (resolve before Phase 4)

- What HTTP status code should `POST /queue/next` return when the queue is empty —
  `204 No Content` or `200` with a `null` body?
  (Plan assumes `204`.)
- Should `POST /queue/complete` accept a standalone `DecisionMessage`, or a wrapper `{task_id, decision}`?
  (Plan assumes the full `DecisionMessage` as the body, since it already carries `task_id`.)

## Task List

### Phase 1: Configuration and Queue Foundation

#### Task 1: Add `QueueConfig` to `config.py`

**Description:** Extend `ForemanConfig` with a new optional `queue: QueueConfig` section.
Mirror the pattern used for `PollingConfig` — a Pydantic model with typed fields and defaults,
added as an optional field on `ForemanConfig`.
Update `config.example.yaml` with the new section (commented out, showing defaults).

**Acceptance criteria:**

- [ ] `QueueConfig` model exists with fields: `db_path: Path | None`, `claim_timeout_seconds: int = 300`,
  `max_retries: int = 3`, `drain_interval_seconds: int = 10`, `requeue_interval_seconds: int = 60`
- [ ] `ForemanConfig.queue` defaults to a zero-config `QueueConfig()` when the section is absent
- [ ] `${VAR}` references in `db_path` resolve correctly (inherits `_resolve_refs_in`)
- [ ] Existing config tests still pass

**Verification:**

- [ ] `uv run pytest --agent-digest=term tests/test_config.py`
- [ ] `pre-commit run --all-files`

**Dependencies:** None

**Files likely touched:**

- `foreman/config.py`
- `config.example.yaml`
- `tests/test_config.py`

**Estimated scope:** S

#### Task 2: Implement `foreman/queue.py` — `TaskQueue`

**Description:** Create `foreman/queue.py` with the `TaskQueue` class and `queue.db` schema.
Follow the exact patterns from `memory.py`: `PRAGMA journal_mode=WAL`, `check_same_thread=False`,
`executescript` for DDL, no ORM.
Implement all six public methods from the spec.

The `claim_next()` method must use a single `UPDATE … RETURNING`
or a `SELECT … FOR UPDATE` workaround to be concurrency-safe under multiple simultaneous callers
(SQLite serialises writes, so `BEGIN IMMEDIATE` + `SELECT` + `UPDATE` in a single transaction is sufficient).

**Acceptance criteria:**

- [ ] `queue.db` schema matches spec (§3.1): `task_queue` table with all columns + index
- [ ] `enqueue()` inserts with `status=pending`
- [ ] `claim_next()` atomically claims oldest pending task for the given `agent_url`; returns `None` when empty
- [ ] `complete()` sets `status=completed` and stores the serialised `DecisionMessage`
- [ ] `heartbeat()` updates `last_heartbeat`
- [ ] `drain_completed()` returns all `completed` rows and sets them to `done`
- [ ] `requeue_stale()` re-enqueues `claimed` tasks past the claim timeout; increments `retry_count`
- [ ] `fail_exhausted()` marks tasks with `retry_count >= max_retries` as `failed`
- [ ] DB file and parent directories are auto-created (matching `MemoryStore` behaviour)

**Verification:**

- [ ] `uv run pytest --agent-digest=term tests/test_queue.py` (written in Task 3)
- [ ] `pre-commit run --all-files`

**Dependencies:** Task 1

**Files likely touched:**

- `foreman/queue.py` (new)

**Estimated scope:** M

#### Task 3: Tests for `TaskQueue`

**Description:** Write `tests/test_queue.py` covering all `TaskQueue` methods.
Use a real temp-file SQLite DB via `pytest tmp_path` — never mock SQLite.
Use `freezegun` or manual timestamp manipulation to test timeout-based behaviour.

**Acceptance criteria:**

- [ ] Schema creation: `task_queue` table and index exist after init
- [ ] `enqueue` + `claim_next` happy path: task round-trips correctly
- [ ] `claim_next` returns `None` on empty queue
- [ ] `complete` + `drain_completed`: completed task is returned and marked `done`
- [ ] `requeue_stale`: task claimed but not heartbeated past timeout → re-enqueued, `retry_count` incremented
- [ ] `fail_exhausted`: task at `max_retries` → `status=failed`
- [ ] Concurrent claim: two threads call `claim_next()` simultaneously; only one receives the task
- [ ] Coverage ≥85% line / ≥80% branch for `foreman/queue.py`

**Verification:**

- [ ] `uv run pytest --agent-digest=term tests/test_queue.py --cov=foreman/queue.py`
- [ ] `pre-commit run --all-files`

**Dependencies:** Task 2

**Files likely touched:**

- `tests/test_queue.py` (new)

**Estimated scope:** M

### Checkpoint: Phase 1

- [ ] `uv run pytest --agent-digest=term` — all tests pass
- [ ] `pre-commit run --all-files` — clean
- [ ] `TaskQueue` is fully exercised; concurrent-claim test passes
- [ ] Human review before proceeding

### Phase 2: Harness Queue API Endpoints

#### Task 4: Queue HTTP endpoints — `foreman/routers/queue.py`

**Description:** Add three new harness endpoints that `ForemanClient` will call.
Follow the existing router pattern (`foreman/routers/health.py`).
The router receives a `TaskQueue` instance via FastAPI dependency injection (use `app.state.task_queue`).

| Endpoint                | Body                   | Response                              |
|-------------------------|------------------------|---------------------------------------|
| `POST /queue/next`      | `{"agent_url": "..."}` | `TaskMessage` (200) or 204 No Content |
| `POST /queue/complete`  | `DecisionMessage` JSON | 202 Accepted                          |
| `POST /queue/heartbeat` | `{"task_id": "..."}`   | 202 Accepted                          |

`POST /queue/complete` calls `TaskQueue.complete()` then immediately triggers the drain loop
(same signal mechanism used by `POST /harness/result`).

**Acceptance criteria:**

- [ ] `POST /queue/next` returns 200 + `TaskMessage` JSON when a task is available
- [ ] `POST /queue/next` returns 204 when the queue is empty
- [ ] `POST /queue/complete` stores the decision and returns 202
- [ ] `POST /queue/heartbeat` updates `last_heartbeat` and returns 202
- [ ] All endpoints return 202 immediately (no blocking on downstream work)
- [ ] Router is included in `app` (registered in `server.py`)

**Verification:**

- [ ] `uv run pytest --agent-digest=term tests/test_queue_router.py` (written in Task 6)
- [ ] `pre-commit run --all-files`

**Dependencies:** Tasks 2, 3

**Files likely touched:**

- `foreman/routers/queue.py` (new)
- `foreman/server.py` (register router, expose `task_queue` on `app.state`)

**Estimated scope:** M

#### Task 5: `POST /harness/result` endpoint — `foreman/routers/result.py`

**Description:** Add the agent-nudge endpoint from spec §3.4.
On receipt, it triggers the drain loop immediately (in addition to its background schedule).
The trigger mechanism is an `asyncio.Event` set in the background loop and reset after each drain;
`POST /harness/result` sets the event.

**Acceptance criteria:**

- [ ] `POST /harness/result` accepts `{"task_id": "<uuid>"}` and returns 202 Accepted
- [ ] Receiving the nudge triggers the drain loop event (verified by inspecting `app.state`)
- [ ] Router is included in `app`

**Verification:**

- [ ] `uv run pytest --agent-digest=term tests/test_result_router.py` (written in Task 6)
- [ ] `pre-commit run --all-files`

**Dependencies:** Task 4

**Files likely touched:**

- `foreman/routers/result.py` (new)
- `foreman/server.py` (register router)

**Estimated scope:** S

#### Task 6: Tests for harness queue endpoints

**Description:** Write `tests/test_queue_router.py` and `tests/test_result_router.py` using FastAPI's `TestClient`.
Mock `TaskQueue` at the boundary (not SQLite — the queue is already tested in Task 3).
Verify HTTP contracts only.

**Acceptance criteria:**

- [ ] `POST /queue/next` — 200 with task body when queue has a task
- [ ] `POST /queue/next` — 204 when `claim_next()` returns `None`
- [ ] `POST /queue/complete` — 202; `TaskQueue.complete()` called with correct args
- [ ] `POST /queue/heartbeat` — 202; `TaskQueue.heartbeat()` called with correct `task_id`
- [ ] `POST /harness/result` — 202; drain event is set

**Verification:**

- [ ] `uv run pytest --agent-digest=term tests/test_queue_router.py tests/test_result_router.py`
- [ ] `pre-commit run --all-files`

**Dependencies:** Tasks 4, 5

**Files likely touched:**

- `tests/test_queue_router.py` (new)
- `tests/test_result_router.py` (new)

**Estimated scope:** M

### Checkpoint: Phase 2

- [ ] `uv run pytest --agent-digest=term` — all tests pass
- [ ] All three queue endpoints + `/harness/result` exist and return correct status codes
- [ ] Human review before proceeding

### Phase 3: `foreman-client` Package

#### Task 7: Scaffold `foreman-client` package + `models.py`

**Description:** Create the `foreman-client/` directory tree with its own `pyproject.toml`
(mirroring the main project's tooling: ruff, mypy, interrogate, pydoclint).
Add `models.py` that re-exports `TaskMessage` and `DecisionMessage` from `foreman.protocol` — or,
since `foreman-client` must be installable independently,
copy the minimal Pydantic models into `foremanclient/models.py` (no dependency on the `foreman` package).

**Acceptance criteria:**

- [ ] Directory structure matches spec §3.3
- [ ] `foremanclient/models.py` defines `TaskMessage` and `DecisionMessage` as standalone
  Pydantic models (no `foreman.*` imports)
- [ ] `pyproject.toml` has `httpx` and `pydantic>=2` as runtime deps; dev deps mirror main project
- [ ] `uv sync` inside `foreman-client/` succeeds
- [ ] `pre-commit run --all-files` passes inside `foreman-client/`

**Verification:**

- [ ] `cd foreman-client && uv sync && pre-commit run --all-files`

**Dependencies:** Tasks 4, 5 (need to know the HTTP contract)

**Files likely touched:**

- `foreman-client/pyproject.toml` (new)
- `foreman-client/foremanclient/__init__.py` (new)
- `foreman-client/foremanclient/models.py` (new)

**Estimated scope:** S

#### Task 8: Implement `ForemanClient` in `foremanclient/client.py`

**Description:** Implement the three public methods using `httpx`.
All HTTP calls are synchronous (no `asyncio` in the client — agent authors control their own async if needed).

- `next_task()` → `POST /queue/next` → parse `TaskMessage` or return `None` on 204
- `complete_task(task_id, decision)` → `POST /queue/complete` (stores decision) then
  `POST /harness/result` (nudges drain)
- `heartbeat(task_id)` → `POST /queue/heartbeat`

Log structured events for each call using `structlog`
(already a dep in the main project; add it to `foreman-client` as well).

**Acceptance criteria:**

- [ ] `next_task()` returns a `TaskMessage` on 200, `None` on 204
- [ ] `complete_task()` sends decision to `/queue/complete` then sends nudge to `/harness/result`
- [ ] `heartbeat()` sends `{"task_id": ...}` to `/queue/heartbeat`
- [ ] All methods raise `ForemanClientError` (a custom exception) on non-2xx responses
- [ ] All public methods and the class have Google-style docstrings (pydoclint passes)
- [ ] Type hints on all public methods

**Verification:**

- [ ] `uv run pytest --agent-digest=term` inside `foreman-client/` (tests written in Task 9)
- [ ] `pre-commit run --all-files` inside `foreman-client/`

**Dependencies:** Task 7

**Files likely touched:**

- `foreman-client/foremanclient/client.py` (new)
- `foreman-client/foremanclient/__init__.py` (update exports)

**Estimated scope:** M

#### Task 9: Tests for `foremanclient`

**Description:** Write `foreman-client/tests/test_client.py` using `respx`
(or `httpx.MockTransport`) to mock the harness HTTP endpoints.
Never spin up a real harness.

**Acceptance criteria:**

- [ ] `next_task()` returns `TaskMessage` when harness returns 200 + JSON
- [ ] `next_task()` returns `None` when harness returns 204
- [ ] `complete_task()` sends `DecisionMessage` JSON to `/queue/complete` then nudge to `/harness/result`
- [ ] `heartbeat()` sends `{"task_id": ...}` to `/queue/heartbeat`
- [ ] `ForemanClientError` raised on 4xx/5xx responses
- [ ] Coverage ≥85% line / ≥80% branch for `foremanclient/client.py`

**Verification:**

- [ ] `cd foreman-client && uv run pytest --agent-digest=term --cov=foremanclient/client.py`
- [ ] `pre-commit run --all-files` inside `foreman-client/`

**Dependencies:** Task 8

**Files likely touched:**

- `foreman-client/tests/__init__.py` (new)
- `foreman-client/tests/test_client.py` (new)

**Estimated scope:** M

### Checkpoint: Phase 3

- [ ] `foreman-client` tests pass with ≥85% line coverage
- [ ] `pre-commit run --all-files` passes in both `foreman-client/` and root
- [ ] Human review of `ForemanClient` public API before proceeding (API is the contract agent
  authors depend on — changes after this point are breaking)

### Phase 4: Dispatcher Refactor and Background Loops

#### Task 10: Refactor `Dispatcher.dispatch()` to enqueue + nudge

**Description:** Replace the synchronous HTTP POST in `Dispatcher.dispatch()` with:

1. `task_queue.enqueue(task, agent_url=route_target.url)`
2. Fire-and-forget `POST /task` nudge to the agent (body: `{"task_id": task.task_id}`)
   using `httpx.AsyncClient` with a short timeout (5 s); log and continue on failure.

Remove the synchronous response-parsing block
(lines 118–147 in current `server.py`),
the `response.status_code != 200` check, and `DecisionMessage` parsing from this method.
The method now returns immediately after the nudge.

The `Dispatcher` constructor gains a `task_queue: TaskQueue` parameter.

**Acceptance criteria:**

- [ ] `dispatch()` calls `task_queue.enqueue()` with correct `TaskMessage` and `agent_url`
- [ ] `dispatch()` sends `POST <agent_url>/task` with body `{"task_id": ...}` and returns 202
- [ ] `dispatch()` does not await agent response or parse `DecisionMessage`
- [ ] Nudge HTTP errors are logged and swallowed (fire-and-forget)
- [ ] All synchronous response-parsing code is deleted
- [ ] `Dispatcher.__init__` accepts `task_queue: TaskQueue`

**Verification:**

- [ ] `uv run pytest --agent-digest=term tests/test_server.py`
- [ ] `pre-commit run --all-files`

**Dependencies:** Tasks 2, 6

**Files likely touched:**

- `foreman/server.py`
- `tests/test_server.py` (update existing tests)

**Estimated scope:** M

#### Task 11: Add drain and requeue background loops to FastAPI lifespan

**Description:** Add a FastAPI lifespan context manager to `server.py` that starts two background `asyncio` tasks:

| Task           | Interval                                        | Action                                                                                              |
|----------------|-------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| `drain_loop`   | `queue.drain_interval_seconds` (default 10 s)   | `drain_completed()` → `executor.execute()` → `memory.upsert_memory_summary()` → `queue.mark_done()` |
| `requeue_loop` | `queue.requeue_interval_seconds` (default 60 s) | `requeue_stale()` + `fail_exhausted()`                                                              |

The drain loop also wakes immediately when `POST /harness/result` sets the drain `asyncio.Event`
(the event is stored on `app.state.drain_event`).

Both tasks are cancelled cleanly on shutdown.

**Acceptance criteria:**

- [ ] `drain_loop` calls `drain_completed()` and passes each `(TaskMessage, DecisionMessage)` to
  `executor.execute()` and `memory.upsert_memory_summary()`
- [ ] `drain_loop` wakes immediately when `drain_event` is set
- [ ] `requeue_loop` calls `requeue_stale()` and `fail_exhausted(max_retries=config.queue.max_retries)`
- [ ] Both tasks log structured events on each cycle
- [ ] Both tasks are cancelled without error on SIGINT/shutdown

**Verification:**

- [ ] `uv run pytest --agent-digest=term tests/test_server.py`
- [ ] `pre-commit run --all-files`

**Dependencies:** Task 10

**Files likely touched:**

- `foreman/server.py`
- `tests/test_server.py`

**Estimated scope:** M

#### Task 12: Wire `TaskQueue` into `__main__.py`

**Description:** Update `_run_start()`
and `_run_loop()` in `__main__.py` to construct a `TaskQueue` from `config.queue`, pass it to `Dispatcher`,
and attach it to `app.state` so the router dependencies can access it.
Add `--queue-db` CLI argument (overrides `config.queue.db_path`).

**Acceptance criteria:**

- [ ] `TaskQueue` is constructed with the resolved `db_path` and `claim_timeout_seconds`
- [ ] `Dispatcher` receives the `task_queue` instance
- [ ] `app.state.task_queue` and `app.state.drain_event` are set before the server starts
- [ ] Default `db_path` is `~/.agent-harness/queue.db` when not set in config
- [ ] Existing `--db` arg for `memory.db` is unchanged

**Verification:**

- [ ] `uv run pytest --agent-digest=term tests/test_main.py`
- [ ] `pre-commit run --all-files`

**Dependencies:** Tasks 10, 11

**Files likely touched:**

- `foreman/__main__.py`
- `tests/test_main.py`

**Estimated scope:** S

#### Task 13: Tests for updated `Dispatcher` and background loops

**Description:** Update and extend `tests/test_server.py`.
Mock `TaskQueue` at the boundary (not SQLite).
Test the drain loop by injecting a mocked `drain_completed()` return and verifying `executor.execute()` is called.

**Acceptance criteria:**

- [ ] `dispatch()` test: `enqueue()` called with correct task + agent_url; nudge POST is fire-and-forget
- [ ] `dispatch()` test: nudge HTTP error is swallowed and logged; no exception propagated
- [ ] Drain loop test: `drain_completed()` returning one task → `executor.execute()` called once
- [ ] Drain loop test: `drain_event` set → drain loop wakes immediately
- [ ] Requeue loop test: `requeue_stale()` and `fail_exhausted()` called on schedule
- [ ] No test directly touches `queue.db`

**Verification:**

- [ ] `uv run pytest --agent-digest=term tests/test_server.py`
- [ ] `pre-commit run --all-files`

**Dependencies:** Tasks 10, 11, 12

**Files likely touched:**

- `tests/test_server.py`

**Estimated scope:** M

### Checkpoint: Phase 4

- [ ] `uv run pytest --agent-digest=term` — all tests pass
- [ ] Synchronous dispatch path is fully deleted from `server.py`
- [ ] `pre-commit run --all-files` — clean
- [ ] Human review before proceeding

### Phase 5: Agent Update

#### Task 14: Update reference agent to use `ForemanClient`

**Description:** Rewrite `agents/issue-triage/issue_triage/agent.py` to use `ForemanClient`.
The `POST /task` endpoint now accepts `{"task_id": "<uuid>"}`, returns 202 immediately,
and fires an asyncio background task that calls `client.next_task()`, processes it, and calls `client.complete_task()`.

Remove the inline `TaskMessage` / `DecisionMessage` model definitions (they came from `foremanclient.models`).
Add `foreman-client` as a runtime dependency in the agent's `pyproject.toml`.

Add a startup poll: on `@app.on_event("startup")`
(or lifespan), call `client.next_task()` to pick up any tasks queued while the agent was down.

**Acceptance criteria:**

- [ ] `POST /task` returns 202 Accepted immediately (not 200 + body)
- [ ] Background task calls `client.next_task()` and `client.complete_task()`
- [ ] Startup poll calls `client.next_task()` once on boot
- [ ] Agent no longer defines its own `TaskMessage` / `DecisionMessage` models
- [ ] `foreman-client` appears in `agents/issue-triage/pyproject.toml` dependencies
- [ ] `GET /health` is unchanged

**Verification:**

- [ ] `uv run pytest --agent-digest=term tests/test_agent_server.py`
- [ ] `pre-commit run --all-files`

**Dependencies:** Tasks 8, 9

**Files likely touched:**

- `agents/issue-triage/issue_triage/agent.py`
- `agents/issue-triage/pyproject.toml`

**Estimated scope:** M

#### Task 15: Tests for updated reference agent

**Description:** Update `tests/test_agent_server.py` to reflect the new 202 response
and mock `ForemanClient` at the boundary.
Test startup poll behaviour.

**Acceptance criteria:**

- [ ] `POST /task` returns 202 (not 200)
- [ ] Background task is triggered; `client.next_task()` and `client.complete_task()` called
- [ ] `client.next_task()` returning `None` does not crash the background task
- [ ] Startup poll fires `client.next_task()` once on lifespan start

**Verification:**

- [ ] `uv run pytest --agent-digest=term tests/test_agent_server.py`
- [ ] `pre-commit run --all-files`

**Dependencies:** Task 14

**Files likely touched:**

- `tests/test_agent_server.py`

**Estimated scope:** S

### Checkpoint: Phase 5

- [ ] `uv run pytest --agent-digest=term` — full suite passes
- [ ] Reference agent uses `ForemanClient`; no inline protocol models remain
- [ ] Human review before proceeding

### Phase 6: Documentation and Integration

#### Task 16: Write `docs/how-to/write-an-agent.md`

**Description:** Agent author guide covering: installing `foreman-client`, the three-method API
(`next_task`, `complete_task`, `heartbeat`),
heartbeat requirements (every 30 s during long LLM calls), idempotency contract
(`task_id` as idempotency key), and a minimal working example using `ForemanClient`.

**Acceptance criteria:**

- [ ] Covers: install, `ForemanClient.__init__` args, `next_task()`, `complete_task()`, `heartbeat()`
- [ ] Explains claim timeout and heartbeat cadence requirement
- [ ] Explains idempotency: what to do if `next_task()` returns an already-processed task
- [ ] Includes a ≤30-line end-to-end example agent using `ForemanClient`
- [ ] Doc is in `docs/how-to/write-an-agent.md`

**Verification:**

- [ ] Human reads and approves the draft

**Dependencies:** Tasks 8, 14

**Files likely touched:**

- `docs/how-to/write-an-agent.md` (new)

**Estimated scope:** S

#### Task 17: Integration test — agent restart resilience

**Description:** Write `tests/test_integration.py`
(extend existing file)
with a test that satisfies the MVP acceptance criterion: zero task loss under a simulated agent restart.

Use real local processes (not mocks): spin up the harness and the reference agent, enqueue a task, stop the agent,
restart it, assert the task reaches `status=done` in `queue.db`.

**Acceptance criteria:**

- [ ] Test spins up harness (subprocess or `TestClient` + real `TaskQueue`)
- [ ] GitHub poller event is injected (mock the poller, call `dispatcher.dispatch()` directly)
- [ ] Agent is stopped immediately after task is enqueued (before it can claim)
- [ ] Agent is restarted; startup poll picks up the pending task
- [ ] `task_queue` row reaches `status=done`
- [ ] `action_log` has an entry for the decision
- [ ] Test is marked `@pytest.mark.integration` and skipped in CI unless `--run-integration` flag is set

**Verification:**

- [ ] `uv run pytest --agent-digest=term -m integration --run-integration tests/test_integration.py`
- [ ] Human observes the test pass end-to-end

**Dependencies:** Tasks 12, 14

**Files likely touched:**

- `tests/test_integration.py`
- `conftest.py` (add `--run-integration` flag if not present)

**Estimated scope:** L

### Checkpoint: Phase 6 (Final)

- [ ] `uv run pytest --agent-digest=term` — full unit suite passes
- [ ] Integration test passes manually
- [ ] `pre-commit run --all-files` — clean
- [ ] `docs/how-to/write-an-agent.md` approved
- [ ] No synchronous dispatch path exists anywhere in the codebase
- [ ] Human sign-off before merge

## Risks and Mitigations

| Risk                                                     | Impact | Mitigation                                                                                                                                            |
|----------------------------------------------------------|--------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| SQLite concurrency under concurrent claim                | High   | Use `BEGIN IMMEDIATE` transaction in `claim_next()` — SQLite serialises writes, preventing double-claim                                               |
| `foreman-client` endpoint contract diverges from harness | High   | Define request/response Pydantic models in `foreman/routers/queue.py` and reference them in `foremanclient/models.py` (or keep them in sync manually) |
| Drain loop misses a completed task                       | Medium | Background poll every 10 s is the safety net; `/harness/result` nudge is the fast path                                                                |
| Agent processes same task twice after restart            | Medium | `task_id` idempotency key in `action_log` (existing invariant, preserved)                                                                             |
| `foreman-client` is sync but agent is async              | Low    | `httpx` supports both sync and async; document that authors should use `asyncio.to_thread()` if calling from async context                            |

## Out of Scope (MVP)

Per spec §10: multiple agents per queue, external backends, prioritization, monitoring UI, `GET /queue/status`.
