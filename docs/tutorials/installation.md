---
title: Installation
summary: System requirements and installation instructions for Foreman.
date: 2026-04-21T00:00:00.000000+00:00
---

# Installation

## Requirements

| Requirement                           | Version            | Notes                              |
|---------------------------------------|--------------------|------------------------------------|
| Python                                | 3.12 or higher     | Earlier versions are not supported |
| Docker                                | Any recent version | Required to run agent containers   |
| [uv](https://github.com/astral-sh/uv) | Latest             | Recommended package manager        |

Docker must be running, and the Docker socket must be accessible before starting Foreman.
If you manage agent containers yourself and use `url:` in your agent config, Docker is optional.

## Install

Clone the repository and install dependencies:

```bash
git clone https://github.com/callowayproject/foreman.git
cd foreman
uv sync
```

`uv sync` installs the `dev`, `test`, and `docs` dependency groups by default (as set in `pyproject.toml`).
To install only the runtime dependencies:

```bash
uv sync --only-group default
```

## Verify

Check that the `foreman` command is available:

```bash
uv run foreman --help
```

You should see:

```text
usage: foreman [-h] {start} ...

Foreman — AI OSS co-maintainer harness

...
```

## Environment Variables

Foreman does not require any environment variables at install time.
You will need to set the following before running:

| Variable            | Description                                                           |
|---------------------|-----------------------------------------------------------------------|
| `GITHUB_TOKEN`      | GitHub Personal Access Token for the bot account (needs `repo` scope) |
| `ANTHROPIC_API_KEY` | Anthropic API key (only if using `provider: anthropic`)               |

These are referenced from your `config.yaml` using `${VAR}` syntax.
See [Configuration Reference](../reference/configuration.md#environment-variable-references).
