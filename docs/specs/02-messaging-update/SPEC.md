# Spec: Queue-Mediated Agent Protocol

**Status:** Draft **Branch:** `message-update-idea` **Replaces:** Synchronous `POST /task → DecisionMessage` dispatch in
`server.py`

---

## 1. Objective

Replace the current fire-and-forget synchronous HTTP dispatch with a durable,
queue-mediated protocol so that GitHub events are never silently dropped — even when agents are temporarily unavailable
(restarts, cold starts) or permanently down (misconfigured, crashed).

**Target users:**

- **Harness operators** — install Foreman, configure repos; gain reliability without extra ops.
- **Agent authors** — build new agents; use `foreman-client` instead of implementing
  queue management themselves.

**MVP acceptance criterion:** Zero task loss under a simulated agent restart.
A task enqueued while the agent is down must be delivered and processed once the agent comes back online.

## 2. How It Works

### 2.1 Data Flow (Happy Path)

```text
GitHub event
    → poller.py detects event
    → queue.py: INSERT task (status=pending) into queue.db
    → Dispatcher nudges agent: POST /task → 202 Accepted  (fire-and-forget)
    → Agent receives nudge (or polls on startup/interval)
    → foreman-client: next_task() → SELECT + UPDATE status=claimed
    → Agent processes task, calls complete_task(task_id, decision)
    → foreman-client: UPDATE status=completed, result=<DecisionMessage JSON>
    → Agent nudges harness: POST /harness/result → 202 Accepted
    → Harness drain loop picks up completed task
    → executor.py executes actions
    → memory.py logs decision and writes summary
    → queue.py: UPDATE status=done
```

### 2.2 Resilience Paths

| Scenario                          | Recovery mechanism                                                              |
|-----------------------------------|---------------------------------------------------------------------------------|
| Agent down when nudge sent        | Background poll interval on agent startup                                       |
| Agent crashes after claiming task | Harness re-enqueues tasks claimed but not completed within claim timeout        |
| Harness misses nudge from agent   | Background drain loop polls for completed tasks on a fixed interval             |
| Agent processes same task twice   | `task_id` is the idempotency key; executor checks `action_log` before executing |

### 2.3 Claim Timeout and Heartbeat

- **Claim timeout** (configurable, default **5 minutes**): If a task is claimed but
  not completed within this window, the harness re-enqueues it (status → pending,
  retry_count incremented).
- **Heartbeat interval** (recommendation for agent authors: **every 30 seconds**):
  Agents doing long LLM calls must call `client.heartbeat(task_id)` at least
  once per 30 seconds to reset the claim timeout clock.
  The `foreman-client` library will document this requirement prominently.

## 3. New Components

### 3.1 `queue.db` — Task Queue Database

A **separate** SQLite database from `memory.db`, stored alongside it
(default: `~/.agent-harness/queue.db`, path overridable in config).
WAL mode enabled at connection time.

**Schema — `task_queue` table:**

```sql
CREATE TABLE task_queue (
    task_id       TEXT PRIMARY KEY,
    agent_url     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
                  -- pending | claimed | completed | done | failed
    payload       TEXT NOT NULL,   -- JSON-serialised TaskMessage
    created_at    REAL NOT NULL,   -- Unix timestamp
    claimed_at    REAL,
    completed_at  REAL,
    result        TEXT,            -- JSON-serialised DecisionMessage
    retry_count   INTEGER NOT NULL DEFAULT 0,
    last_heartbeat REAL            -- updated by heartbeat()
);
CREATE INDEX idx_task_queue_status ON task_queue (status, agent_url);
```

**Status lifecycle:**

```text
pending → claimed → completed → done
                ↘ (timeout)  ↗
              pending (retry)
                        ↘ (max retries exceeded)
                         failed
```

Max retries: configurable, default **3**.

### 3.2 `foreman/queue.py` — Harness Queue Module

Owns all SQLite access for the task queue.
Public interface:

```python
class TaskQueue:
    def __init__(self, db_path: Path, claim_timeout_seconds: int = 300) -> None: ...

    def enqueue(self, task: TaskMessage, agent_url: str) -> None: ...
    """Insert a new task with status=pending."""

    def claim_next(self, agent_url: str) -> TaskMessage | None: ...
    """Claim the oldest pending task for agent_url; returns None if queue empty."""

    def complete(self, task_id: str, decision: DecisionMessage) -> None: ...
    """Mark task completed and store the DecisionMessage result."""

    def heartbeat(self, task_id: str) -> None: ...
    """Reset last_heartbeat to now, extending the claim window."""

    def drain_completed(self) -> list[tuple[TaskMessage, DecisionMessage]]: ...
    """Return all completed tasks and mark them done. Called by the harness drain loop."""

    def requeue_stale(self) -> int: ...
    """Re-enqueue tasks claimed but not heartbeated within claim_timeout. Returns count."""

    def fail_exhausted(self, max_retries: int = 3) -> int: ...
    """Mark tasks exceeding max_retries as failed. Returns count."""
```

