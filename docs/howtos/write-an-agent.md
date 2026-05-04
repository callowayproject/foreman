---
title: Write an Agent
summary: How to build a Foreman-compatible agent using the foreman-client SDK.
date: 2026-05-04
---

# Write an Agent

This guide walks you through building a Foreman-compatible agent from scratch.
Agents are HTTP services that receive task nudges from the harness, claim the task from the queue, process it,
and report a decision back — all via `ForemanClient`.

## Prerequisites

- Python 3.12+
- A running Foreman harness (see [Installation](../tutorials/installation.md))
- `uv` or `pip` for package management

## Install `foreman-client`

```bash
uv add foreman-client
# or
pip install foreman-client
```

`foreman-client` has two runtime dependencies: `httpx` and `pydantic>=2`.

## The Three-Method API

`ForemanClient` exposes exactly three methods an agent needs.

### `ForemanClient(harness_url, agent_url)`

| Argument      | Type  | Description                                                                       |
|---------------|-------|-----------------------------------------------------------------------------------|
| `harness_url` | `str` | Base URL of the Foreman harness (e.g. `"http://localhost:8000"`).                 |
| `agent_url`   | `str` | This agent's own base URL (e.g. `"http://localhost:9001"`). Sent when claiming tasks so the harness knows which agent holds each claim. |

Use it as a context manager to ensure the HTTP connection pool is closed on exit:

```python
with ForemanClient(harness_url="http://localhost:8000", agent_url="http://localhost:9001") as client:
    ...
```

### `next_task() → TaskMessage | None`

Claims and returns the next pending task from the harness queue.
Returns `None` when the queue is empty (harness responds `204 No Content`).
Raises `ForemanClientError` on any non-2xx response.

```python
task = client.next_task()
if task is None:
    return  # nothing to do
```

### `complete_task(task_id, decision)`

Stores the completed `DecisionMessage` in the queue and wakes the harness drain loop.
Call this once per task, after all processing is done.

| Argument   | Type              | Description                                                |
|------------|-------------------|------------------------------------------------------------|
| `task_id`  | `str`             | The `task_id` from the `TaskMessage` returned by `next_task()`. |
| `decision` | `DecisionMessage` | Your agent's decision, rationale, and action list.         |

```python
from foremanclient import DecisionMessage, DecisionType

decision = DecisionMessage(
    task_id=task.task_id,
    decision=DecisionType.label_and_respond,
    rationale="Classified as a bug based on the stack trace.",
    actions=[{"type": "add_label", "label": "bug"}],
)
client.complete_task(task.task_id, decision)
```

### `heartbeat(task_id)`

Extends the claim window for an in-progress task.
The harness defaults to a 300-second claim timeout (`claim_timeout_seconds` in `QueueConfig`).
If your agent hasn't called `complete_task()` within that window, the harness re-queues the task for another attempt.

**Call `heartbeat()` at least once every 30 seconds** during long LLM calls or any blocking work.

```python
import threading

def _heartbeat_loop(client, task_id, stop_event):
    while not stop_event.wait(timeout=25):
        client.heartbeat(task_id)

stop = threading.Event()
t = threading.Thread(target=_heartbeat_loop, args=(client, task.task_id, stop), daemon=True)
t.start()
try:
    decision = run_llm(task)
finally:
    stop.set()
```

## Idempotency

`task_id` is the idempotency key for every task.
The harness writes each decision to `action_log` before executing GitHub API calls, keyed on `task_id`.

If `next_task()` returns a task your agent has already completed
(for example, after an unclean restart), check your own records before processing again:

```python
task = client.next_task()
if task and not already_processed(task.task_id):
    decision = process(task)
    client.complete_task(task.task_id, decision)
```

The simplest approach is to keep a short in-memory set of recently completed `task_id` values.
Across restarts, rely on the harness: if the decision is already in `action_log`, the executor skips duplicate actions.

## Minimal Working Example

A complete, runnable agent in under 30 lines:

```python
import os
from fastapi import BackgroundTasks, FastAPI
from foremanclient import DecisionMessage, DecisionType, ForemanClient
from pydantic import BaseModel

client = ForemanClient(os.environ["FOREMAN_HARNESS_URL"], os.environ["AGENT_URL"])
app = FastAPI()

class TaskNudge(BaseModel):
    task_id: str

def _decide(task):
    return DecisionMessage(
        task_id=task.task_id, decision=DecisionType.skip, rationale="No action needed."
    )

def _run():
    task = client.next_task()
    if task:
        client.complete_task(task.task_id, _decide(task))

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/task", status_code=202)
async def handle_task(nudge: TaskNudge, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run)
    return {"status": "accepted"}
```

Run it with:

```bash
FOREMAN_HARNESS_URL=http://localhost:8000 AGENT_URL=http://localhost:9001 uvicorn myagent:app --port 9001
```

## Required Endpoints

Every agent **must** expose:

| Method | Path      | Description                                                      |
|--------|-----------|------------------------------------------------------------------|
| `POST` | `/task`   | Accept a nudge `{"task_id": "..."}` and return `202 Accepted`.   |
| `GET`  | `/health` | Health check. Must return `200 OK` with `{"status": "ok"}`.      |

The harness sends a `POST /task` nudge (body: `{"task_id": "..."}`) when a new task is enqueued.
The agent should return 202 immediately and process the task in a background thread or task.

## Startup Poll

On startup, call `next_task()` once to pick up any tasks that were enqueued while your agent was down:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    task = client.next_task()
    if task:
        _decide_and_complete(task)
    yield
    client.close()

app = FastAPI(lifespan=lifespan)
```

This is the key mechanism for zero task loss under agent restarts.
The harness re-queues stale claimed tasks after `claim_timeout_seconds`,
and the startup poll ensures your agent claims them immediately on boot.

## Reference

See the [Agent Protocol Reference](../reference/agent-protocol.md) for the full `TaskMessage`, `DecisionMessage`,
and `ActionItem` schemas.
