# Foreman , Project Specification

> Status: In progress , scaffolding complete, implementation underway

## 1. Objective

Build a minimal Python harness that acts as an always-on AI co-maintainer for OSS repositories.
The harness manages process lifecycle, credential injection, message routing, and scheduling.
All intelligence lives in agents.
The system must be composable from specialized agents and runnable anywhere without writing integration glue each time.

**Target user:** A solo OSS maintainer who wants automated triage, dependency updates,
and releases across multiple repos, with a co-maintainer who has their own GitHub identity and opinions.

**Success criterion for MVP:** A maintainer can install the harness, configure one repo, and have an issue triaged
(labeled, responded to, or closed) without writing any code — in under 30 minutes.

## 2. MVP Scope

### In

| Component                | Description                                                  |
| ------------------------ | ------------------------------------------------------------ |
| Harness core             | Process management, credential injection, HTTP message routing, GitHub event polling |
| Agent protocol v0        | JSON over HTTP ,  task in, decision out, action taken        |
| Issue Triage agent       | Label, respond, close stale issues                           |
| LLM backend abstraction  | At least Anthropic and Ollama backends via a common interface (LiteLLM or thin adapter) |
| Config file              | YAML ,  defines repos, agent assignments, LLM backend        |
| Persistent action memory | Per-repo summary store of past agent decisions to inform future ones |
| GitHub bot identity      | Dedicated bot account; harness authenticates as the bot      |
| Polling trigger          | GitHub API polling as primary trigger (no public URL required) |

### Out of MVP (protocol must not block these)

- Multi-agent DAG workflow engine
- Dependency update agent
- Release agent
- Plugin/sharing registry
- Web UI
- Webhook listener (defer until public URL is a supported deployment mode)
- Multi-model routing/fallback logic

## 3. Agent Protocol v0

### Transport

HTTP (JSON over REST).
The harness runs an internal HTTP server.
Each agent runs in a Docker container and exposes an HTTP endpoint.
The harness POSTs tasks to agents; agents return decisions synchronously.

```text
Harness  →  POST /task  →  Agent container
Harness  ←  200 {decision, actions}  ←  Agent container
```

### Message Contract

**Task (harness → agent):**

```json
{
  "task_id": "uuid4",
  "type": "issue.triage",
  "repo": "owner/repo",
  "payload": { /* GitHub event payload */ },
  "context": {
    "memory_summary": "string ,  prior actions on this issue/repo",
    "llm_backend": { "provider": "anthropic", "model": "claude-sonnet-4-6" }
  }
}
```

**Decision (agent → harness):**

```json
{
  "task_id": "uuid4",
  "decision": "label_and_respond | close | escalate | skip",
  "rationale": "string",
  "actions": [
    { "type": "add_label", "label": "bug" },
    { "type": "comment", "body": "string" }
  ]
}
```

**Constraint:** The harness executes all GitHub API calls.
Agents produce decisions and action lists , they never call GitHub directly.
This keeps credentials out of agent containers.

## 4. Project Structure

```text
foreman/
├── foreman/
│   ├── __init__.py
│   ├── config.py           # YAML config loader and validator (runtime repos/agents/LLM config)
│   ├── settings.py         # App-level operational settings via pydantic-settings (env vars)
│   ├── server.py           # FastAPI app ,  dispatch loop: fetch memory → build task → POST to agent → execute
│   ├── poller.py           # GitHub API polling loop (asyncio + semaphore)
│   ├── executor.py         # Execute actions returned by agents (GitHub API calls)
│   ├── memory.py           # Persistent action memory (SQLite ,  action_log + memory_summary)
│   ├── credentials.py      # Credential injection and secret management (${VAR} resolution)
│   ├── protocol.py         # Pydantic models: TaskMessage, DecisionMessage, ActionItem
│   ├── containers.py       # Docker container lifecycle manager for agent containers
│   ├── logging_info.py     # structlog configuration (dev: console, prod: JSON)
│   ├── middleware.py       # Correlation ID middleware for request tracing
│   ├── otel.py             # OpenTelemetry configuration and FastAPI instrumentation
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── health.py       # GET /healthcheck and GET /healthcheck/ready endpoints
│   │   └── agent.py        # Event → agent routing logic (repo+event_type → RouteTarget)
│   └── llm/
│       ├── __init__.py
│       ├── base.py         # Abstract LLMBackend ABC + from_config() factory
│       ├── anthropic.py    # Anthropic backend (wraps LiteLLM)
│       └── ollama.py       # Ollama backend (wraps LiteLLM)
├── agents/
│   └── issue-triage/
│       ├── Dockerfile
│       ├── agent.py        # FastAPI: POST /task, GET /health
│       ├── prompts/
│       │   └── triage.py
│       └── pyproject.toml
├── tests/
│   ├── fixtures/           # Recorded LLM response fixtures (replayed in CI)
│   ├── test_config.py
│   ├── test_router.py
│   ├── test_executor.py
│   ├── test_memory.py
│   ├── test_protocol.py
│   ├── test_poller.py
│   ├── test_containers.py
│   ├── test_server.py
│   ├── test_main.py
│   ├── test_logging_info.py
│   ├── test_middleware.py
│   ├── test_otel.py
│   └── test_agent_triage.py
├── config.example.yaml
├── pyproject.toml
├── SPEC.md
└── CHANGELOG.md
```

