# Foreman — Task List

## Phase 1: Foundation
- [x] Task 1: Fix scaffolding issues in pyproject.toml + complete directory skeleton (server.py/settings.py/middleware.py/otel.py/routers/health.py already exist)
- [x] Task 2: Config system — YAML loader + Pydantic validation
- [x] Task 3: Credential injection

### Checkpoint: Phase 1 — Foundation
- [x] `uv sync` and `pre-commit run --all-files` pass
- [x] `pytest tests/test_config.py tests/test_credentials.py` passes
- [x] Project structure matches spec §4
- [x] Review with human ✋

## Phase 2: Data and Memory Layer
- [x] Task 4: Agent protocol models (Task / Decision Pydantic types)
- [x] Task 5: Persistent memory (SQLite action_log + memory_summary)

### Checkpoint: Phase 2 — Data Layer
- [x] `pytest tests/test_protocol.py tests/test_memory.py` passes
- [x] Memory DB schema matches spec §6 exactly
- [x] Review with human ✋

## Phase 3: LLM Abstraction
- [x] Task 6: LLM backend base interface (ABC + factory)
- [x] Task 7: Anthropic + Ollama backends via LiteLLM (with recorded fixtures)

### Checkpoint: Phase 3 — LLM Abstraction
- [X] `pytest tests/test_llm_*.py` passes with no live LLM calls
- [X] Both backends reachable locally (capture fixtures manually)
- [X] Review with human ✋

## Phase 4: GitHub Integration
- [x] Task 8: GitHub executor (action list → GitHub API calls)
- [x] Task 9: GitHub poller (concurrent polling, unbounded repos, exponential backoff)

### Checkpoint: Phase 4 — GitHub Integration
- [x] `pytest tests/test_executor.py tests/test_poller.py` passes
- [x] No live GitHub calls in tests
- [x] Review with human ✋

## Phase 5: Harness Core
- [x] Task 10: Router — implement `foreman/routers/agent.py` (event → agent URL mapping)
- [x] Task 11: Extend existing `server.py` scaffolding with dispatch loop
- [x] Task 12: Main entrypoint and startup validation

### Checkpoint: Phase 5 — Harness Core
- [x] `pytest tests/` passes (all harness tests) — 155 passing
- [x] `foreman start --config config.example.yaml` starts cleanly
- [x] Full Poller → Router → Server → Executor sequence tested
- [x] Review with human ✋

## Phase 6: Issue Triage Agent
- [x] Task 13: Container lifecycle manager (harness starts/stops agent containers)
- [x] Task 14: Agent HTTP server scaffold + Dockerfile (with /health endpoint)
- [x] Task 15: Triage logic and prompt
- [x] Task 13b: Wire ContainerManager into startup sequence (`__main__.py`)

### Checkpoint: Phase 6 — Issue Triage Agent
- [x] `docker build` succeeds
- [x] Container lifecycle manager starts and stops the triage container cleanly
- [x] Integration tests (container + harness) pass
- [x] Triage decisions verified against all four decision types
- [x] Review with human ✋

## Phase 7: Integration and Polish
- [x] Task 16: End-to-end integration test
- [x] Task 17: config.example.yaml and CHANGELOG bootstrap

### Final Checkpoint
- [x] `pytest tests/` passes ≥85% line / ≥80% branch coverage
- [x] `pre-commit run --all-files` exits 0
- [x] `foreman start --config config.example.yaml` starts and polls a test repo
- [x] Issue triage works end-to-end: new issue → labeled + commented by bot
- [x] Human acceptance test: install on real repo, triage one issue in <30 minutes ✋
