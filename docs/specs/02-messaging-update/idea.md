# Messaging Update: Queue-Mediated Agent Protocol

## Problem Statement

How might we ensure GitHub events dispatched to agent containers are processed reliably,
even when agents are temporarily unavailable?

## Recommended Direction

The harness owns a task queue (SQLite by default, pluggable interface).
Events are enqueued before any dispatch attempt — the queue is the source of truth.
`POST /task → 202 Accepted` becomes a nudge ("check your queue now"), not a delivery mechanism.
Agents poll the queue at startup, on a background interval, and when nudged.

Results flow symmetrically: the agent writes its DecisionMessage back to the queue,
then POSTs to `POST /harness/result → 202 Accepted` to nudge the harness.
The harness also has a background task that periodically checks for completed tasks.
HTTP nudges are optimizations that degrade gracefully — the queue always wins.

This preserves the core constraint: the harness owns all infrastructure.
Agents embed a thin `foreman-client` library that handles queue I/O.
Agent authors call `client.next_task()` and `client.complete_task(task_id, decision)`.
They don't implement queue management.

## Key Assumptions to Validate

- [ ] SQLite with WAL mode handles concurrent harness writes + agent reads
    without contention — benchmark before committing the schema
- [ ] Agents are Python (or can embed a Python client) — validate the agent
    container build process supports a shared library dependency
- [ ] 202 nudge + background poll provides acceptable end-to-end latency —
    define "acceptable" explicitly (target: < 30s for MVP)
- [ ] One agent per queue is sufficient for MVP — the queue abstraction must
    not bake in single-consumer assumptions that block future fan-out

## MVP Scope

**In:**

- `task_queue` table in existing `memory.db`: task_id, agent_url, status,
  payload, created_at, claimed_at, completed_at, result, retry_count
- Harness writes: enqueue on poll event; `POST /task → 202` nudge to agent;
  `POST /result` endpoint for agent callback; background drain loop for
  completed tasks; re-enqueue tasks claimed but not completed within timeout
- Harness reads: poll queue for completed tasks on callback + interval
- `foreman-client` lib: `next_task()`, `complete_task(task_id, decision)`,
  `heartbeat(task_id)` — heartbeat resets the claim timeout clock
- Agent protocol: `POST /task → 202` (nudge only); startup queue poll;
  configurable background poll interval
- Delivery guarantee: at-least-once; task_id is the idempotency key

**Out:**

- Multiple agent containers per queue (no consumer groups in MVP)
- External queue backends (Redis, NATS) — define pluggable interface,
  implement SQLite only
- Task prioritization or ordering beyond FIFO
- Monitoring UI — structured log output only

## Not Doing (and Why)

- **Agent-owned queues** — every agent author would reimplement queue logic;
  harness owns infrastructure
- **Exactly-once delivery** — requires distributed coordination; at-least-once
    - idempotency is sufficient and far simpler
- **File-system queuing** — ephemeral in containers; shared volumes add
  deployment surface for no real gain over SQLite
- **Keep synchronous dispatch as fallback** — two delivery paths means neither
  is authoritative; commit to queue-first fully

## Open Questions

- What is the claim timeout?
  If an agent pulls a task and crashes before completing, the harness must detect and re-enqueue it —
  define the TTL and re-enqueue logic before writing the schema.
- Is `foreman-client` a separate PyPI package, part of the `foreman` package,
  or vendored into each agent at build time?
- Should `GET /queue/status` be exposed on the harness for operator visibility,
  or is structured logging sufficient for MVP?
