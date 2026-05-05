# Phase 3 Review — Remaining Fixes

Status of all items from `phase-3-review.md` as of 2026-05-05.

---

## Already Resolved

| # | Finding | Where fixed |
|---|---------|-------------|
| 1 | `httpx.Client` never closed | `client.py` — `close()`, `__enter__`, `__exit__` added; lifecycle tests in `TestForemanClientLifecycle` |
| 2 | `LLMBackendRef` / `TaskContext` not exported | `__init__.py` — both added to imports and `__all__` |
| 3 | `import json` inside test methods | `test_client.py:5` — moved to module-level |
| 4 | Misleading ordering comment | Removed; `test_sends_decision_then_nudge` now asserts both routes called |

---

## Remaining Work

### Task A — Add configurable `timeout` to `ForemanClient`

**Priority:** Low (suggestion from review finding #6)

**Files:** `foreman-client/foremanclient/client.py`, `foreman-client/tests/test_client.py`

**What to do:**

1. Add `timeout: float = 5.0` parameter to `ForemanClient.__init__`.
2. Pass it to `httpx.Client(base_url=harness_url, timeout=timeout)`.
3. Update the class docstring Args section to document the new parameter.
4. Add one test in `TestForemanClientLifecycle` verifying that the timeout value is
   forwarded to the underlying `httpx.Client`.

**Acceptance criteria:**

- [x] `ForemanClient("http://h", "http://a", timeout=10.0)` constructs without error.
- [x] `httpx.Client` is initialised with the supplied timeout value.
- [x] Default behaviour (no `timeout` arg) is unchanged — uses 5.0 s.
- [x] Docstring documents the parameter.
- [x] New test passes; full test suite passes; pre-commit clean.

---

### Task B — Document `task_id` / `decision.task_id` identity in API docs

**Priority:** Low (spec design note from review finding #5)

**File:** `docs/howtos/write-an-agent.md`

**What to do:**

Add a short callout under the `complete_task(task_id, decision)` section noting
that `task_id` must equal `decision.task_id`.
The current example already uses `task.task_id` for both arguments,
but a reader constructing a `DecisionMessage` independently might pass mismatched values silently.

Suggested addition (after the parameter table):

```text
> **Note:** Always pass `decision.task_id` as the `task_id` argument.
> Passing a different value causes the nudge and the stored decision to
> reference different tasks; the harness will not raise an error, but
> the drain loop will not find the intended result.
```

**Acceptance criteria:**

- [x] Callout appears in the `complete_task` section.
- [x] The existing code examples are unchanged.
- [x] pre-commit clean.

---

## Suggested order

Run Task A first (code change + test), then Task B (docs).
Both are small and can be done in a single commit or as two separate commits.
