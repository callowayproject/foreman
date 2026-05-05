# PR Review: Update task management flow and add integration tests

## Executive Summary

| Aspect             | Value                                                                                                                                                                 |
|--------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **PR Goal**        | Implement a complete queue-mediated agent protocol: SQLite task queue, HTTP endpoints, `foreman-client` SDK, background drain/requeue loops, agent restart resilience |
| **Files Changed**  | 41 (4,781 additions / 714 deletions)                                                                                                                                  |
| **Risk Level**     | 🟡 MEDIUM — core queue mechanics and test coverage are solid; two structural bugs in the drain pipeline need attention before shipping                                |
| **Review Effort**  | 4/5 — six implementation phases spanning new package, background loops, agent protocol, integration test, and documentation                                           |
| **Recommendation** | 🔄 REQUEST CHANGES                                                                                                                                                    |

**Affected Areas**: `foreman/queue.py`, `foreman/server.py`, `foreman/routers/queue.py`, `foreman/routers/result.py`,
`foreman/__main__.py`, `foreman-client/`, `agents/issue-triage/issue_triage/agent.py`, `tests/test_integration.py`

**Business Impact**: This PR enables the zero-task-loss guarantee that is the MVP acceptance criterion.
The queue, client SDK, and integration test are well-constructed.
Two bugs in the drain pipeline can silently drop GitHub actions
or permanently halt task processing on any transient error.

**Flow Changes**: Replaces synchronous `POST→parse→execute` dispatch with durable enqueue + fire-and-forget nudge.
Decisions are now drained asynchronously by a background loop.
Agent startup polls the queue on boot for resilience.

## Ratings

| Aspect          | Score |
|-----------------|-------|
| Correctness     | 3/5   |
| Security        | 5/5   |
| Performance     | 5/5   |
| Maintainability | 4/5   |

## PR Health

- [x] Has clear description
- [x] References implementation plan (docs/specs/02-messaging-update/plan.md)
- [x] Appropriate size (6 phases — large but well-scoped)
- [x] Has relevant tests (261 unit tests + 1 integration test)

---

## High Priority Issues

(Must fix before merge)

### 🐛 #1: `_drain_loop` crashes permanently on any executor or DB exception

**Location:** `foreman/server.py:131-149`

**Confidence:** ✅ HIGH

The `while True` loop runs `task_queue.drain_completed()`, `executor.execute()`,
and `memory.upsert_memory_summary()` with no exception handling.
Any raise — GitHub API rate limit, bad credentials, transient SQLite I/O error —
exits `while True` and the asyncio task dies.
After that every `drain_event.set()` call from `/queue/complete` and `/harness/result` is a no-op: the loop is dead,
completed tasks pile up in the queue, and GitHub actions are never taken.
There is no alert, no restart, no visible signal to the operator.

A second consequence: in `_lifespan`'s `finally` block, `await drain_task` re-raises any non-`CancelledError` exception.
If the drain task crashed earlier with (e.g.) `sqlite3.OperationalError`,
the re-raise propagates out of the `contextlib.suppress(asyncio.CancelledError)` guard and can disrupt clean shutdown.

```diff
# foreman/server.py — inside _drain_loop while loop
     drain_event.clear()

-    pairs = task_queue.drain_completed()
-    for task, decision in pairs:
-        issue_number: int = task.payload.get("number", 0)
-        executor.execute(decision, repo=task.repo, issue_number=issue_number, task_type=task.type)
-        summary = f"decision={decision.decision.value}; rationale={decision.rationale}"
-        memory.upsert_memory_summary(task.repo, issue_number, summary)
-    if pairs:
-        logger.info("Drain loop processed tasks", count=len(pairs))
+    try:
+        pairs = task_queue.drain_completed()
+        for task, decision in pairs:
+            issue_number: int = task.payload.get("number", 0)
+            try:
+                executor.execute(decision, repo=task.repo, issue_number=issue_number, task_type=task.type)
+                summary = f"decision={decision.decision.value}; rationale={decision.rationale}"
+                memory.upsert_memory_summary(task.repo, issue_number, summary)
+            except Exception:
+                logger.exception("Drain loop: failed to execute task", task_id=task.task_id)
+        if pairs:
+            logger.info("Drain loop processed tasks", count=len(pairs))
+    except Exception:
+        logger.exception("Drain loop: unexpected error, continuing")

# foreman/server.py — _lifespan finally block
-    with contextlib.suppress(asyncio.CancelledError):
-        await drain_task
+    with contextlib.suppress(asyncio.CancelledError, Exception):
+        await drain_task
```

---

### 🐛 #2: `drain_completed` marks tasks `done` before executing actions — executor failures silently drop GitHub actions

**Location:** `foreman/queue.py:179-183`, `foreman/server.py:138-146` | **Confidence:** ✅ HIGH

