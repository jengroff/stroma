# Stroma

**dbt didn't replace your data warehouse. Stroma doesn't replace your agent framework.**

dbt gave you typed models, tested transformations, and documented lineage — a software engineering layer that worked regardless of which warehouse you were running. Stroma does the same thing for agent execution graphs: typed node contracts, formal failure classification, and cost-aware execution — portable across whatever orchestration framework you're building on.

The framework handles the graph. Stroma handles the guarantees.

## The problem it solves

LLM pipelines fail in ways that traditional software doesn't. A node returns malformed data and the error surfaces three steps later. A transient timeout kills a 20-minute run and you start over from scratch. Costs spiral past budget with no enforcement mechanism. Failures are silent until they're catastrophic.

Stroma gives you the building blocks to handle this — without locking you into a framework.

## See it in action

The scenario below is the kind that breaks raw LangGraph pipelines: a multi-step run that crashes midway, resumes from checkpoint, and gives you a diff of what changed between the failed and successful run.

```python
import asyncio
from pydantic import BaseModel
from stroma import (
    AsyncInMemoryStore,
    CheckpointManager,
    ContractRegistry,
    NodeContract,
    RunConfig,
    StromaRunner,
    stroma_node,
)


class Document(BaseModel):
    text: str


class Extracted(BaseModel):
    entities: list[str]


class Summary(BaseModel):
    entities: list[str]
    count: int


registry = ContractRegistry()
store = AsyncInMemoryStore()
manager = CheckpointManager(store)

c1 = NodeContract(node_id="extract", input_schema=Document, output_schema=Extracted)
c2 = NodeContract(node_id="summarize", input_schema=Extracted, output_schema=Summary)
registry.register(c1)
registry.register(c2)


@stroma_node("extract", c1)
async def extract(state: Document) -> dict:
    return {"entities": state.text.split()}


@stroma_node("summarize", c2)
async def summarize_failing(state: Extracted) -> dict:
    raise TimeoutError("downstream API unavailable")  # (1)!


@stroma_node("summarize", c2)
async def summarize_fixed(state: Extracted) -> dict:
    return {"entities": state.entities, "count": len(state.entities)}


async def main():
    config1 = RunConfig(run_id="doc-run-1")
    runner1 = StromaRunner(registry, manager, config1)
    result1 = await runner1.run(
        [extract, summarize_failing],
        Document(text="Stroma adds reliability to agent pipelines"),
    )
    print(result1.status)  # FAILED — extract checkpointed, summarize exhausted retries

    config2 = RunConfig(run_id="doc-run-1", resume_from="summarize")  # (2)!
    runner2 = StromaRunner(registry, manager, config2)
    result2 = await runner2.run(
        [extract, summarize_fixed],
        Document(text="Stroma adds reliability to agent pipelines"),
    )
    print(result2.status)       # RESUMED — extract skipped, loaded from checkpoint
    print(result2.final_state)  # entities=[...] count=6

    diffs = result1.trace.diff(result2.trace)  # (3)!
    for d in diffs:
        print(d)


asyncio.run(main())
```

1. `TimeoutError` is classified as `RECOVERABLE`. Stroma retries with jittered backoff. After exhausting retries, the run fails — but `extract`'s output is already checkpointed.
2. Same `run_id`, `resume_from="summarize"`. The runner loads `extract`'s checkpoint and skips re-running it entirely.
3. `diff()` compares both traces — node IDs, attempts, inputs, outputs, failure states — so you can see exactly what changed between the failed run and the successful one.

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
- **LangGraph adapter** — apply contracts to existing LangGraph graphs without rewriting them
- **DeepAgents adapter** — contract validation and cost tracking for deepagents graphs

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

=== "DeepAgents adapter"

    ```bash
    uv add stroma[deepagents]
    ```

## Next Steps

- **[Quickstart](quickstart.md)** — Contracts, retries, checkpoint/resume, and trace inspection in 5 minutes.
- **[Tutorial](tutorial/index.md)** — Build a pipeline step by step, from hello-world to production-grade.
- **[Concepts](concepts.md)** — Architecture and design decisions behind each primitive.
- **[Extending Stroma](extending.md)** — Custom backends, classifiers, and OTel integrations.
- **[API Reference](api/runner.md)** — Full documentation for every class, function, and decorator.
