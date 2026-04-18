# Changelog

## 0.2.1 (2026-04-18)

[Compare the full difference.](https://github.com/callowayproject/foreman/compare/0.2.0...0.2.1)

### Other

- Use `TYPE_CHECKING` for imports in test files and update Phase 4 todo items. [6043d54](https://github.com/callowayproject/foreman/commit/6043d54a2029381d0528090bfe2245e8d8e41543)

- Phase 4: implement GitHub executor and poller (Tasks 8 & 9). [9efa175](https://github.com/callowayproject/foreman/commit/9efa175d6fca43f810579e604a87f2b3a73ac413)

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

- Remove draft flag from release creation script. [131ea10](https://github.com/callowayproject/foreman/commit/131ea103ea75a4edc925a980f0a6b59c01fd5fa8)

## 0.2.0 (2026-04-18)

[Compare the full difference.](https://github.com/callowayproject/foreman/compare/0.1.0...0.2.0)

### Fixes

- Fix unclosed DB connection warnings in test_memory.py. [982f6ec](https://github.com/callowayproject/foreman/commit/982f6ece8fbb4f4b5bd553efe76beb1d3bd5703d)

  Switch store fixtures to yield+context-manager so the connection is
  closed after each test, and remove manual store.close() calls that
  were no longer needed with WAL mode + committed writes.

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

### New

- Add docstrings for clarity in LLM backend tests, remove unused imports, and update CLAUDE.md with test-writing guidance. [0b73671](https://github.com/callowayproject/foreman/commit/0b736714465dc6313bb2fa2d91a606cee967cb31)

### Other

- Replace `mkdocs gh-deploy` with `zensical build --clean` in docs workflows. [4e22796](https://github.com/callowayproject/foreman/commit/4e22796d789c8dcce3bd4d20004facae2eca62e8)

- Generated the changelog. [2f35d59](https://github.com/callowayproject/foreman/commit/2f35d59b98b589dc0f97dc06f7a38c5a355be892)

- Bump the github-actions group with 10 updates. [f1cb391](https://github.com/callowayproject/foreman/commit/f1cb391e51f63a5982e313c5ae6505a1fddf62c3)

  Bumps the github-actions group with 10 updates:

  | Package | From | To |
  | --- | --- | --- |
  | [actions/checkout](https://github.com/actions/checkout) | `4` | `6` |
  | [actions/download-artifact](https://github.com/actions/download-artifact) | `4` | `8` |
  | [actions/setup-python](https://github.com/actions/setup-python) | `5` | `6` |
  | [astral-sh/setup-uv](https://github.com/astral-sh/setup-uv) | `5` | `7` |
  | [github/codeql-action](https://github.com/github/codeql-action) | `3` | `4` |
  | [docker/login-action](https://github.com/docker/login-action) | `3` | `4` |
  | [docker/metadata-action](https://github.com/docker/metadata-action) | `5` | `6` |
  | [docker/build-push-action](https://github.com/docker/build-push-action) | `6` | `7` |
  | [actions/attest-build-provenance](https://github.com/actions/attest-build-provenance) | `2` | `4` |
  | [softprops/action-gh-release](https://github.com/softprops/action-gh-release) | `2` | `3` |

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

  **updated-dependencies:** - dependency-name: actions/checkout
  dependency-version: '6'
  dependency-type: direct:production
  update-type: version-update:semver-major
  dependency-group: github-actions

  **signed-off-by:** dependabot[bot] <support@github.com>

- Phase 3 Tasks 6-7: implement LLM backend abstraction. [02733dc](https://github.com/callowayproject/foreman/commit/02733dceba4331aedbb4cbf1de53786fe3cf00eb)

  - LLMBackend ABC with complete() method and from_config() factory in base.py
  - AnthropicBackend and OllamaBackend wrapping LiteLLM
  - Recorded fixture files for both backends (no live LLM calls in tests)
  - 16 new tests across test_llm_base.py and test_llm_backends.py

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Refine type annotations and optimize imports in protocol and memory tests. [12a6bd8](https://github.com/callowayproject/foreman/commit/12a6bd81808ebdafc23a11cba0977b58cf876946)

- Phase 2 human review approved. [3846ea8](https://github.com/callowayproject/foreman/commit/3846ea849be096d3e1a51c9218f8a94f4d6a4cae)

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Mark Phase 2 tasks complete in todo.md. [78318a0](https://github.com/callowayproject/foreman/commit/78318a0c11b8493e774b436f9be2fa36b77d698d)

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Phase 2 Task 5: implement SQLite memory store. [6b39f0b](https://github.com/callowayproject/foreman/commit/6b39f0b8289c26cc6d6e46813020c4e29846c776)

  Add MemoryStore with action_log and memory_summary tables (WAL mode).
  log_action(), get_memory_summary(), upsert_memory_summary() covered by
  13 tests using real temp-file DBs — no mocks.

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Phase 2 Task 4: implement agent protocol Pydantic models. [829f47f](https://github.com/callowayproject/foreman/commit/829f47f16ecce8965f7c318bd9f29fbb397a4d32)

  Add TaskMessage, DecisionMessage, ActionItem, LLMBackendRef,
  TaskContext, and DecisionType to foreman/protocol.py with 22 tests.

  **co-authored-by:** Claude Sonnet 4.6 <noreply@anthropic.com>

- Phase 1: scaffold, config system, and credential injection. [9f21485](https://github.com/callowayproject/foreman/commit/9f21485eee9dedc8b95c29d914a9fb47be05a6f3)

  - pyproject.toml: add runtime deps (PyYAML, PyGithub, litellm, httpx, docker),
    uncomment [project.scripts] entry pointing to foreman.__main__:main
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

- Remove unused GitHub Actions workflows and update dependabot configuration. [7bbcfb0](https://github.com/callowayproject/foreman/commit/7bbcfb04a104467f712413c87ed2ad08a94bfe69)

- Update httpx requirement from >=0.27 to >=0.28.1. [5cef88e](https://github.com/callowayproject/foreman/commit/5cef88e7648e0cb137d1678c52c62d968459f473)

  Updates the requirements on [httpx](https://github.com/encode/httpx) to permit the latest version.

  - [Release notes](https://github.com/encode/httpx/releases)
  - [Changelog](https://github.com/encode/httpx/blob/master/CHANGELOG.md)
  - [Commits](https://github.com/encode/httpx/compare/0.27.0...0.28.1)

  ______________________________________________________________________

  **updated-dependencies:** - dependency-name: httpx
  dependency-version: 0.28.1
  dependency-type: direct:production

  **signed-off-by:** dependabot[bot] <support@github.com>

- Update pydantic-settings requirement from >=2.8.1 to >=2.13.1. [624e336](https://github.com/callowayproject/foreman/commit/624e3369a0e9690df36e2a5c876a2b43381dbe35)

  Updates the requirements on [pydantic-settings](https://github.com/pydantic/pydantic-settings) to permit the latest version.

  - [Release notes](https://github.com/pydantic/pydantic-settings/releases)
  - [Commits](https://github.com/pydantic/pydantic-settings/compare/v2.8.1...v2.13.1)

  ______________________________________________________________________

  **updated-dependencies:** - dependency-name: pydantic-settings
  dependency-version: 2.13.1
  dependency-type: direct:production

  **signed-off-by:** dependabot[bot] <support@github.com>

- Update opentelemetry-api requirement from >=1.32.0 to >=1.41.0. [ee4c822](https://github.com/callowayproject/foreman/commit/ee4c822dc34cbbad4b99d69d765e0c39b9fca886)

  Updates the requirements on [opentelemetry-api](https://github.com/open-telemetry/opentelemetry-python) to permit the latest version.

  - [Release notes](https://github.com/open-telemetry/opentelemetry-python/releases)
  - [Changelog](https://github.com/open-telemetry/opentelemetry-python/blob/main/CHANGELOG.md)
  - [Commits](https://github.com/open-telemetry/opentelemetry-python/compare/v1.32.0...v1.41.0)

  ______________________________________________________________________

  **updated-dependencies:** - dependency-name: opentelemetry-api
  dependency-version: 1.41.0
  dependency-type: direct:production

  **signed-off-by:** dependabot[bot] <support@github.com>

- Update docker requirement from >=7.0 to >=7.1.0. [e673884](https://github.com/callowayproject/foreman/commit/e673884e9ec82c472faf1770018cd840998d8de3)

  Updates the requirements on [docker](https://github.com/docker/docker-py) to permit the latest version.

  - [Release notes](https://github.com/docker/docker-py/releases)
  - [Commits](https://github.com/docker/docker-py/compare/7.0.0...7.1.0)

  ______________________________________________________________________

  **updated-dependencies:** - dependency-name: docker
  dependency-version: 7.1.0
  dependency-type: direct:production

  **signed-off-by:** dependabot[bot] <support@github.com>

- Update structlog requirement from >=23.1.0 to >=25.5.0. [56a01b0](https://github.com/callowayproject/foreman/commit/56a01b08c54487a4307327f114687533031fe982)

  Updates the requirements on [structlog](https://github.com/hynek/structlog) to permit the latest version.

  - [Release notes](https://github.com/hynek/structlog/releases)
  - [Changelog](https://github.com/hynek/structlog/blob/main/CHANGELOG.md)
  - [Commits](https://github.com/hynek/structlog/compare/23.1.0...25.5.0)

  ______________________________________________________________________

  **updated-dependencies:** - dependency-name: structlog
  dependency-version: 25.5.0
  dependency-type: direct:production

  **signed-off-by:** dependabot[bot] <support@github.com>

- Update HealthCheckModel dependencies type annotation for clarity. [a0ad023](https://github.com/callowayproject/foreman/commit/a0ad023b02890b09757ab50ca3d50eecc19674b7)

- Remove outdated test, add CLAUDE.md for developer guidance, and update scaffolding notes. [dae2a06](https://github.com/callowayproject/foreman/commit/dae2a06c4a999a1f7c9f8774671d9ad187f5a7e5)

## 0.1.0 (2026-04-14)

### Other

- Initial commit. [127955f](https://github.com/callowayproject/foreman/commit/127955f5bf7e4f759155711fdfd3808912d88b51)
