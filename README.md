# Foreman

**An always-on AI co-maintainer for your GitHub repositories.**

[![License](https://img.shields.io/github/license/callowayproject/foreman)](LICENSE)
[![Python version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

## About

Foreman is a Python-based harness designed for solo OSS maintainers who want automated triage, dependency updates,
and releases across multiple repositories.
It acts as a dedicated co-maintainer with its own GitHub identity and opinions,
managing the boring parts of repository maintenance so you can focus on code.

Unlike simple scripts, Foreman provides a robust, composable environment where specialized AI agents
(running in Docker) handle specific tasks like issue triage.
It manages process lifecycles, credential injection, message routing, and persistent memory of past decisions.

## Features

- **Composable Agent Architecture:** Agents run in isolated Docker containers
    and communicate via a simple JSON-over-HTTP protocol.
- **Always-On Polling:** Monitors your repositories for new events (issues, PRs) without requiring public webhooks.
- **Persistent Action Memory:** Uses SQLite to store a summary of past agent decisions,
    ensuring your AI co-maintainer has context for future actions.
- **LLM Backend Abstraction:** Built-in support for Anthropic (Claude) and local models via Ollama.
- **Secure by Design:** The harness executes all GitHub API calls; agents never see your GitHub tokens.
- **Observability:** Integrated with OpenTelemetry and structured logging (structlog) for easy tracing and debugging.

## Requirements

- **Python:** 3.12 or higher.
- **Docker:** Required for running agent containers.
- **Package Manager:** [uv](https://github.com/astral-sh/uv) is recommended for dependency management.

## Installation

```bash
# Clone the repository
git clone https://github.com/callowayproject/foreman.git
cd foreman

# Install dependencies using uv
uv sync
```

## Quick Start

Foreman uses a YAML configuration file to define repositories, agents, and LLM backends.

1. **Configure:** Copy the example configuration:

    ```bash
    cp config.example.yaml config.yaml
    ```

2. **Edit `config.yaml`:** Add your GitHub token and repository details.
3. **Run:** (Note: CLI entrypoint implementation is currently in progress)

    ```bash
    uv run foreman
    ```

For detailed configuration options, see [config.example.yaml](config.example.yaml)
and the [Project Specification](docs/specs/initial/SPEC.md).

## Project Structure

- `foreman/`: The core harness logic (polling, execution, memory, settings).
- `agents/`: Specialized AI agents (e.g., `issue-triage`).
- `specs/`: Detailed project specifications and implementation plans.
- `tests/`: Comprehensive test suite with recorded LLM fixtures.

## Contributing

Contributions are welcome!
Whether it's adding a new agent, improving the harness, or fixing bugs,
please see [CONTRIBUTING.md](CONTRIBUTING.md) for our development guidelines.

### Development Setup

```bash
# Install development dependencies
uv sync --all-groups

# Run tests
uv run pytest
```

## License

Foreman is licensed under the [MIT](LICENSE) license.
See the [`LICENSE`](LICENSE) file for more information.
