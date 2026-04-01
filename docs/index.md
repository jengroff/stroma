# Stroma

**Reliability primitives for agent pipelines.**

## Why Stroma?

LLM agent pipelines fail in ways that traditional software doesn't. API calls time out, models return malformed data, costs spiral, and when something breaks mid-pipeline you lose all progress. Stroma gives you the building blocks to handle this:

- **Contracts** — catch bad data at node boundaries before it propagates downstream
- **Failure classification** — automatically distinguish transient errors from permanent ones
- **Retry policies** — configurable retries with jittered backoff, per failure class or per node
- **Checkpointing** — async-first save and resume across crashes (in-memory or Redis)
- **Cost estimation** — model-aware USD cost tracking via built-in pricing data, plus token and latency budgets
- **Parallel execution** — fan out work to concurrent nodes with `parallel()` and merged output
- **Node hooks** — async lifecycle callbacks for observability and side effects
- **Shared context** — pass runtime configuration through a mutable `context` dict to every node
- **Execution tracing** — full audit trail of every attempt, with diffing and export
- **Per-run logging** — structured `LoggerAdapter` with `run_id` in every log line

No framework lock-in. Works with any async Python code. Compose what you need, ignore what you don't.

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

1. Creates a runner with sensible defaults: in-memory checkpointing, unlimited budget, standard retry policies. Override any of these with keyword arguments.
2. Declares the node's input/output contract and registers it automatically. No separate registry setup needed.
3. Runs the pipeline with contract validation, retry handling, cost tracking, and checkpointing at every step.

## Install

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

<div class="grid cards" markdown>

-   **Tutorial**

    ---

    Build a pipeline step by step, from hello-world to production-grade.

    [:octicons-arrow-right-24: Start the tutorial](tutorial/index.md)

-   **Concepts**

    ---

    Understand the architecture and design decisions behind each primitive.

    [:octicons-arrow-right-24: Read the concepts guide](concepts.md)

-   **API Reference**

    ---

    Full documentation for every class, function, and decorator.

    [:octicons-arrow-right-24: Browse the API](api/runner.md)

</div>