### 3.3 `foreman-client` — Separate PyPI Package

A thin Python library installed by agent authors.
Lives at `foreman-client/` in this repo (separate `pyproject.toml`).
Published to PyPI as `foreman-client`.

**Directory structure:**

```text
foreman-client/
├── pyproject.toml
└── foremanclient/
    ├── __init__.py
    ├── client.py       # ForemanClient
    └── models.py       # Re-exported Pydantic models (TaskMessage, DecisionMessage)
```

**Public API:**

```python
class ForemanClient:
    def __init__(self, harness_url: str, agent_url: str) -> None: ...
    """
    Args:
        harness_url: Base URL of the Foreman harness (e.g. "http://localhost:8000").
        agent_url: This agent's own base URL (used to filter tasks from the queue).
    """

    def next_task(self) -> TaskMessage | None: ...
    """Claim and return the next pending task, or None if the queue is empty."""

    def complete_task(self, task_id: str, decision: DecisionMessage) -> None: ...
    """Write the decision result and nudge the harness via POST /harness/result."""

    def heartbeat(self, task_id: str) -> None: ...
    """Reset the claim timeout clock. Call every ~30 seconds during long LLM calls."""
```

Agent authors interact **only** with these three methods.
They do not manage queue connections, retries, or status transitions directly.

### 3.4 Modified Harness Endpoints

**`POST /task` (agent-facing, harness → agent nudge)**

```text
Request body: {"task_id": "<uuid>"}   # optional hint; agent should poll queue regardless
Response:     202 Accepted            # always; delivery is queue's job, not HTTP's
```

The agent's FastAPI app continues to expose `POST /task`.
The handler now calls `client.next_task()` and processes the result asynchronously, returning 202 immediately.

**`POST /harness/result` (new harness endpoint, agent → harness nudge)**

```text
Request body: {"task_id": "<uuid>"}
Response:     202 Accepted
```

Added in `foreman/routers/result.py`.
On receipt, the harness drain loop is triggered immediately (in addition to its background schedule).

### 3.5 Harness Background Tasks

Two background asyncio tasks started in the FastAPI lifespan:

| Task           | Interval         | Action                                                |
|----------------|------------------|-------------------------------------------------------|
| `drain_loop`   | Every 10 seconds | `drain_completed()` → execute actions → update memory |
| `requeue_loop` | Every 60 seconds | `requeue_stale()` + `fail_exhausted()`                |

Intervals are configurable in `config.yaml` under a new `queue:` section.

---

## 4. Configuration Changes

New `queue:` section in `config.yaml` (and corresponding Pydantic model in `config.py`):

```yaml
queue:
  db_path: ~/.agent-harness/queue.db   # optional; defaults to alongside memory.db
  claim_timeout_seconds: 300           # default 5 minutes
  max_retries: 3
  drain_interval_seconds: 10
  requeue_interval_seconds: 60
```

## 5. Protocol Changes and Migration

### 5.1 What Changes

| Component                  | Before                                                         | After                                             |
|----------------------------|----------------------------------------------------------------|---------------------------------------------------|
| `Dispatcher.dispatch()`    | Synchronous POST; waits for `DecisionMessage` in response body | Enqueues task; sends nudge; returns immediately   |
| Agent `POST /task` handler | Processes task synchronously; returns `DecisionMessage` (200)  | Returns 202 immediately; processes task via queue |
| `DecisionMessage` delivery | HTTP response body                                             | Written to `task_queue.result` column             |

### 5.2 Explicit Removal: Synchronous Dispatch Path

The synchronous dispatch path in `Dispatcher.dispatch()` (`server.py:63–147`) is **removed entirely** in this change.
There is no fallback to synchronous HTTP.
Queue-first is the only delivery mechanism.

Rationale: two delivery paths means neither is authoritative.
Commit fully to the queue to avoid split-brain between what the queue thinks happened and what HTTP delivered.

**Migration steps (in implementation order):**

1. Implement `foreman/queue.py` and `queue.db` schema.
2. Implement `foreman-client` package with tests.
3. Add `POST /harness/result` endpoint to harness.
4. Refactor `Dispatcher.dispatch()` to enqueue + nudge.
5. Add drain and requeue background loops to harness lifespan.
6. Update the reference agent (`agents/issue-triage/agent.py`) to use `ForemanClient`.
7. Delete the synchronous response-parsing block from `Dispatcher.dispatch()`.
8. Remove `response.status_code != 200` error handling (no longer applicable).

