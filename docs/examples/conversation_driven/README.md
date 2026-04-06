# Conversation-Driven Example

## Paradigm

Conversation-driven / multi-agent message passing. Two agents exchange structured messages in turns, each responding to the other's output. The natural reliability boundary is the **message turn** — each agent's contribution is an independent execution step where schema validation catches malformed inter-agent messages before they propagate.

## What the agents do

A reviewer agent examines a code submission and posts structured feedback (issues, severity, summary). A responder agent reads the review and posts a revision plan (changes, rationale). They alternate for two turns. All outputs are deterministic — no LLM calls required. The second turn intentionally demonstrates a malformed message (missing `severity` field) caught by contract validation.

## Running

```bash
uv run python docs/examples/conversation_driven/agent.py
uv run python docs/examples/conversation_driven/with_stroma.py
```

## Comparison

| | Without Stroma | With Stroma |
|---|---|---|
| Malformed inter-agent messages | Silent — downstream agent gets garbage input | `ContractViolation` raised immediately with field-level errors |
| Cost tracking across turns | None | Cumulative tracking via `ReliabilityContext` |
| Per-turn audit trail | None | Full `ExecutionTrace` with per-turn attempt records |

## Stroma primitives used

- **`StromaStep`** — wraps each agent's turn as a decorated async function with contract validation and tracing.
- **`ContractViolation`** — catches the missing `severity` field immediately, classified as `TERMINAL` to prevent propagation.
- **`ExecutionTrace`** — records every turn attempt, enabling post-conversation debugging.
