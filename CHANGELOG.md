# Changelog

## 0.3.0 (2026-05-01)

[Compare the full difference.](https://github.com/callowayproject/foreman/compare/0.2.5...0.3.0)

### New

- Add design system assets, CSS variables, and comprehensive API reference structure. [38cfce0](https://github.com/callowayproject/foreman/commit/38cfce051fb7fa7eef63f835f527ab38e2eac90e)

- Add CHANGELOG.md to excluded files in linter configuration. [a3fa809](https://github.com/callowayproject/foreman/commit/a3fa8090225da475f8d608ca40489a34cb8e69e4)

### Other

- Restructure and update design specs; add messaging update proposal and index file. [f8027a5](https://github.com/callowayproject/foreman/commit/f8027a55de5ce29acd283eb325d477dfb69a1d6c)

### Updates

- Remove outdated tutorials and API docs; add home page layout, visual assets, and updated CSS. [8b2a2fc](https://github.com/callowayproject/foreman/commit/8b2a2fc59f4f82b63dab31f65a9d1b3bf2bccbd8)

## 0.2.5 (2026-04-22)

[Compare the full difference.](https://github.com/callowayproject/foreman/compare/0.2.4...0.2.5)

### New

- Add reference documentation for agent protocol, CLI commands, and configuration schema. [b35c600](https://github.com/callowayproject/foreman/commit/b35c600fa999dbd525ada9a1145999f3d9bf6c59)

- Add rumdl linting support, update README link, and configure pre-commit hooks. [68c7d76](https://github.com/callowayproject/foreman/commit/68c7d76fc816143e8edfb8c6b4261071a1fdfb4c)

### Other

- Reformat several Markdown files. [b97ec91](https://github.com/callowayproject/foreman/commit/b97ec91206d61ccfb9ef76578934443e43bf5891)

- Mark Phase 5 and Final Checkpoint tasks as complete in todo.md. [9149c15](https://github.com/callowayproject/foreman/commit/9149c153c5de2a573d69d3b9d80186e53b28b25b)

- Task 17: mark Phase 7 tasks complete; final coverage at 96%. [f8f6d35](https://github.com/callowayproject/foreman/commit/f8f6d356732d7e496001cc9b63794cd0b9bd3fc1)

  config.example.yaml already matches full schema and loads cleanly.
  CHANGELOG.md already maintained by bump-my-version toolchain.
  214 tests passing, 96% line coverage (target ≥85%), pre-commit clean.

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Task 16: End-to-end integration test for full issue triage pipeline. [440ecec](https://github.com/callowayproject/foreman/commit/440ececc0c387e3b998097c1412c15f9034cbbe4)

  Covers the complete path: poller event → router → dispatcher → executor →
  memory (real SQLite DB). Mocks are limited to PyGithub and httpx boundaries.

  Six tests across two classes:

  - TestFullTriagePipeline: label+comment applied, memory updated, action logged
    before GitHub call, prior summary injected, close_issue blocked when
    allow_close=False
  - TestPollerFeedsDispatcher: poller.poll_all callback routes and dispatches
    a polled issue end-to-end

  214 tests passing.

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- [pre-commit.ci] pre-commit autoupdate. [068ab20](https://github.com/callowayproject/foreman/commit/068ab20f5e5d16a193eb34e12a4626892ccef3f6)

  **updates:** - [github.com/astral-sh/ruff-pre-commit: v0.15.10 → v0.15.11](https://github.com/astral-sh/ruff-pre-commit/compare/v0.15.10...v0.15.11)

### Updates

- Remove redundant sections from CONTRIBUTING.md and fix Code of Conduct link. [5c891a5](https://github.com/callowayproject/foreman/commit/5c891a595089fa963123d803d4987e3d87e89ae9)

- Remove outdated agent-harness spec, update CLAUDE.md with spec-driven development process. [bc252ba](https://github.com/callowayproject/foreman/commit/bc252ba17c48492eb59e6247c341a331056ad996)

## 0.2.4 (2026-04-20)

[Compare the full difference.](https://github.com/callowayproject/foreman/compare/0.2.3...0.2.4)

### Other

- Wire `ContainerManager` and agent lifecycle into `foreman start`.
  Update agent paths, config, tests, and Dockerfile to align with refactored `issue-triage` structure.
  Mark Phase 6 tasks as complete.
  [7e7846d](https://github.com/callowayproject/foreman/commit/7e7846df97f8026d41d7adb435a26be8dc6dd19e)

- Use `SecretStr` for sensitive fields in configuration and GitHubPoller, removing custom masking logic.
  Update tests accordingly.
  [d2e437a](https://github.com/callowayproject/foreman/commit/d2e437ae2582135c2a72388f7662c348a6d85032)

- Task 15: Triage logic and prompt (prompts/triage.py).
  [6518095](https://github.com/callowayproject/foreman/commit/65180958d45351e5de9e246e00ba939328165549)

  - build_prompt: formats issue title/body/author/labels + memory_summary
  - parse_llm_response: extracts JSON from prose, validates decision type,
    applies allow_close guard, defaults to skip on parse failure
  - \_call_llm: LiteLLM wrapper (provider/model from task context)
  - run_triage: duplicate-comment guard (memory keyword check) before LLM call
  - 18 triage tests + full suite at 195 passing

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Task 14: Agent HTTP server scaffold + Dockerfile.
  [60778eb](https://github.com/callowayproject/foreman/commit/60778eb13fe3a6676b42f6ef7e9b6c588a7789d7)

  - FastAPI app with POST /task (DecisionMessage) and GET /health (200 ok)
  - Self-contained protocol models (TaskMessage, DecisionMessage, ActionItem)
  - triage() delegates to prompts/triage.run_triage() — stub for Task 15
  - Dockerfile installs deps and runs uvicorn on port 8000
  - agents/issue-triage/pyproject.toml with runtime deps
  - 7 agent server tests; full suite at 177 passing

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Task 13: Container lifecycle manager (foreman/containers.py).
  [7e7c407](https://github.com/callowayproject/foreman/commit/7e7c407a0211bee197abb68ce2ee8f39cf351fde)

  - ContainerManager pulls images on demand, starts containers, waits for /health
  - stop_all() stops all managed containers; safe to call multiple times
  - handle_container_exit() logs error and restarts once; marks failed on second exit
  - ContainerError raised when Docker socket is unavailable at init
  - 14 tests covering all acceptance criteria; full suite at 170 passing

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Set environment to `github-pages` for `publish-docs` workflow.
  [e2f100f](https://github.com/callowayproject/foreman/commit/e2f100f8e8cdf543e19b9f8ffe4ba93bc86714af)

## 0.2.3 (2026-04-19)

[Compare the full difference.](https://github.com/callowayproject/foreman/compare/0.2.2...0.2.3)

### New

- Add .api-env to .gitignore.
  [ff63ae3](https://github.com/callowayproject/foreman/commit/ff63ae3825ca1f46ddabc25906571436b2fd9624)

  Prevents accidental commit of local env file containing GitHub token and API keys.

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Add initial README with project description, features, requirements, and setup instructions.
  [3a9e9ba](https://github.com/callowayproject/foreman/commit/3a9e9bab536fb4fcd49741d0d87fa24ecc2730ac)

### Other

- Phase 5 — Harness Core + polling error visibility.
  [0a3c781](https://github.com/callowayproject/foreman/commit/0a3c7811b17861055231560633dee575b1ba1092)

  Implements router, server dispatch loop, and main entrypoint (Tasks 10–12).
  Fixes two bugs found during integration testing:

  - SQLite connection used across threads now opens with check_same_thread=False
  - Poller task was created but never awaited; fixed by running concurrently in \_run_loop

  Also fixes silent failure on GitHub API errors: non-rate-limit exceptions
  (including 401 bad credentials)
  are now logged immediately at critical/error level instead of being swallowed until process shutdown.
  Done callback on the poller task surfaces any unexpected crash in real time.

  156 tests passing, all pre-commit hooks green.

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

### Updates

- Update license in README to MIT.
  [64a1e71](https://github.com/callowayproject/foreman/commit/64a1e71af4e9d7309af6383c488c451a323914d6)

- Update dependency versions in `uv.lock` file, including FastAPI (0.136.0), FastAPI Cloud CLI (0.17.0), FileLock
  (3.28.0), HuggingFace Hub (1.11.0), Identify (2.6.19), MkDocStrings (1.0.4), Packaging (26.1), and Virtualenv
  (21.2.4).
  [e0bf184](https://github.com/callowayproject/foreman/commit/e0bf1844062bef9cd4e11ce16ca718e7584cdd59)

## 0.2.2 (2026-04-18)

[Compare the full difference.](https://github.com/callowayproject/foreman/compare/0.2.1...0.2.2)

### Other

- Bump the uv group with 2 updates.
  [b31044f](https://github.com/callowayproject/foreman/commit/b31044f7475bab803bfe1abb0bc0129beb9694de)

  Bumps the uv group with 2 updates:
  [litellm](https://github.com/BerriAI/litellm) and [uv](https://github.com/astral-sh/uv).

  Updates `litellm` from 1.83.7 to 1.83.9

  - [Release notes](https://github.com/BerriAI/litellm/releases)
  - [Commits](https://github.com/BerriAI/litellm/commits)

  Updates `uv` from 0.11.6 to 0.11.7

  - [Release notes](https://github.com/astral-sh/uv/releases)
  - [Changelog](https://github.com/astral-sh/uv/blob/main/CHANGELOG.md)
  - [Commits](https://github.com/astral-sh/uv/compare/0.11.6...0.11.7)

______________________________________________________________________

**updated-dependencies:** - dependency-name: litellm dependency-version: 1.83.9 dependency-type: direct:
production update-type: version-update:semver-patch dependency-group: uv

**signed-off-by:** dependabot[bot] <support@github.com>

## 0.2.1 (2026-04-18)

[Compare the full difference.](https://github.com/callowayproject/foreman/compare/0.2.0...0.2.1)

### Other

- Use `TYPE_CHECKING` for imports in test files and update Phase 4 todo items.
  [6043d54](https://github.com/callowayproject/foreman/commit/6043d54a2029381d0528090bfe2245e8d8e41543)

- Phase 4: implement GitHub executor and poller (Tasks 8 & 9).
  [9efa175](https://github.com/callowayproject/foreman/commit/9efa175d6fca43f810579e604a87f2b3a73ac413)

  executor.py:

  - GitHubExecutor.execute() logs decision to action_log BEFORE any GitHub API call
  - Handles add_label, comment, close_issue (with allow_close guard)
  - Raises UnknownActionError for unrecognized action types

  poller.py:

  - GitHubPoller.poll_repo() fetches issues since last_polled, skips collaborator issues
  - poll_all() runs repos concurrently via asyncio + semaphore (default max 5)
  - Exponential backoff on 403/429; other GithubExceptions propagate
  - Continuous run() loop at configurable interval

  memory.py:

  - Add poll_state table with get_last_polled() / set_last_polled() methods
  - Timestamps stored as ISO-8601 strings, returned as timezone-aware datetime

  39 new tests; 125 total passing.

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

### Updates

- Remove draft flag from release creation script.
  [131ea10](https://github.com/callowayproject/foreman/commit/131ea103ea75a4edc925a980f0a6b59c01fd5fa8)

## 0.2.0 (2026-04-18)

[Compare the full difference.](https://github.com/callowayproject/foreman/compare/0.1.0...0.2.0)

### Fixes

- Fix unclosed DB connection warnings in test_memory.py.
  [982f6ec](https://github.com/callowayproject/foreman/commit/982f6ece8fbb4f4b5bd553efe76beb1d3bd5703d)

  Switch store fixtures to yield+context-manager so the connection is closed after each test,
  and remove manual store.close() calls that were no longer needed with WAL mode + committed writes.

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

### New

- Add docstrings for clarity in LLM backend tests, remove unused imports,
  and update CLAUDE.md with test-writing guidance.
  [0b73671](https://github.com/callowayproject/foreman/commit/0b736714465dc6313bb2fa2d91a606cee967cb31)

### Other

- Replace `mkdocs gh-deploy` with `zensical build --clean` in docs workflows.
  [4e22796](https://github.com/callowayproject/foreman/commit/4e22796d789c8dcce3bd4d20004facae2eca62e8)

- Generated the changelog.
  [2f35d59](https://github.com/callowayproject/foreman/commit/2f35d59b98b589dc0f97dc06f7a38c5a355be892)

- Bump the github-actions group with 10 updates.
  [f1cb391](https://github.com/callowayproject/foreman/commit/f1cb391e51f63a5982e313c5ae6505a1fddf62c3)

  Bumps the github-actions group with 10 updates:

  | Package | From | To | | --- | --- | --- | | [actions/checkout](https://github.com/actions/checkout) | `4` | `6` |
  | [actions/download-artifact](https://github.com/actions/download-artifact) | `4` | `8` | |
  [actions/setup-python](https://github.com/actions/setup-python) | `5` | `6` | |
  [astral-sh/setup-uv](https://github.com/astral-sh/setup-uv) | `5` | `7` | |
  [github/codeql-action](https://github.com/github/codeql-action) | `3` | `4` | |
  [docker/login-action](https://github.com/docker/login-action) | `3` | `4` | |
  [docker/metadata-action](https://github.com/docker/metadata-action) | `5` | `6` | |
  [docker/build-push-action](https://github.com/docker/build-push-action) | `6` | `7` | |
  [actions/attest-build-provenance](https://github.com/actions/attest-build-provenance) | `2` | `4` | |
  [softprops/action-gh-release](https://github.com/softprops/action-gh-release) | `2` | `3` |

  Updates `actions/checkout` from 4 to 6

  - [Release notes](https://github.com/actions/checkout/releases)
  - [Changelog](https://github.com/actions/checkout/blob/main/CHANGELOG.md)
  - [Commits](https://github.com/actions/checkout/compare/v4...v6)

  Updates `actions/download-artifact` from 4 to 8

  - [Release notes](https://github.com/actions/download-artifact/releases)
  - [Commits](https://github.com/actions/download-artifact/compare/v4...v8)

  Updates `actions/setup-python` from 5 to 6

  - [Release notes](https://github.com/actions/setup-python/releases)
  - [Commits](https://github.com/actions/setup-python/compare/v5...v6)

  Updates `astral-sh/setup-uv` from 5 to 7

  - [Release notes](https://github.com/astral-sh/setup-uv/releases)
  - [Commits](https://github.com/astral-sh/setup-uv/compare/v5...v7)

  Updates `github/codeql-action` from 3 to 4

  - [Release notes](https://github.com/github/codeql-action/releases)
  - [Changelog](https://github.com/github/codeql-action/blob/main/CHANGELOG.md)
  - [Commits](https://github.com/github/codeql-action/compare/v3...v4)

  Updates `docker/login-action` from 3 to 4

  - [Release notes](https://github.com/docker/login-action/releases)
  - [Commits](https://github.com/docker/login-action/compare/v3...v4)

  Updates `docker/metadata-action` from 5 to 6

  - [Release notes](https://github.com/docker/metadata-action/releases)
  - [Commits](https://github.com/docker/metadata-action/compare/v5...v6)

  Updates `docker/build-push-action` from 6 to 7

  - [Release notes](https://github.com/docker/build-push-action/releases)
  - [Commits](https://github.com/docker/build-push-action/compare/v6...v7)

  Updates `actions/attest-build-provenance` from 2 to 4

  - [Release notes](https://github.com/actions/attest-build-provenance/releases)
  - [Changelog](https://github.com/actions/attest-build-provenance/blob/main/RELEASE.md)
  - [Commits](https://github.com/actions/attest-build-provenance/compare/v2...v4)

  Updates `softprops/action-gh-release` from 2 to 3

  - [Release notes](https://github.com/softprops/action-gh-release/releases)
  - [Changelog](https://github.com/softprops/action-gh-release/blob/master/CHANGELOG.md)
  - [Commits](https://github.com/softprops/action-gh-release/compare/v2...v3)

______________________________________________________________________

**updated-dependencies:** - dependency-name: actions/checkout dependency-version: '6' dependency-type: direct:
production update-type: version-update:semver-major dependency-group: github-actions

**signed-off-by:** dependabot[bot] <support@github.com>

- Phase 3 Tasks 6-7: implement LLM backend abstraction.
  [02733dc](https://github.com/callowayproject/foreman/commit/02733dceba4331aedbb4cbf1de53786fe3cf00eb)

  - LLMBackend ABC with complete() method and from_config() factory in base.py
  - AnthropicBackend and OllamaBackend wrapping LiteLLM
  - Recorded fixture files for both backends (no live LLM calls in tests)
  - 16 new tests across test_llm_base.py and test_llm_backends.py

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Refine type annotations and optimize imports in protocol and memory tests.
  [12a6bd8](https://github.com/callowayproject/foreman/commit/12a6bd81808ebdafc23a11cba0977b58cf876946)

- Phase 2 human review approved.
  [3846ea8](https://github.com/callowayproject/foreman/commit/3846ea849be096d3e1a51c9218f8a94f4d6a4cae)

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Mark Phase 2 tasks complete in todo.md.
  [78318a0](https://github.com/callowayproject/foreman/commit/78318a0c11b8493e774b436f9be2fa36b77d698d)

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Phase 2 Task 5: implement SQLite memory store.
  [6b39f0b](https://github.com/callowayproject/foreman/commit/6b39f0b8289c26cc6d6e46813020c4e29846c776)

  Add MemoryStore with action_log and memory_summary tables
  (WAL mode)
  . log_action(), get_memory_summary(), upsert_memory_summary() covered by 13 tests using real temp-file DBs —
  no mocks.

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Phase 2 Task 4: implement agent protocol Pydantic models.
  [829f47f](https://github.com/callowayproject/foreman/commit/829f47f16ecce8965f7c318bd9f29fbb397a4d32)

  Add TaskMessage, DecisionMessage, ActionItem, LLMBackendRef, TaskContext,
  and DecisionType to foreman/protocol.py with 22 tests.

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Phase 1: scaffold, config system, and credential injection.
  [9f21485](https://github.com/callowayproject/foreman/commit/9f21485eee9dedc8b95c29d914a9fb47be05a6f3)

  - pyproject.toml: add runtime deps (PyYAML, PyGithub, litellm, httpx, docker),
    uncomment [project.scripts] entry pointing to foreman.**main**:main
  - Add stub modules for all planned foreman/ submodules and llm/ package
  - Add agents/issue-triage/ scaffolding (Dockerfile placeholder, prompts/)
  - Implement foreman/config.py: YAML loader with ${VAR} env resolution,
    Pydantic validation, ConfigError, secret-masking repr for tokens/keys
  - Implement foreman/credentials.py: resolve_env_refs(), get_github_token(),
    CredentialError (variable name only — no secrets in error messages)
  - Add config.example.yaml matching the full schema from spec §5
  - Add types-PyYAML to mypy pre-commit additional_dependencies
  - 35 tests pass; coverage >85% on new modules

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

### Updates

- Remove unused GitHub Actions workflows and update dependabot configuration.
  [7bbcfb0](https://github.com/callowayproject/foreman/commit/7bbcfb04a104467f712413c87ed2ad08a94bfe69)

- Update httpx requirement from >=0.27 to >=0.28.1.
  [5cef88e](https://github.com/callowayproject/foreman/commit/5cef88e7648e0cb137d1678c52c62d968459f473)

  Updates the requirements on [httpx](https://github.com/encode/httpx) to permit the latest version.

  - [Release notes](https://github.com/encode/httpx/releases)
  - [Changelog](https://github.com/encode/httpx/blob/master/CHANGELOG.md)
  - [Commits](https://github.com/encode/httpx/compare/0.27.0...0.28.1)

______________________________________________________________________

**updated-dependencies:** - dependency-name: httpx dependency-version: 0.28.1 dependency-type: direct:production

**signed-off-by:** dependabot[bot] <support@github.com>

- Update pydantic-settings requirement from >=2.8.1 to >=2.13.1.
  [624e336](https://github.com/callowayproject/foreman/commit/624e3369a0e9690df36e2a5c876a2b43381dbe35)

  Updates the requirements on [pydantic-settings](https://github.com/pydantic/pydantic-settings) to permit the latest
  version.

  - [Release notes](https://github.com/pydantic/pydantic-settings/releases)
  - [Commits](https://github.com/pydantic/pydantic-settings/compare/v2.8.1...v2.13.1)

______________________________________________________________________

**updated-dependencies:** - dependency-name: pydantic-settings dependency-version: 2.13.1 dependency-type: direct:
production

**signed-off-by:** dependabot[bot] <support@github.com>

- Update opentelemetry-api requirement from >=1.32.0 to >=1.41.0.
  [ee4c822](https://github.com/callowayproject/foreman/commit/ee4c822dc34cbbad4b99d69d765e0c39b9fca886)

  Updates the requirements on [opentelemetry-api](https://github.com/open-telemetry/opentelemetry-python) to permit
  the latest version.

  - [Release notes](https://github.com/open-telemetry/opentelemetry-python/releases)
  - [Changelog](https://github.com/open-telemetry/opentelemetry-python/blob/main/CHANGELOG.md)
  - [Commits](https://github.com/open-telemetry/opentelemetry-python/compare/v1.32.0...v1.41.0)

______________________________________________________________________

**updated-dependencies:** - dependency-name: opentelemetry-api dependency-version: 1.41.0 dependency-type: direct:
production

**signed-off-by:** dependabot[bot] <support@github.com>

- Update docker requirement from >=7.0 to >=7.1.0.
  [e673884](https://github.com/callowayproject/foreman/commit/e673884e9ec82c472faf1770018cd840998d8de3)

  Updates the requirements on [docker](https://github.com/docker/docker-py) to permit the latest version.

  - [Release notes](https://github.com/docker/docker-py/releases)
  - [Commits](https://github.com/docker/docker-py/compare/7.0.0...7.1.0)

______________________________________________________________________

**updated-dependencies:** - dependency-name: docker dependency-version: 7.1.0 dependency-type: direct:production

**signed-off-by:** dependabot[bot] <support@github.com>

- Update structlog requirement from >=23.1.0 to >=25.5.0.
  [56a01b0](https://github.com/callowayproject/foreman/commit/56a01b08c54487a4307327f114687533031fe982)

  Updates the requirements on [structlog](https://github.com/hynek/structlog) to permit the latest version.

  - [Release notes](https://github.com/hynek/structlog/releases)
  - [Changelog](https://github.com/hynek/structlog/blob/main/CHANGELOG.md)
  - [Commits](https://github.com/hynek/structlog/compare/23.1.0...25.5.0)

______________________________________________________________________

**updated-dependencies:** - dependency-name: structlog dependency-version: 25.5.0 dependency-type: direct:production

**signed-off-by:** dependabot[bot] <support@github.com>

- Update HealthCheckModel dependencies type annotation for clarity.
  [a0ad023](https://github.com/callowayproject/foreman/commit/a0ad023b02890b09757ab50ca3d50eecc19674b7)

- Remove outdated test, add CLAUDE.md for developer guidance, and update scaffolding notes.
  [dae2a06](https://github.com/callowayproject/foreman/commit/dae2a06c4a999a1f7c9f8774671d9ad187f5a7e5)

## 0.1.0 (2026-04-14)

### Other

- Initial commit. [127955f](https://github.com/callowayproject/foreman/commit/127955f5bf7e4f759155711fdfd3808912d88b51)