`drain_completed()` atomically updates all completed rows to `done`
and commits to SQLite **before** returning the list to the caller.
`_drain_loop` then calls `executor.execute()` on those rows.
If the executor raises (network error, GitHub 403, etc.), the task is already `done` — it will never be retried,
and the GitHub action (add label, post comment, close issue) is silently skipped with no record in `action_log`.

Combined with issue #1 (the loop then crashes), one bad executor call causes both action loss and drain-loop death.

The fix is to move the `done` transition to after a successful execute, on a per-task basis:

```diff
# foreman/queue.py — drain_completed: remove batch UPDATE/commit
 def drain_completed(self) -> list[tuple[TaskMessage, DecisionMessage]]:
     rows = self._conn.execute(
         "SELECT task_id, payload, result FROM task_queue WHERE status = 'completed'"
     ).fetchall()
     if not rows:
         return []
-    task_ids = [r[0] for r in rows]
-    placeholders = ",".join("?" * len(task_ids))
-    self._conn.execute(
-        f"UPDATE task_queue SET status = 'done' WHERE task_id IN ({placeholders})",
-        task_ids,
-    )
-    self._conn.commit()
     return [
         (_TaskMessage.model_validate_json(payload), _DecisionMessage.model_validate_json(result))
         for _, payload, result in rows
     ]

+def mark_done(self, task_id: str) -> None:
+    """Transition a single completed task to done after its action is executed.
+
+    Args:
+        task_id: ID of the task to mark done.
+    """
+    self._conn.execute("UPDATE task_queue SET status = 'done' WHERE task_id = ?", (task_id,))
+    self._conn.commit()

# foreman/server.py — _drain_loop: call mark_done per task, after execute succeeds
     for task, decision in pairs:
         issue_number: int = task.payload.get("number", 0)
         executor.execute(decision, repo=task.repo, issue_number=issue_number, task_type=task.type)
         summary = f"decision={decision.decision.value}; rationale={decision.rationale}"
         memory.upsert_memory_summary(task.repo, issue_number, summary)
+        task_queue.mark_done(task.task_id)
```

Note: with this change, a process crash between `executor.execute()`
and `mark_done()` means the task is re-drained on next startup (at-least-once delivery for GitHub actions).
This is correct — it matches the stated design goal.

---

## Medium Priority Issues

(Should fix, not blocking)

### 🐛 #3: Startup poll claims only one task — N−1 tasks queued during downtime are permanently stuck

**Location:** `agents/issue-triage/issue_triage/agent.py:82` | **Confidence:** ✅ HIGH

`_lifespan` calls `_poll_and_process` exactly once.
If 3 tasks accumulated while the agent was down, 1 is claimed; the other 2 remain `pending` indefinitely.
They are not `claimed`, so `requeue_stale()` never touches them.
The harness sends nudges only when new tasks are enqueued, not retroactively for pre-existing `pending` tasks.
Those tasks effectively vanish from the agent's perspective — no nudge, no retry, no failure.

```diff
# agents/issue-triage/issue_triage/agent.py — _lifespan startup poll
 async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
     client = _get_client(application)
-    await _poll_and_process(client)
+    while True:
+        task = await asyncio.to_thread(client.next_task)
+        if task is None:
+            break
+        await _process_task(client, task)
     yield
     client.close()
```

The integration test in `test_integration.py` only covers the single-task case (step 1 enqueues exactly one task).
A second test covering N>1 pending tasks would guard this path.

---

### 🐛 #4: `_requeue_loop` has the same no-exception-handling problem as `_drain_loop`

**Location:** `foreman/server.py:163-168` | **Confidence:** ✅ HIGH

If `task_queue.requeue_stale()` or `task_queue.fail_exhausted()` raises,
the requeue loop exits `while True` and dies permanently.
Stale claimed tasks are never recycled; exhausted tasks are never failed.
The same shutdown re-raise risk applies.

```diff
# foreman/server.py — inside _requeue_loop while loop
     while True:
         await asyncio.sleep(config.queue.requeue_interval_seconds)
-        requeued = task_queue.requeue_stale()
-        failed = task_queue.fail_exhausted(max_retries=config.queue.max_retries)
-        logger.info("Requeue cycle", requeued=requeued, failed=failed)
+        try:
+            requeued = task_queue.requeue_stale()
+            failed = task_queue.fail_exhausted(max_retries=config.queue.max_retries)
+            logger.info("Requeue cycle", requeued=requeued, failed=failed)
+        except Exception:
+            logger.exception("Requeue loop: unexpected error, continuing")

# foreman/server.py — _lifespan finally block (same fix as #1)
-    with contextlib.suppress(asyncio.CancelledError):
-        await requeue_task
+    with contextlib.suppress(asyncio.CancelledError, Exception):
+        await requeue_task
```

