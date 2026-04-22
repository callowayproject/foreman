# Design Specifications

This directory contains design specifications and architectural proposals for the Foreman project.

## Table of Contents

### [01-agent-harness](./01-agent-harness/SPEC.md)

The core specification for the Foreman project.

- **Objective**: Build a minimal Python harness for always-on AI co-maintainers that handles process lifecycle,
    credential injection, and message routing.
- **Key Documents**:
    - [Specification](./01-agent-harness/SPEC.md): Technical details and requirements.
    - [Idea](./01-agent-harness/idea.md): Problem statement and recommended direction.
    - [Plan](./01-agent-harness/plan.md): Implementation roadmap.
    - [Todo](./01-agent-harness/todo.md): Tracked tasks.

### [02-messaging-update](./02-messaging-update/idea.md)

A proposal for improving the messaging system.

- **Objective**: Address the issue where messages sent to disconnected nodes are lost.
- **Key Documents**:
    - [Idea](./02-messaging-update/idea.md): Problem statement regarding the wire protocol and recovery mechanisms.
