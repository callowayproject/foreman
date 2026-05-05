# PR #21 Fix Plan

Implements all seven findings from `pr-21-review.md`.
Tasks are ordered: high-priority blockers first, then medium, then low.

---

## Task 1 — Wrap `_drain_loop` body in exception handlers

**File:** `foreman/server.py:131-149` **Priority:** High (must fix before merge)

Wrap the outer `drain_completed()` call in a broad `try/except` that logs and continues so the loop never dies.
Wrap each per-task `executor.execute()` + `memory.upsert_memory_summary()` block in a separate inner `try/except`
so one bad task does not abort the others.
Also extend the `_lifespan` finally block's `contextlib.suppress` to include `Exception`
so a previously-crashed drain task does not re-raise during shutdown.

**Acceptance criteria:**

- [x] `_drain_loop` has an outer `try/except Exception` around `drain_completed()` that calls `logger.exception`
    and continues the loop
- [x] `_drain_loop` has an inner `try/except Exception` around `executor.execute()` + `memory.upsert_memory_summary()` per
    task
- [x] `_lifespan` finally block uses `contextlib.suppress(asyncio.CancelledError, Exception)` for `drain_task`
- [x] New test: a drain-loop iteration that raises inside `executor.execute` does not kill the loop
    (subsequent iteration still runs)
- [x] Full test suite passes

---

## Task 2 — Split `drain_completed` / add `mark_done`; transition `done` after execute

**Files:** `foreman/queue.py:179-183`, `foreman/server.py:138-146` **Priority:** High (must fix before merge)

Remove the `UPDATE … done` + `commit` from `drain_completed` so it only reads rows.
Add a new `mark_done(task_id: str) -> None` method that transitions a single row to `done` and commits.
In `_drain_loop`, call `task_queue.mark_done(task.task_id)` after `executor.execute()` succeeds.

This gives at-least-once delivery: a crash between `execute` and `mark_done` causes re-drain on next start,
which matches the stated design goal.

Note: `drain_completed` tests in `test_queue.py` that assert `status == 'done'` after the call must be updated —
`drain_completed` now leaves status as `completed`; `mark_done` transitions to `done`.

**Acceptance criteria:**

- [x] `drain_completed` no longer contains any `UPDATE` or `commit` call
- [x] `mark_done(task_id)` method exists on `TaskQueue`, transitions one row `completed → done`, commits
- [x] `_drain_loop` calls `task_queue.mark_done(task.task_id)` inside the per-task try block,
    after `memory.upsert_memory_summary()`
- [x] Existing `drain_completed` tests updated to reflect that rows remain `completed` after the call
- [x] New test: `mark_done` transitions the correct row to `done` and leaves other rows untouched
- [x] New test: executor failure leaves the task in `completed` state (not `done`)
- [x] Full test suite passes

---

## Task 3 — Drain all queued tasks on agent startup (loop until empty)

**File:** `agents/issue-triage/issue_triage/agent.py:82` **Priority:** Medium (should fix)

Replace the single `await _poll_and_process(client)` call in `_lifespan` with a loop
that calls `client.next_task()` repeatedly until it returns `None`, processing each task before moving to the next.

**Acceptance criteria:**

- [x] `_lifespan` startup poll loops:
    `while True: task = await asyncio.to_thread(client.next_task); if task is None: break; await _process_task(client, task)`
- [x] New integration test: 3 tasks enqueued while agent is "down"; agent restart claims and processes all 3
    (no stuck `pending` rows)
- [x] Full test suite passes

---

## Task 4 — Wrap `_requeue_loop` body in exception handler

**File:** `foreman/server.py:163-168` **Priority:** Medium (should fix)

Mirror the fix from Task 1: wrap the `requeue_stale()` + `fail_exhausted()` block in `try/except Exception` with
`logger.exception`.
Also extend `_lifespan` finally block's `contextlib.suppress` for `requeue_task` to include `Exception`.

**Acceptance criteria:**

- [x] `_requeue_loop` has `try/except Exception` around `requeue_stale()` + `fail_exhausted()` that logs and continues
- [x] `_lifespan` finally block uses `contextlib.suppress(asyncio.CancelledError, Exception)` for `requeue_task`
- [x] New test: a requeue-loop iteration that raises does not kill the loop
- [x] Full test suite passes

---

## Task 5 — Remove private-attribute access across module boundary

**Files:** `foreman/server.py`, `foreman/__main__.py:167` **Priority:** Low (nice to have)

Rename `Dispatcher._executor` to `Dispatcher.executor` (public).
Update `__main__.py` to use `dispatcher.executor`.

**Acceptance criteria:**

- [x] `Dispatcher.__init__` assigns `self.executor` (not `self._executor`)
- [x] `__main__.py` references `dispatcher.executor`
- [x] No remaining references to `dispatcher._executor` in the codebase
- [x] Full test suite passes

---

## Task 6 — Add heartbeat thread to reference agent `_process_task`

**File:** `agents/issue-triage/issue_triage/agent.py:52-60` **Priority:** Low (nice to have)

Wrap the `asyncio.to_thread(triage, task)` call with a daemon heartbeat thread
that fires `client.heartbeat(task.task_id)` every 25 seconds until the triage call finishes.

**Acceptance criteria:**

- [x] `_process_task` starts a daemon `threading.Thread` that calls `client.heartbeat(task.task_id)` every 25 s
- [x] The heartbeat thread is stopped (via `threading.Event`) in a `finally` block after `triage` returns or raises
- [x] `import threading` added to `agent.py`
- [x] Full test suite passes

---

## Task 7 — Update minimal working example in docs to include startup poll

**File:** `docs/howtos/write-an-agent.md:125-156` **Priority:** Low (nice to have)

Replace the module-level `ForemanClient` instantiation
and bare `FastAPI()` with a proper `@asynccontextmanager lifespan` that: creates the client, runs a startup poll
(claiming any queued tasks), yields, and closes the client.
Pass the lifespan to `FastAPI(lifespan=lifespan)`.

**Acceptance criteria:**

- [x] Minimal example uses `@asynccontextmanager` lifespan (import from `contextlib`)
- [x] Lifespan creates `ForemanClient`, calls `next_task()` + `complete_task()` in a startup-poll loop, yields,
    calls `client.close()`
- [x] `FastAPI(lifespan=lifespan)` used instead of bare `FastAPI()`
- [x] A note is added (or the startup-poll section is cross-linked) so readers understand why the lifespan is needed
- [x] `rumdl` / pre-commit passes

---

## Implementation Order

```text
Task 2  (queue.py: split drain_completed / add mark_done)
Task 1  (server.py: wrap _drain_loop — depends on mark_done existing)
Task 4  (server.py: wrap _requeue_loop — independent, batch with Task 1 or separate)
Task 3  (agent.py: startup drain loop)
Task 5  (server.py + __main__.py: publicize executor attr)
Task 6  (agent.py: heartbeat thread)
Task 7  (docs: minimal example lifespan)
```

Tasks 2 and 1 are tightly coupled (Task 1's drain loop calls `mark_done`); implement them together.
Tasks 4, 5 are independent and can each be a single commit.
Tasks 6, 7 are independent documentation/agent polish.

---

*Plan created 2026-05-05.* *Derived from `pr-21-review.md`.* *All tasks completed 2026-05-05.*
