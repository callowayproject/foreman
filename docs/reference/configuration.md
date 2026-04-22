---
title: Configuration Reference
summary: Complete reference for the Foreman YAML configuration file.
date: 2026-04-21T00:00:00.000000+00:00
---

# Configuration Reference

Foreman is configured via a single YAML file.
All secrets are supplied as `${ENV_VAR}` references — the file itself never contains raw secret values.
Foreman resolves these references from the process environment before validation.

To get started, copy `config.example.yaml` and edit it:

```bash
cp config.example.yaml config.yaml
```

## Environment Variable References

Any string value in the config file may contain one or more `${VAR}` placeholders.
At startup, Foreman substitutes each placeholder with the value of the named environment variable.
If a referenced variable is not set, Foreman exits immediately with a clear error.

```yaml
github_token: "${GITHUB_TOKEN}"          # single reference
model: "${LLM_PROVIDER}-${LLM_VERSION}"  # multiple references in one string
```

## Top-Level Sections

| Section                 | Required | Description                     |
|-------------------------|----------|---------------------------------|
| [`identity`](#identity) | Yes      | Bot GitHub credentials          |
| [`llm`](#llm)           | Yes      | LLM backend to use              |
| [`polling`](#polling)   | No       | Polling interval (has defaults) |
| [`repos`](#repos)       | No       | Repositories to monitor         |

## `identity`

Bot GitHub identity.
**Required.**

```yaml
identity:
  github_token: "${GITHUB_TOKEN}"
  github_user: "my-bot"
```

### Fields

| Field          | Type   | Required | Description                                                  |
| -------------- | ------ | -------- | ------------------------------------------------------------ |
| `github_token` | string | Yes      | GitHub Personal Access Token for the bot account. Always supply as an environment variable. The token needs `repo` scope (read issues, write labels, write comments). |
| `github_user`  | string | Yes      | GitHub username of the bot account. Used to identify comments and actions made by Foreman. |

## `llm`

LLM backend configuration.
**Required.**

```yaml
llm:
  provider: anthropic
  model: claude-sonnet-4-6
  api_key: "${ANTHROPIC_API_KEY}"
```

### Fields

| Field      | Type   | Required | Description                                                  |
| ---------- | ------ | -------- | ------------------------------------------------------------ |
| `provider` | string | Yes      | LLM provider identifier. Supported values: `anthropic`, `ollama`. |
| `model`    | string | Yes      | Model name or identifier passed to the provider (e.g., `claude-sonnet-4-6`, `llama3`). |
| `api_key`  | string | No       | API key for the provider. Omit this field entirely when using `ollama` or another local provider that does not require a key. |

## `polling`

Controls how often Foreman checks GitHub for new events.
**Optional**.
Defaults are applied when this section is absent.

```yaml
polling:
  interval_seconds: 60
```

### Fields

| Field              | Type    | Required | Default | Description                                                                    |
|--------------------|---------|----------|---------|--------------------------------------------------------------------------------|
| `interval_seconds` | integer | No       | `60`    | How often (in seconds) to poll each configured repository for new open issues. |

## `repos`

List of repositories to monitor and the agents assigned to each.
**Optional**.
Foreman starts successfully with an empty list, but does nothing.

```yaml
repos:
  - owner: callowayproject
    name: bump-my-version
    agents:
      - type: issue-triage
        allow_close: false
        config:
          image: "foreman-issue-triage:latest"
          port: 9001
```

### Repository Fields

| Field    | Type   | Required | Description                                                  |
| -------- | ------ | -------- | ------------------------------------------------------------ |
| `owner`  | string | Yes      | GitHub user or organization that owns the repository.        |
| `name`   | string | Yes      | Repository name (without the owner prefix).                  |
| `agents` | list   | No       | Agents assigned to this repository. Each entry is an [agent assignment](#agent-assignment). |

### Agent Assignment

Each entry in `agents` describes one agent and how it handles events for that repository.

| Field         | Type    | Required | Default | Description                                                  |
| ------------- | ------- | -------- | ------- | ------------------------------------------------------------ |
| `type`        | string  | Yes      | —       | Agent type identifier. Must match an agent implementation (e.g., `issue-triage`). |
| `allow_close` | boolean | No       | `false` | When `false`, `close_issue` actions from this agent are silently skipped. Set to `true` only after verifying the agent's triage behaviour. |
| `config`      | mapping | No       | `{}`    | Agent-specific options. See [Agent Config](#agent-config).   |

### Agent Config

The `config` mapping under each agent assignment is passed verbatim to the agent in every `TaskMessage`.
It also controls how Foreman starts and connects to the container.

#### Container Lifecycle Mode

Foreman pulls the image (if not already present locally), starts the container on startup,
and stops it on clean shutdown.
Use this mode when you want Foreman to own the container lifecycle.

Both `image` and `port` are required for this mode.

| Field   | Type    | Required        | Description                                                  |
| ------- | ------- | --------------- | ------------------------------------------------------------ |
| `image` | string  | Yes (this mode) | Docker image name and tag to run (e.g., `foreman-issue-triage:latest`). |
| `port`  | integer | Yes (this mode) | Host port to bind to container port `8000`. Must be free on the host. |

```yaml
config:
  image: "foreman-issue-triage:latest"
  port: 9001
```

#### Pre-Running Agent Mode

When you manage the container yourself (or connect to a remote agent), omit `image` and `port` and supply `url` instead.
Foreman does not start or stop the container.

| Field | Type   | Required        | Description                                                        |
|-------|--------|-----------------|--------------------------------------------------------------------|
| `url` | string | Yes (this mode) | HTTP base URL of the running agent (e.g. `http://localhost:9001`). |

```yaml
config:
  url: "http://localhost:9001"
```

#### Event Routing

| Field         | Type            | Default                 | Description                                                  |
| ------------- | --------------- | ----------------------- | ------------------------------------------------------------ |
| `event_types` | list of strings | Derived from agent type | An explicit list of event type strings this agent handles (e.g., `["issue.triage"]`). When absent, Foreman derives a prefix from the agent type name: `issue-triage` → handles events that begin with `issue.`. |

#### Issue-Triage Agent Options

These fields are specific to the `issue-triage` agent and are forwarded in the `payload` of each task.

| Field        | Type    | Description                                                                                                                                             |
|--------------|---------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| `stale_days` | integer | Number of days without activity before an issue is considered stale.                                                                                    |
| `labels`     | mapping | Keyword-to-label map. Each key is a label name; the value is a list of keyword strings that trigger that label. Example: `bug: ["crash", "exception"]`. |

## Complete Example

```yaml
identity:
  github_token: "${GITHUB_TOKEN}"
  github_user: "my-bot"

llm:
  provider: anthropic
  model: claude-sonnet-4-6
  api_key: "${ANTHROPIC_API_KEY}"

polling:
  interval_seconds: 60

repos:
  - owner: callowayproject
    name: bump-my-version
    agents:
      - type: issue-triage
        allow_close: false
        config:
          image: "foreman-issue-triage:latest"
          port: 9001
          stale_days: 30
          labels:
            bug: [ "crash", "exception", "error" ]
            question: [ "how do I", "how to" ]

  - owner: callowayproject
    name: another-repo
    agents:
      - type: issue-triage
        allow_close: true
        config:
          url: "http://localhost:9002"
```
