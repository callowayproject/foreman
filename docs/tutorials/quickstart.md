---
title: Quick Start
summary: Get Foreman triaging issues on your first repository in under 30 minutes.
date: 2026-04-21T00:00:00.000000+00:00
---

# Quick Start

This guide walks you through installing Foreman and having it triage issues on a single GitHub repository.

**Prerequisites:** Python 3.12+ installed, Docker running, and a GitHub account with a bot identity set up.
See [Installation](installation.md) for setup.

## Step 1: Create a GitHub account for a bot

Foreman acts under a dedicated GitHub account, so its comments and labels are clearly identified.

1. Create a new GitHub account (e.g., `my-project-bot`).
2. Generate a Personal Access Token for that account with `repo` scope (read/write issues, labels, and comments).
3. Note the token — you'll use it in the next step.

## Step 2: Set environment variables

Export your credentials in the shell where you'll run Foreman:

```bash
export GITHUB_TOKEN="ghp_..."         # bot account token
export ANTHROPIC_API_KEY="sk-ant-..." # omit if using Ollama
```

## Step 3: Create your configuration

Copy the example config and open it in your editor:

```bash
cp config.example.yaml config.yaml
```

Fill in your bot username and the repository you want to monitor:

```yaml
identity:
  github_token: "${GITHUB_TOKEN}"
  github_user: "my-project-bot"     # your bot account username

llm:
  provider: anthropic
  model: claude-sonnet-4-6
  api_key: "${ANTHROPIC_API_KEY}"

polling:
  interval_seconds: 60

repos:
  - owner: your-org
    name: your-repo
    agents:
      - type: issue-triage
        allow_close: false
        config:
          image: "foreman-issue-triage:latest"
          port: 9001
          stale_days: 30
          labels:
            bug: ["crash", "exception", "traceback", "error"]
            question: ["how do I", "how to", "is it possible"]
```

The default `allow_close: false` means the agent can label and comment on issues, but will not close them.
Change it to `true` only after you're comfortable with the agent's behavior.

## Step 4: Start Foreman

```bash
uv run foreman start --config config.yaml
```

Foreman will:

1. Validate your config and resolve environment variable references.
2. Pull the `foreman-issue-triage` Docker image if it is not cached locally.
3. Start the issue-triage agent container on port 9001.
4. Begin polling `your-org/your-repo` every 60 seconds.

Structured logs appear on stdout.
You should see a line similar to:

```text
{"event": "Foreman started — polling every 60 seconds, server on 0.0.0.0:8000", ...}
```

## Step 5: Open a test issue

Create a new issue on your repository.
Within the next polling interval (up to 60 seconds), Foreman will:

- Send the issue to the triage agent.
- Apply any matching labels.
- Post a comment from the bot account.
- Log the decision to `~/.agent-harness/memory.db`.

## Next steps

- Adjust labels, keywords, and stale_days in config.yaml to match your project.
- Add more repositories under `repos`.
- Read the [Configuration Reference](../reference/configuration.md) for all available options.
- Read the [Agent Protocol Reference](../reference/agent-protocol.md) to understand how to build your own agents.
