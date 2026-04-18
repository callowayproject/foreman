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
- [ ] Task 6: LLM backend base interface (ABC + factory)
- [ ] Task 7: Anthropic + Ollama backends via LiteLLM (with recorded fixtures)

### Checkpoint: Phase 3 — LLM Abstraction
- [ ] `pytest tests/test_llm_*.py` passes with no live LLM calls
- [ ] Both backends reachable locally (capture fixtures manually)
- [ ] Review with human ✋

## Phase 4: GitHub Integration
- [ ] Task 8: GitHub executor (action list → GitHub API calls)
- [ ] Task 9: GitHub poller (concurrent polling, unbounded repos, exponential backoff)

### Checkpoint: Phase 4 — GitHub Integration
- [ ] `pytest tests/test_executor.py tests/test_poller.py` passes
- [ ] No live GitHub calls in tests
- [ ] Review with human ✋

## Phase 5: Harness Core
- [ ] Task 10: Router — implement `foreman/routers/agent.py` (event → agent URL mapping)
- [ ] Task 11: Extend existing `server.py` scaffolding with dispatch loop
- [ ] Task 12: Main entrypoint and startup validation

### Checkpoint: Phase 5 — Harness Core
- [ ] `pytest tests/` passes (all harness tests)
- [ ] `foreman start --config config.example.yaml` starts cleanly
- [ ] Full Poller → Router → Server → Executor sequence tested
- [ ] Review with human ✋

## Phase 6: Issue Triage Agent
- [ ] Task 13: Container lifecycle manager (harness starts/stops agent containers)
- [ ] Task 14: Agent HTTP server scaffold + Dockerfile (with /health endpoint)
- [ ] Task 15: Triage logic and prompt

### Checkpoint: Phase 6 — Issue Triage Agent
- [ ] `docker build` succeeds
- [ ] Container lifecycle manager starts and stops the triage container cleanly
- [ ] Integration tests (container + harness) pass
- [ ] Triage decisions verified against all four decision types
- [ ] Review with human ✋

## Phase 7: Integration and Polish
- [ ] Task 16: End-to-end integration test
- [ ] Task 17: config.example.yaml and CHANGELOG bootstrap

### Final Checkpoint
- [ ] `pytest tests/` passes ≥85% line / ≥80% branch coverage
- [ ] `pre-commit run --all-files` exits 0
- [ ] `foreman start --config config.example.yaml` starts and polls a test repo
- [ ] Issue triage works end-to-end: new issue → labeled + commented by bot
- [ ] Human acceptance test: install on real repo, triage one issue in <30 minutes ✋