---

## Low Priority Issues

(Nice to have)

### 🏗️ #5: Private attribute accessed across module boundary

**Location:** `foreman/__main__.py:167` | **Confidence:** ✅ HIGH

`app.state.executor = dispatcher._executor` reaches into `Dispatcher`'s private state.
If the attribute is renamed, this silently becomes `AttributeError` at runtime
(not caught by mypy's `--ignore-missing-imports`).
Expose it via a public attribute or property.

```diff
# foreman/server.py — Dispatcher.__init__
-    self._executor = GitHubExecutor(token=str(config.identity.github_token), memory=memory)
+    self.executor = GitHubExecutor(token=str(config.identity.github_token), memory=memory)

# foreman/__main__.py
-    app.state.executor = dispatcher._executor
+    app.state.executor = dispatcher.executor
```

---

### 🐛 #6: Reference agent has no heartbeat during LLM call

**Location:** `agents/issue-triage/issue_triage/agent.py:52-60` | **Confidence:** ✅ HIGH

`_process_task` runs `triage(task)` (a synchronous LLM call) via `asyncio.to_thread` with no heartbeat.
If the LLM call exceeds `claim_timeout_seconds` (default 300 s), the harness requeues the task.
The next nudge or startup poll claims it again, causing double-processing.
The docs show the heartbeat-thread pattern; the reference implementation should model it.

```diff
# agents/issue-triage/issue_triage/agent.py
+import threading
+
 async def _process_task(client: ForemanClient, task: TaskMessage) -> None:
-    decision = await asyncio.to_thread(triage, task)
+    stop = threading.Event()
+
+    def _hb():
+        while not stop.wait(timeout=25):
+            client.heartbeat(task.task_id)
+
+    hb_thread = threading.Thread(target=_hb, daemon=True)
+    hb_thread.start()
+    try:
+        decision = await asyncio.to_thread(triage, task)
+    finally:
+        stop.set()
     await asyncio.to_thread(client.complete_task, task.task_id, decision)
```

---

### 🎨 #7: Minimal working example in docs omits startup poll

**Location:** `docs/howtos/write-an-agent.md:125-156` | **Confidence:** ✅ HIGH

The 30-line "Minimal Working Example" instantiates `ForemanClient` at module level and has no lifespan.
A reader who copies it verbatim gets an agent without the zero-task-loss recovery path.
The startup poll section appears later but many readers won't reach it.
The example should include a minimal lifespan,
or a note should be added that the example is incomplete for production use.

```diff
-client = ForemanClient(os.environ["FOREMAN_HARNESS_URL"], os.environ["AGENT_URL"])
-app = FastAPI()
+from contextlib import asynccontextmanager
+
+@asynccontextmanager
+async def lifespan(app):
+    client = ForemanClient(os.environ["FOREMAN_HARNESS_URL"], os.environ["AGENT_URL"])
+    app.state.client = client
+    task = client.next_task()   # startup poll — pick up tasks queued while down
+    if task:
+        client.complete_task(task.task_id, _decide(task))
+    yield
+    client.close()
+
+app = FastAPI(lifespan=lifespan)
```

---

## Flow Impact Analysis

**Before this PR**: `Dispatcher.dispatch()` → synchronous `POST /task` → parse `DecisionMessage` → `executor.execute()`
(all in-request, blocking).

**After this PR**:

```text
Dispatcher.dispatch()
  → task_queue.enqueue()          [durable SQLite write]
  → POST /task {task_id}          [fire-and-forget nudge; failure is safe]

Agent:
  POST /task nudge received
  → background_tasks.add_task(_poll_and_process)
    → client.next_task()          [POST /queue/next → claim]
    → triage(task)                [LLM call]
    → client.complete_task()      [POST /queue/complete → status=completed]
                                  [POST /harness/result → drain_event.set()]

_drain_loop (background):
  ← drain_event wakes loop
  → task_queue.drain_completed()  [SELECT completed, UPDATE done — see issue #2]
  → executor.execute()            [GitHub API]
  → memory.upsert_memory_summary()

_requeue_loop (background, every 60 s):
  → task_queue.requeue_stale()    [claimed + timed-out → pending]
  → task_queue.fail_exhausted()   [pending + retries ≥ max → failed]
```

**Changed callers of `Dispatcher`**: `__main__._run_loop`
(unchanged call site; Dispatcher now requires `task_queue` arg).
All existing integration tests updated correctly.

**Affected by issue #2**: `drain_completed` tests in `test_queue.py` will need updating once `mark_done` is split out.
The integration test `test_pending_task_claimed_on_restart` checks `status in ("completed", "done")` —
it will still pass after the fix since `drain_completed` no longer transitions to `done`.

---

*Review conducted on PR #21 against branch `noble-cupcake` → `main`, 2026-05-04.*