### Scaffolded vs. planned

The following modules exist in the scaffolding and are ready for Foreman-specific implementation:

| Module | State | Notes |
|--------|-------|-------|
| `server.py` | Scaffolded (template) | Generic FastAPI app with CORS, GZip, middleware; needs dispatch loop added |
| `settings.py` | Scaffolded | `pydantic-settings` env-var loading for operational settings (log level, OTEL); distinct from YAML config |
| `logging_info.py` | Scaffolded | structlog setup with dev/prod renderers and OTel trace injection |
| `middleware.py` | Scaffolded | Correlation ID bound to each request's log context |
| `otel.py` | Scaffolded | OpenTelemetry with optional OTLP exporter and debug console exporter |
| `routers/health.py` | Scaffolded | `/healthcheck` and `/healthcheck/ready` endpoints |
| All other modules | Not yet created | Per the implementation plan |

**Distinction between `settings.py` and `config.py`:**

- `settings.py` , operational settings loaded from environment variables at startup
    (log level, OTEL connection, environment name).
    Uses `pydantic-settings`.
    No YAML.
- `config.py` , runtime harness config loaded from `config.yaml` (repos, agents, LLM backend, polling interval).
    Uses PyYAML + Pydantic.
    Secrets resolved via `${VAR}` substitution.

## 5. Configuration (YAML)

```yaml
# config.yaml
identity:
  github_token: "${GITHUB_TOKEN}"    # bot account PAT
  github_user: "my-bot"

llm:
  provider: anthropic                # anthropic | ollama
  model: claude-sonnet-4-6
  api_key: "${ANTHROPIC_API_KEY}"    # omit for ollama

polling:
  interval_seconds: 60

repos:
  - owner: my-org
    name: my-repo
    agents:
      - type: issue-triage
        config:
          stale_days: 30
          labels:
            bug: ["crash", "exception", "error"]
            question: ["how do I", "how to"]
```

All secrets are environment variables (`${VAR}`).
The config file itself never contains raw secrets.

## 6. Persistent Memory

**Storage:** SQLite, local file (`~/.agent-harness/memory.db` by default, overridable in config).

**Schema:**

```sql
CREATE TABLE action_log (
  id          INTEGER PRIMARY KEY,
  repo        TEXT NOT NULL,        -- "owner/repo"
  issue_id    INTEGER NOT NULL,
  task_type   TEXT NOT NULL,
  decision    TEXT NOT NULL,
  rationale   TEXT,
  actions     TEXT,                 -- JSON array
  timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE memory_summary (
  repo        TEXT NOT NULL,
  issue_id    INTEGER NOT NULL,
  summary     TEXT NOT NULL,        -- LLM-generated summary of prior actions
  updated_at  DATETIME,
  PRIMARY KEY (repo, issue_id)
);
```

The `memory_summary` table is updated after each action.
When dispatching a new task, the harness fetches the relevant summary and injects it into the task context.

## 7. Tech Stack

| Concern                 | Choice                                                        |
|-------------------------|---------------------------------------------------------------|
| Language                | Python 3.12+                                                  |
| Build system            | Hatchling                                                     |
| Package manager         | uv                                                            |
| HTTP (harness server)   | FastAPI                                                       |
| HTTP (agent client)     | httpx                                                         |
| GitHub API              | PyGithub or raw httpx calls                                   |
| LLM abstraction         | LiteLLM (validate with triage prompt against both backends)   |
| Agent packaging         | Docker containers                                             |
| YAML config parsing     | PyYAML + Pydantic for validation                              |
| App/env settings        | pydantic-settings (env var loading for operational config)    |
| Memory store            | SQLite via stdlib `sqlite3`                                   |
| Structured logging      | structlog (dev: console, prod: JSON; with OTel trace injection)|
| Observability           | OpenTelemetry (FastAPI instrumentation; optional OTLP export) |
| Container management    | Docker SDK for Python (`docker` package)                      |
| Versioning              | bump-my-version                                               |