## 6. Project Structure After Change

```text
foreman/
├── queue.py            # NEW: TaskQueue class (queue.db access)
├── routers/
│   └── result.py       # NEW: POST /harness/result nudge endpoint
├── server.py           # MODIFIED: Dispatcher uses queue; adds background loops
├── config.py           # MODIFIED: QueueConfig Pydantic model added
└── ... (unchanged)

foreman-client/         # NEW: separate package
├── pyproject.toml
└── foremanclient/
    ├── __init__.py
    ├── client.py
    └── models.py

agents/issue-triage/
└── agent.py            # MODIFIED: uses ForemanClient instead of sync response

docs/
└── specs/02-messaging-update/
    ├── idea.md
    ├── SPEC.md          # this file
    └── plan.md          # to be created

docs/how-to/
└── write-an-agent.md   # NEW: agent author guide (task for plan phase)
```

## 7. Code Style

Inherits all project conventions from `CLAUDE.md`:

- **Formatter/linter:** ruff (line length 119, Google docstring convention)
- **Type checking:** mypy (`--no-strict-optional --ignore-missing-imports`)
- **Docstrings:** interrogate (≥90% coverage), pydoclint (Google style)
- **Type hints:** required on all public functions and methods
- **Python minimum:** 3.12
- **`foreman-client`** follows the same conventions; its `pyproject.toml`
  mirrors the tooling configuration from the main project.

## 8. Testing Strategy

### 8.1 `foreman/queue.py`

- Use a real temp-file SQLite DB via `pytest tmp_path` (never mock SQLite).
- Test each status transition: pending → claimed → completed → done.
- Test `requeue_stale()`: claim a task, advance time past timeout, verify re-enqueue.
- Test `fail_exhausted()`: exhaust retries, verify status=failed.
- Test concurrent claim (two threads calling `claim_next()` simultaneously) —
  only one should receive the task.

### 8.2 `foreman-client`

- Unit tests with a mock harness server (use `httpx.MockTransport` or `respx`).
- Test `next_task()` when queue empty returns `None`.
- Test `complete_task()` sends nudge to `POST /harness/result`.
- Test `heartbeat()` updates `last_heartbeat`.

### 8.3 `Dispatcher` (harness)

- Mock `TaskQueue` at the boundary; verify `enqueue()` is called with correct
  `TaskMessage` and `agent_url`.
- Verify nudge HTTP POST is fire-and-forget (does not block on agent response).
- Test drain loop: mock `drain_completed()` returning tasks; verify `executor.execute()`
  is called and memory is updated.
- Test requeue loop: verify `requeue_stale()` and `fail_exhausted()` are called.

### 8.4 Integration Test

- Spin up the harness and the reference agent (`agents/issue-triage/`) locally.
- Send a GitHub event to the harness poller.
- Stop the agent container immediately after task is enqueued.
- Restart the agent container.
- Assert the task was claimed and completed (inspect `task_queue` status=done).
- Assert the `action_log` has the expected decision entry.
- **This test is the primary acceptance gate for the MVP criterion.**

### 8.5 Coverage Target

≥85% line / ≥80% branch for `foreman/queue.py` and `foremanclient/client.py`.

## 9. Boundaries

### Always Do

- Enqueue every event before any dispatch attempt; the queue is the source of truth.
- Write every decision to `action_log` before executing actions (existing invariant, preserved).
- Use WAL mode for `queue.db`; open with `check_same_thread=False`.
- Log structured events for every status transition (enqueue, claim, complete, requeue, fail).

### Ask First (Require Explicit Config)

- `allow_close: true` — closing issues (unchanged from current behavior).
- `max_retries` changes beyond the default — operators must set this deliberately.

### Never Do

- Store raw secrets in `queue.db` or task payloads (GitHub tokens must not appear in `payload`).
- Execute shell commands or arbitrary code from task payloads.
- Let agent containers access `queue.db` directly — all queue I/O goes through
  `foreman-client` ↔ harness API (the harness owns the database file).
- Add a synchronous dispatch fallback path.
- Expose `GET /queue/status` in MVP — structured log output only.

## 10. Out of Scope (MVP)

- Multiple agent containers per queue (no consumer groups).
- External queue backends (Redis, NATS) — pluggable interface defined, SQLite only implemented.
- Task prioritization or ordering beyond FIFO.
- Monitoring UI.
- `GET /queue/status` operator endpoint.

## 11. Documentation Task

The plan phase must include a task to produce `docs/how-to/write-an-agent.md` covering the `foreman-client` API,
heartbeat requirements, idempotency contract, and a minimal agent example using `ForemanClient`.
This doc is the primary reference for agent authors.
