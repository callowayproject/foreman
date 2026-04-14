# Agent Harness

## Problem Statement
How might we give a solo OSS maintainer an always-on AI co-maintainer that handles triage, dependency updates, and releases across multiple repos — composable from specialized agents, runnable anywhere, without writing integration glue each time?

## Recommended Direction

Build a **minimal Python harness with a well-defined agent protocol**, framed from day one as an AI co-maintainer with its own GitHub identity and opinions.

The harness is deliberately thin: it handles process lifecycle, credential injection, message routing, scheduling, and nothing else. All intelligence lives in agents. Agents communicate with the harness over a simple wire protocol — inspired by LSP's architecture: small core, large ecosystem.

The co-maintainer framing matters architecturally. Each agent isn't a "script" — it's a worker with a defined role, a persona, and a contract. This shapes how agents are configured, how they report decisions, and how the user overrides them. It also makes the system feel coherent rather than a bag of automations.

LLM communication is an injectable dependency. The same agent runs against OpenAI, Claude, or a local Ollama instance — the harness doesn't care. This makes local-first deployment a configuration choice, not a redesign.

The Archon-style workflow engine is a **runtime plugin** — one minion among many — not the core. Start without it. Add it when multi-step coordination across agents is needed.

## Key Assumptions to Validate
- [ ] A simple message protocol (JSON over stdin/stdout or unix socket) is sufficient for agent↔harness communication — *test by sketching protocol messages for 3 different agent types before writing code*
- [ ] LLM abstraction (e.g., LiteLLM) doesn't impose unacceptable latency or capability loss for triage/release tasks — *test by running a triage prompt against 2-3 backends with the same interface*
- [ ] A solo maintainer can get from install to first useful action (an issue triaged) in under 30 minutes — *test against a real repo during early development*
- [ ] GitHub webhooks + a lightweight scheduler covers the triggering needs without a heavy event bus — *test before adding infrastructure*

## MVP Scope

One harness, one agent, one repo.

**In:**
- Harness core: process management, credential injection, message routing, webhook listener
- Agent protocol v0: JSON message contract (task in, decision out, action taken)
- One agent: Issue Triage (label, respond, close stale)
- LLM backend abstraction with at least two providers (e.g., Anthropic + Ollama)
- Config file to define repos, agent assignments, and LLM backend
- GitHub identity for the co-maintainer (dedicated bot account)

**Out of MVP, but protocol must allow:**
- Multi-agent workflows / DAG engine
- Dependency update and release agents
- Plugin/sharing registry
- Web UI

## Not Doing (and Why)
- **DAG workflow engine in v1** — adds complexity before the protocol is proven; the Archon integration is a plugin, not the foundation
- **Community marketplace** — needs trust/sandboxing infrastructure; defer until the protocol is stable and there are at least 3 first-party agents to show the pattern
- **Web UI** — CLI + config file is sufficient for a solo maintainer; UI is scope inflation at this stage
- **Multi-model routing / fallback logic** — LLM abstraction means swapping backends is a config change; smart routing is a future optimization
- **Self-hosted infra automation** — assume the user handles deployment; harness is just a Python process

## Open Questions
- What is the minimal viable agent protocol? (stdin/stdout JSON vs. unix socket vs. HTTP — pick one and commit)
- Does the co-maintainer need a persistent memory store in v1, or is per-run context sufficient for triage?
- What's the right config format — TOML, YAML, Python DSL? (affects how composable workflows feel before the DAG engine exists)
