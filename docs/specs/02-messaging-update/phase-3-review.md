# Phase 3 Code Review — `foreman-client`

Reviewed commit `adffcef` (Phase 3 implementation).
Files: `foreman-client/foremanclient/client.py`, `models.py`, `__init__.py`, `tests/test_client.py`.

---

## Findings

### Important — Fix before Phase 4

#### 1. `httpx.Client` is never closed (`client.py:51`)

`ForemanClient.__init__` creates `self._http = httpx.Client(base_url=harness_url)` but the class has no `close()` method
and no context manager support.
The `httpx.Client` holds a connection pool; in long-running agent services this leaks file descriptors.

**Fix:** add `close()` and `__enter__`/`__exit__`:

```python
def close(self) -> None:
    """Close the underlying HTTP connection pool."""
    self._http.close()

def __enter__(self) -> ForemanClient:
    return self

def __exit__(self, *_: object) -> None:
    self.close()
```

#### 2. `LLMBackendRef` and `TaskContext` not exported (`__init__.py:4`)

Both types appear as nested fields of `TaskMessage`.
Agent authors constructing `TaskMessage` instances in unit tests need them.
They should be in `__all__` alongside `TaskMessage`.

**Fix:** add to `__init__.py`:

```python
from foremanclient.models import (
    ActionItem, DecisionMessage, DecisionType,
    LLMBackendRef, TaskContext, TaskMessage,
)

__all__ = [
    ...,
    "LLMBackendRef",
    "TaskContext",
]
```

---

### Suggestions — Lower priority

#### 3. `import json` inside test methods (`test_client.py:119, 133, 185`)

`import json` appears inside three test method bodies.
Move to module-level imports.

#### 4. Misleading ordering comment in test (`test_client.py:105-107`)

The comment "Verify /queue/complete was called first" is followed by assertions that only check requests are not None —
not actual call order.
Either remove the comment or verify ordering via `respx.calls` timestamp/index.

#### 5. Redundant `task_id` param on `complete_task` (spec design note)

`complete_task(task_id, decision)` — `task_id` is already in `decision.task_id`.
The nudge uses the positional `task_id` while the complete body uses `decision.model_dump()`.
If a caller passes mismatched values, both calls proceed with different IDs silently.
This matches the spec's stated API, so it is a spec-level design concern rather than a code bug.

Consider for Phase 6 (API docs): note that callers should always pass `decision.task_id` as `task_id`.

#### 6. No configurable timeout on `httpx.Client` (`client.py:51`)

Defaults to httpx's 5-second connect + read timeout.
For heartbeat callers, a failing harness causes a 5-second block.
Exposing a `timeout: float = 5.0` constructor parameter would let agent authors tune this.

---

## Axes Verdict

| Axis | Result | Notes |
|---|---|---|
| Correctness | Pass (with caveats) | Resource leak and missing exports are the gaps |
| Readability | Pass | Minor import style issue in tests |
| Architecture | Pass | Clean standalone package; correct HTTP contract |
| Security | Pass | No SSRF risk; no secrets in logs |
| Performance | Pass | Connection pooling correct; timeout note is minor |

---

## Status

- [ ] Fix `httpx.Client` lifecycle (close + context manager) — **before Phase 4 merge**
- [ ] Export `LLMBackendRef` and `TaskContext` — **before Phase 4 merge**
- [ ] Move `import json` to module level in tests — anytime
- [ ] Remove misleading ordering comment — anytime
