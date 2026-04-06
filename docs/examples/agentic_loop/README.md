# Agentic Loop Example

## Paradigm

Agentic loop / tool-calling. The model decides the next action at each iteration by selecting a tool and arguments. The natural reliability boundary is the **tool call** — each dispatch to a tool is an independent execution step where input/output validation, cost tracking, and failure handling apply.

## What the agent does

A research agent answers a question by calling tools in a scripted loop: it searches for information, fetches page content (which fails transiently on the first attempt), and synthesizes a summary. All tool outputs and LLM decisions are deterministic — no API keys or network calls required.

## Running

```bash
uv run python docs/examples/agentic_loop/agent.py
uv run python docs/examples/agentic_loop/with_stroma.py
```

## Comparison

| | Without Stroma | With Stroma |
|---|---|---|
| Transient tool failure | `TimeoutError` crashes the loop | Classified as `RECOVERABLE`, retried automatically |
| Cost visibility | None — tokens are returned but never aggregated | `ctx.cost_tracker.total_tokens` gives cumulative spend |
| Per-call audit trail | None | Full `ExecutionTrace` with per-tool attempt records |

## Stroma primitives used

- **`ReliabilityContext`** — bundles cost tracker, retry budget, and trace for the entire agent run.
- **`execute_step()`** — wraps each tool dispatch with contract validation, retry logic, and cost tracking.
- **`NodeContract`** — validates that each tool receives a `ToolCall` and returns a `ToolResult`.
