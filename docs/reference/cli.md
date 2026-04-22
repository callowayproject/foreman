---
title: CLI Reference
summary: Reference for the Foreman command-line interface.
date: 2026-04-21T00:00:00.000000+00:00
---

# CLI Reference

Foreman is invoked via the `foreman` command installed by the package.

```text
foreman <command> [options]
```

## Commands

| Command                   | Description               |
|---------------------------|---------------------------|
| [`start`](#foreman-start) | Start the Foreman harness |

## `foreman start`

Start the Foreman harness: load configuration, initialize the memory database, start any configured agent containers,
then run the GitHub poller and internal HTTP server concurrently.

```text
foreman start --config <CONFIG> [--db <DB_PATH>] [--host <HOST>] [--port <PORT>]
```

Foreman runs until interrupted (SIGINT or SIGTERM).
On shutdown, it cancels the poller and stops any containers it started.

### Options

| Option     | Metavar   | Default                      | Description                                                                                                                        |
|------------|-----------|------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| `--config` | `CONFIG`  | *(required)*                 | Path to the YAML configuration file. See [Configuration Reference](configuration.md).                                              |
| `--db`     | `DB_PATH` | `~/.agent-harness/memory.db` | Path to the SQLite memory database. The file and any intermediate directories are created automatically on first run.              |
| `--host`   | `HOST`    | `0.0.0.0`                    | Host address to bind the internal HTTP server to. Change to `127.0.0.1` to prevent external access.                                |
| `--port`   | `PORT`    | `8000`                       | Port for the internal HTTP server. This is the port that agent containers call back to — it must be reachable by those containers. |

### Examples

Start with a config file in the current directory:

```bash
foreman start --config config.yaml
```

Store the memory database in a custom location:

```bash
foreman start --config config.yaml --db /var/lib/foreman/memory.db
```

Bind only to localhost and use a non-default port:

```bash
foreman start --config config.yaml --host 127.0.0.1 --port 9000
```

### Startup Sequence

When `foreman` starts running, it performs these steps in order:

1. Load and validate the configuration file.
    Exits with a clear error message if the file is missing, the YAML is invalid, a required field is absent,
    or a referenced environment variable is not set.
2. Open (or create) the SQLite memory database at `--db`.
3. For each agent configured with an image and a port, pull the Docker image
    (if not cached locally) and start the container.
    Exits if Docker is unavailable or a container fails its health check.
4. Log a startup summary to stdout (structured JSON via structlog).
5. Run the GitHub poller and the internal HTTP server concurrently in a single asyncio event loop.

### Exit Codes

| Code | Meaning                                          |
|------|--------------------------------------------------|
| `0`  | Clean shutdown (SIGINT or SIGTERM received)      |
| `1`  | Configuration error or container startup failure |
| `2`  | No command supplied (usage error)                |
