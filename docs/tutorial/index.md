# Tutorial

Learn to build reliable agent pipelines with Stroma, one concept at a time.

Each page builds on the previous one, but they're also designed to work standalone — jump to any topic that interests you.

## What you'll learn

| Page | What you'll build |
|------|-------------------|
| [Your First Pipeline](first-pipeline.md) | A working pipeline in under 10 lines |
| [Adding Contracts](adding-contracts.md) | Input/output validation at every node boundary |
| [Retry & Failures](retry-and-failures.md) | Automatic failure classification and retry policies |
| [Checkpointing](checkpointing.md) | Save progress and resume after crashes |
| [Cost Control](cost-control.md) | Token, dollar, and latency budgets |
| [Tracing & Debugging](tracing.md) | Inspect every execution attempt |
| [Observability Hooks](hooks.md) | Plug in external telemetry at node boundaries |
| [Shared Context](shared-context.md) | Share resources across nodes without globals |
| [Parallel Execution](parallel.md) | Run independent nodes concurrently |
| [LangGraph Integration](langgraph.md) | Apply contracts to existing LangGraph graphs |

## Prerequisites

- Python 3.12+
- Basic familiarity with `async`/`await`
- [Pydantic](https://docs.pydantic.dev) (installed automatically with Stroma)

## Install

```bash
uv add stroma
```

!!! tip
    Every code example on these pages is a complete, runnable script. Copy any snippet, save it as a `.py` file, and run it.
