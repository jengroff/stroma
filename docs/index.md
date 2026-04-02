# Stroma

**Framework-agnostic reliability primitives for agent pipelines.**

## Why Stroma?

LLM agent pipelines fail in ways that traditional software doesn't. API calls time out, models return malformed data, costs spiral, and when something breaks mid-pipeline you lose all progress. Stroma gives you the building blocks to handle this — without locking you into a framework.

## Quick Start

```python
from pydantic import BaseModel
from stroma import StromaRunner


class Input(BaseModel):
    value: int


class Output(BaseModel):
    result: int


runner = StromaRunner.quick()  # (1)!

@runner.node("double", input=Input, output=Output)  # (2)!
async def double(state: Input) -> dict:
    return {"result": state.value * 2}

result = await runner.run([double], Input(value=5))  # (3)!
print(result.status)       # COMPLETED
print(result.final_state)  # result=10
```

1. Creates a runner with sensible defaults: in-memory checkpointing, unlimited budget, standard retry policies.
2. Declares the node's input/output contract and registers it automatically.
3. Runs the pipeline with contract validation, retry handling, cost tracking, and checkpointing at every step.

## What you get

**Core reliability primitives:**

- **Typed node boundary contracts** — Pydantic input/output validation at every node edge, not just graph entry
- **Formal failure classification** — three-class taxonomy (recoverable, terminal, ambiguous) with custom classifier support
- **Per-node retry policies** — configurable per failure class, per node, with jittered backoff
- **Cost budget enforcement** — token, USD, and latency limits with model-aware pricing

**Execution infrastructure (composable, optional):**

- **Checkpointing** — async-first save and resume with in-memory and Redis backends
- **Execution tracing** — structured audit trail of every attempt, with diffing, replay, and JSON export
- **Parallel execution, hooks, shared context, structured logging** — fan-out, lifecycle callbacks, runtime config injection

## Before and after

**Before** — failures are silent, retries are manual, state is lost on crash:

```python
result = await call_llm(prompt)
# Did it fail? Was the output valid? Can we retry? Where's the trace?
```

**After** — every step is validated, classified, checkpointed, and traced:

```python
@runner.node("summarize", input=Document, output=Summary)
async def summarize(state: Document) -> dict:
    result = await call_llm(state.text)
    return {"summary": result}

# Contract validation, retry on transient failure, checkpoint on success,
# full trace on every attempt — all automatic.
```

## Install

Requires **Python 3.12+**.

```bash
uv add stroma
```

Optional extras:

=== "Redis checkpointing"

    ```bash
    uv add stroma[redis]
    ```

=== "LangGraph adapter"

    ```bash
    uv add stroma[langgraph]
    ```

## Next Steps

- **[Quickstart](quickstart.md)** — Full working pipeline in 5 minutes, including failure and resume demos.
- **[Tutorial](tutorial/index.md)** — Build a pipeline step by step, from hello-world to production-grade.
- **[Concepts](concepts.md)** — Understand the architecture and design decisions behind each primitive.
- **[Extending Stroma](extending.md)** — Write custom backends, classifiers, and OTel integrations.
- **[API Reference](api/runner.md)** — Full documentation for every class, function, and decorator.
