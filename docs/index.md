# Stroma

**Contracts, retries, checkpoints, and traceability for async Python agent pipelines.**

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

- **Input/output validation at every step** — Pydantic contracts catch bad data at node boundaries before it propagates
- **Retry only when failures are recoverable** — three-class failure taxonomy (recoverable, terminal, ambiguous) with configurable policies
- **Resume from where execution failed** — async-first checkpointing with in-memory and Redis backends
- **Inspect the full execution trace** — structured audit trail of every attempt, with diffing, replay, and JSON export

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
pip install stroma
```

Optional extras:

=== "Redis checkpointing"

    ```bash
    pip install stroma[redis]
    ```

=== "LangGraph adapter"

    ```bash
    pip install stroma[langgraph]
    ```

## Next Steps

- **[Quickstart](quickstart.md)** — Full working pipeline in 5 minutes, including failure and resume demos.
- **[Tutorial](tutorial/index.md)** — Build a pipeline step by step, from hello-world to production-grade.
- **[Concepts](concepts.md)** — Understand the architecture and design decisions behind each primitive.
- **[Extending Stroma](extending.md)** — Write custom backends, classifiers, and OTel integrations.
- **[API Reference](api/runner.md)** — Full documentation for every class, function, and decorator.