## 8. Code Style

Matches the project's established toolchain:

- **Formatter/linter:** ruff (line length 119, Google docstring convention)
- **Type checking:** mypy (`--no-strict-optional --ignore-missing-imports`)
- **Docstring coverage:** interrogate (≥90%, Google style, validated by pydoclint)
- **Pre-commit hooks:** ruff-format, ruff-check, mypy, pydoclint, interrogate, detect-secrets, pyupgrade, check-yaml,
    check-toml, check-github-actions, check-github-workflows
- **Type hints:** Required on all public functions and methods; `--keep-runtime-typing`
- **Python minimum:** 3.12

## 9. Testing Strategy

- **Framework:** pytest + pytest-cov (branch coverage)
- **LLM calls:** Recorded fixtures , real LLM responses captured once and replayed.
    No live LLM calls in CI.
    Fixture files live in `tests/fixtures/`.
- **GitHub API calls:** pytest-mock to mock PyGithub/httpx calls at the boundary
- **Agent protocol:** Integration tests that spin up the agent container locally and send real HTTP task messages;
    record expected response fixtures
- **Coverage target:** ≥85% line coverage, ≥80% branch coverage
- **What is NOT mocked:** SQLite memory store (use a real in-memory or temp-file DB in tests)

## 10. Boundaries

### Always do automatically

- Poll configured repos on the set interval without user intervention
- Inject credentials from the environment; never log or expose them
- Write every decision and action to the action log before executing
- Validate config file on startup; fail fast with a clear error if invalid

### Ask before doing (require explicit config opt-in)

- Closing an issue (default: label + comment only; closing requires `allow_close: true` in agent config)
- Acting on issues created by repo owners or maintainers (default: skip)
- Posting more than one comment on the same issue within 24 hours

### Never do

- Call GitHub API as anything other than the configured bot identity
- Store raw secrets in config files, logs, or the memory database
- Execute shell commands or arbitrary code from agent decision payloads
- Implement a DAG workflow engine in v1
- Build a web UI in v1
- Assume a public-facing URL exists for webhook delivery

## 11. Open Questions (resolved)

| Question                 | Decision                                                   |
| ------------------------ | ---------------------------------------------------------- |
| Wire protocol            | HTTP (JSON over REST)                                      |
| Persistent memory in v1? | Yes ,  per-issue action summary injected into task context |
| Config format            | YAML                                                       |
| Agent packaging          | Docker containers                                          |
| Webhook vs. polling      | Polling only in v1; no public URL assumed                  |
| LLM test strategy        | Recorded fixtures                                          |
| Code style               | ruff + mypy + pydoclint + interrogate (existing toolchain) |

## 12. Known Scaffolding Issues to Fix

The following issues were identified in the boilerplate scaffolding and must be fixed before or during implementation:

1. **`pyproject.toml` missing CLI entry point:** The `[project.scripts]` section is commented out.
    Uncomment and point to the Foreman CLI once `foreman/__main__.py` is implemented.
2. **`pyproject.toml` missing runtime dependencies:** `PyYAML`, `PyGithub`, `litellm`, `httpx`, `docker`
    (Python SDK) are not yet listed.
    Add these during the relevant implementation tasks.
3. **`server.py` is a template, not Foreman's dispatch loop:** The scaffolded `server.py` is a generic FastAPI app.
    It must be extended to implement the task dispatch loop described in §3
    while retaining the existing middleware/CORS/logging setup.

## 13. Key Assumptions to Validate Before Coding

1. HTTP round-trip latency between harness and agent container (localhost) is acceptable for a polling-based system:
    *sketch one full triage flow end-to-end before building the full protocol*
2. LiteLLM abstraction works transparently for both Anthropic and Ollama without capability gaps on triage prompts:
    *test same prompt against both backends before committing*
3. SQLite is sufficient for memory at single-maintainer scale:
    *revisit only if concurrent multi-repo polling causes locking issues*
4. Docker is available in the target deployment environment: *document as a hard prerequisite*
